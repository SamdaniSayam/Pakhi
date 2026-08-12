"""WS-1: end-to-end harness — PIT -> events -> engine -> report, on real data.

Every locked Evaluation Contract number is re-derived here from the real
archive and asserted, and the BacktestEngine cross-validation must reproduce
the PIT forward returns exactly (float-level).
"""

from __future__ import annotations

import pandas as pd
import pytest

from pakhi.ws1.harness import run_harness
from pakhi.ws1.pit import COST, load_oj, load_pit


@pytest.fixture(scope="module")
def pit():
    return load_pit()


@pytest.fixture(scope="module")
def oj():
    return load_oj()


@pytest.fixture(scope="module")
def report(pit, oj):
    return run_harness(pit=pit, oj=oj)


class TestLockedNumbersReproduced:
    def test_valid(self, report):
        assert report["valid"]

    def test_episode_counts(self, report):
        assert report["locked"]["n_episodes_total"] == 16
        assert report["locked"]["n_episodes_oos"] == 13

    def test_oos_rows_and_span(self, report):
        assert report["locked"]["oos_rows"] == 1247
        assert report["locked"]["span_years"] == pytest.approx(3.4114, abs=1e-4)

    def test_benchmark(self, report):
        assert report["locked"]["benchmark_2sess_pct"] == pytest.approx(0.2406, abs=1e-3)

    def test_cost(self, report):
        assert report["locked"]["cost_round_trip_bps"] == 30.0


class TestEvents:
    def test_event_counts(self, report):
        assert report["events"]["n_oos_events"] == 13
        assert report["events"]["n_scored"] == 13
        assert report["events"]["n_embargoed"] == 0
        assert report["events"]["n_weekend_entries_oos"] == 6
        assert report["events"]["n_next_close_entries_oos"] == 7
        assert not report["events"]["holds_merged_in_engine"]

    def test_metrics_reported(self, report):
        m = report["metrics"]
        assert m["n_events"] == 13
        lo, hi = m["ci_95_net_of_benchmark_sharpe"]
        assert lo < hi
        assert 0.0 < hi - lo < 10.0  # finite, sane-width percentile CI


class TestEngineCrossValidation:
    def test_all_oos_events_matched(self, report):
        xv = report["engine_context"]["cross_validation"]
        assert xv["n_oos_events"] == 13
        assert xv["matched_trades"] == 13
        assert xv["unmatched_events"] == []

    def test_engine_reproduces_pit_returns_exactly(self, report):
        xv = report["engine_context"]["cross_validation"]
        assert xv["max_return_abs_error"] < 1e-9
        assert xv["price_mismatches"] == 0

    def test_engine_trade_count(self, report):
        assert report["engine_context"]["full_oos_trades"] == 13

    def test_four_fold_runs(self, report):
        assert [f["fold"] for f in report["engine_context"]["per_fold"]] == [
            "fold1",
            "fold2",
            "fold3",
            "fold4",
        ]


class TestLedgerSemantics:
    def test_gross_equals_pit_fwd2(self, pit):
        led = run_harness(pit=pit, oj=load_oj())  # real ledger
        # Reconstruct via the harness's own ledger file path is not needed:
        # re-run with a temp path to inspect.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "ledger.csv"
            rep = run_harness(pit=pit, oj=load_oj(), ledger_path=csv)
            led = pd.read_csv(csv)
        assert rep["valid"]
        pit_by_date = pit.set_index("date")
        for _, ev in led.iterrows():
            expected_gross = float(
                pit_by_date.loc[pd.Timestamp(ev["entry_cycle"]), "fwd2_return"]
            )
            assert ev["gross"] == pytest.approx(expected_gross, abs=1e-12)
            assert ev["net"] == pytest.approx(ev["gross"] - COST, abs=1e-15)

    def test_exit_is_two_sessions_after_entry(self):
        oj = load_oj()
        sessions = oj.index
        from pakhi.ws1.harness import _build_ledger
        from pakhi.ws1.pit import benchmark_2sess

        pit = load_pit()
        led = _build_ledger(pit, sessions, benchmark_2sess(pit))
        for _, ev in led.iterrows():
            i, j = sessions.get_loc(pd.Timestamp(ev["entry_session"])), sessions.get_loc(
                pd.Timestamp(ev["exit_session"])
            )
            assert j - i == 2

    def test_scored_equals_oos_events_under_v11_fills(self, report):
        # v1.1 next-close fills: no OOS event falls inside any fold's
        # first-5-session embargo window (the old 2025-11-09 fold4-head
        # embargo case now fills 2025-11-10, session 6).  scored = in_oos & ~embargoed.
        assert report["events"]["n_scored"] == report["events"]["n_oos_events"]
