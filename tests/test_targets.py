"""Tests for target variables in pakhi.targets."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from pakhi.targets.hurricane import saffir_simpson
from pakhi.targets.pressure import central_pressure_to_category
from pakhi.targets.solar import solar_position
from pakhi.targets.temperature import freeze_probability
from pakhi.targets.wind import power_curve

# ---------------------------------------------------------------------------
# freeze_probability
# ---------------------------------------------------------------------------


class TestFreezeProbability:
    def test_all_above_threshold(self):
        temps = np.array([5.0, 8.0, 10.0, 12.0, 15.0])
        prob = freeze_probability(temps, threshold_celsius=0.0, window_days=5)
        assert prob == 0.0

    def test_all_below_threshold(self):
        temps = np.array([-5.0, -3.0, -1.0, -2.0, -4.0])
        prob = freeze_probability(temps, threshold_celsius=0.0, window_days=5)
        assert prob == 1.0

    def test_half_below(self):
        temps = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        prob = freeze_probability(temps, threshold_celsius=0.0, window_days=5)
        assert 0.3 <= prob <= 0.7

    def test_worst_case_method(self):
        temps = np.array([-5.0, -5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        prob = freeze_probability(temps, threshold_celsius=0.0, window_days=4, method="worst_case")
        assert prob == 1.0  # worst day has all members below

    def test_quantile_10_method(self):
        temps = np.array([-5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        prob = freeze_probability(temps, threshold_celsius=0.0, window_days=4, method="quantile_10")
        assert 0.0 <= prob <= 1.0

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown method"):
            freeze_probability(np.array([1.0]), method="bad")

    def test_scalar_like_input(self):
        prob = freeze_probability(np.array([-1.0]), threshold_celsius=0.0, window_days=1)
        assert prob == 1.0


# ---------------------------------------------------------------------------
# wind.power_curve
# ---------------------------------------------------------------------------


class TestPowerCurve:
    def test_below_cut_in(self):
        assert power_curve(0.0, turbine="vestas_v110") == 0.0
        assert power_curve(1.0, turbine="vestas_v110") == 0.0
        assert power_curve(2.0, turbine="vestas_v110") == 0.0

    def test_at_rated_speed(self):
        p = power_curve(12.0, turbine="vestas_v110", hub_height_m=80.0)
        assert p == pytest.approx(2.0, abs=0.01)

    def test_above_cut_out(self):
        assert power_curve(30.0, turbine="vestas_v110") == 0.0

    def test_ramp_region(self):
        p5 = power_curve(5.0, turbine="vestas_v110", hub_height_m=80.0)
        p8 = power_curve(8.0, turbine="vestas_v110", hub_height_m=80.0)
        p12 = power_curve(12.0, turbine="vestas_v110", hub_height_m=80.0)
        assert 0 < p5 < p8 < p12

    def test_array_input(self):
        speeds = np.array([0, 3, 6, 12, 25, 30])
        p = power_curve(speeds, turbine="vestas_v110", hub_height_m=80.0)
        assert p.shape == (6,)
        assert p[0] == 0.0
        assert p[3] == pytest.approx(2.0, abs=0.01)
        assert p[5] == 0.0

    def test_invalid_turbine_raises(self):
        with pytest.raises(ValueError, match="Unknown turbine"):
            power_curve(10.0, turbine="nonexistent")

    def test_different_turbines_different_output(self):
        p_v110 = power_curve(10.0, turbine="vestas_v110", hub_height_m=80.0)
        p_v90 = power_curve(10.0, turbine="vestas_v90", hub_height_m=80.0)
        assert p_v110 != p_v90


# ---------------------------------------------------------------------------
# pressure.central_pressure_to_category
# ---------------------------------------------------------------------------


class TestCentralPressureToCategory:
    def test_tropical_depression_high_pressure(self):
        assert central_pressure_to_category(1015.0) == "TD"

    def test_tropical_depression_moderate(self):
        assert central_pressure_to_category(1005.0) == "TD"

    def test_tropical_storm(self):
        assert central_pressure_to_category(990.0) == "TS"

    def test_category_1(self):
        assert central_pressure_to_category(978.0) == "Cat1"

    def test_category_2(self):
        assert central_pressure_to_category(960.0) == "Cat2"

    def test_category_3(self):
        assert central_pressure_to_category(948.0) == "Cat3"

    def test_category_4(self):
        assert central_pressure_to_category(930.0) == "Cat4"

    def test_category_5(self):
        assert central_pressure_to_category(910.0) == "Cat5"

    def test_all_categories_covered(self):
        pressures = [1015, 1005, 990, 978, 960, 948, 930, 910]
        categories = [central_pressure_to_category(p) for p in pressures]
        expected = ["TD", "TD", "TS", "Cat1", "Cat2", "Cat3", "Cat4", "Cat5"]
        assert categories == expected


# ---------------------------------------------------------------------------
# solar.solar_position
# ---------------------------------------------------------------------------


class TestSolarPosition:
    def test_known_location_noon(self):
        # Equator, March equinox, solar noon should give zenith near 0
        dt = datetime(2023, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        pos = solar_position(0.0, 0.0, dt)
        assert 0 <= pos["zenith"] <= 90
        assert 0 <= pos["elevation"] <= 90
        assert pos["elevation"] == pytest.approx(90 - pos["zenith"], abs=0.01)

    def test_night_time(self):
        # High latitude in winter, midnight — sun should be well below horizon
        dt = datetime(2023, 12, 21, 0, 0, 0, tzinfo=timezone.utc)
        pos = solar_position(65.0, 0.0, dt)
        assert pos["zenith"] > 90
        assert pos["elevation"] < 0

    def test_azimuth_range(self):
        dt = datetime(2023, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        pos = solar_position(40.0, -74.0, dt)
        assert 0 <= pos["azimuth"] <= 360

    def test_all_keys_present(self):
        dt = datetime(2023, 7, 4, 15, 30, 0, tzinfo=timezone.utc)
        pos = solar_position(41.88, -87.63, dt)
        assert "zenith" in pos
        assert "azimuth" in pos
        assert "elevation" in pos


# ---------------------------------------------------------------------------
# hurricane.saffir_simpson
# ---------------------------------------------------------------------------


class TestSaffirSimpson:
    def test_tropical_depression(self):
        # 20 kt = well below 34 kt threshold
        assert saffir_simpson(1010.0, 37.04) == 0  # 37 km/h ≈ 20 kt

    def test_tropical_storm(self):
        # 50 kt ≈ 92.6 km/h — still below hurricane threshold (64 kt)
        assert saffir_simpson(1000.0, 92.6) == 0

    def test_category_1(self):
        # 70 kt ≈ 129.6 km/h
        assert saffir_simpson(980.0, 129.6) == 1

    def test_category_2(self):
        # 90 kt ≈ 166.7 km/h, pressure < 965
        assert saffir_simpson(960.0, 166.7) == 2

    def test_category_3(self):
        # 105 kt ≈ 194.5 km/h, pressure < 945
        assert saffir_simpson(940.0, 194.5) == 3

    def test_category_4(self):
        # 125 kt ≈ 231.5 km/h, pressure < 920
        assert saffir_simpson(915.0, 231.5) == 4

    def test_category_5(self):
        # 150 kt ≈ 277.8 km/h
        assert saffir_simpson(890.0, 277.8) == 5

    def test_all_categories(self):
        test_cases = [
            (1010.0, 37.04, 0),  # TD
            (1000.0, 92.6, 0),  # TS
            (980.0, 129.6, 1),  # Cat1
            (960.0, 166.7, 2),  # Cat2
            (940.0, 194.5, 3),  # Cat3
            (915.0, 231.5, 4),  # Cat4
            (890.0, 277.8, 5),  # Cat5
        ]
        for pressure, wind, expected_cat in test_cases:
            assert saffir_simpson(pressure, wind) == expected_cat, (
                f"pressure={pressure}, wind={wind}"
            )
