"""Tests for feature engineering in pakhi.features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pakhi.features.anomaly import AnomalyFeatures
from pakhi.features.climate import ClimateFeatures
from pakhi.features.satellite import SatelliteFeatures

# ---------------------------------------------------------------------------
# ClimateFeatures
# ---------------------------------------------------------------------------


class TestClimateFeaturesHDD:
    def test_scalar_below_base(self):
        assert ClimateFeatures.hdd(10.0, base_celsius=18.3) == pytest.approx(8.3)

    def test_scalar_above_base(self):
        assert ClimateFeatures.hdd(25.0, base_celsius=18.3) == 0.0

    def test_scalar_at_base(self):
        assert ClimateFeatures.hdd(18.3, base_celsius=18.3) == 0.0

    def test_array(self):
        temps = np.array([0.0, 10.0, 18.3, 25.0, 30.0])
        result = ClimateFeatures.hdd(temps, base_celsius=18.3)
        assert isinstance(result, np.ndarray)
        assert result[0] == pytest.approx(18.3)
        assert result[2] == 0.0
        assert result[4] == 0.0

    def test_pandas_series(self):
        s = pd.Series([5.0, 15.0, 20.0])
        result = ClimateFeatures.hdd(s, base_celsius=18.3)
        assert isinstance(result, pd.Series)
        assert result.iloc[0] == pytest.approx(13.3)

    def test_xarray(self):
        da = xr.DataArray([5.0, 15.0, 20.0])
        result = ClimateFeatures.hdd(da, base_celsius=18.3)
        assert isinstance(result, xr.DataArray)
        assert float(result[0]) == pytest.approx(13.3)


class TestClimateFeaturesCDD:
    def test_scalar_above_base(self):
        assert ClimateFeatures.cdd(25.0, base_celsius=18.3) == pytest.approx(6.7)

    def test_scalar_below_base(self):
        assert ClimateFeatures.cdd(10.0, base_celsius=18.3) == 0.0

    def test_array(self):
        temps = np.array([0.0, 18.3, 25.0, 35.0])
        result = ClimateFeatures.cdd(temps, base_celsius=18.3)
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] == pytest.approx(6.7)
        assert result[3] == pytest.approx(16.7)


class TestClimateFeaturesGDD:
    def test_below_base(self):
        assert ClimateFeatures.gdd(5.0, base_celsius=10.0, max_celsius=30.0) == 0.0

    def test_between_base_and_max(self):
        assert ClimateFeatures.gdd(20.0, base_celsius=10.0, max_celsius=30.0) == pytest.approx(10.0)

    def test_above_max(self):
        assert ClimateFeatures.gdd(40.0, base_celsius=10.0, max_celsius=30.0) == pytest.approx(20.0)

    def test_array_clamping(self):
        temps = np.array([0.0, 15.0, 25.0, 35.0, 45.0])
        result = ClimateFeatures.gdd(temps, base_celsius=10.0, max_celsius=30.0)
        assert result[0] == 0.0
        assert result[1] == pytest.approx(5.0)
        assert result[2] == pytest.approx(15.0)
        assert result[3] == pytest.approx(20.0)
        assert result[4] == pytest.approx(20.0)


class TestClimateFeaturesFrost:
    def test_scalar_freezing(self):
        assert ClimateFeatures.frost_days(-5.0) is True

    def test_scalar_above_freezing(self):
        assert ClimateFeatures.frost_days(5.0) is False

    def test_array(self):
        temps = np.array([-2.0, 0.0, 1.0, -1.0])
        result = ClimateFeatures.frost_days(temps)
        expected = np.array([True, True, False, True])
        np.testing.assert_array_equal(result, expected)


class TestClimateFeaturesHeatwave:
    def test_no_heatwave(self):
        temps = np.array([20.0, 22.0, 24.0, 23.0, 21.0])
        result = ClimateFeatures.heatwave_days(temps, threshold_celsius=35.0, consecutive_days=3)
        assert not np.any(result)

    def test_heatwave_detected(self):
        temps = np.array([36.0, 37.0, 38.0, 37.0, 20.0])
        result = ClimateFeatures.heatwave_days(temps, threshold_celsius=35.0, consecutive_days=3)
        assert result[0]
        assert result[1]
        assert result[2]
        assert result[3]
        assert not result[4]


# ---------------------------------------------------------------------------
# AnomalyFeatures
# ---------------------------------------------------------------------------


class TestAnomalyFeatures:
    def test_zscore_anomaly_numpy(self):
        data = np.array([10.0, 12.0, 14.0])
        mean = np.array([10.0, 10.0, 10.0])
        std = np.array([2.0, 2.0, 2.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        expected = np.array([0.0, 1.0, 2.0])
        np.testing.assert_allclose(result, expected)

    def test_zscore_zero_std_gives_nan(self):
        data = np.array([10.0, 12.0])
        mean = np.array([10.0, 10.0])
        std = np.array([0.0, 2.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        assert np.isnan(result[0])
        assert result[1] == pytest.approx(1.0)

    def test_zscore_anomaly_pandas(self):
        data = pd.Series([10.0, 12.0, 14.0])
        mean = pd.Series([10.0, 10.0, 10.0])
        std = pd.Series([2.0, 2.0, 2.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        np.testing.assert_allclose(result.values, [0.0, 1.0, 2.0])

    def test_zscore_anomaly_xarray(self):
        data = xr.DataArray([10.0, 12.0, 14.0])
        mean = xr.DataArray([10.0, 10.0, 10.0])
        std = xr.DataArray([2.0, 2.0, 2.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        np.testing.assert_allclose(result.values, [0.0, 1.0, 2.0])

    def test_departure_from_normal(self):
        data = np.array([15.0, 20.0, 25.0])
        normal = np.array([10.0, 10.0, 10.0])
        result = AnomalyFeatures.departure_from_normal(data, normal)
        np.testing.assert_allclose(result, [5.0, 10.0, 15.0])


# ---------------------------------------------------------------------------
# SatelliteFeatures
# ---------------------------------------------------------------------------


class TestSatelliteFeatures:
    def test_brightness_temperature_scalar(self):
        bt = SatelliteFeatures.brightness_temperature(50.0, band_number=4)
        assert np.asarray(bt).size == 1
        assert float(np.asarray(bt).ravel()[0]) > 0

    def test_brightness_temperature_zero_radiance(self):
        bt = SatelliteFeatures.brightness_temperature(0.0, band_number=4)
        assert np.asarray(bt).ravel()[0] > 0

    def test_brightness_temperature_array(self):
        radiances = np.array([10.0, 50.0, 100.0, 200.0])
        bt = SatelliteFeatures.brightness_temperature(radiances, band_number=4)
        assert bt.shape == (4,)
        assert np.all(bt[1:] > 0)

    def test_cloud_fraction_all_clear(self):
        bt_data = np.full((10, 10), 300.0)
        frac = SatelliteFeatures.cloud_fraction(bt_data, threshold_k=260.0)
        assert frac == pytest.approx(0.0)

    def test_cloud_fraction_all_cloudy(self):
        bt_data = np.full((10, 10), 200.0)
        frac = SatelliteFeatures.cloud_fraction(bt_data, threshold_k=260.0)
        assert frac == pytest.approx(1.0)

    def test_cloud_fraction_mixed(self):
        bt_data = np.full((10, 10), 300.0)
        bt_data[:5, :] = 200.0
        frac = SatelliteFeatures.cloud_fraction(bt_data, threshold_k=260.0)
        assert frac == pytest.approx(0.5)

    def test_cloud_fraction_xarray(self):
        bt_data = xr.DataArray(np.full((5, 5), 250.0))
        frac = SatelliteFeatures.cloud_fraction(bt_data, threshold_k=260.0)
        assert float(frac) == pytest.approx(1.0)
