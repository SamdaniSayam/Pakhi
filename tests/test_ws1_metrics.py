"""WS-1: event-based metrics — Sharpe, t-stat, bootstrap CI (§6-7)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.ws1.metrics import annualized_sharpe, bootstrap_ci, event_metrics, t_stat


class TestAnnualizedSharpe:
    def test_hand_computed(self):
        # returns = [0.01, 0.02, 0.03], span 1y
        r = np.array([0.01, 0.02, 0.03])
        mean, sigma = r.mean(), r.std(ddof=1)
        expected = mean / sigma * np.sqrt(3 / 1.0)
        assert annualized_sharpe(r, span_years=1.0) == pytest.approx(float(expected))
        assert annualized_sharpe(r, span_years=1.0) == pytest.approx(3.4641016151377544)

    def test_annualisation_uses_sqrt_n_over_span(self):
        # Double the span halves the annualized Sharpe.
        r = np.array([0.01, 0.02, 0.03])
        s1 = annualized_sharpe(r, span_years=1.0)
        s2 = annualized_sharpe(r, span_years=4.0)
        assert s2 == pytest.approx(s1 / 2.0)

    def test_zero_variance_returns_zero(self):
        assert annualized_sharpe(np.array([0.1, 0.1, 0.1]), 1.0) == 0.0

    def test_too_few_observations(self):
        assert annualized_sharpe(np.array([0.01]), 1.0) == 0.0


class TestTStat:
    def test_hand_computed(self):
        r = np.array([0.01, 0.02, 0.03])
        expected = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        assert t_stat(r) == pytest.approx(float(expected))

    def test_single_observation(self):
        assert t_stat(np.array([0.01])) == 0.0


class TestBootstrapCI:
    def test_deterministic_under_seed(self):
        r = np.array([0.01, -0.005, 0.02, -0.01, 0.03, 0.0, 0.015, -0.02])
        a = bootstrap_ci(r, span_years=3.0)
        b = bootstrap_ci(r, span_years=3.0)
        assert a == b

    def test_ci_has_expected_width(self):
        rng = np.random.default_rng(7)
        r = rng.normal(0.001, 0.02, 30)
        lo, hi = bootstrap_ci(r, span_years=3.0, n_resamples=5000)
        assert lo < hi

    def test_ci_uses_locked_resample_count_and_seed(self):
        # Sanity: the locked defaults are 10_000 resamples, seed 42.
        r = np.array([0.01, -0.005, 0.02, -0.01, 0.03])
        a = bootstrap_ci(r, span_years=2.0, n_resamples=10_000, seed=42)
        b = bootstrap_ci(r, span_years=2.0, n_resamples=10_000, seed=42)
        assert a == b
        assert a[0] < a[1]

    def test_few_observations_returns_zero(self):
        assert bootstrap_ci(np.array([0.01]), 1.0) == (0.0, 0.0)


class TestEventMetrics:
    @pytest.fixture
    def trades(self):
        return pd.DataFrame(
            {
                "gross": [0.01, -0.02, 0.005],
                "net": [0.007, -0.023, 0.002],
                "net_of_benchmark": [0.005, -0.025, 0.0],
            }
        )

    def test_metric_keys_and_values(self, trades):
        m = event_metrics(trades, benchmark_mean=0.002, span_years=3.0)
        assert m["n_events"] == 3
        assert m["mean_gross"] == pytest.approx((0.01 - 0.02 + 0.005) / 3)
        assert m["mean_net"] == pytest.approx((0.007 - 0.023 + 0.002) / 3)
        nb = np.array([0.005, -0.025, 0.0])
        assert m["mean_net_of_benchmark"] == pytest.approx(nb.mean())
        assert m["net_of_benchmark_sharpe"] == pytest.approx(annualized_sharpe(nb, 3.0))
        assert m["t_stat"] == pytest.approx(t_stat(nb))
        assert m["win_rate"] == pytest.approx(2 / 3)
        assert m["gross_sharpe"] == pytest.approx(
            annualized_sharpe(np.array([0.01, -0.02, 0.005]), 3.0)
        )

    def test_empty_ledger(self):
        m = event_metrics(pd.DataFrame(), benchmark_mean=0.002, span_years=3.0)
        assert m["n_events"] == 0
        for k, v in m.items():
            if k == "ci_95_net_of_benchmark_sharpe":
                assert v == (0.0, 0.0)
            elif k != "_cost":
                assert v == 0.0
