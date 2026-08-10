"""Tests for pakhi.risk — alerts, uncertainty, metrics, backtest."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pakhi.risk.alerts import Alert, AlertManager, AlertSeverity, send_alert
from pakhi.risk.backtest import BacktestEngine, BacktestResult
from pakhi.risk.metrics import (
    calmar_ratio,
    cvar,
    information_ratio,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    var,
)
from pakhi.risk.uncertainty import (
    calibration_error,
    coverage,
    ensemble_spread,
    sharpness,
)


class TestAlertSeverity:
    def test_values(self):
        assert AlertSeverity.LOW.value == "LOW"
        assert AlertSeverity.CRITICAL.value == "CRITICAL"


class TestAlert:
    def test_creation(self):
        a = Alert(
            severity=AlertSeverity.HIGH,
            message="Freeze warning",
            timestamp=datetime.now(timezone.utc),
            trigger_value=-5.0,
            alert_type="freeze",
        )
        assert a.severity == AlertSeverity.HIGH
        assert a.alert_type == "freeze"
        assert a.metadata == {}

    def test_with_metadata(self):
        a = Alert(
            severity=AlertSeverity.LOW,
            message="test",
            timestamp=datetime.now(timezone.utc),
            trigger_value=0.0,
            alert_type="test",
            metadata={"key": "value"},
        )
        assert a.metadata == {"key": "value"}


class TestAlertManager:
    def test_instantiation(self):
        mgr = AlertManager()
        assert mgr is not None

    def test_check_freeze_returns_alert(self):
        mgr = AlertManager()
        result = mgr.check_freeze({"temperature_min": -5.0, "location": "Houston"})
        assert result is not None
        assert result.alert_type == "freeze"
        assert result.severity == AlertSeverity.MEDIUM

    def test_check_freeze_no_alert(self):
        mgr = AlertManager()
        result = mgr.check_freeze({"temperature_min": 10.0})
        assert result is None

    def test_check_freeze_severity_levels(self):
        mgr = AlertManager()
        # Low severity (delta <= 2)
        r = mgr.check_freeze({"temperature_min": -1.0}, threshold=0.0)
        assert r.severity == AlertSeverity.LOW
        # Medium (2 < delta <= 5)
        r = mgr.check_freeze({"temperature_min": -3.0}, threshold=0.0)
        assert r.severity == AlertSeverity.MEDIUM
        # High (5 < delta <= 10)
        r = mgr.check_freeze({"temperature_min": -7.0}, threshold=0.0)
        assert r.severity == AlertSeverity.HIGH

    def test_check_heatwave(self):
        mgr = AlertManager()
        result = mgr.check_heatwave(
            {
                "temperature_forecast": [39, 40, 41, 42, 38],
                "location": "Dallas",
            },
            threshold=38.0,
            days=3,
        )
        assert result is not None
        assert result.alert_type == "heatwave"

    def test_check_heatwave_no_alert(self):
        mgr = AlertManager()
        result = mgr.check_heatwave(
            {
                "temperature_forecast": [30, 31, 32],
            },
            threshold=38.0,
            days=3,
        )
        assert result is None

    def test_check_heatwave_empty(self):
        mgr = AlertManager()
        result = mgr.check_heatwave({"temperature_forecast": []})
        assert result is None

    def test_check_hurricane(self):
        mgr = AlertManager()
        result = mgr.check_hurricane(
            {
                "landfall_prob": 0.8,
                "category": 4,
                "closest_approach_miles": 50,
            }
        )
        assert result is not None
        assert result.alert_type == "hurricane"
        assert result.severity == AlertSeverity.CRITICAL

    def test_check_hurricane_low_prob(self):
        mgr = AlertManager()
        result = mgr.check_hurricane(
            {
                "landfall_prob": 0.05,
                "category": 1,
                "closest_approach_miles": 500,
            }
        )
        assert result is None

    def test_check_drought(self):
        mgr = AlertManager()
        spi = list(np.full(35, -2.0))
        result = mgr.check_drought(
            {
                "spi_values": spi,
                "region": "Midwest",
            },
            threshold=-1.5,
            days=30,
        )
        assert result is not None
        assert result.alert_type == "drought"

    def test_check_drought_no_alert(self):
        mgr = AlertManager()
        result = mgr.check_drought(
            {
                "spi_values": [1.0, 0.5, -0.2],
                "region": "Midwest",
            },
            threshold=-1.5,
            days=30,
        )
        assert result is None

    def test_check_drought_empty(self):
        mgr = AlertManager()
        result = mgr.check_drought({"spi_values": [], "region": "X"})
        assert result is None


class TestSendAlert:
    def test_log_channel(self):
        a = Alert(
            severity=AlertSeverity.LOW,
            message="test",
            timestamp=datetime.now(timezone.utc),
            trigger_value=0.0,
            alert_type="test",
        )
        send_alert(a, channels=["log"])

    def test_email_placeholder(self):
        a = Alert(
            severity=AlertSeverity.LOW,
            message="test",
            timestamp=datetime.now(timezone.utc),
            trigger_value=0.0,
            alert_type="test",
        )
        send_alert(a, channels=["email", "slack", "telegram"])

    def test_unknown_channel(self):
        a = Alert(
            severity=AlertSeverity.LOW,
            message="test",
            timestamp=datetime.now(timezone.utc),
            trigger_value=0.0,
            alert_type="test",
        )
        send_alert(a, channels=["carrier_pigeon"])

    def test_default_channels(self):
        a = Alert(
            severity=AlertSeverity.LOW,
            message="test",
            timestamp=datetime.now(timezone.utc),
            trigger_value=0.0,
            alert_type="test",
        )
        send_alert(a)


class TestUncertainty:
    def test_ensemble_spread_1d(self):
        spread = ensemble_spread(np.array([1.0, 2.0, 3.0, 4.0]))
        assert spread > 0

    def test_ensemble_spread_single(self):
        assert ensemble_spread(np.array([5.0])) == 0.0

    def test_ensemble_spread_2d(self):
        ensemble = np.array([[1.0, 2.0], [1.5, 2.5], [2.0, 3.0]])
        spread = ensemble_spread(ensemble)
        assert spread >= 0.0

    def test_ensemble_spread_empty(self):
        assert np.isnan(ensemble_spread(np.array([])))

    def test_calibration_error(self):
        ece = calibration_error(
            np.array([0.1, 0.5, 0.9]),
            np.array([0.1, 0.4, 0.85]),
        )
        assert 0.0 <= ece <= 1.0

    def test_calibration_error_zero_bins(self):
        assert calibration_error(np.array([0.5]), np.array([0.5]), n_bins=0) == 0.0

    def test_calibration_error_nan(self):
        assert np.isnan(calibration_error(np.array([]), np.array([])))

    def test_sharpness(self):
        q = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        assert sharpness(q) == pytest.approx(40.0)

    def test_sharpness_few_quantiles(self):
        q = np.array([10.0, 50.0])
        assert sharpness(q) == pytest.approx(40.0)

    def test_sharpness_nan(self):
        assert np.isnan(sharpness(np.array([5.0])))

    def test_coverage(self):
        lower = np.array([1.0, 2.0, 3.0])
        upper = np.array([5.0, 6.0, 7.0])
        obs = np.array([3.0, 4.0, 5.0])
        assert coverage(lower, upper, obs) == pytest.approx(1.0)

    def test_coverage_partial(self):
        lower = np.array([1.0, 1.0])
        upper = np.array([2.0, 2.0])
        obs = np.array([1.5, 5.0])
        assert coverage(lower, upper, obs) == pytest.approx(0.5)

    def test_coverage_empty(self):
        assert np.isnan(coverage(np.array([]), np.array([]), np.array([])))


class TestMetrics:
    def test_var(self):
        returns = np.random.randn(252) * 0.01
        v = var(returns, confidence=0.95)
        assert v >= 0.0

    def test_var_empty(self):
        assert np.isnan(var(np.array([])))

    def test_cvar(self):
        returns = np.random.randn(252) * 0.01
        cv = cvar(returns, confidence=0.95)
        assert cv >= 0.0

    def test_cvar_empty(self):
        assert np.isnan(cvar(np.array([])))

    def test_sharpe_ratio(self):
        returns = np.random.randn(252) * 0.01 + 0.0003
        s = sharpe_ratio(returns)
        assert isinstance(s, float)

    def test_sharpe_ratio_empty(self):
        assert np.isnan(sharpe_ratio(np.array([])))

    def test_sortino_ratio(self):
        returns = np.random.randn(252) * 0.01
        s = sortino_ratio(returns)
        assert isinstance(s, float)

    def test_sortino_ratio_empty(self):
        assert np.isnan(sortino_ratio(np.array([])))

    def test_max_drawdown(self):
        equity = np.array([100, 110, 105, 120, 90, 95])
        md = max_drawdown(equity)
        assert 0.0 < md <= 1.0

    def test_max_drawdown_monotonic(self):
        assert max_drawdown(np.array([1, 2, 3, 4, 5])) == pytest.approx(0.0)

    def test_max_drawdown_short(self):
        assert max_drawdown(np.array([100.0])) == 0.0

    def test_calmar_ratio(self):
        returns = np.random.randn(252) * 0.01
        cr = calmar_ratio(returns)
        assert isinstance(cr, float)

    def test_calmar_ratio_empty(self):
        assert np.isnan(calmar_ratio(np.array([])))

    def test_information_ratio(self):
        returns = np.random.randn(252) * 0.01
        benchmark = np.random.randn(252) * 0.01
        ir = information_ratio(returns, benchmark)
        assert isinstance(ir, float)

    def test_information_ratio_empty(self):
        assert np.isnan(information_ratio(np.array([]), np.array([])))


class TestBacktest:
    def test_backtest_result_defaults(self):
        r = BacktestResult()
        assert r.total_return == 0.0
        assert r.trades == []

    def test_backtest_run(self):
        engine = BacktestEngine()
        dates = pd.date_range("2023-01-01", periods=100)
        data = pd.DataFrame(
            {
                "close": np.cumsum(np.random.randn(100) * 0.5) + 100,
            },
            index=dates,
        )

        def sig_gen(df, idx):
            from pakhi.signals.base import Action, Signal

            return Signal(
                action=Action.LONG,
                size=0.1,
                confidence=0.6,
                instrument="TEST",
                timestamp=df.index[-1],
                reasoning="test",
            )

        result = engine.run(sig_gen, data)
        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) > 0

    def test_backtest_missing_column(self):
        engine = BacktestEngine(price_column="missing")
        data = pd.DataFrame({"x": [1, 2, 3]}, index=pd.date_range("2023-01-01", periods=3))

        def sig_gen(df, idx):
            from pakhi.signals.base import Action, Signal

            return Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=df.index[-1],
                reasoning="x",
            )

        with pytest.raises(ValueError, match="not found"):
            engine.run(sig_gen, data)

    def test_backtest_short_data(self):
        engine = BacktestEngine()
        data = pd.DataFrame({"close": [100.0]}, index=pd.date_range("2023-01-01", periods=1))

        def sig_gen(df, idx):
            from pakhi.signals.base import Action, Signal

            return Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=df.index[-1],
                reasoning="x",
            )

        result = engine.run(sig_gen, data)
        assert len(result.equity_curve) == 0

    def test_walk_forward(self):
        engine = BacktestEngine()
        dates = pd.date_range("2023-01-01", periods=400)
        data = pd.DataFrame(
            {
                "close": np.cumsum(np.random.randn(400) * 0.5) + 100,
            },
            index=dates,
        )

        def sig_gen(df, idx):
            from pakhi.signals.base import Action, Signal

            return Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=df.index[-1],
                reasoning="x",
            )

        results = engine.walk_forward(sig_gen, data, train_window=100, test_window=50)
        assert isinstance(results, list)
        assert len(results) >= 1
