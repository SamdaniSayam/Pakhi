"""WS-6 T4 — support SLA: deterministic triage + status-page incident feed.

Severities, response targets, triage keywords, and the escalation matrix are
**locked in the contract twin** (§7) — this module only reads them, so a test
pins the parser against the twin (single source of truth rule). An S1 is an
incident: written to the WS-5 ``/v1/status`` incident feed (read straight from
the audit chain, so it is durable evidence, not a config file) and into the
chain by the S1 path itself (T1 ``metering.s1`` / ``metering.suspend``).

Targets are operational commitments, distinct from the conditional 99.9 %
offer (WS-5 window, untouched by WS-6).
"""

from __future__ import annotations

from sqlalchemy import select

from pakhi.ws4.db import AuditEvent
from pakhi.ws6.contract import billing_contract

INCIDENT_ACTIONS = frozenset({"metering.s1", "metering.suspend", "metering.block_invoice"})

_SEVERITY_ORDER = ("S1", "S2", "S3")


def support_sla() -> dict:
    return billing_contract()["support_sla"]


def response_target(severity: str) -> str | None:
    return support_sla()["severities"].get(severity, {}).get("target")


def escalation_path(severity: str) -> str | None:
    return support_sla()["escalation"].get(severity)


def classify_severity(text: str, *, default: str = "S3") -> str:
    """Deterministic triage: locked keywords from the twin, priority S1→S2→S3.

    Case-insensitive substring match on the *first keyword hit*; unmatched text
    falls through to ``S3`` (minor bug / question) — never raises, never
    classifies upward without a keyword.
    """
    lowered = text.lower()
    for severity in _SEVERITY_ORDER:
        for keyword in support_sla()["severities"][severity]["keywords"]:
            if keyword in lowered:
                return severity
    return default


def recent_incidents(engine, limit: int = 5) -> list[dict]:
    """Recent S1-class audit-chain rows for the ``/v1/status`` incident feed.

    Read-only over the WS-4 chain: the incident *is* the audit row, so the
    feed cannot drift from the ledger of truth.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            select(AuditEvent)
            .where(AuditEvent.action.in_(INCIDENT_ACTIONS))
            .order_by(AuditEvent.ts.desc())
            .limit(limit)
        ).all()
    return [
        {
            "ts": r.ts,
            "tenant": r.tenant_id,
            "action": r.action,
            "summary": (r.payload or {}).get("reason")
            or (r.payload or {}).get("description")
            or r.action,
        }
        for r in rows
    ]
