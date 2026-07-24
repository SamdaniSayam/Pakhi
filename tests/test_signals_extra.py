"""Tests for pakhi.signals — all signal modules."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from pakhi.signals.base import Action, BaseSignal, Signal, position_size
from pakhi.signals.drought import DroughtSignal
from pakhi.signals.ensemble_signal import EnsembleSignal
from pakhi.signals.heat import PowerSignal
from pakhi.signals.hurricane import HurricaneSignal
from pakhi.signals.wind_power import WindPowerSignal


class TestPositionSize:
    def test_kelly(self):
        s = position_size(0.7, method="kelly", odds=2.0)
        assert 0.0 <= s <= 0.25

    def test_uniform(self):
        s = position_size(0.7, method="uniform", max_size=0.1)
        assert s == pytest.approx(0.1)

    def test_confidence(self):
        s = position_size(0.7, method="confidence", max_size=0.25)
        assert s == pytest.approx(0.7 * 0.25)

    def test_kelly_negative_edge(self):
        s = position_size(0.1, method="kelly", odds=2.0)
        assert s == 0.0

    def test_unknown_method(self):
        with pytest.raises(ValueError, match="Unknown method"):
            position_size(0.5, method="invalid")


class TestSignal:
    def test_signal_clipping(self):
        s = Signal(action=Action.LONG, size=2.0, confidence=-0.5,
                   instrument="X", timestamp=datetime.now(timezone.utc),
                   reasoning="test")
        assert s.size == 1.0
        assert s.confidence == 0.0


class TestDroughtSignal:
    def test_generate_long(self):
        sig = DroughtSignal(spi_threshold=-1.5, min_days=3)
        spi = list(np.full(10, -2.0))
        result = sig.generate({"spi_values": spi, "region": "Midwest"})
        assert result.action == Action.LONG
        assert result.confidence > 0

    def test_generate_flat(self):
        sig = DroughtSignal(spi_threshold=-1.5, min_days=30)
        result = sig.generate({"spi_values": [0.5, 0.3, -0.1], "region": "X"})
        assert result.action == Action.FLAT

    def test_generate_empty(self):
        sig = DroughtSignal()
        result = sig.generate({"spi_values": [], "region": "X"})
        assert result.action == Action.FLAT


class TestEnsembleSignal:
    def test_combine_agreement(self):
        ensemble = EnsembleSignal(min_agreement=0.5)
        now = datetime.now(timezone.utc)
        signals = [
            Signal(Action.LONG, 0.1, 0.8, "A", now, "a"),
            Signal(Action.LONG, 0.1, 0.7, "B", now, "b"),
            Signal(Action.SHORT, 0.1, 0.6, "C", now, "c"),
        ]
        result = ensemble.combine(signals)
        assert result.action == Action.LONG

    def test_combine_insufficient_agreement(self):
        ensemble = EnsembleSignal(min_agreement=0.8)
        now = datetime.now(timezone.utc)
        signals = [
            Signal(Action.LONG, 0.1, 0.5, "A", now, "a"),
            Signal(Action.SHORT, 0.1, 0.5, "B", now, "b"),
        ]
        result = ensemble.combine(signals)
        assert result.action == Action.FLAT

    def test_combine_empty(self):
        ensemble = EnsembleSignal()
        with pytest.raises(ValueError, match="At least one"):
            ensemble.combine([])

    def test_combine_all_zero_confidence(self):
        ensemble = EnsembleSignal()
        now = datetime.now(timezone.utc)
        signals = [
            Signal(Action.LONG, 0.1, 0.0, "A", now, "a"),
        ]
        result = ensemble.combine(signals)
        assert result.action == Action.FLAT

    def test_generate_raises(self):
        ensemble = EnsembleSignal()
        with pytest.raises(NotImplementedError):
            ensemble.generate({})


class TestPowerSignal:
    def test_generate_heatwave(self):
        sig = PowerSignal(heatwave_threshold=38.0, min_consecutive_days=3)
        result = sig.generate({
            "temperature_forecast": [39, 40, 41, 42],
            "market": "ERCOT",
        })
        assert result.action == Action.LONG

    def test_generate_no_heatwave(self):
        sig = PowerSignal(heatwave_threshold=38.0, min_consecutive_days=3)
        result = sig.generate({
            "temperature_forecast": [30, 31, 32],
            "market": "ERCOT",
        })
        assert result.action == Action.FLAT

    def test_generate_empty(self):
        sig = PowerSignal()
        result = sig.generate({"temperature_forecast": [], "market": "ERCOT"})
        assert result.action == Action.FLAT

    def test_with_wind(self):
        sig = PowerSignal(min_consecutive_days=2)
        result = sig.generate({
            "temperature_forecast": [39, 40, 41],
            "market": "ERCOT",
            "wind_capacity_factor": [0.05, 0.08, 0.10],
        })
        assert result.action == Action.LONG


class TestHurricaneSignal:
    def test_generate_long(self):
        sig = HurricaneSignal(entry_threshold=0.3)
        result = sig.generate({
            "landfall_prob": 0.8,
            "category": 4,
            "closest_approach_miles": 100,
            "hours_to_landfall": 24,
        })
        assert result.action == Action.LONG
        assert result.instrument == "NG_FUTURES"

    def test_generate_flat(self):
        sig = HurricaneSignal(entry_threshold=0.9)
        result = sig.generate({
            "landfall_prob": 0.1,
            "category": 1,
            "closest_approach_miles": 500,
            "hours_to_landfall": 168,
        })
        assert result.action == Action.FLAT

    def test_generate_override_prob(self):
        sig = HurricaneSignal(entry_threshold=0.3)
        result = sig.generate(
            {"category": 4, "closest_approach_miles": 50,
             "hours_to_landfall": 24},
            landfall_probability=0.9,
        )
        assert result.action == Action.LONG


class TestWindPowerSignal:
    def test_low_wind(self):
        sig = WindPowerSignal()
        result = sig.generate({
            "wind_forecast": [0.05, 0.08, 0.10],
            "market": "PJM",
        })
        assert result.action == Action.FLAT

    def test_high_wind(self):
        sig = WindPowerSignal()
        result = sig.generate({
            "wind_forecast": [0.8, 0.9, 0.95],
            "wind_climatology": [0.1, 0.2, 0.3, 0.4, 0.5],
            "market": "PJM",
        })
        assert result.action == Action.SHORT

    def test_normal_wind(self):
        sig = WindPowerSignal()
        result = sig.generate({
            "wind_forecast": [0.4, 0.5, 0.5],
            "market": "PJM",
        })
        assert result.action == Action.FLAT

    def test_empty(self):
        sig = WindPowerSignal()
        result = sig.generate({"wind_forecast": [], "market": "PJM"})
        assert result.action == Action.FLAT

    def test_with_climatology(self):
        sig = WindPowerSignal()
        result = sig.generate({
            "wind_forecast": [0.05],
            "wind_climatology": [0.3, 0.4, 0.5],
            "market": "PJM",
        })
        assert result.action == Action.LONG
