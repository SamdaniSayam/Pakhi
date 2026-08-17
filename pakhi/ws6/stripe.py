"""WS-6 T2 Stripe integration — thin REST client + daily usage sync.

No Stripe SDK dependency: the billing surface is a small, testable client over
Stripe's REST API with an **injectable transport** (tests use a recording fake,
production uses ``httpx``). Money rules from the contract twin (§3.2, §5):

- **Daily sync, never end-of-month.** ``sync_day`` submits one idempotent batch
  per tenant per day; ``batch_id`` is the unique key (ours *and* Stripe's
  idempotency key), so a re-send is a no-op.
- **Subscription ↔ tier sync.** A Stripe price must equal the tenant's WS-4
  tier per the twin; a mismatch is a ``TierMismatchError`` (boot error), never
  a silent override.
- **Staleness.** A day without a successful sync flips the staleness check so
  the alert fires (> 24 h) — a Tuesday failure leaves 29 days to recover.
- **No card data, ever.** Our schemas and code never see a PAN/CVV.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pakhi.ws6.contract import billing_contract
from pakhi.ws6.db import StripeSyncEvent


class TierMismatchError(RuntimeError):
    """A tenant's Stripe price does not match its WS-4 tier (boot error)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def price_ids() -> dict[str, str]:
    return billing_contract()["stripe"]["price_ids"]


def tier_for_price(price_id: str) -> str | None:
    for tier, pid in price_ids().items():
        if pid == price_id:
            return tier
    return None


def verify_webhook_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Verify a Stripe-Signature header: ``t=<ts>,v1=<hex>`` over ``t.payload``.

    Uses stdlib HMAC-SHA256 (no SDK); constant-time comparison. A missing,
    malformed, or mismatched signature is ``False`` — never logged-and-applied.
    """
    if not signature_header or not secret:
        return False
    parts: dict[str, str] = {}
    for item in signature_header.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k] = v
    t, v1 = parts.get("t"), parts.get("v1")
    if not t or not v1:
        return False
    signed = f"{t}.{payload.decode()}".encode()
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def sync_subscription_tier(engine, tenant_id: str, price_id: str) -> str:
    """Verify a subscription price matches the tenant's tier (boot error on
    mismatch). Returns the tier. Never overrides a tier silently."""
    from pakhi.ws4.db import Tenant

    with engine.connect() as conn:
        tier = conn.execute(select(Tenant.tier).where(Tenant.id == tenant_id)).scalar()
    if tier is None:
        raise TierMismatchError(f"unknown tenant {tenant_id}")
    if price_ids().get(tier) != price_id:
        raise TierMismatchError(
            f"tenant={tenant_id} tier={tier} expects price {price_ids().get(tier)} "
            f"but Stripe says {price_id}"
        )
    return tier


def record_subscription(
    engine, *, tenant_id: str, customer_id: str, subscription_item_id: str
) -> None:
    """Store the Stripe linkage on the tenant row (T2 audit fix).

    Stripe's usage-records API attaches to the *subscription item* id (``si_…``),
    never to a customer or internal tenant id. The webhook is the only place we
    learn it; without it no usage can ever be submitted, so an unknown tenant is
    a boot error, not a silent skip.
    """
    from pakhi.ws4.db import Tenant

    with Session(engine) as session:
        row = session.get(Tenant, tenant_id)
        if row is None:
            raise TierMismatchError(f"unknown tenant {tenant_id}")
        row.stripe_customer_id = customer_id
        row.stripe_subscription_item_id = subscription_item_id
        session.commit()


def clear_subscription(engine, *, tenant_id: str) -> None:
    """A subscription was deleted: stop submitting usage records for it.

    The tier is a product decision — untouched here; only the Stripe linkage
    (item/customer ids) is cleared so the daily sync stops attaching usage to a
    cancelled subscription. Audited ``billing.subscription_removed`` (internal
    bookkeeping, never a billable API call).
    """
    from pakhi.ws4.audit_events import AuditSpec, apply_audit
    from pakhi.ws4.db import Tenant

    with Session(engine) as session:
        row = session.get(Tenant, tenant_id)
        if row is None:
            raise TierMismatchError(f"unknown tenant {tenant_id}")
        row.stripe_customer_id = None
        row.stripe_subscription_item_id = None
        apply_audit(
            session,
            AuditSpec(
                request_id=f"stripe-sub-deleted-{tenant_id}-{int(_utcnow().timestamp())}",
                tenant_id=tenant_id,
                actor_id="ws6.stripe",
                action="billing.subscription_removed",
                resource="tenant",
                resource_id=tenant_id,
            ),
        )
        session.commit()


def _tenant_stripe(engine, tenant_id: str) -> tuple[str, str]:
    """(tier, subscription_item_id) for a tenant; item is '' when unlinked."""
    from pakhi.ws4.db import Tenant

    with engine.connect() as conn:
        row = conn.execute(
            select(Tenant.tier, Tenant.stripe_subscription_item_id).where(Tenant.id == tenant_id)
        ).first()
    if row is None:
        raise TierMismatchError(f"unknown tenant {tenant_id}")
    return row[0], row[1] or ""


def build_usage_batches(
    engine,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    """Metered usage for [day_start, day_end) as Stripe usage-batch payloads.

    One batch per tenant with usage; ``batch_id`` = ``usage-<day>-<tenant>`` is
    the idempotency key for both our table and the Stripe idempotency header.
    Each batch carries the tenant's Stripe **subscription item id** (captured
    from the webhook, stored on the tenant row) — Stripe's usage-records API
    attaches usage to a ``si_…`` item, never to a customer/tenant id.

    A tenant with usage but **no** subscription item id:
    - free/trial tenant → no batch at all (nothing to bill, silent skip);
    - paid tenant → a batch with ``subscription_item=None`` so ``submit_batch``
      records a ``failed`` sync event (revenue-bleed alert: a paying tenant that
      cannot be billed), never a silent drop.
    """
    from pakhi.ws6 import metering

    usage = metering.rollup(
        engine,
        day_start.isoformat(),
        day_end.isoformat(),
        write_chain=True,
    )
    day = day_start.date().isoformat()
    batches: list[dict[str, Any]] = []
    for u in usage:
        quantity = u.api_calls + int(u.feed_hours * 1000) + int(u.backtest_hours * 1000)
        if quantity <= 0:
            continue
        tier, item_id = _tenant_stripe(engine, u.tenant_id)
        if not item_id and tier == "free":
            continue
        batches.append(
            {
                "batch_id": f"usage-{day}-{u.tenant_id}",
                "tenant_id": u.tenant_id,
                "tier": u.tier,
                "subscription_item": item_id or None,
                "period": day,
                "quantity": quantity,
                "api_calls": u.api_calls,
                "feed_hours": u.feed_hours,
                "backtest_hours": u.backtest_hours,
            }
        )
    return batches


def submit_batch(engine, client, batch: dict[str, Any]) -> None:
    """Submit one batch through the transport (idempotent: re-send is a no-op).

    Each billable metric (``api_calls``, ``feed_hours``, ``backtest_hours``) is
    submitted as its OWN usage record with its own quantity and its own
    idempotency key — never blended into one number at one price. A metric
    already recorded as submitted is skipped. Failures record
    ``status="failed"`` so staleness and retry stay honest — including a paid
    tenant whose batch has no subscription item id (a revenue-bleed alert, never
    a silent drop).
    """
    subscription_item = batch.get("subscription_item")
    metrics = (
        ("api_calls", "api_calls", 1),
        ("feed_hours", "feed_hours", 1000),
        ("backtest_hours", "backtest_hours", 1000),
    )
    submitted_any = False
    with Session(engine) as session:
        for metric, key, scale in metrics:
            quantity = int((batch.get(key, 0) or 0) * scale)
            if quantity <= 0:
                continue
            sync_id = f"{batch['batch_id']}::{metric}"
            existing = _batch_status(engine, sync_id)
            if existing == "submitted":
                continue
            if not subscription_item:
                status, detail = "failed", "missing stripe subscription_item_id"
            else:
                try:
                    client.submit_usage(
                        idempotency_key=sync_id,
                        tenant_id=batch["tenant_id"],
                        subscription_item=subscription_item,
                        quantity=quantity,
                        timestamp=int(_utcnow().timestamp()),
                    )
                    status, detail = "submitted", None
                except Exception as exc:  # transport failure recorded, never thrown away
                    status, detail = "failed", str(exc)
            row = session.execute(
                select(StripeSyncEvent).where(StripeSyncEvent.batch_id == sync_id)
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    StripeSyncEvent(
                        batch_id=sync_id,
                        tenant_id=batch["tenant_id"],
                        period=batch["period"],
                        quantity=quantity,
                        status=status,
                        detail=detail,
                    )
                )
            else:
                row.status, row.detail, row.quantity = status, detail, quantity
            if status == "submitted":
                submitted_any = True
        session.commit()
    if submitted_any:
        from pakhi.ws6 import metrics as _metrics

        _metrics.record_stripe_sync_timestamp(int(_utcnow().timestamp()))


def sync_day(engine, client, day: datetime) -> list[dict[str, Any]]:
    """Daily sync entry point: submit every batch for the completed day.

    Returns the batches; a batch that fails leaves ``status="failed"`` (the
    staleness alert + retry handles it), a re-send of the same day is a no-op.
    """
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    batches = build_usage_batches(engine, day_start, day_end)
    for batch in batches:
        submit_batch(engine, client, batch)
    return batches


def _batch_status(engine, batch_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            select(StripeSyncEvent.status).where(StripeSyncEvent.batch_id == batch_id)
        ).scalar()


def last_sync_timestamp(engine) -> datetime | None:
    """Latest successful submission, or None (never synced) — staleness input."""
    with engine.connect() as conn:
        ts = conn.execute(
            select(func.max(StripeSyncEvent.submitted_utc)).where(
                StripeSyncEvent.status == "submitted"
            )
        ).scalar()
    return ts


def _has_billable_activity(engine) -> bool:
    """True when some paid tenant actually has usage to submit.

    A day (or a fresh deployment) with no billable activity is *neutral*, not
    stale — there is simply nothing to sync. Staleness means sync was expected
    (billable activity exists) but did not happen.
    """
    from pakhi.ws2.db import BacktestJob
    from pakhi.ws4.db import AuditEvent, Tenant
    from pakhi.ws6 import metering

    with engine.connect() as conn:
        if conn.execute(
            select(AuditEvent.id)
            .join(Tenant, Tenant.id == AuditEvent.tenant_id)
            .where(
                AuditEvent.action.notin_(list(metering.INTERNAL_ACTIONS)),
                Tenant.tier != "free",
            )
            .limit(1)
        ).first():
            return True
        if conn.execute(
            select(AuditEvent.id)
            .join(Tenant, Tenant.id == AuditEvent.tenant_id)
            .where(
                AuditEvent.action.in_(["feed.connect", "feed.disconnect"]),
                Tenant.tier != "free",
            )
            .limit(1)
        ).first():
            return True
        if conn.execute(
            select(BacktestJob.id)
            .join(Tenant, Tenant.id == BacktestJob.tenant_id)
            .where(BacktestJob.status == "done", Tenant.tier != "free")
            .limit(1)
        ).first():
            return True
    return False


def is_sync_stale(engine, *, max_age_hours: int | None = None) -> bool:
    """True when no successful sync within the locked cadence (contract §5).

    Also true when a sync failed — a failed submission is not a successful one.
    A deployment with no billable activity (free-only / quiet days) is *not*
    stale: there was simply nothing to submit.
    """
    max_age = max_age_hours or billing_contract()["stripe"]["staleness_alert_hours"]
    last = last_sync_timestamp(engine)
    if last is None:
        return _has_billable_activity(engine)
    if last.tzinfo is None:  # SQLite drops tz; treat stored times as UTC
        last = last.replace(tzinfo=timezone.utc)
    return _utcnow() - last > timedelta(hours=max_age)


class WebhookError(RuntimeError):
    """Signature invalid, payload malformed, or tier mismatch (boot error)."""


def _persist_webhook_event(engine, event_id: str, event_type: str, event) -> bool:
    """Persist the webhook event exactly once. Returns False on a duplicate id."""
    from sqlalchemy.exc import IntegrityError

    from pakhi.ws6.db import StripeWebhookEvent

    with Session(engine) as session:
        session.add(StripeWebhookEvent(event_id=event_id, type=event_type, payload=event))
        try:
            session.commit()
        except IntegrityError:
            return False
    return True


def _webhook_subscription(engine, event: dict, event_id: str, event_type: str) -> dict | None:
    """Handle ``customer.subscription.updated`` / ``.created``.

    Captures the Stripe subscription item id (mirrored for both events) by
    scanning **all** line items and preferring the one whose price matches the
    tenant's tier, falling back to the line item carrying a known price. Returns
    a "skipped" result dict (no usable metadata) or ``None`` on success (handler
    should persist + report applied). Raises ``WebhookError`` on a tier mismatch
    or a missing subscription item id — which must NOT be persisted, so Stripe
    retries until the tenant's tier resolves.
    """
    obj = event.get("data", {}).get("object", {})
    tenant_id = obj.get("metadata", {}).get("tenant_id", "")
    if not tenant_id or not obj.get("items", {}).get("data"):
        return {
            "event_id": event_id,
            "type": event_type,
            "applied": True,
            "note": "no tenant_id/items metadata; skipped",
        }
    items = obj.get("items", {}).get("data", [])
    try:
        tier, _ = _tenant_stripe(engine, tenant_id)
        expected = price_ids().get(tier)
        match = next((it for it in items if it.get("price", {}).get("id") == expected), None)
        if match is None:
            known = set(price_ids().values())
            match = next((it for it in items if it.get("price", {}).get("id") in known), None)
        if match is None:
            match = items[0]
        price_id = match.get("price", {}).get("id", "")
        subscription_item_id = match.get("id", "")
        customer_id = obj.get("customer", "")
        if not price_id:
            return {
                "event_id": event_id,
                "type": event_type,
                "applied": True,
                "note": "no price metadata; skipped",
            }
        if not subscription_item_id:
            raise WebhookError(f"{event_type} missing subscription item id (items.data[].id)")
        sync_subscription_tier(engine, tenant_id, price_id)
    except TierMismatchError as exc:
        raise WebhookError(str(exc)) from exc
    record_subscription(
        engine,
        tenant_id=tenant_id,
        customer_id=customer_id,
        subscription_item_id=subscription_item_id,
    )
    return None


def apply_webhook(engine, raw_body: bytes, signature_header: str, secret: str) -> dict[str, Any]:
    """Apply one Stripe webhook event — applied **once** per Stripe event id.

    - Invalid/missing signature → ``WebhookError`` (never logged-and-applied).
    - Event id already handled → no-op, deduped.
    - The type-specific handler runs **before** the webhook event is persisted.
      If it raises (tier mismatch, unknown tenant, missing item id) the event is
      left uncommitted so Stripe's retry re-runs the handler — once the tenant's
      tier resolves, ``record_subscription`` runs and the item id is captured
      (otherwise a paid tenant would be billed ``failed`` forever). Only on
      success is the event marked handled.
    - ``customer.subscription.updated`` / ``.created`` → subscription ↔ tier
      sync; a price that contradicts the tenant's tier is a ``WebhookError``
      (boot error), never a silent override.
    """
    import json

    from pakhi.ws6.db import StripeWebhookEvent

    if not verify_webhook_signature(raw_body, signature_header, secret):
        raise WebhookError("invalid Stripe signature — rejected")
    try:
        event = json.loads(raw_body.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookError(f"malformed webhook payload: {exc}") from exc
    event_id = str(event.get("id", ""))
    event_type = str(event.get("type", ""))
    if not event_id:
        raise WebhookError("webhook payload has no event id")

    with Session(engine) as session:
        if session.get(StripeWebhookEvent, event_id) is not None:
            return {"event_id": event_id, "type": event_type, "applied": False}

    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        skip = _webhook_subscription(engine, event, event_id, event_type)
        if skip is not None:
            if not _persist_webhook_event(engine, event_id, event_type, event):
                return {"event_id": event_id, "type": event_type, "applied": False}
            return skip
    elif event_type == "customer.subscription.deleted":
        tenant_id = event.get("data", {}).get("object", {}).get("metadata", {}).get("tenant_id", "")
        if not tenant_id:
            if not _persist_webhook_event(engine, event_id, event_type, event):
                return {"event_id": event_id, "type": event_type, "applied": False}
            return {
                "event_id": event_id,
                "type": event_type,
                "applied": True,
                "note": "no tenant_id metadata; skipped",
            }
        try:
            clear_subscription(engine, tenant_id=tenant_id)
        except TierMismatchError as exc:
            raise WebhookError(str(exc)) from exc

    if not _persist_webhook_event(engine, event_id, event_type, event):
        return {"event_id": event_id, "type": event_type, "applied": False}
    return {"event_id": event_id, "type": event_type, "applied": True}
