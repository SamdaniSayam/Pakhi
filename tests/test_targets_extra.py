"""Tests for pakhi.targets — all target modules."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from pakhi.targets.precipitation import (
    drought_index,
    precipitation_accumulation,
    rain_days_probability,
    snow_probability,
)
from pakhi.targets.hurricane import (
    rainfall_accumulation,
    rapid_intensification_probability,
    saffir_simpson,
    wind_radius_estimate,
)
from pakhi.targets.solar import (
    clear_sky_radiation,
    ghi_from_cloud_cover,
    photovoltaic_output,
    solar_position,
)
from pakhi.targets.temperature import (
    diurnal_temperature_range,
    freeze_probability,
    growing_degree_days,
    heat_index,
    wind_chill,
)
from pakhi.targets.wind import (
    beaufort_scale,
    power_curve,
    wind_direction_components,
    wind_power_forecast,
)
from pakhi.targets.pressure import (
    central_pressure_to_category,
    pressure_gradient_force,
    pressure_tendency,
    storm_surge_estimate,
)


class TestPrecipitation:
    def test_precipitation_accumulation(self):
        rates = np.array([1.0, 2.0, 3.0, 4.0])
        result = precipitation_accumulation(rates, window_hours=24)
        assert result > 0

    def test_precipitation_accumulation_single(self):
        assert precipitation_accumulation(np.array([5.0]), window_hours=24) == 0.0

    def test_snow_probability(self):
        temp = np.array([-5, -2, 0, 1, 3])
        precip = np.array([1.0, 1.0, 1.0, 1.0, 0.0])
        result = snow_probability(temp, precip)
        assert 0.0 <= result <= 1.0

    def test_snow_probability_no_precip(self):
        result = snow_probability(np.array([0.0]), np.array([0.0]))
        assert result == 0.0

    def test_snow_probability_all_warm(self):
        temp = np.array([25.0, 30.0, 28.0])
        precip = np.array([1.0, 1.0, 1.0])
        result = snow_probability(temp, precip)
        assert result == pytest.approx(0.0)

    def test_drought_index(self):
        precip = np.random.exponential(5, 200)
        result = drought_index(precip, window_days=30)
        assert isinstance(result, float)

    def test_drought_index_too_short(self):
        with pytest.raises(ValueError):
            drought_index(np.array([1.0, 2.0]), window_days=30)

    def test_rain_days_probability(self):
        precip = np.array([0.0, 2.0, 0.0, 5.0, 0.0])
        result = rain_days_probability(precip)
        assert 0.0 <= result <= 1.0

    def test_rain_days_probability_empty(self):
        assert rain_days_probability(np.array([])) == 0.0


class TestHurricane:
    def test_saffir_simpson(self):
        assert saffir_simpson(950, 200) >= 1
        assert saffir_simpson(950, 200) <= 5

    def test_saffir_simpson_depression(self):
        assert saffir_simpson(1010, 50) == 0

    def test_saffir_simpson_cat5(self):
        assert saffir_simpson(900, 300) == 5

    def test_rapid_intensification(self):
        prob = rapid_intensification_probability(30, 30.0, 5.0)
        assert 0.0 <= prob <= 1.0

    def test_wind_radius(self):
        v = wind_radius_estimate(3, 50.0)
        assert v >= 0.0

    def test_wind_radius_at_center(self):
        v = wind_radius_estimate(3, 0.1)
        assert v >= 0.0

    def test_rainfall_accumulation(self):
        total = rainfall_accumulation(3, 20.0, 24.0)
        assert total > 0

    def test_rainfall_zero_speed(self):
        total = rainfall_accumulation(1, 0.0, 24.0)
        assert total > 0


class TestSolar:
    def test_solar_position(self):
        result = solar_position(32.0, -88.0, datetime(2024, 6, 21, 18, 0, tzinfo=timezone.utc))
        assert "zenith" in result
        assert "azimuth" in result
        assert "elevation" in result

    def test_clear_sky(self):
        ghi = clear_sky_radiation(30.0, 100.0, 0.1)
        assert ghi > 0

    def test_clear_sky_high_zenith(self):
        ghi = clear_sky_radiation(90.0, 0.0, 0.1)
        assert ghi == pytest.approx(0.0, abs=1e-10)

    def test_ghi_from_cloud(self):
        ghi = ghi_from_cloud_cover(0.0, 30.0)
        assert ghi > 0

    def test_ghi_from_cloud_overcast(self):
        clear = ghi_from_cloud_cover(0.0, 30.0)
        cloudy = ghi_from_cloud_cover(1.0, 30.0)
        assert cloudy < clear

    def test_ghi_night(self):
        assert ghi_from_cloud_cover(0.5, 100.0) == 0.0

    def test_pv_output(self):
        p = photovoltaic_output(800.0, 0.20, 10.0, 25.0)
        assert p > 0

    def test_pv_output_zero(self):
        assert photovoltaic_output(0.0, 0.20, 10.0, 25.0) == 0.0

    def test_pv_output_hot(self):
        cool = photovoltaic_output(800.0, 0.20, 10.0, 20.0)
        hot = photovoltaic_output(800.0, 0.20, 10.0, 45.0)
        assert cool > hot


class TestTemperature:
    def test_freeze_probability_ensemble_mean(self):
        temps = np.array([-2, -1, 0, 1, 2, 3, 4, 5, -1, 0])
        prob = freeze_probability(temps, method="ensemble_mean")
        assert 0.0 <= prob <= 1.0

    def test_freeze_probability_worst_case(self):
        temps = np.array([-5, -3, -1, 1, 3, -2, 0, 2, -4, -1])
        prob = freeze_probability(temps, method="worst_case")
        assert 0.0 <= prob <= 1.0

    def test_freeze_probability_quantile(self):
        temps = np.array([-5, -3, -1, 1, 3, -2, 0, 2, -4, -1])
        prob = freeze_probability(temps, method="quantile_10")
        assert 0.0 <= prob <= 1.0

    def test_freeze_probability_bad_method(self):
        with pytest.raises(ValueError):
            freeze_probability(np.array([1.0]), method="bad")

    def test_heat_index(self):
        hi = heat_index(35.0, 70.0)
        assert hi > 35.0

    def test_heat_index_cool(self):
        hi = heat_index(20.0, 50.0)
        assert hi < 30.0

    def test_wind_chill(self):
        wc = wind_chill(-10.0, 30.0)
        assert wc < -10.0

    def test_wind_chill_warm(self):
        wc = wind_chill(15.0, 30.0)
        assert wc == 15.0

    def test_wind_chill_calm(self):
        wc = wind_chill(-10.0, 2.0)
        assert wc == -10.0

    def test_growing_degree_days(self):
        gdd = growing_degree_days(np.array([20.0, 22.0, 25.0]))
        assert gdd > 0

    def test_growing_degree_days_cold(self):
        gdd = growing_degree_days(np.array([5.0, 8.0, 9.0]))
        assert gdd == 0.0

    def test_diurnal_range(self):
        dtr = diurnal_temperature_range(
            np.array([30.0, 32.0]),
            np.array([15.0, 18.0]),
        )
        assert dtr > 0

    def test_diurnal_range_mismatch(self):
        with pytest.raises(ValueError):
            diurnal_temperature_range(np.array([30.0]), np.array([15.0, 18.0]))


class TestWind:
    def test_power_curve(self):
        p = power_curve(12.0, turbine="vestas_v110")
        assert p > 0

    def test_power_curve_below_cutin(self):
        p = power_curve(1.0, turbine="vestas_v110")
        assert p == 0.0

    def test_power_curve_above_cutout(self):
        p = power_curve(30.0, turbine="vestas_v110")
        assert p == 0.0

    def test_power_curve_array(self):
        ws = np.array([0.0, 5.0, 12.0, 30.0])
        p = power_curve(ws)
        assert len(p) == 4

    def test_power_curve_unknown(self):
        with pytest.raises(ValueError):
            power_curve(10.0, turbine="nonexistent")

    def test_wind_power_forecast(self):
        p = wind_power_forecast(2.0, 100.0, 50)
        assert p > 0
        assert p <= 100.0

    def test_beaufort(self):
        assert beaufort_scale(0.0) == 0
        assert beaufort_scale(1.0) == 1
        assert beaufort_scale(35.0) == 12

    def test_wind_direction_components(self):
        u, v = wind_direction_components(10.0, 0.0)
        assert u == pytest.approx(0.0, abs=0.01)
        assert v == pytest.approx(-10.0, abs=0.01)

    def test_wind_direction_array(self):
        ws = np.array([10.0, 10.0])
        wd = np.array([0.0, 90.0])
        u, v = wind_direction_components(ws, wd)
        assert len(u) == 2


class TestPressure:
    def test_central_pressure_category(self):
        assert central_pressure_to_category(1015) == "TD"
        assert central_pressure_to_category(990) == "TS"
        assert central_pressure_to_category(960) == "Cat2"
        assert central_pressure_to_category(910) == "Cat5"

    def test_storm_surge(self):
        surge = storm_surge_estimate(950.0, 25.0, 0.05)
        assert surge > 0

    def test_pressure_tendency(self):
        assert pressure_tendency(1000.0, 1005.0) == "rising"
        assert pressure_tendency(1000.0, 995.0) == "falling"
        assert pressure_tendency(1000.0, 1000.5) == "steady"

    def test_pressure_gradient_force(self):
        mag, direction = pressure_gradient_force(0.01, 0.005, 45.0)
        assert mag > 0
        assert 0 <= direction <= 360

    def test_pgf_equator(self):
        mag, direction = pressure_gradient_force(0.01, 0.005, 0.0)
        assert mag > 0
