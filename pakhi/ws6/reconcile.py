"""WS-6 T1 reconciliation — durable money sources only (contract §4).

Two targets, never the Redis limiters (a control, not a ledger):

1. **Chain — exact (identity).** The rollup is an aggregation of the audit
   chain, so rollup totals must equal an independent chain recount exactly.
   A mismatch is a rollup bug.
2. **Access logs — tolerance.** Chain-derived counts vs the WS-5 structured
   access-log counts for the same tenant within ``tolerance_percent``. This
   catches the one hole the chain alone cannot: **lost audit rows**.

Drift response (contract §4.1) — never a silent drop: beyond tolerance is an
**S1 incident** with invoicing blocked *and flagged*; extreme (beyond the hard
threshold, or an un-producible rollup) additionally **temporarily suspends the
tenant's API keys** to stop un-metered consumption, auto-lifted once
reconciliation returns to tolerance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import ApiKey
from pakhi.ws6 import metering
from pakhi.ws6.contract import hard_threshold_percent, tolerance_percent
from pakhi.ws6.db import MeteringInvoiceBlock, MeteringSuspension

logger = logging.getLogger(__name__)

NORMAL = "normal"
DRIFT = "drift"
EXTREME = "extreme"


@dataclass
class ReconciliationReport:
    tenant_id: str
    chain_calls: int  # independent recount of the audit chain
    rollup_calls: int  # what the meter recorded
    log_calls: int  # structured access-log count (external input)
    chain_ok: bool  # rollup == chain (exact, by construction)
    log_drift_percent: float | None  # |chain - log| / chain * 100
    state: str = NORMAL
    actions: list[str] = field(default_factory=list)


def drift_percent(chain_count: int, log_count: int) -> float | None:
    """|chain - log| / chain * 100; None when chain_count == 0."""
    if chain_count == 0:
        return None
    return round(abs(chain_count - log_count) / chain_count * 100.0, 4)


def classify(chain_count: int, log_count: int) -> str:
    """Contract §4.1 state machine (tolerance / hard threshold)."""
    if chain_count == 0:
        # A tenant with zero chain rows but access-log traffic lost audit rows
        # (the one hole the chain alone cannot see) — treat as EXTREME drift,
        # not NORMAL, so S1 / block / suspend fire exactly as for the extreme
        # branch.
        return EXTREME if log_count > 0 else NORMAL
    pct = drift_percent(chain_count, log_count)
    if pct > hard_threshold_percent():
        return EXTREME
    if pct > tolerance_percent():
        return DRIFT
    return NORMAL


def reconcile(
    engine,
    start: str,
    end: str,
    access_log_counts: dict[str, int],
) -> list[ReconciliationReport]:
    """Reconcile the meter for [start, end) against chain + access logs.

    ``access_log_counts`` maps tenant_id → structured access-log request count
    for the period (the WS-5 log sink provides it; external to the app).
    """
    events = metering.chain_events(engine, start, end)
    chain_calls = metering.api_calls_by_tenant(events)
    tenants = sorted(set(chain_calls) | set(access_log_counts))
    reports: list[ReconciliationReport] = []
    for tenant in tenants:
        chain = chain_calls.get(tenant, 0)
        rollup = metering.rollup_calls_for(engine, tenant, start, end) or 0
        log_count = access_log_counts.get(tenant, 0)
        chain_ok = rollup == chain
        pct = drift_percent(chain, log_count)
        if not chain_ok:
            state = EXTREME if pct is None or pct > tolerance_percent() else DRIFT
        else:
            state = classify(chain, log_count)
        actions: list[str] = []
        if not chain_ok:
            actions.append("rollup-mismatch")
        if pct is not None and pct > tolerance_percent():
            actions.append("log-drift")
        reports.append(
            ReconciliationReport(
                tenant_id=tenant,
                chain_calls=chain,
                rollup_calls=rollup,
                log_calls=log_count,
                chain_ok=chain_ok,
                log_drift_percent=pct,
                state=state,
                actions=actions,
            )
        )
    return reports


def handle_drift(engine, reports: list[ReconciliationReport]) -> list[str]:
    """Act on drift per contract §4.1; returns a list of S1 descriptions."""
    incidents: list[str] = []
    for r in reports:
        if r.state == NORMAL:
            _auto_clear(engine, r)
            continue
        desc = (
            f"tenant={r.tenant_id} state={r.state} rollup={r.rollup_calls} "
            f"chain={r.chain_calls} log={r.log_calls} drift={r.log_drift_percent}"
        )
        incidents.append(desc)
        _s1(engine, r, desc)
        if r.state == DRIFT:
            _block_invoice(engine, r)
        elif r.state == EXTREME:
            _block_invoice(engine, r)
            _suspend(engine, r)
    return incidents


def _audit(session, tenant_id: str, action: str, payload: dict) -> None:
    apply_audit(
        session,
        AuditSpec(
            request_id=f"metering-{action}-{tenant_id}",
            tenant_id=tenant_id,
            actor_id="ws6.meter",
            action=action,
            resource="metering",
            payload=payload,
        ),
    )


def _s1(engine, r: ReconciliationReport, desc: str) -> None:
    logger.error("S1 metering reconciliation drift: %s", desc)
    with Session(engine) as session:
        _audit(
            session,
            r.tenant_id,
            "metering.s1",
            {"kind": "reconciliation-drift", "state": r.state, "detail": desc},
        )
        session.commit()


def _block_invoice(engine, r: ReconciliationReport) -> None:
    with Session(engine) as session:
        session.add(
            MeteringInvoiceBlock(
                tenant_id=r.tenant_id,
                period_start="-",
                reason=f"{r.state}: rollup={r.rollup_calls} chain={r.chain_calls} "
                f"log={r.log_calls} drift={r.log_drift_percent}",
                drift_percent=r.log_drift_percent,
            )
        )
        _audit(session, r.tenant_id, "metering.block_invoice", {"state": r.state})
        session.commit()


def _suspend(engine, r: ReconciliationReport) -> None:
    with Session(engine) as session:
        existing = (
            session.execute(
                select(MeteringSuspension).where(
                    MeteringSuspension.tenant_id == r.tenant_id,
                    MeteringSuspension.lifted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if existing:
            session.commit()
            return
        rows = (
            session.execute(
                select(ApiKey).where(
                    ApiKey.tenant_id == r.tenant_id,
                    ApiKey.revoked_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            session.commit()
            return
        now = datetime.now(timezone.utc)
        session.add(
            MeteringSuspension(
                tenant_id=r.tenant_id,
                reason="extreme metering drift",
                drift_percent=r.log_drift_percent,
                key_ids=[k.id for k in rows],
                suspended_at=now,  # the exact time the keys below are revoked
            )
        )
        for k in rows:
            k.revoked_at = now
        _audit(
            session,
            r.tenant_id,
            "metering.suspend",
            {"drift_percent": r.log_drift_percent, "key_ids": [k.id for k in rows]},
        )
        session.commit()


def _lift_suspensions(session: Session, suspensions: list) -> int:
    """Lift suspensions, restoring ONLY the system's own key revocations.

    ``_suspend`` revokes each key at the exact ``suspended_at`` timestamp (stored
    on the suspension row). A key whose ``revoked_at`` still equals that
    timestamp is the system's suspension revoke and is restored. A key an admin
    later revoked manually (``revoked_at`` moved to the admin's time) is
    **left revoked** — the lift must never un-revoke a human decision. Returns
    the number of keys restored.
    """
    now = datetime.now(timezone.utc)
    restored = 0
    for s in suspensions:
        if s.lifted_at is not None:
            continue
        s.lifted_at = now
        for key_id in s.key_ids or []:
            key = session.get(ApiKey, key_id)
            if key is None:
                continue
            if key.revoked_at is not None and key.revoked_at == s.suspended_at:
                key.revoked_at = None
                restored += 1
    return restored


def _auto_clear(engine, r: ReconciliationReport) -> None:
    """Auto-lift blocks + suspensions when reconciliation returns to normal."""
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        blocks = (
            session.execute(
                select(MeteringInvoiceBlock).where(
                    MeteringInvoiceBlock.tenant_id == r.tenant_id,
                    MeteringInvoiceBlock.cleared_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if blocks:
            for b in blocks:
                b.cleared_at = now
            _audit(session, r.tenant_id, "metering.cleared", {"cleared": "invoice-block"})
        suspensions = (
            session.execute(
                select(MeteringSuspension).where(
                    MeteringSuspension.tenant_id == r.tenant_id,
                    MeteringSuspension.lifted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if suspensions:
            restored = _lift_suspensions(session, suspensions)
            _audit(
                session,
                r.tenant_id,
                "metering.unsuspend",
                {
                    "suspension_ids": [s.id for s in suspensions],
                    "keys_restored": restored,
                },
            )
        if blocks or suspensions:
            session.commit()


def lift_suspension(engine, tenant_id: str) -> bool:
    """Explicit lift (also used by tests / manual intervention)."""
    with Session(engine) as session:
        rows = (
            session.execute(
                select(MeteringSuspension).where(
                    MeteringSuspension.tenant_id == tenant_id,
                    MeteringSuspension.lifted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return False
        restored = _lift_suspensions(session, rows)
        _audit(
            session,
            tenant_id,
            "metering.unsuspend",
            {"explicit": True, "keys_restored": restored},
        )
        session.commit()
        return True
