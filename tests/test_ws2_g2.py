"""WS-2 T4: G2 handoff tests — live-ledger re-run, self-hash-pinned record."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import insert

from pakhi.ws2.db import PaperLedger, get_engine, init_db
from pakhi.ws2.g2 import (
    build_g2_decision,
    g2_decision_consistent,
    load_live_ledger,
    produce_g2_report,
    record_sha256,
    scored_events,
)

REPO = Path(__file__).resolve().parent.parent
WS1_LEDGER_COLUMNS = pd.read_csv(REPO / "data" / "ws1" / "t4_candidate_ledger.csv").columns.tolist()


def _row(
    episode_id,
    entry_cycle="2026-09-01",
    entry_session="2026-09-01",
    exit_session="2026-09-03",
    gross=0.02,
    net=0.017,
    net_of_benchmark=0.016,
    scored=True,
    forecast_cycle_id=None,
):
    return {
        "episode_id": episode_id,
        "entry_cycle": pd.Timestamp(entry_cycle).to_pydatetime(),
        "entry_session": pd.Timestamp(entry_session).to_pydatetime(),
        "exit_session": pd.Timestamp(exit_session).to_pydatetime(),
        "gross": gross,
        "net": net,
        "net_of_benchmark": net_of_benchmark,
        "fold": "live",
        "in_oos": scored,
        "embargoed": False,
        "entry_weekend": False,
        "next_close_fill": False,
        "fill_days_after_cycle": 0,
        "entry_freeze_prob": 0.05,
        "entry_temperature_min": -3.0,
        "forecast_cycle_id": forecast_cycle_id or f"2026090{episode_id}_12z",
        "publication_ts": pd.Timestamp("2026-09-01 15:30:00+00:00").to_pydatetime(),
        "model_version": "GFS-0p50",
        "contract_month": "Dec26",
        "adjustment_factor": 0.9,
        "scored": scored,
        "archive_source": "noaa-gfs-bdp-pds",
        "vintage_hash": "a" * 64,
        "fetch_date": pd.Timestamp("2026-09-01T16:00:00+00:00").to_pydatetime(),
    }


@pytest.fixture
def engine(tmp_path):
    e = get_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    init_db(e)
    return e


def _insert(engine, rows):
    with engine.begin() as conn:
        conn.execute(insert(PaperLedger), rows)


def _report(tmp_path, engine, suffix="r"):
    return produce_g2_report(
        engine,
        out_json=tmp_path / f"g2_{suffix}.json",
        out_md=tmp_path / f"WS2_G2_REPORT_{suffix}.md",
    )


def test_ledger_shape_matches_ws1_csv(engine):
    _insert(engine, [_row(1), _row(2, scored=False)])
    df = load_live_ledger(engine)
    assert df.columns.tolist() == WS1_LEDGER_COLUMNS
    assert len(df) == 2
    scored = scored_events(df)
    assert len(scored) == 1
    assert scored.iloc[0]["episode_id"] == 1


def test_record_sha256_is_self_pinning():
    payload = {"a": 1, "b": [1, 2, 3]}
    assert record_sha256(payload) == record_sha256(dict(payload))
    assert record_sha256(payload) != record_sha256({**payload, "a": 2})


def test_zero_trades_honest_verdict(engine, tmp_path):
    record = _report(tmp_path, engine, "zero")
    assert record["outcome"] == "ZERO_TRADES"
    assert record["live_ledger"]["n_scored_events"] == 0
    assert record["g1_predecessor"]["outcome"] == "UNDER_POWERED"
    assert g2_decision_consistent(record)
    assert (tmp_path / "g2_zero.json").exists()
    assert (tmp_path / "WS2_G2_REPORT_zero.md").exists()


def test_underpowered_when_n_lt_8(engine, tmp_path):
    _insert(engine, [_row(i) for i in range(1, 4)])
    record = _report(tmp_path, engine, "up")
    assert record["outcome"] == "UNDER_POWERED"
    assert record["headline_metric"]["n_events"] == 3
    assert record["live_ledger"]["n_ledger_rows"] == 3
    assert g2_decision_consistent(record)


def test_pass_at_n_ge_8_positive(engine, tmp_path):
    # Varied (non-degenerate) positive net-of-benchmark returns.  Gross varies
    # with net_of_benchmark so the live recompute (gross - COST - rbar) stays
    # positive and varied rather than collapsing to a constant zero-variance series.
    nb = [0.0160, 0.0168, 0.0152, 0.0174, 0.0165, 0.0158, 0.0170, 0.0162]
    rows = [
        _row(i, gross=net + 0.005, net=net + 0.002, net_of_benchmark=net)
        for i, net in enumerate(nb, start=1)
    ]
    _insert(engine, rows)
    record = _report(tmp_path, engine, "pass")
    assert record["outcome"] == "PASS"
    assert record["headline_metric"]["n_events"] == 8
    assert record["headline_metric"]["net_of_benchmark_event_sharpe"] > 1.0
    assert record["headline_metric"]["ci_95_lower"] > 0.0
    assert g2_decision_consistent(record)


def test_fail_pivot_when_negative_edge(engine, tmp_path):
    rows = [_row(i, gross=-0.01, net=-0.013, net_of_benchmark=-0.014) for i in range(1, 9)]
    _insert(engine, rows)
    record = _report(tmp_path, engine, "fail")
    assert record["outcome"] == "FAIL_PIVOT"
    assert record["headline_metric"]["n_events"] == 8
    assert g2_decision_consistent(record)


def test_tampered_record_breaks_self_hash(engine):
    record = build_g2_decision(
        {
            "net_of_benchmark_sharpe": 1.5,
            "ci_95_net_of_benchmark_sharpe": (0.1, 3.0),
            "bootstrap_pvalue_edge_gt_zero": 0.01,
            "n_events": 8,
            "power_class": "shrunk edge claim (N_min = 8)",
            "mean_net_of_benchmark": 0.01,
            "classic_t": 2.0,
            "newey_west_t": 1.9,
            "newey_west_lag": 1,
            "decision": {"outcome": "PASS", "reason": "x"},
        },
        n_scored_events=8,
        n_ledger_rows=8,
        rbar=0.002,
        span_years=0.01,
        live_start="2026-08-12",
    )
    assert g2_decision_consistent(record)
    record["headline_metric"]["n_events"] = 99  # tamper
    assert not g2_decision_consistent(record)


def test_json_artifact_matches_fresh_build(engine, tmp_path):
    record = _report(tmp_path, engine, "roundtrip")
    artifact = json.loads((tmp_path / "g2_roundtrip.json").read_text())
    assert artifact["payload_sha256"] == record["payload_sha256"]
    assert artifact["outcome"] == record["outcome"]
