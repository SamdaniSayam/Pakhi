"""Tests for risk metrics in pakhi.risk."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.risk.backtest import BacktestEngine, BacktestResult
from pakhi.risk.metrics import (
    cvar,
    max_drawdown,
    sharpe_ratio,
    var,
)
from pakhi.signals.base import Action, Signal

# ---------------------------------------------------------------------------
# var
# ---------------------------------------------------------------------------


class TestVaR:
    def test_known_distribution(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.02, 10000)
        v = var(returns, confidence=0.95)
        # For normal(0.001, 0.02), 5th percentile ≈ 0.001 - 1.645*0.02 ≈ -0.032
        assert 0.02 < v < 0.05

    def test_all_positive_returns(self):
        returns = np.ones(100) * 0.01
        v = var(returns, confidence=0.95)
        assert v == pytest.approx(-0.01, abs=1e-6)

    def test_empty_returns(self):
        assert np.isnan(var(np.array([])))

    def test_99_confidence(self):
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.01, 1000)
        v95 = var(returns, confidence=0.95)
        v99 = var(returns, confidence=0.99)
        assert v99 >= v95


# ---------------------------------------------------------------------------
# cvar
# ---------------------------------------------------------------------------


class TestCVaR:
    def test_known_distribution(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.02, 10000)
        cv = cvar(returns, confidence=0.95)
        v = var(returns, confidence=0.95)
        assert cv >= v

    def test_all_positive(self):
        returns = np.ones(100) * 0.01
        cv = cvar(returns, confidence=0.95)
        assert cv == pytest.approx(-0.01, abs=1e-6)

    def test_empty(self):
        assert np.isnan(cvar(np.array([])))


# ---------------------------------------------------------------------------
# sharpe_ratio
# ---------------------------------------------------------------------------


class TestSharpeRatio:
    def test_positive_returns(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_returns(self):
        returns = np.zeros(252)
        sr = sharpe_ratio(returns)
        assert np.isnan(sr)

    def test_known_calculation(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        sr = sharpe_ratio(returns, risk_free_rate=0.0)
        rf_per = 0.0
        excess = returns - rf_per
        expected = float(np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(252))
        assert sr == pytest.approx(expected, rel=1e-6)

    def test_single_return(self):
        assert np.isnan(sharpe_ratio(np.array([0.01])))


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_monotonic_increase(self):
        eq = np.array([100, 110, 120, 130, 140.0])
        assert max_drawdown(eq) == 0.0

    def test_known_drawdown(self):
        eq = np.array([100, 110, 90, 95, 80.0])
        # Peak = 110, trough = 80, dd = 30/110 ≈ 0.2727
        dd = max_drawdown(eq)
        assert dd == pytest.approx(30.0 / 110.0, rel=1e-4)

    def test_single_value(self):
        assert max_drawdown(np.array([100.0])) == 0.0

    def test_all_equal(self):
        eq = np.ones(10) * 100.0
        assert max_drawdown(eq) == 0.0

    def test_full_recovery(self):
        eq = np.array([100, 80, 100.0])
        dd = max_drawdown(eq)
        assert dd == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------


class TestBacktestEngine:
    def _make_data(self, n=200):
        rng = np.random.default_rng(42)
        dates = pd.date_range("2023-01-01", periods=n, freq="D")
        price = 100.0 + np.cumsum(rng.normal(0, 1, n))
        return pd.DataFrame({"close": price}, index=dates)

    def _always_long(self, data, step):
        return Signal(
            action=Action.LONG,
            size=0.1,
            confidence=0.8,
            instrument="TEST",
            timestamp=data.index[step],
            reasoning="always long",
        )

    def _always_flat(self, data, step):
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="TEST",
            timestamp=data.index[step],
            reasoning="always flat",
        )

    def test_run_basic(self):
        data = self._make_data()
        engine = BacktestEngine()
        result = engine.run(self._always_long, data)
        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) == len(data)
        assert result.equity_curve[0] == 1_000_000.0

    def test_flat_no_trades(self):
        data = self._make_data()
        engine = BacktestEngine()
        result = engine.run(self._always_flat, data)
        assert result.total_return == pytest.approx(0.0, abs=1e-6)
        assert len(result.trades) == 0

    def test_missing_column_raises(self):
        data = pd.DataFrame({"wrong_col": [1, 2, 3]})
        engine = BacktestEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.run(self._always_long, data)

    def test_initial_capital(self):
        data = self._make_data()
        engine = BacktestEngine()
        result = engine.run(self._always_long, data, initial_capital=500_000)
        assert result.equity_curve[0] == 500_000.0

    def test_commission_impact(self):
        data = self._make_data()
        engine = BacktestEngine()
        r1 = engine.run(self._always_long, data, commission_bps=0, slippage_bps=0)
        r2 = engine.run(self._always_long, data, commission_bps=100, slippage_bps=100)
        assert r1.equity_curve[-1] >= r2.equity_curve[-1]
