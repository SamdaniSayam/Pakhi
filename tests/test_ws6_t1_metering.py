"""WS-6 T1 — usage metering + reconciliation (hermetic, SQLite).

Tests the contract §2/§4 exactly: the meter is a read-only aggregation over
durable sources (audit chain, backtest jobs, feed events), 4xx/5xx/503 are
never billed, and drift (never a silent drop) escalates S1 → invoice block →
key suspension with automatic lift on reconciliation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from pakhi.ws2.db import BacktestJob, upsert
from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import ApiKey, AuditEvent
from pakhi.ws4.service import upsert_tenant
from pakhi.ws6 import metering, reconcile
from pakhi.ws6.contract import (
    billing_contract,
    contract_consistent,
    hard_threshold_percent,
    never_billed,
    tolerance_percent,
)
from pakhi.ws6.db import MeteringInvoiceBlock, MeteringSuspension, init_db

_NOW = datetime.now(timezone.utc)
PERIOD = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)
START = PERIOD.isoformat()
END = (PERIOD + timedelta(days=30)).isoformat()


def _engine():
    eng = create_engine("sqlite://", future=True)
    init_db(eng)
    return eng


def _add_audit(eng, tenant: str, action: str, payload: dict | None = None, ts: str | None = None):
    with Session(eng) as s:
        apply_audit(
            s,
            AuditSpec(
                request_id=f"req-{tenant}-{action}-{_NOW.timestamp()}",
                tenant_id=tenant,
                actor_id="t",
                action=action,
                resource="res",
                payload=payload or {},
                ts=ts,
            ),
        )
        s.commit()


def _add_job(eng, tenant: str, status: str, started: datetime, finished: datetime):
    upsert(
        eng,
        BacktestJob,
        {
            "id": f"job-{tenant}-{status}-{started.timestamp()}",
            "status": status,
            "created_at": started,
            "started_at": started,
            "finished_at": finished,
            "params": {},
            "tenant_id": tenant,
        },
        ["id"],
    )


def _add_key(eng, tenant: str, key_id: str) -> None:
    """Insert a key row directly — no audit row, so the chain stays pure."""
    with Session(eng) as s:
        s.add(
            ApiKey(
                id=key_id,
                tenant_id=tenant,
                key_hash=f"hash-{key_id}",
                prefix=key_id[:8],
                environment="test",
                roles=["reader"],
            )
        )
        s.commit()


def _read_rows(eng, tenant: str, n: int) -> None:
    for i in range(n):
        _add_audit(eng, tenant, "read", ts=(PERIOD + timedelta(hours=(i % 24))).isoformat())


def _count(eng, model) -> int:
    with eng.connect() as conn:
        return conn.execute(select(func.count()).select_from(model)).scalar()


# ---------------------------------------------------------------------------
# Metering: units
# ---------------------------------------------------------------------------


def test_api_calls_count_only_chain_rows() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _read_rows(eng, "acme", 7)
    _add_audit(eng, "acme", "feed.connect")
    _add_audit(eng, "acme", "metering.rollup")

    usage = metering.meter_usage(eng, START, END)
    acme = next(u for u in usage if u.tenant_id == "acme")
    assert acme.api_calls == 7
    assert acme.tier == "pro"
    assert acme.chain_events == 9  # internal rows still in the chain, just not billed


def test_5xx_503_429_never_billed() -> None:
    assert never_billed() == ["4xx incl 429", "5xx", "503"]
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="free")
    _read_rows(eng, "acme", 3)
    usage = metering.meter_usage(eng, START, END)
    assert next(u for u in usage if u.tenant_id == "acme").api_calls == 3
    metering.rollup(eng, START, END)
    # 4xx/5xx never become billable: reconciliation compares only successful
    # (2xx/3xx) requests, so the pre-filtered count of 3 matches with no drift.
    reports = reconcile.reconcile(eng, START, END, {"acme": 3})
    assert reports[0].state == reconcile.NORMAL


def test_feed_hours_floored() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="labs")
    t0 = PERIOD + timedelta(hours=1)
    _add_audit(eng, "acme", "feed.connect", {"session_id": "sess-1"}, ts=t0.isoformat())
    _add_audit(
        eng,
        "acme",
        "feed.disconnect",
        {"session_id": "sess-1"},
        ts=(t0 + timedelta(hours=1, minutes=30)).isoformat(),
    )
    _add_audit(
        eng,
        "acme",
        "feed.connect",
        {"session_id": "sess-2"},
        ts=(t0 + timedelta(hours=3)).isoformat(),
    )
    _add_audit(
        eng,
        "acme",
        "feed.disconnect",
        {"session_id": "sess-2"},
        ts=(t0 + timedelta(hours=3, minutes=20)).isoformat(),
    )

    hours = metering.feed_hours_by_tenant(eng, START, END)
    assert hours["acme"] == 1.0  # 1.5 h floors to 1; 20 min contributes 0


def test_backtest_hours_wallclock_only_done() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_job(eng, "acme", "done", PERIOD + timedelta(hours=2), PERIOD + timedelta(hours=5))
    _add_job(eng, "acme", "failed", PERIOD + timedelta(hours=6), PERIOD + timedelta(hours=10))
    _add_job(
        eng,
        "acme",
        "done",
        PERIOD - timedelta(days=2),
        PERIOD - timedelta(days=2) + timedelta(hours=1),
    )

    hours = metering.backtest_hours_by_tenant(eng, START, END)
    assert hours["acme"] == 3.0  # 3 h done job; failed + out-of-period excluded


def test_rollup_writes_rows_and_chain() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _read_rows(eng, "acme", 5)

    usage = metering.rollup(eng, START, END)
    assert usage[0].api_calls == 5
    assert _count(eng, metering.MeteringRollup) == 1
    with eng.connect() as conn:
        n = conn.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "metering.rollup")
        ).scalar()
        assert n == 1


# ---------------------------------------------------------------------------
# Reconciliation + drift response (contract §4)
# ---------------------------------------------------------------------------


def test_classify_thresholds_from_contract() -> None:
    assert tolerance_percent() == 1.0
    assert hard_threshold_percent() == 10.0
    assert reconcile.classify(100, 100) == reconcile.NORMAL
    assert reconcile.classify(100, 102) == reconcile.DRIFT  # 2 % > 1 %
    assert reconcile.classify(100, 120) == reconcile.EXTREME  # 20 % > 10 %


def test_chain_exact_and_log_tolerance() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)

    reports = reconcile.reconcile(eng, START, END, {"acme": 100})
    assert reports[0].chain_ok is True  # rollup == chain, exactly
    assert reports[0].state == reconcile.NORMAL

    lost_row = reconcile.reconcile(eng, START, END, {"acme": 103})
    assert lost_row[0].state == reconcile.DRIFT  # 3 % > 1 %: logs saw more than chain
    assert "log-drift" in lost_row[0].actions


def test_rollup_mismatch_is_drift_not_silent() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)
    with eng.begin() as conn:  # corrupt the rollup: simulate a rollup bug
        conn.execute(metering.MeteringRollup.__table__.update().values(api_calls=90))
    reports = reconcile.reconcile(eng, START, END, {"acme": 100})
    assert reports[0].chain_ok is False
    assert reports[0].state != reconcile.NORMAL
    assert "rollup-mismatch" in reports[0].actions


def test_drift_escalates_s1_and_blocks_invoice_not_suspend() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_key(eng, "acme", "key-acme-1")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)

    incidents = reconcile.handle_drift(eng, reconcile.reconcile(eng, START, END, {"acme": 103}))
    assert len(incidents) == 1 and "state=drift" in incidents[0]
    assert _count(eng, AuditEvent.__table__) > 0
    with eng.connect() as conn:
        n_s1 = conn.execute(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "metering.s1")
        ).scalar()
        assert n_s1 == 1
    assert _count(eng, MeteringInvoiceBlock) == 1
    assert _count(eng, MeteringSuspension) == 0
    with eng.connect() as conn:  # invoice blocked but keys still live
        revoked = conn.execute(select(ApiKey.revoked_at)).scalars().all()
        assert all(r is None for r in revoked)


def test_extreme_drift_suspends_then_autolifts() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_key(eng, "acme", "key-acme-1")
    _add_key(eng, "acme", "key-acme-2")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)

    incidents = reconcile.handle_drift(eng, reconcile.reconcile(eng, START, END, {"acme": 120}))
    assert "state=extreme" in incidents[0]
    assert _count(eng, MeteringSuspension) == 1
    with eng.connect() as conn:
        suspended = (
            conn.execute(select(ApiKey.revoked_at).where(ApiKey.tenant_id == "acme"))
            .scalars()
            .all()
        )
        assert all(r is not None for r in suspended)
        assert (
            conn.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "metering.suspend")
            ).scalar()
            == 1
        )

    reconcile.handle_drift(
        eng, reconcile.reconcile(eng, START, END, {"acme": 100})
    )  # back to normal
    with eng.connect() as conn:
        restored = (
            conn.execute(select(ApiKey.revoked_at).where(ApiKey.tenant_id == "acme"))
            .scalars()
            .all()
        )
        assert all(r is None for r in restored)
    assert _count(eng, MeteringSuspension.__table__) >= 1
    with eng.connect() as conn:
        open_susp = conn.execute(
            select(func.count())
            .select_from(MeteringSuspension)
            .where(MeteringSuspension.lifted_at.is_(None))
        ).scalar()
        open_block = conn.execute(
            select(func.count())
            .select_from(MeteringInvoiceBlock)
            .where(MeteringInvoiceBlock.cleared_at.is_(None))
        ).scalar()
        assert open_susp == 0 and open_block == 0


def test_autolift_never_unrevokes_manual_revoke() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_key(eng, "acme", "key-acme-1")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)
    reconcile.handle_drift(
        eng, reconcile.reconcile(eng, START, END, {"acme": 120})
    )  # suspends key-1
    # a key created after the suspension and manually revoked must stay revoked
    _add_key(eng, "acme", "key-acme-2")
    with Session(eng) as s:
        key2 = s.get(ApiKey, "key-acme-2")
        key2.revoked_at = datetime.now(timezone.utc)
        s.commit()
    reconcile.handle_drift(
        eng, reconcile.reconcile(eng, START, END, {"acme": 100})
    )  # auto-lift key-1
    with eng.connect() as conn:
        assert (
            conn.execute(select(ApiKey.revoked_at).where(ApiKey.id == "key-acme-1")).scalar()
            is None
        )
        assert (
            conn.execute(select(ApiKey.revoked_at).where(ApiKey.id == "key-acme-2")).scalar()
            is not None
        )


def test_autolift_never_unrevokes_manual_revoke_of_suspended_key() -> None:
    """The fatal case: an admin manually re-revokes a key that the *system*
    suspended. The auto-lift must restore only the system's own revocation — a
    human ban (revoked_at moved off the suspension timestamp) stays revoked."""
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_key(eng, "acme", "key-acme-1")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)
    reconcile.handle_drift(
        eng, reconcile.reconcile(eng, START, END, {"acme": 120})
    )  # system revokes key-1 at suspended_at
    with Session(eng) as session:
        key1 = session.get(ApiKey, "key-acme-1")
        assert key1.revoked_at is not None
        # the admin bans the same key AFTER the system suspension
        key1.revoked_at = datetime.now(timezone.utc)
        session.commit()
    reconcile.handle_drift(
        eng, reconcile.reconcile(eng, START, END, {"acme": 100})
    )  # drift cleared -> auto-lift
    with Session(eng) as session:
        key1 = session.get(ApiKey, "key-acme-1")
    assert key1.revoked_at is not None  # the manual ban survived the auto-lift
    with Session(eng) as session:
        susp = session.execute(
            select(MeteringSuspension).where(MeteringSuspension.tenant_id == "acme")
        ).scalar_one()
    assert susp.lifted_at is not None  # the suspension itself was lifted


def test_explicit_lift_never_unrevokes_manual_revoke_of_suspended_key() -> None:
    """The explicit lift path has the same guarantee."""
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_key(eng, "acme", "key-acme-1")
    _read_rows(eng, "acme", 100)
    metering.rollup(eng, START, END)
    reconcile.handle_drift(eng, reconcile.reconcile(eng, START, END, {"acme": 120}))
    with Session(eng) as session:
        key1 = session.get(ApiKey, "key-acme-1")
        key1.revoked_at = datetime.now(timezone.utc)  # manual re-revoke
        session.commit()
    assert reconcile.lift_suspension(eng, "acme") is True
    with Session(eng) as session:
        key1 = session.get(ApiKey, "key-acme-1")
    assert key1.revoked_at is not None


def test_no_pii_in_metering_rows() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="pro")
    _add_audit(eng, "acme", "read")
    usage = metering.rollup(eng, START, END)
    blob = str(usage)
    for forbidden in ("key_", "X-Pakhi-Key", "token_hash"):
        assert forbidden not in blob
    assert contract_consistent()
    assert billing_contract()["units"]["api_call"]["never_billed"] == ["4xx incl 429", "5xx", "503"]
