"""WS-1 T5: statistical significance engine.

Blueprint T5 exit: *performance reports output probability distributions and
p-values, exposing whether sparse-trade variance is too high.*  These tests
prove the Newey-West HAC machinery against hand-computed values, the bootstrap
p-value is deterministic and signs correctly, the locked §8 decision gate fires
in every branch, and the harness report carries the full significance table.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.ws1.harness import run_harness
from pakhi.ws1.metrics import t_stat
from pakhi.ws1.pit import load_oj, load_pit, oos_span_years
from pakhi.ws1.significance import (
    N_FULL,
    N_MIN,
    SHARPE_GATE,
    bootstrap_pvalue,
    decision_gate,
    newey_west_lag,
    newey_west_se,
    newey_west_tstat,
    significance_report,
)

SPAN = oos_span_years()


class TestNeweyWest:
    def test_hand_computed_se_and_t(self):
        # r = [1,2,3,4], lag=1:
        # gamma0=1.25, gamma1=0.3125, w=0.5 -> long-run=1.5625 -> SE=sqrt(1.5625/4)=0.625.
        r = np.array([1.0, 2.0, 3.0, 4.0])
        assert newey_west_se(r, lag=1) == pytest.approx(0.625, abs=1e-12)
        assert newey_west_tstat(r, lag=1) == pytest.approx(4.0, abs=1e-12)

    def test_lag_rule(self):
        assert newey_west_lag(7) == 2
        assert newey_west_lag(100) == 4

    def test_iid_series_nw_agrees_with_classic(self):
        rng = np.random.default_rng(0)
        r = rng.normal(0, 1, 200)
        assert abs(newey_west_tstat(r) - t_stat(r)) < 1.5

    def test_short_series_returns_zero(self):
        assert newey_west_tstat(np.array([1.0])) == 0.0


class TestBootstrapPvalue:
    def test_deterministic(self):
        rng = np.random.default_rng(1)
        r = rng.normal(0.002, 0.005, 50)
        assert bootstrap_pvalue(r, SPAN) == bootstrap_pvalue(r, SPAN)

    def test_positive_edge_small_p(self):
        rng = np.random.default_rng(1)
        r = rng.normal(0.002, 0.005, 50)
        assert bootstrap_pvalue(r, SPAN) < 0.1

    def test_negative_edge_large_p(self):
        rng = np.random.default_rng(1)
        r = rng.normal(-0.002, 0.005, 50)
        assert bootstrap_pvalue(r, SPAN) > 0.9


class TestDecisionGate:
    def test_zero_trades(self):
        assert decision_gate(0, 0.0, 0.0, 0.0)["outcome"] == "ZERO_TRADES"

    def test_under_powered(self):
        out = decision_gate(7, -0.2, -1.0, -0.01)
        assert out["outcome"] == "UNDER_POWERED"
        assert f"{N_MIN}" in out["reason"]

    def test_pass(self):
        out = decision_gate(8, 1.5, 0.3, 0.01)
        assert out["outcome"] == "PASS"
        assert f"{SHARPE_GATE}" in out["reason"]

    def test_fail_ci_includes_zero(self):
        assert decision_gate(8, 0.8, -0.5, 0.01)["outcome"] == "FAIL_PIVOT"

    def test_fail_mean_non_positive(self):
        # A negative mean (sharpe < 0 => ci_lo < 0) can never PASS: FAIL_PIVOT.
        assert decision_gate(8, -1.5, -2.0, -0.01)["outcome"] == "FAIL_PIVOT"

    def test_constants_locked(self):
        assert N_MIN == 8
        assert N_FULL == 30
        assert SHARPE_GATE == 1.0


class TestSignificanceReport:
    def test_empty_ledger(self):
        rep = significance_report(pd.DataFrame(), 0.0, SPAN)
        assert rep["n_events"] == 0
        assert rep["decision"]["outcome"] == "ZERO_TRADES"
        assert rep["bootstrap_pvalue_edge_gt_zero"] == 1.0

    def test_requires_net_of_benchmark_column(self):
        trades = pd.DataFrame(
            {
                "net_of_benchmark": [0.01, -0.02, 0.005],
                "entry_session": pd.to_datetime(["2023-01-02", "2023-02-02", "2023-03-02"]),
            }
        )
        rep = significance_report(trades, 0.0, SPAN)
        assert rep["n_events"] == 3
        assert rep["classic_t"] == pytest.approx(t_stat(np.array([0.01, -0.02, 0.005])), abs=1e-12)

    def test_overlap_check_zero_on_real_candidate(self):
        rep = run_harness(pit=load_pit(), oj=load_oj(), candidate=True)
        sig = rep["significance"]
        assert sig["overlap_check"]["n_overlapping_events"] == 0
        assert sig["overlap_check"]["purging_needed"] is False


class TestHarnessIntegration:
    def test_report_has_significance_candidate(self):
        rep = run_harness(pit=load_pit(), oj=load_oj(), candidate=True)
        sig = rep["significance"]
        assert sig["n_events"] == rep["signal"]["n_trades"]
        assert sig["n_events"] == 7
        assert sig["decision"]["outcome"] == "UNDER_POWERED"
        assert sig["power_class"] == "under-powered (N < N_min)"
        assert sig["newey_west_lag"] == 2
        lo, hi = sig["ci_95_net_of_benchmark_sharpe"]
        assert lo < 0 < hi  # sparse variance: CI straddles zero
        assert sig["bootstrap_pvalue_edge_gt_zero"] > 0.05

    def test_report_has_significance_demo(self):
        rep = run_harness(pit=load_pit(), oj=load_oj())
        assert rep["significance"]["n_events"] == 13
        assert "decision" in rep["significance"]
