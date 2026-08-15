"""WS-6 T2 — Stripe billing surface (hermetic, SQLite, mocked transport).

Contract §3.2/§5 exactly: daily sync (never end-of-month), idempotent per-day
batches, subscription ↔ tier sync (price mismatch = boot error), webhook
signature verification + dedupe on Stripe event id, staleness > 24 h, and no
card data anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import AuditEvent, Tenant
from pakhi.ws4.service import upsert_tenant
from pakhi.ws6.contract import billing_contract, contract_consistent
from pakhi.ws6.db import StripeSyncEvent, StripeWebhookEvent, init_db
from pakhi.ws6.stripe import (
    TierMismatchError,
    WebhookError,
    apply_webhook,
    build_usage_batches,
    is_sync_stale,
    last_sync_timestamp,
    price_ids,
    submit_batch,
    sync_day,
    sync_subscription_tier,
    tier_for_price,
    verify_webhook_signature,
)

_NOW = datetime.now(timezone.utc)
DAY = (_NOW - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class FakeClient:
    """Matches the transport surface; validates what the real API is strict
    about — ``subscription_item`` must be a Stripe Subscription Item id
    (``si_...``), never the internal tenant id."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit_usage(
        self, *, idempotency_key, tenant_id, subscription_item, quantity, timestamp
    ) -> None:
        if not str(subscription_item).startswith("si_"):
            raise ValueError(
                f"subscription_item for {tenant_id} must be a Stripe item id (si_...), "
                f"got {subscription_item!r}"
            )
        self.submitted.append(
            {
                "idempotency_key": idempotency_key,
                "tenant_id": tenant_id,
                "subscription_item": subscription_item,
                "quantity": quantity,
                "timestamp": timestamp,
            }
        )


def _engine():
    eng = create_engine("sqlite://", future=True)
    init_db(eng)
    return eng


def _seed(eng, tenant: str = "acme", tier: str = "pro", item_id: str = "si_acme") -> None:
    upsert_tenant(eng, tenant_id=tenant, name=tenant, tier=tier)
    if item_id:
        with Session(eng) as session:
            row = session.get(Tenant, tenant)
            row.stripe_customer_id = "cus_1"
            row.stripe_subscription_item_id = item_id
            session.commit()
    rows = [
        {"action": "read", "ts": DAY.isoformat()},
        {"action": "read", "ts": (DAY + timedelta(hours=1)).isoformat()},
        {"action": "read", "ts": (DAY + timedelta(days=1, hours=1)).isoformat()},
    ]
    for i, r in enumerate(rows):
        with Session(eng) as s:
            apply_audit(
                s,
                AuditSpec(
                    request_id=f"req-{i}",
                    tenant_id=tenant,
                    actor_id="t",
                    action=r["action"],
                    resource="res",
                    ts=r["ts"],
                ),
            )
            s.commit()


def _sync_payload(
    event_type: str = "customer.subscription.updated",
    item_id: str = "si_acme",
    event_id: str = "evt_0001",
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "data": {
                "object": {
                    "customer": "cus_1",
                    "metadata": {"tenant_id": "acme"},
                    "items": {"data": [{"id": item_id, "price": {"id": "price_pro"}}]},
                }
            },
        }
    ).encode()


def _sign(payload: bytes, secret: str = "whsec_test") -> str:
    t = str(int(_NOW.timestamp()))
    v1 = hmac.new(secret.encode(), f"{t}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def test_contract_consistent_with_price_ids() -> None:
    assert contract_consistent()
    assert price_ids()["pro"] == "price_pro"
    assert tier_for_price("price_labs") == "labs"
    assert tier_for_price("price_nope") is None
    assert billing_contract()["stripe"]["idempotency"] == "per-day batch id -> usage record id 1:1"


def test_sync_day_submits_idempotent_daily_batches() -> None:
    eng = _engine()
    _seed(eng)
    client = FakeClient()
    batches = sync_day(eng, client, DAY)
    assert batches and batches[0]["batch_id"] == f"usage-{DAY.date().isoformat()}-acme"
    # exactly one successful submission
    assert len(client.submitted) == 1
    # the usage record attaches to the tenant's Stripe subscription *item* id
    # (si_...), never the internal tenant id
    assert client.submitted[0]["subscription_item"] == "si_acme"
    assert client.submitted[0]["tenant_id"] == "acme"
    # re-sync is a no-op: same batch id, nothing new submitted
    sync_day(eng, client, DAY)
    assert len(client.submitted) == 1
    assert len(client.submitted[0]["idempotency_key"]) > 0
    with eng.connect() as conn:
        rows = conn.execute(select(StripeSyncEvent)).all()
    assert len(rows) == 1 and rows[0].status == "submitted"


def test_paid_tenant_without_item_id_alerted_never_dropped() -> None:
    """A paying tenant whose Stripe item id is missing must fail loudly (ops
    alert via staleness + retry), never submit silently and never drop."""
    eng = _engine()
    _seed(eng, item_id=None)  # pro tenant, no subscription_item_id yet
    client = FakeClient()
    batches = sync_day(eng, client, DAY)
    assert batches and batches[0]["subscription_item"] is None
    assert client.submitted == []  # nothing reached the transport
    with eng.connect() as conn:
        rows = conn.execute(select(StripeSyncEvent)).all()
    assert len(rows) == 1 and rows[0].status == "failed"
    assert "subscription_item_id" in (rows[0].detail or "")
    assert is_sync_stale(eng) is True  # the failure keeps the alert honest


def test_free_tenant_without_item_id_skipped_silently() -> None:
    """A free/trial tenant has no subscription — no batch, no failure noise."""
    eng = _engine()
    _seed(eng, tier="free", item_id=None)
    client = FakeClient()
    batches = sync_day(eng, client, DAY)
    assert batches == []
    assert client.submitted == []
    with eng.connect() as conn:
        rows = conn.execute(select(StripeSyncEvent)).all()
    assert rows == []


def test_webhook_captures_and_stores_subscription_item_id() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    payload = _sync_payload(item_id="si_live_123")
    result = apply_webhook(eng, payload, _sign(payload), "whsec_test")
    assert result["applied"] is True
    with Session(eng) as session:
        row = session.get(Tenant, "acme")
    assert row.stripe_customer_id == "cus_1"
    assert row.stripe_subscription_item_id == "si_live_123"
    # the sync now attaches usage to the captured item id
    _seed(eng, item_id=None)
    with Session(eng) as session:
        row = session.get(Tenant, "acme")
        row.stripe_subscription_item_id = "si_live_123"
        session.commit()
    client = FakeClient()
    sync_day(eng, client, DAY)
    assert client.submitted[0]["subscription_item"] == "si_live_123"


def test_webhook_updated_without_item_id_is_boot_error() -> None:
    """A signed subscription.updated that omits the item id cannot be billed —
    reject it rather than silently lose the linkage."""
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    payload = _sync_payload(item_id="")
    with pytest.raises(WebhookError, match="subscription item id"):
        apply_webhook(eng, payload, _sign(payload), "whsec_test")


def test_subscription_deleted_clears_linkage() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    apply_webhook(eng, _sync_payload(), _sign(_sync_payload()), "whsec_test")
    deleted = _sync_payload(event_type="customer.subscription.deleted", event_id="evt_0002")
    result = apply_webhook(eng, deleted, _sign(deleted), "whsec_test")
    assert result["applied"] is True
    with Session(eng) as session:
        row = session.get(Tenant, "acme")
        actions = set(session.execute(select(AuditEvent.action)).scalars())
    assert row.stripe_customer_id is None
    assert row.stripe_subscription_item_id is None
    assert "billing.subscription_removed" in actions


def test_batch_never_double_submitted_on_retry() -> None:
    eng = _engine()
    _seed(eng)
    client = FakeClient()
    batches = build_usage_batches(eng, DAY, DAY + timedelta(days=1))
    submit_batch(eng, client, batches[0])
    submit_batch(eng, client, batches[0])  # retry
    assert len(client.submitted) == 1


def test_failed_batch_recorded_for_staleness() -> None:
    eng = _engine()
    _seed(eng)
    batches = build_usage_batches(eng, DAY, DAY + timedelta(days=1))

    class BoomClient:
        def submit_usage(self, **kw) -> None:
            raise RuntimeError("stripe down")

    submit_batch(eng, BoomClient(), batches[0])
    from sqlalchemy.orm import Session

    with Session(eng) as session:
        row = session.execute(select(StripeSyncEvent)).scalar_one()
    assert row.status == "failed"
    assert is_sync_stale(eng) is True  # a failure is not a successful sync


def test_staleness_alert_after_cadence() -> None:
    eng = _engine()
    _seed(eng)
    assert is_sync_stale(eng) is True  # never synced
    sync_day(eng, FakeClient(), DAY)
    assert is_sync_stale(eng) is False
    # Simulate a sync 30 h ago (> 24 h cadence) -> stale
    with eng.connect() as conn:
        conn.execute(
            StripeSyncEvent.__table__.update().values(submitted_utc=_NOW - timedelta(hours=30))
        )
        conn.commit()
    assert is_sync_stale(eng) is True
    assert last_sync_timestamp(eng) is not None


def test_subscription_tier_sync_and_mismatch_boot_error() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    assert sync_subscription_tier(eng, "acme", "price_pro") == "pro"
    with pytest.raises(TierMismatchError):
        sync_subscription_tier(eng, "acme", "price_labs")
    with pytest.raises(TierMismatchError):
        sync_subscription_tier(eng, "ghost", "price_pro")
    with eng.connect() as conn:
        tier = conn.execute(select(Tenant.tier).where(Tenant.id == "acme")).scalar()
    assert tier == "pro"  # never silently overridden


def test_webhook_signature_verify() -> None:
    payload = b'{"id":"evt_1","type":"x"}'
    good = _sign(payload)
    assert verify_webhook_signature(payload, good, "whsec_test")
    assert not verify_webhook_signature(payload, good, "whsec_wrong")
    assert not verify_webhook_signature(b"tampered", good, "whsec_test")
    assert not verify_webhook_signature(payload, "v1=deadbeef", "whsec_test")
    assert not verify_webhook_signature(payload, "", "whsec_test")


def test_webhook_applied_once_deduped_by_event_id() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    payload = _sync_payload()
    header = _sign(payload)
    first = apply_webhook(eng, payload, header, "whsec_test")
    assert first["applied"] is True
    # duplicate delivery of the same event id -> no-op
    second = apply_webhook(eng, payload, header, "whsec_test")
    assert second["applied"] is False
    with eng.connect() as conn:
        assert conn.execute(select(StripeWebhookEvent.event_id)).scalar_one() == "evt_0001"


def test_webhook_invalid_signature_rejected() -> None:
    eng = _engine()
    payload = _sync_payload()
    with pytest.raises(WebhookError):
        apply_webhook(eng, payload, "v1=bad", "whsec_test")
    with eng.connect() as conn:
        assert conn.execute(select(StripeWebhookEvent.event_id)).scalar() is None


def test_webhook_tier_mismatch_is_boot_error() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="labs")
    payload = _sync_payload()  # says price_pro but tenant is labs
    with pytest.raises(WebhookError):
        apply_webhook(eng, payload, _sign(payload), "whsec_test")


def test_no_card_fields_anywhere_in_schemas() -> None:
    import pakhi.api  # noqa: F401  (import surface to catch schema drift)

    billing_files = [
        "pakhi/ws6/stripe.py",
        "scripts/run_ws6_stripe_sync.py",
    ]
    for rel in billing_files:
        src = Path(rel).read_text()
        for tok in ("card_number", "cvc", "cvv", "exp_month", "exp_year", "pan"):
            assert tok not in src, f"{rel} must never touch {tok}"
    assert billing_contract()["stripe"]["card_data"] == "never stored on our servers"
