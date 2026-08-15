"""WS-6 tables — registered on the WS-2 store ``Base`` (single store, single
source of truth). Tables: ``metering_rollups`` (T1), ``metering_suspensions``
(T1). ``init_db`` here is a thin alias so ``pakhi.ws6.db.init_db`` is
unambiguous about what it creates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String

from pakhi.ws2.db import Base

_TZ = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_TZ)


class MeteringRollup(Base):
    """One monthly usage bucket per tenant, sealed as an audit row source.

    The row itself is derived from the audit chain + ``backtest_jobs`` + feed
    events (read-only aggregation; never a separate per-request counter).
    ``tier`` is snapshotted at rollup time so a mid-period tier change is
    visible, and the row is written to the chain as ``action="metering.rollup"``.
    """

    __tablename__ = "metering_rollups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    tier = Column(String, nullable=False)
    period_start = Column(String, nullable=False)  # ISO8601 UTC
    period_end = Column(String, nullable=False)  # ISO8601 UTC (exclusive)
    api_calls = Column(Integer, nullable=False, default=0)
    feed_hours = Column(Float, nullable=False, default=0.0)
    backtest_hours = Column(Float, nullable=False, default=0.0)
    chain_events = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class MeteringSuspension(Base):
    """An active metering-drift suspension (extreme drift, contract-gated).

    Recorded alongside ``revoked_at`` on the tenant's API keys so the lift can
    distinguish "metering-drift suspension" from a manual revoke: only keys
    with an open suspension row are restored by ``lift_suspension``.
    """

    __tablename__ = "metering_suspensions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    reason = Column(String, nullable=False)
    drift_percent = Column(Float, nullable=True)
    key_ids = Column(JSON, nullable=True)  # keys revoked by this suspension only
    suspended_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    lifted_at = Column(DateTime(timezone=True), nullable=True)


class MeteringInvoiceBlock(Base):
    """A metering-drift invoice block (beyond tolerance, below extreme).

    The block flags the tenant so the Stripe sync (T2) refuses to submit usage
    while it is open — invoicing is blocked *and flagged*, never silently
    dropped. Cleared automatically when reconciliation returns to tolerance.
    """

    __tablename__ = "metering_invoice_blocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    period_start = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    drift_percent = Column(Float, nullable=True)
    blocked_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    cleared_at = Column(DateTime(timezone=True), nullable=True)


class StripeSyncEvent(Base):
    """One daily usage submission batch (T2). ``batch_id`` is unique so a
    re-send is a no-op — the batch id is both our idempotency key and the
    Stripe idempotency key; a failed batch leaves ``status="failed"`` so the
    staleness check and retry stay honest.
    """

    __tablename__ = "stripe_sync_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String, nullable=False, unique=True)
    tenant_id = Column(String, nullable=False, index=True)
    period = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="submitted")  # submitted | failed
    detail = Column(String, nullable=True)
    submitted_utc = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class StripeWebhookEvent(Base):
    """Deduped Stripe webhook events (T2): applied once per Stripe event id."""

    __tablename__ = "stripe_webhook_events"

    event_id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    handled_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class TenantTrial(Base):
    """One 14-day trial per org (T3): unique on tenant_id + on contact_id —
    the DB enforces the anti-gaming rule, the audit rows are the evidence.
    Expiry is a downgrade to ``free`` (``downgraded_at``), never a deletion;
    conversion records ``converted_at`` and hooks the subscription flow.
    """

    __tablename__ = "tenant_trials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, unique=True)
    contact_id = Column(String, nullable=False, unique=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    converted_at = Column(DateTime(timezone=True), nullable=True)
    downgraded_at = Column(DateTime(timezone=True), nullable=True)
    tier_at_trial = Column(String, nullable=False, default="free")


class NotificationOutbox(Base):
    """Webhook-deliverable lifecycle notices (T3) — a queue, not email.

    Honest per contract §6: "trial expiring" is webhook-deliverable, not
    email-guaranteed. Rows are enqueued with the audit transition and
    ``delivered_at`` set when the transport accepts them; ``kind`` =
    ``trial.expiring`` | ``trial.expired`` | ``trial.converted``.
    """

    __tablename__ = "notification_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | sent
    enqueued_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    delivered_at = Column(DateTime(timezone=True), nullable=True)


def init_db(engine) -> None:
    """Create WS-2 + WS-4 + WS-6 tables (idempotent)."""
    from pakhi.ws4.db import init_db as ws4_init

    ws4_init(engine)
    Base.metadata.create_all(engine)
