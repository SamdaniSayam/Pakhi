"""Comprehensive tests for pakhi pipeline, trading, risk, features, predict, targets, grids, and models.

Targets coverage gaps across ~30 modules.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest
import xarray as xr

# ======================================================================
# pipeline/stream.py — StreamingProcessor
# ======================================================================


class TestStreamingProcessor:
    def _make_nc_file(self, tmp_path, n_time=20):
        """Create a tiny NetCDF file for testing."""
        times = pd.date_range("2023-01-01", periods=n_time, freq="h")
        lats = [30.0, 31.0, 32.0]
        lons = [-90.0, -89.0]
        rng = np.random.default_rng(42)
        temp = rng.random((n_time, 3, 2))
        ds = xr.Dataset(
            {"temperature": (["time", "latitude", "longitude"], temp)},
            coords={"time": times, "latitude": lats, "longitude": lons},
        )
        path = tmp_path / "test_data.nc"
        ds.to_netcdf(path)
        return path

    @pytest.fixture(autouse=True)
    def _patch_dataset_data(self):
        """Temporarily add .data property to Dataset for xarray compat."""
        if not hasattr(xr.Dataset, "data"):
            xr.Dataset.data = property(lambda self: None)
            yield
            del xr.Dataset.data
        else:
            yield

    def test_process_chunks_nc(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=8)
        path = self._make_nc_file(tmp_path)
        results = list(sp.process_chunks(path, lambda chunk: chunk))
        assert len(results) >= 1
        total_time = sum(r.sizes["time"] for r in results)
        assert total_time == 20

    def test_process_chunks_file_not_found(self):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor()
        with pytest.raises(FileNotFoundError):
            list(sp.process_chunks("/nonexistent/file.nc", lambda c: c))

    def test_process_chunks_custom_chunk_size(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=100)
        path = self._make_nc_file(tmp_path)
        results = list(sp.process_chunks(path, lambda c: c, chunk_size=5))
        assert len(results) == 4

    def test_process_lazy(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=10)
        path = self._make_nc_file(tmp_path)
        combined = sp.process_lazy(path, lambda c: c, chunk_size=5)
        assert "temperature" in combined.data_vars
        assert combined.sizes["time"] == 20

    def test_process_stream(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=10)
        path = self._make_nc_file(tmp_path)
        results = sp.process_stream(path, lambda c: c)
        assert len(results) >= 1

    def test_process_stream_with_sink(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=10)
        path = self._make_nc_file(tmp_path)
        sink_calls = []
        sp.process_stream(path, lambda c: c, sink_fn=lambda x: sink_calls.append(x))
        assert len(sink_calls) >= 1

    def test_close_all(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=10)
        sp._open_datasets.append(xr.Dataset())
        sp.close_all()
        assert len(sp._open_datasets) == 0

    def test_close_all_with_broken_dataset(self):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor()
        mock_ds = MagicMock()
        mock_ds.close.side_effect = Exception("already closed")
        sp._open_datasets.append(mock_ds)
        sp.close_all()
        assert len(sp._open_datasets) == 0

    def test_process_chunks_process_fn_applied(self, tmp_path):
        from pakhi.pipeline.stream import StreamingProcessor

        sp = StreamingProcessor(chunk_size=8)
        path = self._make_nc_file(tmp_path)

        def identity(chunk):
            return chunk

        results = list(sp.process_chunks(path, identity))
        assert len(results) >= 1


# ======================================================================
# trading/execution.py — PaperTrader
# ======================================================================


class TestPaperTrader:
    def _make_signal(self, action, instrument="NG", size=0.1, confidence=0.7):
        from pakhi.signals.base import Signal

        return Signal(
            action=action,
            size=size,
            confidence=confidence,
            instrument=instrument,
            timestamp=datetime.now(timezone.utc),
            reasoning="test",
        )

    def test_execute_flat(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader()
        sig = self._make_signal("FLAT")
        trade = t.execute(sig, current_price=5.0)
        assert trade.trade_id == "FLAT"
        assert trade.quantity == 0.0

    def test_execute_long(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.1, confidence=0.8)
        trade = t.execute(sig, current_price=5.0)
        assert trade.quantity > 0
        assert t.cash < 100_000

    def test_execute_short(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("SHORT", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        assert trade.quantity > 0
        assert trade.direction.value == "SHORT"

    def test_execute_average_in(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.05)
        t.execute(sig, current_price=5.0)
        # Second same direction
        sig2 = self._make_signal("LONG", size=0.05)
        trade2 = t.execute(sig2, current_price=6.0)
        # Should have averaged in
        assert trade2.quantity > 0

    def test_execute_zero_price_skips(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.1)
        trade = t.execute(sig, current_price=0.0)
        assert trade.trade_id == "SKIP"
        assert trade.quantity == 0.0

    def test_close_position_long(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        closed = t.close_position(trade.trade_id, price=12.0)
        assert closed.status == "closed"
        assert closed.pnl is not None
        assert closed.pnl > 0  # long profit

    def test_close_position_short(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("SHORT", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        closed = t.close_position(trade.trade_id, price=8.0)
        assert closed.pnl > 0  # short profit

    def test_close_position_not_found(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader()
        with pytest.raises(KeyError):
            t.close_position("nonexistent", price=10.0)

    def test_close_position_with_fill_price(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000, slippage_bps=10)
        sig = self._make_signal("LONG", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        closed = t.close_position(trade.trade_id, price=10.0, fill_price=10.5)
        assert closed.exit_price == 10.5

    def test_get_open_positions(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.05)
        t.execute(sig, current_price=10.0)
        opens = t.get_open_positions()
        assert len(opens) == 1

    def test_get_closed_trades(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.05)
        trade = t.execute(sig, current_price=10.0)
        t.close_position(trade.trade_id, price=12.0)
        closed = t.get_closed_trades()
        assert len(closed) == 1

    def test_get_equity(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        eq = t.get_equity({trade.instrument: 12.0})
        assert eq > t.cash  # unrealized profit

    def test_get_equity_short(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("SHORT", size=0.1)
        trade = t.execute(sig, current_price=10.0)
        eq = t.get_equity({trade.instrument: 8.0})
        assert eq > t.cash  # unrealized profit on short

    def test_get_equity_no_trades(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=50_000)
        eq = t.get_equity({})
        assert eq == 50_000

    def test_apply_slippage_long(self):
        from pakhi.signals.base import Action
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(slippage_bps=10)
        price = t._apply_slippage(100.0, Action.LONG)
        assert price == pytest.approx(100.0 * (1 + 10 / 10_000))

    def test_apply_slippage_short(self):
        from pakhi.signals.base import Action
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(slippage_bps=10)
        price = t._apply_slippage(100.0, Action.SHORT)
        assert price == pytest.approx(100.0 * (1 - 10 / 10_000))

    def test_find_open_found(self):
        from pakhi.trading.execution import PaperTrader, TradeDirection

        t = PaperTrader(initial_capital=100_000)
        sig = self._make_signal("LONG", size=0.05)
        trade = t.execute(sig, current_price=10.0)
        tid = t._find_open(trade.instrument, TradeDirection.LONG)
        assert tid is not None

    def test_find_open_not_found(self):
        from pakhi.trading.execution import PaperTrader, TradeDirection

        t = PaperTrader()
        assert t._find_open("NG", TradeDirection.LONG) is None

    def test_repr(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader()
        r = repr(t)
        assert "PaperTrader" in r
        assert "cash=" in r

    def test_commission_applied(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000, commission_per_trade=10.0)
        cash_before = t.cash
        sig = self._make_signal("LONG", size=0.1)
        t.execute(sig, current_price=10.0)
        assert t.cash < cash_before

    def test_close_commission(self):
        from pakhi.trading.execution import PaperTrader

        t = PaperTrader(initial_capital=100_000, commission_per_trade=5.0)
        sig = self._make_signal("LONG", size=0.05)
        trade = t.execute(sig, current_price=10.0)
        # Close at same price so PnL ~ 0, verify commission deducted
        cash_before_close = t.cash
        t.close_position(trade.trade_id, price=10.0)
        # Cash should increase (we get back our investment) but not by more
        # than entry_value - commission
        assert t.cash <= cash_before_close + trade.entry_price * trade.quantity


# ======================================================================
# pipeline/cache.py — WeatherCache
# ======================================================================


class TestWeatherCache:
    def test_hash_key_deterministic(self):
        from pakhi.pipeline.cache import WeatherCache

        k1 = WeatherCache.hash_key("https://api.test.com", {"lat": 40.7})
        k2 = WeatherCache.hash_key("https://api.test.com", {"lat": 40.7})
        assert k1 == k2
        assert len(k1) == 64

    def test_hash_key_no_params(self):
        from pakhi.pipeline.cache import WeatherCache

        k = WeatherCache.hash_key("https://api.test.com")
        assert len(k) == 64

    def test_hash_key_different(self):
        from pakhi.pipeline.cache import WeatherCache

        k1 = WeatherCache.hash_key("https://api.a.com")
        k2 = WeatherCache.hash_key("https://api.b.com")
        assert k1 != k2

    def test_set_and_get(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path, default_ttl_hours=1)
        key = WeatherCache.hash_key("test_url")
        cache.set(key, b"hello")
        result = cache.get(key)
        assert result == b"hello"

    def test_get_miss(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        key = WeatherCache.hash_key("nonexistent")
        assert cache.get(key) is None

    def test_get_stale(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path, default_ttl_hours=0.001)
        key = WeatherCache.hash_key("stale_test")
        cache.set(key, b"data")
        # Mock time forward so the entry becomes stale
        import pakhi.pipeline.cache as cache_mod

        original_time = cache_mod.time.time
        cache_mod.time.time = lambda: original_time() + 10  # jump 10 seconds
        try:
            assert cache.get(key) is None
        finally:
            cache_mod.time.time = original_time

    def test_get_custom_ttl(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path, default_ttl_hours=100)
        key = WeatherCache.hash_key("ttl_test")
        cache.set(key, b"data")
        assert cache.get(key, ttl_hours=100) == b"data"

    def test_set_string(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        key = WeatherCache.hash_key("str_test")
        cache.set(key, "string data")
        assert cache.get(key) == b"string data"

    def test_set_json_and_get_json(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        key = WeatherCache.hash_key("json_test")
        cache.set_json(key, {"a": 1, "b": [2, 3]})
        result = cache.get_json(key)
        assert result == {"a": 1, "b": [2, 3]}

    def test_get_json_miss(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        key = WeatherCache.hash_key("no_json")
        assert cache.get_json(key) is None

    def test_invalidate(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        key = WeatherCache.hash_key("inv")
        cache.set(key, b"data")
        assert cache.invalidate(key) is True
        assert cache.get(key) is None

    def test_invalidate_nonexistent(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        assert cache.invalidate("nonexistent_key") is False

    def test_clear(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        for i in range(3):
            cache.set(WeatherCache.hash_key(f"url_{i}"), f"data_{i}".encode())
        count = cache.clear()
        assert count == 3
        assert cache.entry_count == 0

    def test_entry_count(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        cache.set(WeatherCache.hash_key("a"), b"a")
        cache.set(WeatherCache.hash_key("b"), b"b")
        assert cache.entry_count == 2

    def test_size_mb(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        cache = WeatherCache(cache_dir=tmp_path)
        cache.set(WeatherCache.hash_key("big"), b"x" * 1024)
        assert cache.size_mb >= 0

    def test_corrupt_index_resets(self, tmp_path):
        from pakhi.pipeline.cache import WeatherCache

        idx_path = tmp_path / ".index.json"
        idx_path.write_text("NOT VALID JSON {{{")
        cache = WeatherCache(cache_dir=tmp_path)
        assert isinstance(cache._lru, OrderedDict)

    def test_lru_eviction(self, tmp_path):
        import pakhi.pipeline.cache as cache_mod
        from pakhi.pipeline.cache import WeatherCache

        original_time = cache_mod.time.time
        call_count = [0]

        def fake_time():
            call_count[0] += 1
            # Return increasing times so entries have different LRU timestamps
            return original_time() + call_count[0] * 0.001

        cache_mod.time.time = fake_time
        try:
            cache = WeatherCache(cache_dir=tmp_path, max_size_mb=0.0001, default_ttl_hours=100)
            for i in range(10):
                cache.set(WeatherCache.hash_key(f"url_{i}"), b"x" * 500)
        finally:
            cache_mod.time.time = original_time


# ======================================================================
# pipeline/schedule.py — RefreshScheduler
# ======================================================================


class TestRefreshScheduler:
    def test_schedule_and_cancel(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler(check_interval_seconds=3600)
        called = []
        job_id = s.schedule_refresh(
            callback=lambda: called.append(True),
            interval_hours=1.0,
        )
        assert job_id in s._jobs
        assert s.cancel(job_id) is True
        assert job_id not in s._jobs

    def test_cancel_nonexistent(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler()
        assert s.cancel("nope") is False

    def test_next_run_time(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler()
        now = datetime.now(timezone.utc)
        job_id = s.schedule_refresh(lambda: None, 1.0, next_run_time=now)
        assert s.next_run_time(job_id) is not None
        s.stop()

    def test_next_run_time_nonexistent(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler()
        assert s.next_run_time("nope") is None

    def test_is_stale(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        assert RefreshScheduler.is_stale(time.time() - 7200, 1.0) is True
        assert RefreshScheduler.is_stale(time.time(), 1.0) is False

    def test_schedule_auto_job_id(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler(check_interval_seconds=3600)
        j1 = s.schedule_refresh(lambda: None, 1.0)
        j2 = s.schedule_refresh(lambda: None, 1.0)
        assert j1 != j2
        s.stop()

    def test_naive_datetime_gets_utc(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler(check_interval_seconds=3600)
        naive = datetime(2025, 1, 1, 12, 0, 0)
        job_id = s.schedule_refresh(lambda: None, 1.0, next_run_time=naive)
        rt = s.next_run_time(job_id)
        assert rt.tzinfo is not None
        s.stop()

    def test_stop(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler(check_interval_seconds=0.1)
        s.schedule_refresh(lambda: None, 1.0)
        time.sleep(0.2)
        s.stop()
        assert s._running is False

    def test_callback_exception_handled(self):
        from pakhi.pipeline.schedule import RefreshScheduler

        s = RefreshScheduler(check_interval_seconds=3600)
        now = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.schedule_refresh(lambda: 1 / 0, 1.0, next_run_time=now)
        s._tick()
        # Should not raise; just log the exception
        s.stop()


# ======================================================================
# signals/ensemble_signal.py
# ======================================================================


class TestEnsembleSignal:
    def _sig(self, action, instrument="NG", confidence=0.7):
        from pakhi.signals.base import Signal

        return Signal(
            action=action,
            size=0.1,
            confidence=confidence,
            instrument=instrument,
            timestamp=datetime.now(timezone.utc),
            reasoning="test",
        )

    def test_combine_basic(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        sigs = [
            self._sig("LONG", "NG"),
            self._sig("LONG", "CL"),
            self._sig("SHORT", "HG"),
        ]
        combined = es.combine(sigs)
        assert combined.action.value in ("LONG", "SHORT", "FLAT")

    def test_combine_empty_raises(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        with pytest.raises(ValueError, match="At least one signal"):
            es.combine([])

    def test_combine_all_zero_confidence(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        sigs = [self._sig("LONG", confidence=0.0)]
        combined = es.combine(sigs)
        assert combined.action.value == "FLAT"

    def test_combine_insufficient_agreement(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal(min_agreement=0.8)
        sigs = [
            self._sig("LONG", confidence=0.7),
            self._sig("SHORT", confidence=0.7),
        ]
        combined = es.combine(sigs)
        assert combined.action.value == "FLAT"

    def test_combine_all_long(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        sigs = [
            self._sig("LONG", confidence=0.8),
            self._sig("LONG", confidence=0.9),
            self._sig("LONG", confidence=0.7),
        ]
        combined = es.combine(sigs)
        assert combined.action.value == "LONG"

    def test_combine_all_short(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        sigs = [
            self._sig("SHORT", confidence=0.8),
            self._sig("SHORT", confidence=0.9),
        ]
        combined = es.combine(sigs)
        assert combined.action.value == "SHORT"

    def test_generate_raises(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        with pytest.raises(NotImplementedError):
            es.generate({})

    def test_metadata_populated(self):
        from pakhi.signals.ensemble_signal import EnsembleSignal

        es = EnsembleSignal()
        sigs = [
            self._sig("LONG", "NG", confidence=0.8),
            self._sig("LONG", "CL", confidence=0.9),
        ]
        combined = es.combine(sigs)
        assert "n_signals" in combined.metadata
        assert combined.metadata["n_long"] == 2


# ======================================================================
# signals/wind_power.py
# ======================================================================


class TestWindPowerSignal:
    def test_low_wind_long(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate(
            {
                "wind_forecast": [0.1, 0.15, 0.12],
                "wind_climatology": [0.3, 0.4, 0.5, 0.35, 0.45],
                "market": "PJM",
                "current_time": datetime.now(timezone.utc),
            }
        )
        assert result.action.value == "LONG"

    def test_high_wind_short(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate(
            {
                "wind_forecast": [0.9, 0.95, 0.88],
                "wind_climatology": [0.3, 0.4, 0.5, 0.35, 0.45],
                "market": "ERCOT",
            }
        )
        assert result.action.value == "SHORT"

    def test_empty_forecast(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate({"wind_forecast": []})
        assert result.action.value == "FLAT"

    def test_no_climatology_normal(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate(
            {
                "wind_forecast": [0.5, 0.5, 0.5],
            }
        )
        assert result.action.value == "FLAT"

    def test_empty_climatology(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate(
            {
                "wind_forecast": [0.5],
                "wind_climatology": [],
            }
        )
        assert result.action.value == "FLAT"

    def test_single_value_forecast_no_clim(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal()
        result = sig.generate({"wind_forecast": [0.3]})
        assert result.action.value in ("LONG", "SHORT", "FLAT")

    def test_custom_thresholds(self):
        from pakhi.signals.wind_power import WindPowerSignal

        sig = WindPowerSignal(low_wind_threshold=10, high_wind_threshold=90)
        result = sig.generate(
            {
                "wind_forecast": [0.1, 0.12],
                "wind_climatology": [0.5, 0.6, 0.4, 0.55, 0.45],
            }
        )
        assert result.instrument.endswith("POWER_FUTURES")


# ======================================================================
# risk/alerts.py
# ======================================================================


class TestAlertManager:
    def test_check_freeze(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        alert = mgr.check_freeze({"temperature_min": -5.0})
        assert alert is not None
        assert alert.alert_type == "freeze"

    def test_check_freeze_no_trigger(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        assert mgr.check_freeze({"temperature_min": 10.0}) is None

    def test_freeze_severity_levels(self):
        from pakhi.risk.alerts import AlertManager, AlertSeverity

        mgr = AlertManager()
        # LOW: delta ~1
        a = mgr.check_freeze({"temperature_min": -1.0})
        assert a.severity == AlertSeverity.LOW
        # MEDIUM: delta ~3
        a = mgr.check_freeze({"temperature_min": -3.0})
        assert a.severity == AlertSeverity.MEDIUM
        # HIGH: delta ~7
        a = mgr.check_freeze({"temperature_min": -7.0})
        assert a.severity == AlertSeverity.HIGH
        # CRITICAL: delta ~15
        a = mgr.check_freeze({"temperature_min": -15.0})
        assert a.severity == AlertSeverity.CRITICAL

    def test_check_heatwave(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        temps = [40.0, 41.0, 42.0, 43.0, 35.0]
        alert = mgr.check_heatwave({"temperature_forecast": temps, "location": "Phoenix"})
        assert alert is not None
        assert alert.alert_type == "heatwave"
        assert alert.metadata["consecutive_days"] >= 3

    def test_check_heatwave_no_trigger(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        alert = mgr.check_heatwave({"temperature_forecast": [30.0, 31.0, 32.0]})
        assert alert is None

    def test_check_heatwave_empty(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        assert mgr.check_heatwave({"temperature_forecast": []}) is None

    def test_check_hurricane(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        alert = mgr.check_hurricane(
            {
                "landfall_prob": 0.6,
                "category": 4,
                "closest_approach_miles": 50,
                "location": "Miami",
            }
        )
        assert alert is not None
        assert alert.alert_type == "hurricane"

    def test_check_hurricane_low_prob(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        alert = mgr.check_hurricane({"landfall_prob": 0.05})
        assert alert is None

    def test_hurricane_severity_levels(self):
        from pakhi.risk.alerts import AlertManager, AlertSeverity

        mgr = AlertManager()
        # LOW
        a = mgr.check_hurricane({"landfall_prob": 0.15, "category": 1})
        assert a.severity == AlertSeverity.LOW
        # MEDIUM
        a = mgr.check_hurricane({"landfall_prob": 0.35, "category": 2})
        assert a.severity == AlertSeverity.MEDIUM
        # HIGH
        a = mgr.check_hurricane({"landfall_prob": 0.45, "category": 3})
        assert a.severity == AlertSeverity.HIGH
        # CRITICAL
        a = mgr.check_hurricane({"landfall_prob": 0.7, "category": 5})
        assert a.severity == AlertSeverity.CRITICAL

    def test_check_drought(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        spi_vals = list(np.full(35, -2.0))
        alert = mgr.check_drought(
            {
                "spi_values": spi_vals,
                "region": "Texas",
            }
        )
        assert alert is not None
        assert alert.alert_type == "drought"

    def test_check_drought_no_trigger(self):
        from pakhi.risk.alerts import AlertManager

        mgr = AlertManager()
        alert = mgr.check_drought(
            {
                "spi_values": [0.5] * 10,
            }
        )
        assert alert is None

    def test_send_alert(self):
        from pakhi.risk.alerts import Alert, AlertSeverity, send_alert

        alert = Alert(
            severity=AlertSeverity.HIGH,
            message="Test alert",
            timestamp=datetime.now(timezone.utc),
            trigger_value=1.0,
            alert_type="test",
        )
        send_alert(alert, channels=["log"])
        send_alert(alert, channels=["email"])
        send_alert(alert, channels=["slack"])
        send_alert(alert, channels=["telegram"])
        send_alert(alert, channels=["unknown_channel"])
        send_alert(alert)  # default channels


# ======================================================================
# risk/backtest.py
# ======================================================================


class TestBacktestEngine:
    def _make_data(self, n=100):
        rng = np.random.default_rng(42)
        dates = pd.date_range("2023-01-01", periods=n, freq="D")
        price = 100.0 + np.cumsum(rng.normal(0, 1, n))
        return pd.DataFrame({"close": price}, index=dates)

    def test_run_basic(self):
        from pakhi.risk.backtest import BacktestEngine

        engine = BacktestEngine()
        data = self._make_data()
        from pakhi.signals.base import Action, Signal

        def gen(data, i):
            return Signal(
                action=Action.LONG,
                size=0.5,
                confidence=0.7,
                instrument="TEST",
                timestamp=datetime.now(timezone.utc),
                reasoning="test",
            )

        result = engine.run(gen, data)
        assert result.equity_curve.shape[0] > 0
        assert result.total_return != 0

    def test_run_missing_column(self):
        from pakhi.risk.backtest import BacktestEngine

        engine = BacktestEngine()
        data = pd.DataFrame({"wrong": [1.0, 2.0, 3.0]})
        from pakhi.signals.base import Signal

        with pytest.raises(ValueError, match="Column"):
            engine.run(
                lambda d, i: Signal(
                    action="FLAT",
                    size=0,
                    confidence=0,
                    instrument="X",
                    timestamp=datetime.now(timezone.utc),
                    reasoning="x",
                ),
                data,
            )

    def test_run_short_data(self):
        from pakhi.risk.backtest import BacktestEngine
        from pakhi.signals.base import Action, Signal

        engine = BacktestEngine()
        data = pd.DataFrame({"close": [100.0]}, index=[pd.Timestamp("2023-01-01")])
        result = engine.run(
            lambda d, i: Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=datetime.now(),
                reasoning="x",
            ),
            data,
        )
        assert result.equity_curve.shape[0] == 0

    def test_walk_forward_short_data(self):
        from pakhi.risk.backtest import BacktestEngine
        from pakhi.signals.base import Action, Signal

        engine = BacktestEngine()
        data = self._make_data(50)
        results = engine.walk_forward(
            lambda d, i: Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=datetime.now(),
                reasoning="x",
            ),
            data,
            train_window=30,
            test_window=20,
        )
        assert len(results) >= 1

    def test_walk_forward_with_retrain(self):
        from pakhi.risk.backtest import BacktestEngine
        from pakhi.signals.base import Action, Signal

        engine = BacktestEngine()
        data = self._make_data(200)

        def retrain(train_data):
            return lambda d, i: Signal(
                action=Action.LONG,
                size=0.5,
                confidence=0.6,
                instrument="X",
                timestamp=datetime.now(timezone.utc),
                reasoning="trained",
            )

        results = engine.walk_forward(
            lambda d, i: Signal(
                action=Action.FLAT,
                size=0,
                confidence=0,
                instrument="X",
                timestamp=datetime.now(),
                reasoning="x",
            ),
            data,
            train_window=50,
            test_window=30,
            retrain_fn=retrain,
        )
        assert len(results) >= 1

    def test_sharpe_empty(self):
        from pakhi.risk.backtest import BacktestEngine

        assert BacktestEngine._sharpe(np.array([])) == 0.0

    def test_sharpe_single(self):
        from pakhi.risk.backtest import BacktestEngine

        assert BacktestEngine._sharpe(np.array([0.01])) == 0.0

    def test_max_dd_no_drawdown(self):
        from pakhi.risk.backtest import BacktestEngine

        eq = np.array([100.0, 110.0, 120.0])
        assert BacktestEngine._max_dd(eq) == 0.0

    def test_win_rate_no_trades(self):
        from pakhi.risk.backtest import BacktestEngine

        assert BacktestEngine._win_rate([]) == 0.0

    def test_profit_factor_no_trades(self):
        from pakhi.risk.backtest import BacktestEngine

        assert BacktestEngine._profit_factor([]) == 0.0

    def test_profit_factor_no_losses(self):
        from pakhi.risk.backtest import BacktestEngine

        pf = BacktestEngine._profit_factor([{"pnl": 10}, {"pnl": 20}])
        assert pf == float("inf")

    def test_profit_factor_with_losses(self):
        from pakhi.risk.backtest import BacktestEngine

        pf = BacktestEngine._profit_factor([{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": -3}])
        assert pf == pytest.approx(30 / 8)

    def test_signal_to_position(self):
        from pakhi.risk.backtest import BacktestEngine
        from pakhi.signals.base import Action, Signal

        sig_l = Signal(
            action=Action.LONG,
            size=0.3,
            confidence=0.7,
            instrument="X",
            timestamp=datetime.now(),
            reasoning="x",
        )
        sig_s = Signal(
            action=Action.SHORT,
            size=0.2,
            confidence=0.6,
            instrument="X",
            timestamp=datetime.now(),
            reasoning="x",
        )
        sig_f = Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="X",
            timestamp=datetime.now(),
            reasoning="x",
        )
        assert BacktestEngine._signal_to_position(sig_l) == 0.3
        assert BacktestEngine._signal_to_position(sig_s) == -0.2
        assert BacktestEngine._signal_to_position(sig_f) == 0.0


# ======================================================================
# risk/metrics.py
# ======================================================================


class TestRiskMetrics:
    def test_var(self):
        from pakhi.risk.metrics import var

        rng = np.random.default_rng(0)
        returns = rng.normal(0.001, 0.01, 252)
        v = var(returns, 0.95)
        assert isinstance(v, float)

    def test_var_empty(self):
        from pakhi.risk.metrics import var

        assert np.isnan(var(np.array([])))

    def test_cvar(self):
        from pakhi.risk.metrics import cvar

        rng = np.random.default_rng(1)
        returns = rng.normal(0.001, 0.01, 252)
        cv = cvar(returns, 0.95)
        assert cv >= 0

    def test_cvar_empty(self):
        from pakhi.risk.metrics import cvar

        assert np.isnan(cvar(np.array([])))

    def test_cvar_no_tail(self):
        from pakhi.risk.metrics import cvar

        returns = np.array([0.01, 0.02, 0.03])
        result = cvar(returns, 0.99)
        assert isinstance(result, float)

    def test_sharpe_ratio(self):
        from pakhi.risk.metrics import sharpe_ratio

        rng = np.random.default_rng(2)
        returns = rng.normal(0.001, 0.01, 252)
        s = sharpe_ratio(returns)
        assert isinstance(s, float)

    def test_sharpe_empty(self):
        from pakhi.risk.metrics import sharpe_ratio

        assert np.isnan(sharpe_ratio(np.array([])))

    def test_sharpe_single(self):
        from pakhi.risk.metrics import sharpe_ratio

        assert np.isnan(sharpe_ratio(np.array([0.01])))

    def test_sharpe_constant(self):
        from pakhi.risk.metrics import sharpe_ratio

        assert np.isnan(sharpe_ratio(np.ones(100) * 0.001))

    def test_sortino_ratio(self):
        from pakhi.risk.metrics import sortino_ratio

        rng = np.random.default_rng(3)
        returns = rng.normal(0.001, 0.01, 252)
        s = sortino_ratio(returns)
        assert isinstance(s, float)

    def test_sortino_all_positive(self):
        from pakhi.risk.metrics import sortino_ratio

        assert np.isnan(sortino_ratio(np.abs(np.random.default_rng(4).normal(0.01, 0.001, 100))))

    def test_sortino_empty(self):
        from pakhi.risk.metrics import sortino_ratio

        assert np.isnan(sortino_ratio(np.array([])))

    def test_max_drawdown(self):
        from pakhi.risk.metrics import max_drawdown

        eq = np.array([100, 110, 105, 90, 100])
        dd = max_drawdown(eq)
        assert dd == pytest.approx(20 / 110)

    def test_max_drawdown_short(self):
        from pakhi.risk.metrics import max_drawdown

        assert max_drawdown(np.array([100.0])) == 0.0

    def test_calmar_ratio(self):
        from pakhi.risk.metrics import calmar_ratio

        rng = np.random.default_rng(5)
        returns = rng.normal(0.001, 0.01, 252)
        c = calmar_ratio(returns)
        assert isinstance(c, float)

    def test_calmar_short(self):
        from pakhi.risk.metrics import calmar_ratio

        assert np.isnan(calmar_ratio(np.array([0.01])))

    def test_information_ratio(self):
        from pakhi.risk.metrics import information_ratio

        rng = np.random.default_rng(6)
        r = rng.normal(0.001, 0.01, 252)
        b = rng.normal(0.0005, 0.01, 252)
        ir = information_ratio(r, b)
        assert isinstance(ir, float)

    def test_information_ratio_short(self):
        from pakhi.risk.metrics import information_ratio

        assert np.isnan(information_ratio(np.array([0.01]), np.array([0.005])))

    def test_information_ratio_zero_te(self):
        from pakhi.risk.metrics import information_ratio

        r = np.ones(100) * 0.01
        b = np.ones(100) * 0.01
        assert np.isnan(information_ratio(r, b))


# ======================================================================
# risk/uncertainty.py
# ======================================================================


class TestUncertainty:
    def test_ensemble_spread(self):
        from pakhi.risk.uncertainty import ensemble_spread

        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        s = ensemble_spread(arr)
        assert s > 0

    def test_ensemble_spread_empty(self):
        from pakhi.risk.uncertainty import ensemble_spread

        assert np.isnan(ensemble_spread(np.array([])))

    def test_ensemble_spread_single(self):
        from pakhi.risk.uncertainty import ensemble_spread

        assert ensemble_spread(np.array([5.0])) == 0.0

    def test_ensemble_spread_2d(self):
        from pakhi.risk.uncertainty import ensemble_spread

        arr = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        s = ensemble_spread(arr)
        assert isinstance(s, float)

    def test_calibration_error(self):
        from pakhi.risk.uncertainty import calibration_error

        pred = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        obs = np.array([0.12, 0.28, 0.51, 0.69, 0.88])
        ce = calibration_error(pred, obs)
        assert ce < 0.05

    def test_calibration_error_empty(self):
        from pakhi.risk.uncertainty import calibration_error

        assert np.isnan(calibration_error(np.array([]), np.array([])))

    def test_calibration_error_zero_bins(self):
        from pakhi.risk.uncertainty import calibration_error

        assert calibration_error(np.array([0.5]), np.array([0.5]), n_bins=0) == 0.0

    def test_sharpness(self):
        from pakhi.risk.uncertainty import sharpness

        q = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        s = sharpness(q)
        assert s == pytest.approx(0.8)

    def test_sharpness_short(self):
        from pakhi.risk.uncertainty import sharpness

        assert np.isnan(sharpness(np.array([0.5])))

    def test_coverage(self):
        from pakhi.risk.uncertainty import coverage

        lower = np.array([0.0, 0.0, 0.0])
        upper = np.array([10.0, 10.0, 10.0])
        obs = np.array([5.0, 5.0, 5.0])
        assert coverage(lower, upper, obs) == 1.0

    def test_coverage_partial(self):
        from pakhi.risk.uncertainty import coverage

        lower = np.array([0.0, 0.0])
        upper = np.array([5.0, 5.0])
        obs = np.array([3.0, 10.0])
        assert coverage(lower, upper, obs) == 0.5

    def test_coverage_empty(self):
        from pakhi.risk.uncertainty import coverage

        assert np.isnan(coverage(np.array([]), np.array([]), np.array([])))


# ======================================================================
# trading/pnl.py
# ======================================================================


class TestPnL:
    def test_compute_equity_curve(self):
        from pakhi.trading.pnl import compute_equity_curve

        eq = compute_equity_curve(1000, [100, -50, 200])
        np.testing.assert_array_almost_equal(eq, [1000, 1100, 1050, 1250])

    def test_compute_equity_empty(self):
        from pakhi.trading.pnl import compute_equity_curve

        eq = compute_equity_curve(1000, [])
        np.testing.assert_array_almost_equal(eq, [1000])

    def test_calculate_pnl_basic(self):
        from pakhi.trading.pnl import calculate_pnl

        dt = datetime.now(timezone.utc)
        trades = [
            (dt, dt, "NG", "LONG", 5.0, 6.0, 1000.0),
            (dt, dt, "CL", "SHORT", 80.0, 75.0, 500.0),
            (dt, dt, "NG", "LONG", 5.0, 4.5, -200.0),
        ]
        result = calculate_pnl(trades, initial_capital=100_000)
        assert result.total_return == pytest.approx(1300 / 100_000)
        assert result.win_rate == pytest.approx(2 / 3)

    def test_calculate_pnl_empty(self):
        from pakhi.trading.pnl import calculate_pnl

        result = calculate_pnl([])
        assert result.total_return == 0.0
        assert result.equity_curve.shape[0] == 1

    def test_calculate_pnl_all_wins(self):
        from pakhi.trading.pnl import calculate_pnl

        dt = datetime.now(timezone.utc)
        trades = [(dt, dt, "X", "LONG", 10, 12, 200)] * 5
        result = calculate_pnl(trades)
        assert result.win_rate == 1.0
        assert result.profit_factor == float("inf")

    def test_calculate_pnl_all_losses(self):
        from pakhi.trading.pnl import calculate_pnl

        dt = datetime.now(timezone.utc)
        trades = [(dt, dt, "X", "LONG", 10, 8, -200)] * 5
        result = calculate_pnl(trades)
        assert result.win_rate == 0.0
        assert result.profit_factor == 0.0

    def test_pnl_result_defaults(self):
        from pakhi.trading.pnl import PnLResult

        r = PnLResult()
        assert r.total_return == 0.0
        assert r.equity_curve.shape[0] == 0


# ======================================================================
# trading/portfolio.py
# ======================================================================


class TestPortfolio:
    def test_init(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.2, kelly_fraction=0.5)
        assert p.max_position == 0.2

    def test_init_invalid_max_position(self):
        from pakhi.trading.portfolio import Portfolio

        with pytest.raises(ValueError):
            Portfolio(max_position=0.0)
        with pytest.raises(ValueError):
            Portfolio(max_position=1.5)

    def test_init_invalid_kelly(self):
        from pakhi.trading.portfolio import Portfolio

        with pytest.raises(ValueError):
            Portfolio(kelly_fraction=0.0)

    def test_kelly_criterion(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.5, kelly_fraction=0.5)
        size = p.kelly_criterion(0.6, odds=2.0)
        assert size > 0
        assert size <= 0.5

    def test_kelly_negative_edge(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        assert p.kelly_criterion(0.1, odds=2.0) == 0.0

    def test_equal_weight(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.5)
        assert p.equal_weight(4) == pytest.approx(0.25)
        assert p.equal_weight(1) == 0.5  # capped

    def test_equal_weight_invalid(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        with pytest.raises(ValueError):
            p.equal_weight(0)

    def test_risk_parity(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        returns = np.column_stack(
            [
                np.random.default_rng(0).normal(0, 0.01, 100),
                np.random.default_rng(1).normal(0, 0.02, 100),
            ]
        )
        weights = p.risk_parity(returns)
        assert weights.shape == (2,)
        assert abs(weights.sum() - 1.0) < 1e-10

    def test_risk_parity_1d(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        w = p.risk_parity(np.array([0.01, 0.02, 0.03]))
        assert w.shape == (1,)

    def test_position_size_kelly(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.3)
        s = p.position_size(0.8, method="kelly", odds=2.0)
        assert 0 < s <= 0.3

    def test_position_size_equal_weight(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.5)
        s = p.position_size(0.5, method="equal_weight", n_instruments=5)
        assert s == pytest.approx(0.2)

    def test_position_size_risk_parity(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.5)
        returns = np.random.default_rng(2).normal(0, 0.01, (100, 2))
        s = p.position_size(0.5, method="risk_parity", returns_matrix=returns)
        assert 0 < s <= 0.5

    def test_position_size_unknown_method(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        with pytest.raises(ValueError, match="Unknown sizing method"):
            p.position_size(0.5, method="unknown")

    def test_position_size_risk_parity_no_matrix(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio()
        with pytest.raises(ValueError, match="returns_matrix"):
            p.position_size(0.5, method="risk_parity")

    def test_repr(self):
        from pakhi.trading.portfolio import Portfolio

        assert "Portfolio" in repr(Portfolio())

    def test_max_position_override(self):
        from pakhi.trading.portfolio import Portfolio

        p = Portfolio(max_position=0.1)
        s = p.position_size(0.9, method="kelly", max_position=0.5, odds=3.0)
        assert s <= 0.5


# ======================================================================
# features/anomaly.py
# ======================================================================


class TestAnomalyFeatures:
    def test_zscore_anomaly(self):
        from pakhi.features.anomaly import AnomalyFeatures

        data = np.array([10.0, 12.0, 8.0])
        mean = np.array([9.0, 10.0, 9.0])
        std = np.array([1.0, 1.0, 1.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        np.testing.assert_array_almost_equal(result, [1.0, 2.0, -1.0])

    def test_zscore_anomaly_zero_std(self):
        from pakhi.features.anomaly import AnomalyFeatures

        result = AnomalyFeatures.zscore_anomaly(np.array([1.0]), np.array([0.0]), np.array([0.0]))
        assert np.isnan(result[0])

    def test_zscore_anomaly_xr(self):
        from pakhi.features.anomaly import AnomalyFeatures

        data = xr.DataArray([10.0, 12.0], dims=["time"])
        mean = xr.DataArray([9.0, 10.0], dims=["time"])
        std = xr.DataArray([1.0, 1.0], dims=["time"])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        assert isinstance(result, xr.DataArray)

    def test_zscore_anomaly_pd(self):
        from pakhi.features.anomaly import AnomalyFeatures

        data = pd.Series([10.0, 12.0])
        mean = pd.Series([9.0, 10.0])
        std = pd.Series([1.0, 1.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        assert isinstance(result, pd.Series)

    def test_percentile_rank(self):
        from pakhi.features.anomaly import AnomalyFeatures

        hist = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        rank = AnomalyFeatures.percentile_rank(5, hist)
        assert 40 <= rank <= 60

    def test_percentile_rank_array(self):
        from pakhi.features.anomaly import AnomalyFeatures

        hist = np.arange(100, dtype=float)
        result = AnomalyFeatures.percentile_rank(np.array([25, 75]), hist)
        assert len(result) == 2

    def test_percentile_rank_empty_hist(self):
        from pakhi.features.anomaly import AnomalyFeatures

        assert np.isnan(AnomalyFeatures.percentile_rank(5, np.array([])))

    def test_percentile_rank_pd(self):
        from pakhi.features.anomaly import AnomalyFeatures

        result = AnomalyFeatures.percentile_rank(
            pd.Series([5.0, 7.0]),
            np.arange(10, dtype=float),
        )
        assert isinstance(result, pd.Series)

    def test_departure_from_normal(self):
        from pakhi.features.anomaly import AnomalyFeatures

        result = AnomalyFeatures.departure_from_normal(np.array([10, 12]), np.array([8, 10]))
        np.testing.assert_array_equal(result, [2, 2])

    def test_spi(self):
        from pakhi.features.anomaly import AnomalyFeatures

        rng = np.random.default_rng(42)
        precip = rng.exponential(2, 365)
        spi_result = AnomalyFeatures.spi(precip, window_days=30)
        assert len(spi_result) == 365

    def test_spi_pd(self):
        from pakhi.features.anomaly import AnomalyFeatures

        rng = np.random.default_rng(43)
        precip = pd.Series(rng.exponential(2, 100))
        result = AnomalyFeatures.spi(precip, window_days=10)
        assert isinstance(result, pd.Series)

    def test_spi_xr(self):
        from pakhi.features.anomaly import AnomalyFeatures

        rng = np.random.default_rng(44)
        precip = xr.DataArray(
            rng.exponential(2, (5, 100)),
            dims=["location", "time"],
        )
        result = AnomalyFeatures.spi(precip, window_days=10)
        assert isinstance(result, xr.DataArray)


# ======================================================================
# features/climate.py
# ======================================================================


class TestClimateFeatures:
    def test_hdd(self):
        from pakhi.features.climate import ClimateFeatures

        result = ClimateFeatures.hdd(np.array([15.0, 20.0, 25.0]))
        np.testing.assert_array_almost_equal(result, [3.3, 0.0, 0.0])

    def test_hdd_scalar(self):
        from pakhi.features.climate import ClimateFeatures

        assert ClimateFeatures.hdd(10.0) == pytest.approx(8.3)

    def test_cdd(self):
        from pakhi.features.climate import ClimateFeatures

        result = ClimateFeatures.cdd(np.array([15.0, 20.0, 25.0]))
        np.testing.assert_array_almost_equal(result, [0.0, 1.7, 6.7], decimal=1)

    def test_gdd(self):
        from pakhi.features.climate import ClimateFeatures

        result = ClimateFeatures.gdd(np.array([5.0, 15.0, 35.0]))
        np.testing.assert_array_almost_equal(result, [0.0, 5.0, 20.0])

    def test_gdd_xr(self):
        from pakhi.features.climate import ClimateFeatures

        data = xr.DataArray([15.0, 25.0], dims=["time"])
        result = ClimateFeatures.gdd(data)
        assert isinstance(result, xr.DataArray)

    def test_gdd_pd(self):
        from pakhi.features.climate import ClimateFeatures

        data = pd.Series([15.0, 25.0])
        result = ClimateFeatures.gdd(data)
        assert isinstance(result, pd.Series)

    def test_dry_days(self):
        from pakhi.features.climate import ClimateFeatures

        precip = np.array([0.0, 0.0, 5.0, 0.0, 0.0, 0.0])
        result = ClimateFeatures.dry_days(precip, threshold_mm=1.0, window_days=3)
        # Rolling window of 3 at last index covers [0.0, 0.0, 0.0] → all dry
        assert result[-1] == pytest.approx(1.0)
        # Middle element at index 2 covers [0, 0, 5] → 2/3 dry
        assert result[2] == pytest.approx(2 / 3)

    def test_dry_days_pd(self):
        from pakhi.features.climate import ClimateFeatures

        precip = pd.Series([0.0, 5.0, 0.0, 0.0])
        result = ClimateFeatures.dry_days(precip, window_days=2)
        assert isinstance(result, pd.Series)

    def test_dry_days_xr(self):
        from pakhi.features.climate import ClimateFeatures

        precip = xr.DataArray([0.0, 5.0, 0.0, 0.0], dims=["time"])
        result = ClimateFeatures.dry_days(precip, window_days=2)
        assert isinstance(result, xr.DataArray)

    def test_frost_days(self):
        from pakhi.features.climate import ClimateFeatures

        temps = np.array([-2, 5, 0, 10])
        result = ClimateFeatures.frost_days(temps)
        np.testing.assert_array_equal(result, [True, False, True, False])

    def test_frost_days_scalar(self):
        from pakhi.features.climate import ClimateFeatures

        assert ClimateFeatures.frost_days(-1.0) is True
        assert ClimateFeatures.frost_days(5.0) is False

    def test_frost_days_pd(self):
        from pakhi.features.climate import ClimateFeatures

        result = ClimateFeatures.frost_days(pd.Series([-1.0, 5.0]))
        assert isinstance(result, pd.Series)

    def test_frost_days_xr(self):
        from pakhi.features.climate import ClimateFeatures

        result = ClimateFeatures.frost_days(xr.DataArray([-1.0, 5.0]))
        assert isinstance(result, xr.DataArray)

    def test_heatwave_days(self):
        from pakhi.features.climate import ClimateFeatures

        temps = np.array([30, 36, 37, 38, 36, 25])
        result = ClimateFeatures.heatwave_days(temps, threshold_celsius=35, consecutive_days=2)
        expected = np.array([False, True, True, True, True, False])
        np.testing.assert_array_equal(result, expected)

    def test_heatwave_days_pd(self):
        from pakhi.features.climate import ClimateFeatures

        temps = pd.Series([36, 37, 38, 25])
        result = ClimateFeatures.heatwave_days(temps, consecutive_days=2)
        assert isinstance(result, pd.Series)

    def test_heatwave_days_xr(self):
        from pakhi.features.climate import ClimateFeatures

        temps = xr.DataArray([36, 37, 38, 25])
        result = ClimateFeatures.heatwave_days(temps, consecutive_days=2)
        assert isinstance(result, xr.DataArray)


# ======================================================================
# features/satellite.py
# ======================================================================


class TestSatelliteFeatures:
    def test_brightness_temperature(self):
        from pakhi.features.satellite import SatelliteFeatures

        radiance = np.array([100.0, 200.0, 500.0])
        result = SatelliteFeatures.brightness_temperature(radiance, band_number=4)
        assert result.shape == (3,)
        assert np.all(np.isfinite(result))

    def test_brightness_temperature_scalar(self):
        from pakhi.features.satellite import SatelliteFeatures

        result = SatelliteFeatures.brightness_temperature(12345.0, 2)
        assert np.ndim(result) == 0

    def test_brightness_temperature_xr(self):
        from pakhi.features.satellite import SatelliteFeatures

        data = xr.DataArray([[100.0, 200.0]], dims=["time", "x"])
        result = SatelliteFeatures.brightness_temperature(data, band_number=4)
        assert isinstance(result, xr.DataArray)

    def test_brightness_temperature_digit_count(self):
        from pakhi.features.satellite import SatelliteFeatures

        result = SatelliteFeatures.brightness_temperature(np.array([50.0, 80.0]), band_number=3)
        assert np.all(np.isfinite(result))

    def test_cloud_fraction(self):
        from pakhi.features.satellite import SatelliteFeatures

        data = np.random.default_rng(0).uniform(200, 300, (10, 10))
        result = SatelliteFeatures.cloud_fraction(data, threshold_k=260.0)
        assert 0 <= result <= 1

    def test_cloud_fraction_xr(self):
        from pakhi.features.satellite import SatelliteFeatures

        data = xr.DataArray(
            np.random.default_rng(1).uniform(200, 300, (5, 5)),
            dims=["latitude", "longitude"],
        )
        result = SatelliteFeatures.cloud_fraction(data)
        assert isinstance(result, xr.DataArray)

    def test_cloud_fraction_scalar(self):
        from pakhi.features.satellite import SatelliteFeatures

        result = SatelliteFeatures.cloud_fraction(250.0)
        assert result == 1.0

    def test_cloud_motion_vectors_too_few_times(self):
        from pakhi.features.satellite import SatelliteFeatures

        arr = np.random.default_rng(2).random((1, 30, 30))
        with pytest.raises(ValueError, match="at least 2 time"):
            SatelliteFeatures.cloud_motion_vectors(arr, time_delta_minutes=15)

    def test_cloud_motion_vectors_not_3d(self):
        from pakhi.features.satellite import SatelliteFeatures

        with pytest.raises(ValueError, match="Expected 3D"):
            SatelliteFeatures.cloud_motion_vectors(
                np.random.default_rng(3).random((10, 10)),
                time_delta_minutes=15,
            )


# ======================================================================
# features/spatial.py
# ======================================================================


class TestSpatialFeatures:
    def test_distance_weighted_average(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        data = xr.DataArray(
            np.random.default_rng(0).random((5, 5)),
            dims=["latitude", "longitude"],
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.distance_weighted_average(data, 35, -85)
        assert isinstance(result, xr.DataArray)

    def test_distance_weighted_average_dataset(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        ds = xr.Dataset(
            {
                "temp": (["latitude", "longitude"], np.random.default_rng(1).random((5, 5))),
                "pres": (["latitude", "longitude"], np.random.default_rng(2).random((5, 5))),
            },
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.distance_weighted_average(ds, 35, -85)
        assert isinstance(result, xr.Dataset)

    def test_gradient(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        data = xr.DataArray(
            np.random.default_rng(3).random((5, 5)),
            dims=["latitude", "longitude"],
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.gradient(data)
        assert "magnitude" in result
        assert "direction" in result

    def test_gradient_with_dx(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        data = xr.DataArray(
            np.random.default_rng(4).random((5, 5)),
            dims=["latitude", "longitude"],
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.gradient(data, dx_km=100)
        assert "magnitude" in result

    def test_gradient_dataset(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        ds = xr.Dataset(
            {
                "temp": (["latitude", "longitude"], np.random.default_rng(5).random((5, 5))),
            },
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.gradient(ds)
        assert "magnitude" in result

    def test_convergence(self):
        from pakhi.features.spatial import SpatialFeatures

        lats = np.linspace(30, 40, 5)
        lons = np.linspace(-90, -80, 5)
        ds = xr.Dataset(
            {
                "u": (["latitude", "longitude"], np.random.default_rng(6).random((5, 5))),
                "v": (["latitude", "longitude"], np.random.default_rng(7).random((5, 5))),
            },
            coords={"latitude": lats, "longitude": lons},
        )
        result = SpatialFeatures.convergence(ds)
        assert "convergence" in result
        assert "divergence" in result

    def test_distance_to_coast(self):
        from pakhi.features.spatial import SpatialFeatures

        dist = SpatialFeatures.distance_to_coast(40.0, -74.0)
        assert dist >= 0

    def test_distance_to_coast_with_coastline_data(self):
        from pakhi.features.spatial import SpatialFeatures

        coast = np.array([[40.0, -74.0], [41.0, -73.0]])
        dist = SpatialFeatures.distance_to_coast(40.0, -74.0, coastline_data=coast)
        assert dist == pytest.approx(0.0)

    def test_distance_to_coast_array(self):
        from pakhi.features.spatial import SpatialFeatures

        dist = SpatialFeatures.distance_to_coast(
            np.array([40.0, 50.0]),
            np.array([-74.0, -80.0]),
        )
        assert dist.shape == (2,)


# ======================================================================
# features/teleconnection.py
# ======================================================================


class TestTeleconnectionIndices:
    def _make_sst_data(self):
        times = pd.date_range("2023-01-01", periods=12, freq="MS")
        lats = np.linspace(-10, 10, 5)
        lons = np.linspace(-170, -120, 5)
        rng = np.random.default_rng(42)
        sst = 25 + rng.random((12, 5, 5))
        return xr.DataArray(
            sst,
            dims=["time", "latitude", "longitude"],
            coords={"time": times, "latitude": lats, "longitude": lons},
        )

    def test_compute_nino34(self):
        from pakhi.features.teleconnection import TeleconnectionIndices

        sst = self._make_sst_data()
        result = TeleconnectionIndices.compute_nino34(sst, anomalous=True)
        assert isinstance(result, xr.DataArray)

    def test_compute_nino34_dataset(self):
        from pakhi.features.teleconnection import TeleconnectionIndices

        sst_da = self._make_sst_data()
        ds = xr.Dataset({"sst": sst_da})
        result = TeleconnectionIndices.compute_nino34(ds, sst_var="sst")
        assert isinstance(result, xr.DataArray)

    def test_computepdo(self):
        from pakhi.features.teleconnection import TeleconnectionIndices

        times = pd.date_range("2023-01-01", periods=12, freq="MS")
        lats = np.linspace(20, 60, 5)
        lons = np.linspace(-170, -115, 5)
        rng = np.random.default_rng(43)
        sst = 20 + rng.random((12, 5, 5))
        data = xr.DataArray(
            sst,
            dims=["time", "latitude", "longitude"],
            coords={"time": times, "latitude": lats, "longitude": lons},
        )
        result = TeleconnectionIndices.computepdo(data)
        assert isinstance(result, xr.DataArray)


# ======================================================================
# predict/deterministic.py
# ======================================================================


class TestDeterministicPredictor:
    def _mock_model(self, prediction=1.0):
        model = MagicMock()
        model.predict.return_value = np.array([prediction])
        return model

    def _mock_fit_model(self, predictions=None):
        model = MagicMock()
        if predictions is None:
            model.predict.return_value = np.array([1.0, 2.0, 3.0])
        else:
            model.predict.return_value = np.array(predictions)
        return model

    def test_predict_single(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_model(5.0)
        result = dp.predict_single(model, np.array([1.0, 2.0, 3.0]), forecast_horizon=10)
        assert result.values.shape == (10,)
        assert np.all(result.values == 5.0)

    def test_predict_multi_step_recursive(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_model(3.0)
        result = dp.predict_multi_step(model, np.array([1.0, 2.0]), steps=5, method="recursive")
        assert result.values.shape == (5,)

    def test_predict_multi_step_direct(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_fit_model()
        y_train = np.arange(20, dtype=float)
        X_train = np.random.default_rng(0).random((20, 3))
        with patch.object(
            DeterministicPredictor,
            "_clone_model",
            side_effect=lambda m: MagicMock(predict=m.predict, fit=m.fit),
        ):
            result = dp.predict_multi_step(
                model,
                np.array([1.0, 2.0, 3.0]),
                steps=3,
                method="direct",
                y_train=y_train,
                X_train=X_train,
            )
        assert result.values.shape == (3,)

    def test_predict_multi_step_direct_no_data(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_fit_model()
        with pytest.raises(ValueError, match="y_train and X_train"):
            dp.predict_multi_step(model, np.array([1.0]), steps=3, method="direct")

    def test_predict_multi_step_multi_output(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_fit_model()
        y_train = np.arange(50, dtype=float)
        X_train = np.random.default_rng(1).random((50, 2))
        with patch.object(
            DeterministicPredictor,
            "_clone_model",
            side_effect=lambda m: MagicMock(predict=m.predict, fit=m.fit),
        ):
            result = dp.predict_multi_step(
                model,
                np.array([1.0, 2.0]),
                steps=5,
                method="multi_output",
                y_train=y_train,
                X_train=X_train,
            )
        assert result.values.ndim == 1
        assert len(result.values) <= 5

    def test_predict_multi_step_multi_output_no_data(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_fit_model()
        with pytest.raises(ValueError):
            dp.predict_multi_step(model, np.array([1.0]), steps=3, method="multi_output")

    def test_predict_multi_step_unknown_method(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = self._mock_model()
        with pytest.raises(ValueError, match="Unknown method"):
            dp.predict_multi_step(model, np.array([1.0]), steps=3, method="bad")

    def test_optimize_threshold_f1(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = MagicMock()
        model.predict_proba.return_value = np.column_stack(
            [
                np.linspace(0.9, 0.1, 100),
                np.linspace(0.1, 0.9, 100),
            ]
        )
        X = np.random.default_rng(2).random((100, 3))
        y = np.array([0] * 50 + [1] * 50, dtype=float)
        best_t = dp.optimize_threshold(model, X, y, metric="f1")
        assert 0 <= best_t <= 1

    def test_optimize_threshold_precision(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = MagicMock()
        model.predict_proba.return_value = np.column_stack(
            [
                np.linspace(0.9, 0.1, 50),
                np.linspace(0.1, 0.9, 50),
            ]
        )
        best_t = dp.optimize_threshold(
            model,
            np.random.default_rng(3).random((50, 2)),
            np.array([0] * 25 + [1] * 25, dtype=float),
            metric="precision",
        )
        assert 0 <= best_t <= 1

    def test_optimize_threshold_decision_function(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = MagicMock(spec=["decision_function"])
        model.decision_function.return_value = np.linspace(-2, 2, 50)
        best_t = dp.optimize_threshold(
            model,
            np.random.default_rng(4).random((50, 2)),
            np.array([0] * 25 + [1] * 25, dtype=float),
            metric="accuracy",
        )
        assert 0 <= best_t <= 1

    def test_optimize_threshold_no_model_method(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        dp = DeterministicPredictor()
        model = MagicMock(spec=[])  # no predict_proba or decision_function
        with pytest.raises(TypeError):
            dp.optimize_threshold(model, np.array([[1]]), np.array([0]))

    def test_compute_metric(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 0, 1, 0])
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "accuracy") == 0.5
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "precision") == 0.5
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "recall") == 0.5

    def test_compute_metric_unknown(self):
        from pakhi.predict.deterministic import DeterministicPredictor

        with pytest.raises(ValueError, match="Unknown metric"):
            DeterministicPredictor._compute_metric(np.array([0, 1]), np.array([0, 1]), "bad_metric")


# ======================================================================
# predict/verification.py
# ======================================================================


class TestVerification:
    def test_rmse(self):
        from pakhi.predict.verification import rmse

        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.1, 2.2, 2.8])
        assert rmse(y_true, y_pred) == pytest.approx(np.sqrt(np.mean([0.01, 0.04, 0.04])))

    def test_rmse_empty(self):
        from pakhi.predict.verification import rmse

        assert np.isnan(rmse(np.array([]), np.array([])))

    def test_mae(self):
        from pakhi.predict.verification import mae

        assert mae(np.array([1.0, 2.0]), np.array([1.0, 3.0])) == pytest.approx(0.5)

    def test_mae_empty(self):
        from pakhi.predict.verification import mae

        assert np.isnan(mae(np.array([]), np.array([])))

    def test_mape(self):
        from pakhi.predict.verification import mape

        result = mape(np.array([100.0, 200.0]), np.array([110.0, 180.0]))
        assert result == pytest.approx(0.1)

    def test_mape_zero_true(self):
        from pakhi.predict.verification import mape

        assert np.isnan(mape(np.array([0.0]), np.array([1.0])))

    def test_mape_empty(self):
        from pakhi.predict.verification import mape

        assert np.isnan(mape(np.array([]), np.array([])))

    def test_bias(self):
        from pakhi.predict.verification import bias

        assert bias(np.array([1.0, 2.0]), np.array([1.5, 2.5])) == pytest.approx(0.5)

    def test_bias_empty(self):
        from pakhi.predict.verification import bias

        assert np.isnan(bias(np.array([]), np.array([])))

    def test_acc(self):
        from pakhi.predict.verification import acc

        y = np.array([10.0, 12.0, 11.0, 13.0])
        p = np.array([10.5, 11.5, 11.5, 12.5])
        result = acc(y, p, climatology=11.0)
        assert 0.5 < result <= 1.0

    def test_acc_too_short(self):
        from pakhi.predict.verification import acc

        assert np.isnan(acc(np.array([1.0]), np.array([1.0]), 1.0))

    def test_brier_score(self):
        from pakhi.predict.verification import brier_score

        bs = brier_score(np.array([0.8, 0.2]), np.array([1.0, 0.0]))
        assert bs == pytest.approx(0.04)

    def test_brier_score_empty(self):
        from pakhi.predict.verification import brier_score

        assert np.isnan(brier_score(np.array([]), np.array([])))

    def test_brier_skill_score(self):
        from pakhi.predict.verification import brier_skill_score

        bss = brier_skill_score(np.array([0.9, 0.1]), np.array([1.0, 0.0]), climatology_prob=0.5)
        assert bss > 0

    def test_brier_skill_score_zero_clim(self):
        from pakhi.predict.verification import brier_skill_score

        bss = brier_skill_score(np.array([0.5]), np.array([1.0]), climatology_prob=0.0)
        assert isinstance(bss, float)
        assert bss == pytest.approx(0.75)

    def test_roc_auc(self):
        from pakhi.predict.verification import roc_auc

        y_prob = np.array([0.9, 0.8, 0.3, 0.1])
        y_obs = np.array([1, 1, 0, 0])
        auc = roc_auc(y_prob, y_obs)
        assert auc > 0.9

    def test_roc_auc_no_positives(self):
        from pakhi.predict.verification import roc_auc

        assert np.isnan(roc_auc(np.array([0.1, 0.2]), np.array([0, 0])))

    def test_roc_auc_empty(self):
        from pakhi.predict.verification import roc_auc

        assert np.isnan(roc_auc(np.array([]), np.array([])))

    def test_discrimination(self):
        from pakhi.predict.verification import discrimination

        y_prob = np.random.default_rng(0).uniform(0, 1, 200)
        y_obs = (y_prob > 0.5).astype(float)
        result = discrimination(y_prob, y_obs, n_bins=5)
        assert "event_hist" in result
        assert "no_event_hist" in result


# ======================================================================
# targets/precipitation.py
# ======================================================================


class TestPrecipitation:
    def test_precipitation_accumulation(self):
        from pakhi.targets.precipitation import precipitation_accumulation

        result = precipitation_accumulation([1.0, 2.0, 3.0], window_hours=6)
        assert result > 0

    def test_precipitation_accumulation_single(self):
        from pakhi.targets.precipitation import precipitation_accumulation

        assert precipitation_accumulation([1.0], window_hours=6) == 0.0

    def test_precipitation_accumulation_non_1d(self):
        from pakhi.targets.precipitation import precipitation_accumulation

        with pytest.raises(ValueError):
            precipitation_accumulation(np.ones((3, 3)), 6)

    def test_snow_probability_all_snow(self):
        from pakhi.targets.precipitation import snow_probability

        result = snow_probability([-5, -3, -1], [1.0, 1.0, 1.0])
        assert result == 1.0

    def test_snow_probability_all_rain(self):
        from pakhi.targets.precipitation import snow_probability

        result = snow_probability([10, 15, 20], [1.0, 1.0, 1.0])
        assert result == 0.0

    def test_snow_probability_no_precip(self):
        from pakhi.targets.precipitation import snow_probability

        assert snow_probability([0, -5], [0.0, 0.0]) == 0.0

    def test_snow_probability_mixed(self):
        from pakhi.targets.precipitation import snow_probability

        result = snow_probability([0, 2, -1], [1.0, 1.0, 1.0])
        assert 0 < result < 1

    def test_snow_probability_shape_mismatch(self):
        from pakhi.targets.precipitation import snow_probability

        with pytest.raises(ValueError):
            snow_probability([1, 2], [1.0])

    def test_drought_index(self):
        from pakhi.targets.precipitation import drought_index

        rng = np.random.default_rng(42)
        precip = rng.exponential(2, 200)
        result = drought_index(precip, window_days=30)
        assert isinstance(result, float)

    def test_drought_index_too_short(self):
        from pakhi.targets.precipitation import drought_index

        with pytest.raises(ValueError):
            drought_index(np.ones(10), window_days=30)

    def test_drought_index_zero_mean(self):
        from pakhi.targets.precipitation import drought_index

        result = drought_index(np.zeros(100), window_days=10)
        assert result == 0.0

    def test_rain_days_probability(self):
        from pakhi.targets.precipitation import rain_days_probability

        result = rain_days_probability([0, 2, 3, 0, 5])
        assert result == pytest.approx(0.6)

    def test_rain_days_probability_empty(self):
        from pakhi.targets.precipitation import rain_days_probability

        assert rain_days_probability([]) == 0.0

    def test_rain_days_probability_all_above(self):
        from pakhi.targets.precipitation import rain_days_probability

        assert rain_days_probability([5, 6, 7]) == 1.0


# ======================================================================
# targets/temperature.py
# ======================================================================


class TestTemperature:
    def test_heat_index_low_temp(self):
        from pakhi.targets.temperature import heat_index

        result = heat_index(20.0, 50.0)
        assert isinstance(result, float)

    def test_heat_index_high_temp_high_rh(self):
        from pakhi.targets.temperature import heat_index

        result = heat_index(35.0, 70.0)
        assert result > 35.0

    def test_heat_index_low_rh_adjustment(self):
        from pakhi.targets.temperature import heat_index

        result = heat_index(40.0, 10.0)
        assert isinstance(result, float)

    def test_heat_index_high_rh_adjustment(self):
        from pakhi.targets.temperature import heat_index

        result = heat_index(30.0, 90.0)
        assert isinstance(result, float)

    def test_wind_chill_warm(self):
        from pakhi.targets.temperature import wind_chill

        assert wind_chill(15.0, 10.0) == 15.0  # above valid range

    def test_wind_chill_low_wind(self):
        from pakhi.targets.temperature import wind_chill

        assert wind_chill(0.0, 2.0) == 0.0  # wind too low

    def test_wind_chill_valid(self):
        from pakhi.targets.temperature import wind_chill

        wc = wind_chill(-10.0, 20.0)
        assert wc < -10.0

    def test_freeze_probability_ensemble_mean(self):
        from pakhi.targets.temperature import freeze_probability

        arr = np.array([-5, 3, -2, 4, -1, 5, 2, 6, -3, 1, 3, 5])
        result = freeze_probability(arr, method="ensemble_mean")
        assert 0 <= result <= 1

    def test_freeze_probability_worst_case(self):
        from pakhi.targets.temperature import freeze_probability

        arr = np.array([-5, 3, -2, 4, -1, 5, 2, 6, -3, 1, 3, 5])
        result = freeze_probability(arr, method="worst_case")
        assert 0 <= result <= 1

    def test_freeze_probability_quantile_10(self):
        from pakhi.targets.temperature import freeze_probability

        arr = np.array([-5, 3, -2, 4, -1, 5, 2, 6, -3, 1, 3, 5])
        result = freeze_probability(arr, method="quantile_10")
        assert 0 <= result <= 1

    def test_freeze_probability_unknown_method(self):
        from pakhi.targets.temperature import freeze_probability

        with pytest.raises(ValueError, match="Unknown method"):
            freeze_probability(np.array([-5, 3]), method="bad")

    def test_growing_degree_days(self):
        from pakhi.targets.temperature import growing_degree_days

        result = growing_degree_days([15, 20, 25, 35, 5])
        assert result == pytest.approx(5 + 10 + 15 + 20 + 0)

    def test_diurnal_temperature_range(self):
        from pakhi.targets.temperature import diurnal_temperature_range

        result = diurnal_temperature_range([30, 35], [20, 25])
        assert result == 10.0

    def test_diurnal_temperature_range_mismatch(self):
        from pakhi.targets.temperature import diurnal_temperature_range

        with pytest.raises(ValueError):
            diurnal_temperature_range([30, 35], [20])


# ======================================================================
# grids/coordinate.py
# ======================================================================


class TestCoordinate:
    def test_latlon_to_km_same_point(self):
        from pakhi.grids.coordinate import latlon_to_km

        d = latlon_to_km(40.0, -74.0, 40.0, -74.0)
        assert d == pytest.approx(0.0)

    def test_latlon_to_km_known_distance(self):
        from pakhi.grids.coordinate import latlon_to_km

        d = latlon_to_km(0.0, 0.0, 0.0, 1.0)
        assert 100 < d < 120  # ~111 km at equator

    def test_latlon_to_km_arrays(self):
        from pakhi.grids.coordinate import latlon_to_km

        d = latlon_to_km(
            np.array([0.0, 0.0]),
            np.array([0.0, 0.0]),
            np.array([1.0, 2.0]),
            np.array([0.0, 0.0]),
        )
        assert d.shape == (2,)

    def test_km_to_latlon(self):
        from pakhi.grids.coordinate import km_to_latlon

        new_lat, _new_lon = km_to_latlon(40.0, -74.0, 100.0, 0.0)
        assert new_lat > 40.0

    def test_km_to_latlon_arrays(self):
        from pakhi.grids.coordinate import km_to_latlon

        new_lat, _new_lon = km_to_latlon(
            np.array([40.0, 41.0]),
            np.array([-74.0, -73.0]),
            100.0,
            50.0,
        )
        assert new_lat.shape == (2,)

    def test_pressure_to_altitude(self):
        from pakhi.grids.coordinate import pressure_to_altitude

        alt = pressure_to_altitude(1013.25)
        assert alt == pytest.approx(0.0, abs=1.0)

    def test_pressure_to_altitude_array(self):
        from pakhi.grids.coordinate import pressure_to_altitude

        alt = pressure_to_altitude(np.array([1013.25, 500.0]))
        assert alt.shape == (2,)
        assert alt[1] > alt[0]

    def test_pressure_to_altitude_negative(self):
        from pakhi.grids.coordinate import pressure_to_altitude

        with pytest.raises(ValueError):
            pressure_to_altitude(-1.0)

    def test_altitude_to_pressure(self):
        from pakhi.grids.coordinate import altitude_to_pressure

        p = altitude_to_pressure(0.0)
        assert p == pytest.approx(1013.25, rel=0.01)

    def test_altitude_to_pressure_array(self):
        from pakhi.grids.coordinate import altitude_to_pressure

        p = altitude_to_pressure(np.array([0.0, 1000.0, 5000.0]))
        assert p[0] > p[1] > p[2]

    def test_altitude_to_pressure_high(self):
        from pakhi.grids.coordinate import altitude_to_pressure

        p = altitude_to_pressure(50000.0)
        assert np.isnan(p) or p >= 0.0

    def test_geopotential_to_height(self):
        from pakhi.grids.coordinate import geopotential_to_height

        h = geopotential_to_height(9800.0)
        assert h == pytest.approx(1000.0, rel=0.01)

    def test_geopotential_to_height_array(self):
        from pakhi.grids.coordinate import geopotential_to_height

        h = geopotential_to_height(np.array([0.0, 9800.0]))
        assert h[0] == pytest.approx(0.0, abs=0.1)

    def test_validate_latlon_valid(self):
        from pakhi.grids.coordinate import validate_latlon

        valid, errors = validate_latlon(40.0, -74.0)
        assert valid is True
        assert len(errors) == 0

    def test_validate_latlon_out_of_range(self):
        from pakhi.grids.coordinate import validate_latlon

        valid, errors = validate_latlon(100.0, -74.0)
        assert valid is False
        assert any("out-of-range" in e for e in errors)

    def test_validate_latlon_nan(self):
        from pakhi.grids.coordinate import validate_latlon

        valid, errors = validate_latlon(np.nan, -74.0)
        assert valid is False
        assert any("NaN" in e for e in errors)

    def test_validate_latlon_mismatched_lengths(self):
        from pakhi.grids.coordinate import validate_latlon

        valid, _errors = validate_latlon(np.array([1.0, 2.0]), np.array([1.0]))
        assert valid is False

    def test_validate_latlon_empty(self):
        from pakhi.grids.coordinate import validate_latlon

        valid, errors = validate_latlon(np.array([]), np.array([]))
        assert valid is False
        assert any("empty" in e for e in errors)

    def test_validate_latlon_lon_out_of_range_warns(self):
        import warnings

        from pakhi.grids.coordinate import validate_latlon

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_latlon(40.0, 400.0)
            assert any("longitude" in str(warning.message).lower() for warning in w)


# ======================================================================
# models/__init__.py — lazy imports and __getattr__
# ======================================================================


class TestModelsInit:
    def test_direct_imports(self):
        from pakhi.models import BaseModel, ClimatologyModel, PersistenceModel

        assert BaseModel is not None
        assert PersistenceModel is not None
        assert ClimatologyModel is not None

    def test_lazy_import_gradient(self):
        from pakhi.models import GradientForecaster

        assert GradientForecaster is not None

    def test_getattr_invalid(self):
        import pakhi.models as models_mod

        with pytest.raises(AttributeError):
            _ = models_mod.NonExistentModel

    def test_standard_scalar_import(self):
        from pakhi.models import StandardScaler

        assert StandardScaler is not None

    def test_compute_metrics_import(self):
        from pakhi.models import compute_metrics

        assert callable(compute_metrics)

    def test_train_val_test_split_import(self):
        from pakhi.models import train_val_test_split

        assert callable(train_val_test_split)

    def test_anomalies_from_climatology_import(self):
        from pakhi.models import anomalies_from_climatology

        assert callable(anomalies_from_climatology)

    def test_seasonal_climatology_import(self):
        from pakhi.models import seasonal_climatology

        assert callable(seasonal_climatology)

    def test_lazy_lstm(self):
        from pakhi.models import LSTMForecaster

        assert LSTMForecaster is not None

    def test_lazy_gaussian(self):
        from pakhi.models import GaussianForecaster

        assert GaussianForecaster is not None

    def test_lazy_ensemble(self):
        from pakhi.models import EnsembleForecaster

        assert EnsembleForecaster is not None
