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

    ``client.submit_usage`` is called with the idempotency key and the tenant's
    Stripe subscription item id. A batch already recorded as submitted is
    skipped. Failures record ``status="failed"`` so staleness and retry stay
    honest — including a paid tenant whose batch has no subscription item id
    (a revenue-bleed alert, never a silent drop).
    """
    existing = _batch_status(engine, batch["batch_id"])
    if existing == "submitted":
        return
    subscription_item = batch.get("subscription_item")
    if not subscription_item:
        status, detail = "failed", "missing stripe subscription_item_id"
    else:
        try:
            client.submit_usage(
                idempotency_key=batch["batch_id"],
                tenant_id=batch["tenant_id"],
                subscription_item=subscription_item,
                quantity=batch["quantity"],
                timestamp=int(_utcnow().timestamp()),
            )
            status, detail = "submitted", None
        except Exception as exc:  # transport failure recorded, never thrown away
            status, detail = "failed", str(exc)
    with Session(engine) as session:
        if existing is None:
            session.add(
                StripeSyncEvent(
                    batch_id=batch["batch_id"],
                    tenant_id=batch["tenant_id"],
                    period=batch["period"],
                    quantity=batch["quantity"],
                    status=status,
                    detail=detail,
                )
            )
        else:
            row = session.execute(
                select(StripeSyncEvent).where(StripeSyncEvent.batch_id == batch["batch_id"])
            ).scalar_one()
            row.status, row.detail = status, detail
        session.commit()
    if status == "submitted":
        from pakhi.ws6 import metrics

        metrics.record_stripe_sync_timestamp(int(_utcnow().timestamp()))


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


def is_sync_stale(engine, *, max_age_hours: int | None = None) -> bool:
    """True when no successful sync within the locked cadence (contract §5).

    Also true when a sync failed — a failed submission is not a successful one.
    """
    max_age = max_age_hours or billing_contract()["stripe"]["staleness_alert_hours"]
    last = last_sync_timestamp(engine)
    if last is None:
        return True
    if last.tzinfo is None:  # SQLite drops tz; treat stored times as UTC
        last = last.replace(tzinfo=timezone.utc)
    return _utcnow() - last > timedelta(hours=max_age)


class WebhookError(RuntimeError):
    """Signature invalid, payload malformed, or tier mismatch (boot error)."""


def apply_webhook(engine, raw_body: bytes, signature_header: str, secret: str) -> dict[str, Any]:
    """Apply one Stripe webhook event — applied **once** per Stripe event id.

    - Invalid/missing signature → ``WebhookError`` (never logged-and-applied).
    - Event id already handled (or currently being handled) → no-op, deduped.
    - ``customer.subscription.updated`` → subscription ↔ tier sync; a price
      that contradicts the tenant's tier is a ``WebhookError`` (boot error),
      never a silent override.
    """
    import json

    from sqlalchemy.exc import IntegrityError

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
        session.add(StripeWebhookEvent(event_id=event_id, type=event_type, payload=event))
        try:
            session.commit()
        except IntegrityError:
            return {"event_id": event_id, "type": event_type, "applied": False}

    if event_type == "customer.subscription.updated":
        obj = event.get("data", {}).get("object", {})
        items = obj.get("items", {}).get("data", [{}])[0]
        price_id = items.get("price", {}).get("id", "")
        subscription_item_id = items.get("id", "")
        customer_id = obj.get("customer", "")
        tenant_id = obj.get("metadata", {}).get("tenant_id", "")
        if not tenant_id or not price_id:
            return {
                "event_id": event_id,
                "type": event_type,
                "applied": True,
                "note": "no tenant_id/price metadata; skipped",
            }
        if not subscription_item_id:
            raise WebhookError(
                "customer.subscription.updated missing subscription item id (items.data[0].id)"
            )
        try:
            sync_subscription_tier(engine, tenant_id, price_id)
        except TierMismatchError as exc:
            raise WebhookError(str(exc)) from exc
            
        record_subscription(
            engine,
            tenant_id=tenant_id,
            customer_id=customer_id,
            subscription_item_id=subscription_item_id,
        )
    elif event_type == "customer.subscription.deleted":
        tenant_id = event.get("data", {}).get("object", {}).get("metadata", {}).get("tenant_id", "")
        if not tenant_id:
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
    return {"event_id": event_id, "type": event_type, "applied": True}
