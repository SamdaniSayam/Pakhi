"""Tests for critical bug fixes in pakhi.

Covers: PaperTrader cash management, confidence sizing, SPI data leakage,
anomaly detection rolling behavior, and walk-forward retraining.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pakhi.features.anomaly import AnomalyFeatures
from pakhi.features.temporal import TemporalFeatures
from pakhi.risk.backtest import BacktestEngine
from pakhi.signals.base import Action, Signal, position_size
from pakhi.trading.execution import PaperTrader

# ---------------------------------------------------------------------------
# PaperTrader: invested capital must be returned on close
# ---------------------------------------------------------------------------


class TestPaperTraderCashManagement:
    """Verify that closing a position returns invested capital + PnL."""

    def test_round_trip_cash_conservation(self):
        """Open at 100, close at 110 → cash should increase by profit only."""
        trader = PaperTrader(initial_capital=100_000, commission_per_trade=0.0)
        signal = Signal(
            action=Action.LONG,
            size=0.5,
            confidence=0.7,
            instrument="TEST",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            reasoning="test",
        )

        # Open position at 100
        trade = trader.execute(signal, current_price=100.0)
        cash_after_open = trader.cash
        # Should have invested 50% of 100k at price 100 → 500 shares
        expected_qty = 0.5 * 100_000 / 100.0
        assert trade.quantity == pytest.approx(expected_qty)
        assert cash_after_open == pytest.approx(100_000 - expected_qty * 100.0)

        # Close at 110 → profit = (110-100) * 500 = 5000
        closed = trader.close_position(trade.trade_id, price=110.0)
        expected_pnl = (110.0 - 100.0) * expected_qty
        assert closed.pnl == pytest.approx(expected_pnl)

        # Cash should be: 100k - 50k (invested) + 50k (returned) + 5k (profit) = 105k
        assert trader.cash == pytest.approx(100_000 + expected_pnl)

    def test_round_trip_with_commission(self):
        """Commission deducted on both open and close."""
        trader = PaperTrader(initial_capital=100_000, commission_per_trade=10.0)
        signal = Signal(
            action=Action.LONG,
            size=0.5,
            confidence=0.7,
            instrument="TEST",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            reasoning="test",
        )

        trade = trader.execute(signal, current_price=100.0)
        closed = trader.close_position(trade.trade_id, price=110.0)

        # Profit = 5000, commission = 20 total
        expected_pnl = (110.0 - 100.0) * (0.5 * 100_000 / 100.0)
        assert closed.pnl == pytest.approx(expected_pnl)
        assert trader.cash == pytest.approx(100_000 + expected_pnl - 20.0)

    def test_short_position_cash(self):
        """Short position: profit when price drops."""
        trader = PaperTrader(initial_capital=100_000, commission_per_trade=0.0)
        signal = Signal(
            action=Action.SHORT,
            size=0.5,
            confidence=0.7,
            instrument="TEST",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            reasoning="test",
        )

        trade = trader.execute(signal, current_price=100.0)
        closed = trader.close_position(trade.trade_id, price=90.0)

        # Short profit = (100-90) * qty
        expected_qty = 0.5 * 100_000 / 100.0
        expected_pnl = (100.0 - 90.0) * expected_qty
        assert closed.pnl == pytest.approx(expected_pnl)
        assert trader.cash == pytest.approx(100_000 + expected_pnl)

    def test_exit_time_uses_sim_time(self):
        """Exit time should match entry time (sim time), not wall clock."""
        trader = PaperTrader(initial_capital=100_000)
        ts = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        signal = Signal(
            action=Action.LONG,
            size=0.1,
            confidence=0.6,
            instrument="TEST",
            timestamp=ts,
            reasoning="test",
        )
        trade = trader.execute(signal, current_price=50.0)
        closed = trader.close_position(trade.trade_id, price=55.0, timestamp=ts)
        assert closed.exit_time == ts


# ---------------------------------------------------------------------------
# Confidence position sizing
# ---------------------------------------------------------------------------


class TestConfidenceSizing:
    """Verify the confidence method scales linearly with max_size."""

    def test_confidence_scales_linearly(self):
        size = position_size(0.7, method="confidence", max_size=0.25)
        assert size == pytest.approx(0.7 * 0.25)

    def test_confidence_low(self):
        size = position_size(0.3, method="confidence", max_size=0.25)
        assert size == pytest.approx(0.3 * 0.25)

    def test_confidence_clamped_at_max(self):
        size = position_size(1.0, method="confidence", max_size=0.25)
        assert size == pytest.approx(0.25)

    def test_confidence_zero(self):
        size = position_size(0.0, method="confidence", max_size=0.25)
        assert size == 0.0


# ---------------------------------------------------------------------------
# SPI: no data leakage from future values
# ---------------------------------------------------------------------------


class TestSPINoLeakage:
    """Verify SPI at time t uses only data up to t."""

    def test_spi_early_values_differ_from_late(self):
        """SPI should change as new data arrives, not be constant."""
        np.random.seed(42)
        precip = np.random.exponential(2.0, size=200)
        spi = AnomalyFeatures.spi(precip, window_days=30)

        # Early values (before enough history) should be NaN
        assert np.isnan(spi[0])
        assert np.isnan(spi[5])

        # Later values should be computed
        assert not np.isnan(spi[50])
        assert not np.isnan(spi[100])

    def test_spi_does_not_use_future_data(self):
        """SPI computed on subset should differ from full series at later indices."""
        np.random.seed(42)
        precip = np.random.exponential(2.0, size=100)

        # Compute SPI on first 60 values
        spi_partial = AnomalyFeatures.spi(precip[:60], window_days=30)

        # Compute SPI on all 100 values
        spi_full = AnomalyFeatures.spi(precip, window_days=30)

        # At index 50, the partial series has no future data,
        # but the full series does. If SPI uses future data, these would differ.
        # With rolling fit, they should be the same (both use only data up to t=50).
        if not np.isnan(spi_partial[50]) and not np.isnan(spi_full[50]):
            assert spi_partial[50] == pytest.approx(spi_full[50])

    def test_spi_missing_data_returns_nan(self):
        """All-NaN windows should produce NaN, not 0.0."""
        precip = np.full(50, np.nan)
        spi = AnomalyFeatures.spi(precip, window_days=30)
        assert all(np.isnan(spi))


# ---------------------------------------------------------------------------
# Anomaly detection: rolling only, no future leakage
# ---------------------------------------------------------------------------


class TestAnomalyRolling:
    """Verify anomaly flags use only past + present data."""

    def test_anomaly_detects_spike(self):
        """A sudden spike should be flagged."""
        np.random.seed(42)
        data = np.random.normal(0, 1, 100)
        data[50] = 10.0  # inject spike

        import xarray as xr

        ds = xr.Dataset(
            {"temp": ("time", data)},
            coords={"time": pd.date_range("2024-01-01", periods=100, freq="h")},
        )

        tf = TemporalFeatures(windows=[24], stats=["anomaly"])
        result = tf.build(ds, variables=["temp"])

        # The spike at index 50 should be flagged as anomaly
        # (z-score > 3.0 with window=24)
        is_anom = result["temp_is_anomaly_24"].values
        assert is_anom[50] == True  # noqa: E712

    def test_anomaly_no_future_leakage(self):
        """Anomaly at time t should not depend on data at t+1."""
        data = np.zeros(100)
        data[50] = 10.0  # spike at 50

        import xarray as xr

        ds = xr.Dataset(
            {"temp": ("time", data)},
            coords={"time": pd.date_range("2024-01-01", periods=100, freq="h")},
        )

        tf = TemporalFeatures(windows=[24], stats=["anomaly"])

        # Build on first 51 points (includes spike)
        result_51 = tf.build(ds.isel(time=slice(0, 51)), variables=["temp"])
        result_51["temp_is_anomaly_24"].values[50]

        # Build on first 50 points (no spike yet)
        result_50 = tf.build(ds.isel(time=slice(0, 50)), variables=["temp"])
        # The last value's anomaly flag should not depend on index 50
        # (it's not computed for index 50 since we only have 50 points)
        # But critically, flag at index 49 should be the same in both
        flag_49_in_51 = result_51["temp_is_anomaly_24"].values[49]
        flag_49_in_50 = result_50["temp_is_anomaly_24"].values[49]
        assert flag_49_in_51 == flag_49_in_50


# ---------------------------------------------------------------------------
# Walk-forward: retraining
# ---------------------------------------------------------------------------


class TestWalkForward:
    """Verify walk-forward can retrain the signal generator."""

    def test_walk_forward_retrains(self):
        """retrain_fn should be called with training data each fold."""
        call_log: list[int] = []

        def my_retrain(train_data: pd.DataFrame):
            call_log.append(len(train_data))

            def gen(data: pd.DataFrame, step: int) -> Signal:
                return Signal(
                    action=Action.FLAT,
                    size=0.0,
                    confidence=0.0,
                    instrument="TEST",
                    timestamp=datetime.now(timezone.utc),
                    reasoning="test",
                )

            return gen

        engine = BacktestEngine()
        dates = pd.date_range("2020-01-01", periods=400, freq="D")
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(400) * 0.5)
        data = pd.DataFrame({"close": prices}, index=dates)

        engine.walk_forward(
            signal_generator=None,  # type: ignore
            data=data,
            train_window=100,
            test_window=50,
            retrain_fn=my_retrain,
        )

        # Should have retrained for each fold
        assert len(call_log) > 0
        assert all(n == 100 for n in call_log)

    def test_walk_forward_without_retrain(self):
        """Without retrain_fn, same signal_generator is reused."""

        def gen(data: pd.DataFrame, step: int) -> Signal:
            return Signal(
                action=Action.FLAT,
                size=0.0,
                confidence=0.0,
                instrument="TEST",
                timestamp=datetime.now(timezone.utc),
                reasoning="test",
            )

        engine = BacktestEngine()
        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        prices = 100 + np.cumsum(np.random.randn(300) * 0.5)
        data = pd.DataFrame({"close": prices}, index=dates)

        results = engine.walk_forward(
            signal_generator=gen,
            data=data,
            train_window=100,
            test_window=50,
        )
        assert len(results) > 0
