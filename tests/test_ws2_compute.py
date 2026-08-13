"""WS-2 T2: compute worker tests — frozen-θ gate, equivalence, UPSERT round-trip."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from pakhi.ws1.pit import COST, benchmark_2sess, load_oj, load_pit
from pakhi.ws2 import compute
from pakhi.ws2.compute import (
    ComputeError,
    EquivalenceError,
    build_ledger_row,
    compute_cycle,
    evaluate_cycle,
    frozen_thresholds,
    offline_verdict,
)
from pakhi.ws2.db import ForecastCycle, PaperLedger, Signal, get_engine, init_db
from pakhi.ws2.ingest import RejectCycleError

KNOWN = {
    "cycle": "2026-01-14",
    "cid": "20260114_12z",
    "freeze_prob": 0.036364,
    "temperature_min": -2.155341,
    "gross": 0.054895,
    "net": 0.051895,
    "contract_month": "Mar26",
}


def _record(features=None, **over) -> dict:
    rec = {
        "forecast_cycle_id": KNOWN["cid"],
        "cycle_date": KNOWN["cycle"],
        "publication_ts": "2026-01-14 15:30:00+00:00",
        "model_version": "GFS-0p50",
        "archive_source": "noaa-gfs-bdp-pds",
        "vintage": {"sha256": "a" * 64},
        "fetch_date": "2026-08-13T00:00:00+00:00",
        "features": {
            "freeze_prob": KNOWN["freeze_prob"],
            "temperature_min": KNOWN["temperature_min"],
        },
    }
    rec.update(over)
    if features:
        rec["features"].update(features)
    return rec


def test_frozen_thresholds_match_locked_protocol():
    th = frozen_thresholds()
    assert th["theta_p"] == pytest.approx(0.03636363636363636)
    assert th["theta_t"] == 0.0
    assert th["source"].startswith("1ce98669")


def test_offline_equivalence_no_fire():
    rec = _record(features={"freeze_prob": 0.0, "temperature_min": 16.0})
    d = evaluate_cycle(rec)
    assert d["fires"] is False
    assert d["equivalence"] == {"stored": False, "offline": False, "pass": True}


def test_offline_equivalence_fire():
    d = evaluate_cycle(_record())
    assert d["fires"] is True
    assert d["equivalence"]["pass"] is True
    th = frozen_thresholds()
    assert offline_verdict(_record()["features"], th) is True


def test_equivalence_mismatch_halts(monkeypatch):
    monkeypatch.setattr(compute, "offline_verdict", lambda features, th: not True)
    with pytest.raises(EquivalenceError, match="!="):
        evaluate_cycle(_record())


def test_known_value_roundtrip(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    init_db(engine)
    record = _record()
    result = compute_cycle(
        record,
        engine=engine,
        sessions=load_oj().index,
        oj=load_oj(),
        rbar=benchmark_2sess(load_pit()),
        episode_id=4,
    )
    row = result["ledger_row"]
    assert row["gross"] == pytest.approx(KNOWN["gross"], abs=1e-6)
    assert row["net"] == pytest.approx(KNOWN["gross"] - COST, abs=1e-6)
    assert row["net_of_benchmark"] == pytest.approx(
        KNOWN["gross"] - COST - benchmark_2sess(load_pit()), abs=1e-6
    )
    assert row["contract_month"] == KNOWN["contract_month"]
    assert row["entry_freeze_prob"] == pytest.approx(KNOWN["freeze_prob"])

    with engine.connect() as conn:
        stored = conn.execute(select(PaperLedger)).mappings().one()
    assert stored["forecast_cycle_id"] == KNOWN["cid"]
    assert stored["gross"] == pytest.approx(KNOWN["gross"], abs=1e-6)
    assert stored["net"] == pytest.approx(KNOWN["gross"] - COST, abs=1e-6)
    assert stored["entry_freeze_prob"] == pytest.approx(KNOWN["freeze_prob"])
    assert stored["archive_source"] == "noaa-gfs-bdp-pds"
    assert stored["vintage_hash"] == "a" * 64
    assert stored["model_version"] == "GFS-0p50"
    assert stored["contract_month"] == KNOWN["contract_month"]
    assert stored["scored"] is False

    with engine.connect() as conn:
        sig = conn.execute(select(Signal)).mappings().one()
    assert sig["action"] == "LONG"
    assert sig["forecast_cycle_id"] == KNOWN["cid"]


def test_upsert_is_idempotent(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    init_db(engine)
    sessions, oj = load_oj().index, load_oj()
    rbar = benchmark_2sess(load_pit())
    compute_cycle(_record(), engine=engine, sessions=sessions, oj=oj, rbar=rbar, episode_id=1)
    compute_cycle(_record(), engine=engine, sessions=sessions, oj=oj, rbar=rbar, episode_id=9)
    with engine.connect() as conn:
        n_ledger = conn.execute(select(PaperLedger)).scalars().all()
        n_signal = conn.execute(select(Signal)).scalars().all()
        n_cycles = conn.execute(select(ForecastCycle)).scalars().all()
    assert len(n_ledger) == 1
    assert len(n_signal) == 1
    assert len(n_cycles) == 1


def test_no_fire_upserts_forecast_cycle_only(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    init_db(engine)
    result = compute_cycle(
        _record(features={"freeze_prob": 0.0, "temperature_min": 16.0}),
        engine=engine,
        sessions=load_oj().index,
        oj=load_oj(),
    )
    assert result["ledger_row"] is None
    with engine.connect() as conn:
        n_cycles = len(conn.execute(select(ForecastCycle)).scalars().all())
        n_signal = len(conn.execute(select(Signal)).scalars().all())
        n_ledger = len(conn.execute(select(PaperLedger)).scalars().all())
    assert (n_cycles, n_signal, n_ledger) == (1, 0, 0)


def test_firing_event_without_oj_close_rejected():
    sessions = load_oj().index
    with pytest.raises(RejectCycleError, match="no trading session"):
        compute_cycle(
            _record(cycle_date="2026-08-12", forecast_cycle_id="20260812_12z"),
            sessions=sessions,
        )
    with pytest.raises(RejectCycleError, match="no exit session"):
        compute_cycle(
            _record(cycle_date="2026-08-07", forecast_cycle_id="20260807_12z"),
            sessions=sessions,
        )


def test_compute_never_silent_drop():
    with pytest.raises((ComputeError, Exception)) as excinfo:
        build_ledger_row(
            _record(cycle_date="2026-08-12", forecast_cycle_id="20260812_12z"),
            {"fires": True},
            load_oj().index,
            load_oj(),
        )
    assert isinstance(excinfo.value, RejectCycleError)
