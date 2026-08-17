"""WS-2 T3: orchestration & failover tests — replay autonomy, alerting, idempotency.

All replay tests are hermetic: synthetic GFS parquets in a tmp cache, real
market data (as the rest of the suite), and a tmp replay database.  No network.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from pakhi.ws2 import orchestrate
from pakhi.ws2.alerts import Alert, file_notifier, send_alert, webhook_notifier
from pakhi.ws2.db import ForecastCycle, PaperLedger, Signal, get_engine, init_db
from pakhi.ws2.orchestrate import CycleOutcome, replay_cycles

REPO = Path(__file__).resolve().parent.parent
MARKET = REPO / "data" / "market"
DATES = ["20260302", "20260303", "20260304"]


def _synthetic_frame(cycle_date: str, t2m_k: float) -> pd.DataFrame:
    run = pd.Timestamp(f"{cycle_date} 12:00:00", tz="UTC")
    lats = np.arange(31.0, 23.5, -0.5)
    lons = np.arange(275.0, 280.5, 0.5)
    frames = []
    for lead in (0, 12, 24, 48):
        rows = [
            {
                "latitude": lat,
                "longitude": lon,
                "time": run,
                "step": pd.Timedelta(hours=lead),
                "valid_time": run + pd.Timedelta(hours=lead),
                "t2m": t2m_k,
                "date": cycle_date.replace("-", ""),
                "cycle": "12",
                "lead": lead,
            }
            for lat in lats
            for lon in lons
        ]
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def synthetic_cache(tmp_path):
    def _write(dates=DATES, t2m=290.0, cold_dates=()):
        gfs = tmp_path / "gfs"
        gfs.mkdir(exist_ok=True)
        for d in dates:
            temp = 240.0 if d in cold_dates else t2m
            frame = _synthetic_frame(d, temp)
            for lead in (0, 12, 24, 48):
                sub = frame[frame["lead"] == lead]
                sub.to_parquet(gfs / f"gfs_{d}_12z_f{lead:03d}_W24S-85E31N-80.parquet", index=False)
        return {
            "gfs_dir": gfs,
            "ingested_dir": tmp_path / "ingested",
            "manifest_path": tmp_path / "vintage_manifest.json",
            "market_dir": MARKET,
        }

    return _write


@pytest.fixture
def replay_engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    init_db(engine)
    return engine


def _capture_notifier():
    fired: list[Alert] = []

    def _capture(alert: Alert) -> None:
        fired.append(alert)

    return fired, _capture


def test_replay_autonomy_end_to_end(synthetic_cache, replay_engine, tmp_path):
    dirs = synthetic_cache(cold_dates=["20260304"])
    log_sink = tmp_path / "logs" / "orchestrate.jsonl"
    summary = replay_cycles(DATES, engine=replay_engine, log_sink=log_sink, **dirs)

    assert summary["counts"][CycleOutcome.FAILED] == 0
    assert summary["counts"][CycleOutcome.OK] == len(DATES)
    assert summary["counts"][CycleOutcome.REJECTED] == 0
    assert summary["fired"] == 1  # the cold cycle
    assert summary["ledger_rows"] == 1
    assert log_sink.exists()
    lines = [json.loads(line) for line in log_sink.read_text().splitlines()]
    assert len(lines) == len(DATES) + 1  # per-cycle records + summary

    with replay_engine.connect() as conn:
        assert len(conn.execute(select(ForecastCycle)).scalars().all()) == len(DATES)
        assert len(conn.execute(select(Signal)).scalars().all()) == 1
        rows = conn.execute(select(PaperLedger)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["episode_id"] == 1
    assert rows[0]["forecast_cycle_id"] == "20260304_12z"
    # Pre-G1 window (G1 date 2026-08-12): not scored — live paper events start
    # at G1 and need realized closes after the current market archive.
    assert rows[0]["scored"] is False
    assert rows[0]["contract_month"] is not None


def test_replay_is_idempotent(synthetic_cache, replay_engine, tmp_path):
    dirs = synthetic_cache(cold_dates=["20260304"])
    replay_cycles(DATES, engine=replay_engine, log_sink=tmp_path / "a.jsonl", **dirs)
    replay_cycles(DATES, engine=replay_engine, log_sink=tmp_path / "b.jsonl", **dirs)
    with replay_engine.connect() as conn:
        n_ledger = len(conn.execute(select(PaperLedger)).scalars().all())
        n_signal = len(conn.execute(select(Signal)).scalars().all())
        n_cycles = len(conn.execute(select(ForecastCycle)).scalars().all())
    assert (n_ledger, n_signal, n_cycles) == (1, 1, len(DATES))


def test_missing_cycle_rejected_loudly_and_cache_preserved(
    synthetic_cache, replay_engine, tmp_path
):
    dirs = synthetic_cache()
    gfs = dirs["gfs_dir"]
    before = sorted(p.name for p in gfs.iterdir())
    fired, notifier = _capture_notifier()
    rec = orchestrate.orchestrate_cycle(
        "20300101",
        engine=replay_engine,
        ref_time="2030-01-01 17:30:00",
        offline=True,
        notifiers=[notifier],
        **dirs,
    )
    assert rec["status"] == CycleOutcome.REJECTED
    assert rec["reject"]["type"] == "UpstreamMissingError"
    assert fired and fired[0].severity == "ERROR"
    assert "20300101" in fired[0].summary
    after = sorted(p.name for p in gfs.iterdir())
    assert after == before  # offline replay never deletes the shared cache


def test_compute_crash_alerts_critical(synthetic_cache, replay_engine, tmp_path, monkeypatch):
    dirs = synthetic_cache()
    fired, notifier = _capture_notifier()

    def _boom(*a, **k):
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(orchestrate, "compute_cycle", _boom)
    rec = orchestrate.orchestrate_cycle(
        DATES[0],
        engine=replay_engine,
        ref_time=f"{DATES[0]} 17:30:00",
        offline=True,
        notifiers=[notifier],
        **dirs,
    )
    assert rec["status"] == CycleOutcome.FAILED
    assert rec["failure"]["type"] == "RuntimeError"
    assert fired and fired[0].severity == "CRITICAL"


def test_send_alert_never_raises():
    def _explode(alert: Alert) -> None:
        raise RuntimeError("webhook blew up")

    alert = send_alert("boom", notifiers=[_explode])
    assert isinstance(alert, Alert)
    assert alert.severity == "ERROR"


def test_webhook_notifier_no_url_is_noop(monkeypatch):
    monkeypatch.delenv("PAKHI_ALERT_WEBHOOK_URL", raising=False)
    n = webhook_notifier(url=None)
    n(Alert(summary="x"))  # no-op, must not raise


def test_file_notifier_appends_jsonl(tmp_path):
    sink = tmp_path / "alerts.jsonl"
    n = file_notifier(sink)
    n(Alert(summary="one", cycle_id="c1"))
    n(Alert(summary="two", cycle_id="c2", severity="WARNING"))
    lines = [json.loads(line) for line in sink.read_text().splitlines()]
    assert [x["summary"] for x in lines] == ["one", "two"]
    assert lines[1]["severity"] == "WARNING"


def test_deploy_scheduler_units_exist():
    # The deploy scheduler units and the ws2-daily workflow are intentionally
    # private (Pakhi-private). In a public-tree checkout they are absent, so the
    # test is skipped; in the private repo (deploy/ or private-staging/) it still
    # validates the shipped scheduler options.
    service = timer = None
    for base in (REPO / "deploy", REPO / "private-staging" / "deploy"):
        cand_s = base / "ws2-orchestrate.service"
        cand_t = base / "ws2-orchestrate.timer"
        if cand_s.exists() and cand_t.exists():
            service, timer = cand_s, cand_t
            break
    workflow = None
    for wf in (
        REPO / ".github" / "workflows" / "ws2-daily.yml",
        REPO / "private-staging" / ".github" / "workflows" / "ws2-daily.yml",
    ):
        if wf.exists():
            workflow = wf
            break
    if service is None or timer is None or workflow is None:
        pytest.skip("deploy scheduler units are private (Pakhi-private)")
    assert "ExecStart=" in service.read_text()
    assert "OnCalendar=" in timer.read_text()
    assert "ws2-daily" in workflow.read_text()


def test_structured_log_single_sink(tmp_path):
    sink = tmp_path / "orchestrate.jsonl"
    orchestrate.structured_log({"a": 1}, sink)
    orchestrate.structured_log({"b": 2}, sink)
    assert len(sink.read_text().splitlines()) == 2
