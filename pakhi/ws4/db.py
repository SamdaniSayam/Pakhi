"""WS-4 tables — registered on the WS-2 store ``Base`` so the existing
``init_db(engine)`` creates them alongside the reference tables (single store,
single source of truth; no new service). Tables: ``users``, ``refresh_tokens``
(T1); ``tenants``, ``api_keys`` (T2); ``audit_events`` (T4). ``init_db`` here is
a thin alias so ``pakhi.ws4.db.init_db`` is unambiguous about what it creates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String

from pakhi.ws2.db import Base

_TZ = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_TZ)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    tier = Column(String, nullable=False, default="free")  # free | pro | labs
    limit_per_min = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_by = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_item_id = Column(String, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)  # sub claim
    tenant_id = Column(String, nullable=False, index=True)
    roles = Column(JSON, nullable=False)
    tier = Column(String, nullable=False, default="free")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_by = Column(String, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)  # prefix, e.g. pk_live_ab12...
    tenant_id = Column(String, nullable=False, index=True)
    key_hash = Column(String, nullable=False, unique=True)  # sha256 of raw key
    prefix = Column(String, nullable=False)
    environment = Column(String, nullable=False, default="test")  # live | test
    roles = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token_hash = Column(String, primary_key=True)  # sha256 of the opaque token
    user_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False)
    family_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by = Column(String, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    actor_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    resource_id = Column(String, nullable=True)
    outcome = Column(String, nullable=False, default="success")
    ts = Column(String, nullable=False)  # ISO8601 UTC
    prev_hash = Column(String, nullable=True)
    hash = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=True)


def init_db(engine) -> None:
    """Create WS-2 + WS-4 tables (idempotent)."""
    Base.metadata.create_all(engine)


def migrate(engine) -> None:
    """One-shot additive migrations for existing stores (idempotent).

    ``create_all`` does not alter existing tables, so a pre-WS-4 store that
    already has a ``backtest_jobs`` table needs the nullable ``tenant_id``
    column added in place. NULL rows read as the default tenant
    ("pakhi-internal") per the WS-4 scoping rules. Safe to run on every boot:
    the column presence is checked before altering.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if insp.has_table("backtest_jobs"):
        cols = {c["name"] for c in insp.get_columns("backtest_jobs")}
        if "tenant_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE backtest_jobs ADD COLUMN tenant_id VARCHAR"))

    if insp.has_table("tenants"):
        cols = {c["name"] for c in insp.get_columns("tenants")}
        if "stripe_subscription_item_id" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN stripe_subscription_item_id VARCHAR")
                )
