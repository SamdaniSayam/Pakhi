"""WS-6 T1 feed metering — connect/disconnect audit rows for /stream/signals.

The ``feed_hour`` billable unit needs a durable connect→disconnect record.
The WS-4 audit chain is that record: ``feed.connect`` / ``feed.disconnect``
rows carry a ``session_id`` and the route pairs them to bill floored hours.

Recording is best-effort by design (the metering failure is contained by
reconciliation drift → S1, never by breaking the stream): a missing feed row
surfaces as a chain-vs-access-log drift, which the contract turns into an
incident, not a silent un-billed hour.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import ApiKey

SID_SCOPE_KEY = "ws6_feed_session_id"


def resolve_tenant_id(engine, key_hash: str | None) -> str | None:
    """Map an API-key hash to its tenant; None when unknown (unauthenticated)."""
    if not key_hash or engine is None:
        return None
    with engine.connect() as conn:
        from sqlalchemy import select

        return conn.execute(select(ApiKey.tenant_id).where(ApiKey.key_hash == key_hash)).scalar()


def new_session_id() -> str:
    return uuid.uuid4().hex


def record_connect(engine, tenant_id: str, session_id: str, request_id: str) -> None:
    if engine is None or tenant_id is None:
        return
    with Session(engine) as session:
        apply_audit(
            session,
            AuditSpec(
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id="feed",
                action="feed.connect",
                resource="stream/signals",
                payload={"session_id": session_id},
            ),
        )
        session.commit()


def record_disconnect(engine, tenant_id: str, session_id: str, request_id: str) -> None:
    if engine is None or tenant_id is None:
        return
    with Session(engine) as session:
        apply_audit(
            session,
            AuditSpec(
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id="feed",
                action="feed.disconnect",
                resource="stream/signals",
                payload={"session_id": session_id},
            ),
        )
        session.commit()
