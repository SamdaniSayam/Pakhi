"""WS-6 T1 metering — read-only usage aggregation over durable sources.

The meter is an **aggregation**, never a second counter. Sources:

- ``api_call``: WS-4 ``audit_events`` rows — the hash-chained set of successful
  authenticated requests (status < 400). Internal metering/feed/suspension
  rows (``INTERNAL_ACTIONS``) are excluded so the count is billable API calls
  only. 4xx (incl. 429) and 5xx/503 never reach the chain and are never billed.
- ``feed_hour``: ``feed.connect``/``feed.disconnect`` audit rows paired by
  ``session_id``; each session bills ``floor(duration_hours)`` (contract:
  "active ≥ 1 h, floored" — generous to the client).
- ``backtest_hour``: ``backtest_jobs`` rows with ``status="done"`` billed as
  wall-clock ``started_at``→``finished_at``.

Rollups are written to ``metering_rollups`` and sealed into the chain as
``action="metering.rollup"`` so billing inputs inherit the chain's
tamper-evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pakhi.ws2.db import BacktestJob
from pakhi.ws4.db import AuditEvent, Tenant
from pakhi.ws6.db import MeteringRollup

# Internal bookkeeping rows that are audit rows but never API calls. The
# lifecycle transitions (trial/onboarding/billing) are automation, not client
# requests — billing them would inflate the invoice (T3 keeps the meter honest).
INTERNAL_ACTIONS = frozenset(
    {
        "metering.rollup",
        "metering.suspend",
        "metering.unsuspend",
        "metering.s1",
        "metering.block_invoice",
        "metering.cleared",
        "feed.connect",
        "feed.disconnect",
        "trial.started",
        "trial.expiring",
        "trial.expired",
        "trial.converted",
        "trial.denied",
        "billing.subscription_created",
        "billing.subscription_removed",
        "billing.tier_upgrade",
        "billing.tier_downgrade",
        "onboarding.tenant_provisioned",
    }
)

DEFAULT_TENANT_ID = "pakhi-internal"
_MIN_FEED_HOURS = 1.0  # contract: sessions < 1 h contribute 0; hours floored


@dataclass
class Usage:
    tenant_id: str
    tier: str
    api_calls: int
    feed_hours: float
    backtest_hours: float
    chain_events: int


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def chain_events(engine, start: str, end: str) -> list[AuditEvent]:
    """Audit rows in [start, end) — the billable surface plus internal rows."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(AuditEvent).where(AuditEvent.ts >= start, AuditEvent.ts < end)
        ).all()
        return list(rows)


def api_calls_by_tenant(events: Iterable[AuditEvent]) -> dict[str, int]:
    """Billable API calls per tenant: chain rows minus internal actions."""
    counts: dict[str, int] = {}
    for ev in events:
        if ev.action in INTERNAL_ACTIONS:
            continue
        tenant = ev.tenant_id or DEFAULT_TENANT_ID
        counts[tenant] = counts.get(tenant, 0) + 1
    return counts


def feed_hours_by_tenant(engine, start: str, end: str) -> dict[str, float]:
    """Billable feed hours per tenant from paired connect/disconnect rows."""
    sessions: dict[tuple[str, str], list[datetime]] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            select(AuditEvent).where(
                AuditEvent.action.in_(["feed.connect", "feed.disconnect"]),
                AuditEvent.ts >= start,
                AuditEvent.ts < end,
            )
        ).all()
    for ev in rows:
        key = (ev.tenant_id or DEFAULT_TENANT_ID, str((ev.payload or {}).get("session_id", "")))
        sessions.setdefault(key, []).append(_iso(ev.ts))
    hours: dict[str, float] = {}
    for (tenant, _sid), stamps in sessions.items():
        total = 0.0
        for i in range(0, len(stamps) - 1, 2):
            delta = (stamps[i + 1] - stamps[i]).total_seconds() / 3600.0
            total += max(0.0, int(delta)) if delta >= _MIN_FEED_HOURS else 0.0
        if total > 0:
            hours[tenant] = hours.get(tenant, 0.0) + total
    return hours


def backtest_hours_by_tenant(engine, start: str, end: str) -> dict[str, float]:
    """Billable compute hours per tenant from completed backtest jobs."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(BacktestJob).where(
                BacktestJob.status == "done",
                BacktestJob.started_at.is_not(None),
                BacktestJob.finished_at.is_not(None),
            )
        ).all()
    hours: dict[str, float] = {}
    for job in rows:
        started, finished = _utc(job.started_at), _utc(job.finished_at)
        if finished <= started or not (start <= started.isoformat() < end):
            continue
        tenant = job.tenant_id or DEFAULT_TENANT_ID
        hours[tenant] = hours.get(tenant, 0.0) + (finished - started).total_seconds() / 3600.0
    return hours


def tier_for(engine, tenant_id: str) -> str:
    with engine.connect() as conn:
        tier = conn.execute(select(Tenant.tier).where(Tenant.id == tenant_id)).scalar()
    return tier if tier else "free"


def meter_usage(engine, start: str, end: str) -> list[Usage]:
    """Usage per tenant for [start, end), tier snapshotted at rollup time."""
    events = chain_events(engine, start, end)
    calls = api_calls_by_tenant(events)
    feeds = feed_hours_by_tenant(engine, start, end)
    backs = backtest_hours_by_tenant(engine, start, end)
    tenants = sorted(set(calls) | set(feeds) | set(backs))
    return [
        Usage(
            tenant_id=t,
            tier=tier_for(engine, t),
            api_calls=calls.get(t, 0),
            feed_hours=round(feeds.get(t, 0.0), 3),
            backtest_hours=round(backs.get(t, 0.0), 3),
            chain_events=sum(1 for e in events if (e.tenant_id or DEFAULT_TENANT_ID) == t),
        )
        for t in tenants
    ]


def rollup(engine, start: str, end: str, *, write_chain: bool = True) -> list[Usage]:
    """Run the meter and write ``metering_rollups`` (+ chain rows when asked)."""
    usage = meter_usage(engine, start, end)
    if not usage:
        return usage
    with Session(engine) as session:
        for u in usage:
            session.add(
                MeteringRollup(
                    tenant_id=u.tenant_id,
                    tier=u.tier,
                    period_start=start,
                    period_end=end,
                    api_calls=u.api_calls,
                    feed_hours=u.feed_hours,
                    backtest_hours=u.backtest_hours,
                    chain_events=u.chain_events,
                )
            )
        if write_chain:
            from pakhi.ws4.audit_events import AuditSpec, apply_audit

            for u in usage:
                apply_audit(
                    session,
                    AuditSpec(
                        request_id=f"metering-{start}-{u.tenant_id}",
                        tenant_id=u.tenant_id,
                        actor_id="ws6.meter",
                        action="metering.rollup",
                        resource="metering_rollup",
                        payload={
                            "period_start": start,
                            "period_end": end,
                            "api_calls": u.api_calls,
                            "feed_hours": u.feed_hours,
                            "backtest_hours": u.backtest_hours,
                        },
                    ),
                )
        session.commit()
    return usage


def rollup_calls_for(engine, tenant_id: str, start: str, end: str) -> int | None:
    """The rollup's recorded api_calls for a tenant/period (for reconciliation)."""
    with engine.connect() as conn:
        return conn.execute(
            select(func.max(MeteringRollup.api_calls)).where(
                MeteringRollup.tenant_id == tenant_id,
                MeteringRollup.period_start == start,
                MeteringRollup.period_end == end,
            )
        ).scalar()
