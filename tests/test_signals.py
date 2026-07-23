"""Tests for trading signals in pakhi.signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pakhi.signals.base import Action, Signal, position_size
from pakhi.signals.freeze import FreezeSignal

# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


class TestSignalDataclass:
    def test_creation(self):
        sig = Signal(
            action=Action.LONG,
            size=0.15,
            confidence=0.8,
            instrument="OJ_FUTURES",
            timestamp=datetime.now(timezone.utc),
            reasoning="test",
        )
        assert sig.action == Action.LONG
        assert sig.size == 0.15

    def test_clipping(self):
        sig = Signal(
            action=Action.LONG,
            size=2.0,
            confidence=1.5,
            instrument="OJ_FUTURES",
            timestamp=datetime.now(timezone.utc),
            reasoning="test",
        )
        assert sig.size == 1.0
        assert sig.confidence == 1.0

    def test_string_action_coerced(self):
        sig = Signal(
            action="FLAT",
            size=0.0,
            confidence=0.0,
            instrument="OJ_FUTURES",
            timestamp=datetime.now(timezone.utc),
            reasoning="test",
        )
        assert sig.action == Action.FLAT


# ---------------------------------------------------------------------------
# position_size — Kelly criterion
# ---------------------------------------------------------------------------


class TestPositionSize:
    def test_kelly_basic(self):
        # p=0.6, odds=2.0 → f* = (2*0.6 - 0.4)/2 = 0.4, half = 0.2
        size = position_size(0.6, method="kelly", odds=2.0, half_kelly=True)
        assert size == pytest.approx(0.2)

    def test_kelly_full(self):
        size = position_size(0.6, method="kelly", odds=2.0, half_kelly=False, max_size=1.0)
        assert size == pytest.approx(0.4)

    def test_kelly_negative_edge(self):
        # p=0.2, odds=1.0 → f* = (1*0.2 - 0.8)/1 = -0.6 → 0
        size = position_size(0.2, method="kelly", odds=1.0, half_kelly=True)
        assert size == 0.0

    def test_kelly_max_size(self):
        size = position_size(0.99, method="kelly", odds=10.0, half_kelly=False, max_size=0.15)
        assert size == pytest.approx(0.15)

    def test_uniform(self):
        size = position_size(0.9, method="uniform", max_size=0.25)
        assert size == pytest.approx(0.1)

    def test_confidence_method(self):
        size = position_size(0.7, method="confidence", max_size=0.25)
        assert size == pytest.approx(0.175)

    def test_confidence_capped(self):
        size = position_size(1.0, method="confidence", max_size=0.25)
        assert size == pytest.approx(0.25)

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown method"):
            position_size(0.5, method="invalid")

    def test_zero_confidence(self):
        size = position_size(0.0, method="kelly", odds=2.0)
        assert size == 0.0

    def test_one_confidence(self):
        size = position_size(1.0, method="kelly", odds=2.0, half_kelly=True, max_size=1.0)
        assert size > 0


# ---------------------------------------------------------------------------
# FreezeSignal
# ---------------------------------------------------------------------------


class TestFreezeSignal:
    def test_high_probability_generates_long(self):
        now = datetime.now(timezone.utc)
        sig_gen = FreezeSignal(entry_threshold=0.5)
        forecast = {
            "freeze_prob": 0.8,
            "event_peak_time": now,
            "temperature_min": -5.0,
            "current_time": now,
        }
        signal = sig_gen.generate(forecast)
        assert signal.action == Action.LONG
        assert signal.size > 0
        assert signal.confidence > 0

    def test_low_probability_generates_flat(self):
        now = datetime.now(timezone.utc)
        sig_gen = FreezeSignal(entry_threshold=0.6)
        forecast = {
            "freeze_prob": 0.1,
            "event_peak_time": now,
            "temperature_min": 5.0,
            "current_time": now,
        }
        signal = sig_gen.generate(forecast)
        assert signal.action == Action.FLAT
        assert signal.size == 0.0

    def test_time_decay_reduces_signal(self):
        now = datetime.now(timezone.utc)
        peak_time = now - timedelta(hours=96)
        sig_gen = FreezeSignal(entry_threshold=0.3, time_decay_hours=48.0)
        forecast = {
            "freeze_prob": 0.7,
            "event_peak_time": peak_time,
            "temperature_min": -3.0,
            "current_time": now,
        }
        signal = sig_gen.generate(forecast)
        # After 96h with 48h half-life, decay ≈ 0.25, effective ≈ 0.175
        assert signal.action == Action.FLAT

    def test_metadata_present(self):
        now = datetime.now(timezone.utc)
        sig_gen = FreezeSignal(entry_threshold=0.3)
        forecast = {
            "freeze_prob": 0.9,
            "event_peak_time": now,
            "temperature_min": -2.0,
            "current_time": now,
        }
        signal = sig_gen.generate(forecast)
        assert "freeze_prob" in signal.metadata
        assert "effective_prob" in signal.metadata
        assert "decay_factor" in signal.metadata

    def test_warm_temperature_flat(self):
        now = datetime.now(timezone.utc)
        sig_gen = FreezeSignal(entry_threshold=0.3)
        forecast = {
            "freeze_prob": 0.9,
            "event_peak_time": now,
            "temperature_min": 5.0,  # above 0°C
            "current_time": now,
        }
        signal = sig_gen.generate(forecast)
        assert signal.action == Action.FLAT
