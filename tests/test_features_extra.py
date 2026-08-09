"""Tests for pakhi.features — spatial, teleconnection, satellite, temporal, climate, anomaly."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pakhi.features.spatial import SpatialFeatures
from pakhi.features.teleconnection import TeleconnectionIndices
from pakhi.features.satellite import SatelliteFeatures
from pakhi.features.temporal import TemporalFeatures
from pakhi.features.climate import ClimateFeatures
from pakhi.features.anomaly import AnomalyFeatures


def _make_grid_2d(n_lat=10, n_lon=10):
    lats = np.linspace(30, 35, n_lat)
    lons = np.linspace(-90, -85, n_lon)
    data = np.random.randn(n_lat, n_lon)
    return xr.DataArray(data, dims=["latitude", "longitude"],
                        coords={"latitude": lats, "longitude": lons})


def _make_grid_3d(n_time=5, n_lat=10, n_lon=10):
    lats = np.linspace(30, 35, n_lat)
    lons = np.linspace(-90, -85, n_lon)
    times = np.arange(n_time)
    data = np.random.randn(n_time, n_lat, n_lon)
    return xr.DataArray(data, dims=["time", "latitude", "longitude"],
                        coords={"time": times, "latitude": lats, "longitude": lons})


def _make_sst_3d():
    lats = np.linspace(-5, 5, 5)
    lons = np.linspace(-170, -120, 5)
    times = pd.date_range("2020-01-01", periods=12, freq="MS")
    data = np.random.randn(12, 5, 5) + 280
    return xr.DataArray(data, dims=["time", "latitude", "longitude"],
                        coords={"time": times, "latitude": lats, "longitude": lons})


def _make_series(n=100):
    return pd.Series(np.random.randn(n), index=pd.date_range("2020-01-01", periods=n))


class TestSpatial:
    def test_distance_weighted_average(self):
        grid = _make_grid_2d()
        result = SpatialFeatures.distance_weighted_average(grid, 32.0, -88.0)
        assert result is not None

    def test_distance_weighted_too_far(self):
        grid = _make_grid_2d()
        with pytest.raises(ValueError, match="No grid points"):
            SpatialFeatures.distance_weighted_average(grid, 50.0, -120.0, max_distance_km=1.0)

    def test_gradient(self):
        grid = _make_grid_2d()
        result = SpatialFeatures.gradient(grid)
        assert "magnitude" in result
        assert "d_dx" in result

    def test_gradient_uniform(self):
        grid = _make_grid_2d()
        grid.values[:] = 5.0
        result = SpatialFeatures.gradient(grid)
        assert float(result["magnitude"].mean()) == pytest.approx(0.0, abs=0.01)

    def test_convergence(self):
        lats = np.linspace(30, 35, 10)
        lons = np.linspace(-90, -85, 10)
        ds = xr.Dataset({
            "u": xr.DataArray(np.random.randn(10, 10), dims=["latitude", "longitude"],
                              coords={"latitude": lats, "longitude": lons}),
            "v": xr.DataArray(np.random.randn(10, 10), dims=["latitude", "longitude"],
                              coords={"latitude": lats, "longitude": lons}),
        })
        result = SpatialFeatures.convergence(ds)
        assert "convergence" in result
        assert "divergence" in result

    def test_distance_to_coast(self):
        dist = SpatialFeatures.distance_to_coast(32.0, -88.0)
        assert dist >= 0

    def test_distance_to_coast_with_coastline(self):
        coast = np.array([[30.0, -90.0], [35.0, -85.0]])
        dist = SpatialFeatures.distance_to_coast(32.0, -88.0, coastline_data=coast)
        assert dist >= 0


class TestTeleconnection:
    def test_nino34(self):
        sst = _make_sst_3d()
        result = TeleconnectionIndices.compute_nino34(sst)
        assert result is not None
        assert "nino34" in result.name

    def test_nao(self):
        lats = np.linspace(30, 70, 10)
        lons = np.linspace(-25, -15, 5)
        times = pd.date_range("2020-01-01", periods=12, freq="MS")
        slp = xr.DataArray(np.random.randn(12, 10, 5) * 10 + 1013,
                           dims=["time", "latitude", "longitude"],
                           coords={"time": times, "latitude": lats, "longitude": lons})
        result = TeleconnectionIndices.compute_nao(slp)
        assert result is not None

    def test_pdo(self):
        lats = np.linspace(25, 55, 10)
        lons = np.linspace(-165, -120, 10)
        times = pd.date_range("2020-01-01", periods=12, freq="MS")
        sst = xr.DataArray(np.random.randn(12, 10, 10) + 280,
                           dims=["time", "latitude", "longitude"],
                           coords={"time": times, "latitude": lats, "longitude": lons})
        result = TeleconnectionIndices.computepdo(sst)
        assert result is not None

    def test_mjo(self):
        lats = np.linspace(-5, 5, 5)
        lons = np.linspace(60, 170, 10)
        times = pd.date_range("2020-01-01", periods=50, freq="D")
        olr = xr.DataArray(np.random.randn(50, 5, 10) + 250,
                           dims=["time", "latitude", "longitude"],
                           coords={"time": times, "latitude": lats, "longitude": lons})
        result = TeleconnectionIndices.compute_mjo(olr)
        assert "rmm1" in result


class TestSatelliteFeatures:
    def test_brightness_temperature(self):
        result = SatelliteFeatures.brightness_temperature(50.0, band_number=4)
        assert result > 0

    def test_brightness_temperature_array(self):
        rad = np.array([10.0, 50.0, 100.0])
        result = SatelliteFeatures.brightness_temperature(rad, band_number=4)
        assert len(result) == 3

    def test_brightness_temperature_xr(self):
        da = xr.DataArray([50.0, 100.0], dims=["x"])
        result = SatelliteFeatures.brightness_temperature(da, band_number=4)
        assert isinstance(result, xr.DataArray)

    def test_cloud_fraction(self):
        ir_data = np.random.uniform(200, 300, (10, 10))
        result = SatelliteFeatures.cloud_fraction(ir_data)
        assert 0.0 <= result <= 1.0

    def test_cloud_fraction_xr(self):
        da = xr.DataArray(np.random.uniform(200, 300, (10, 10)),
                          dims=["latitude", "longitude"])
        result = SatelliteFeatures.cloud_fraction(da)
        assert 0.0 <= float(result) <= 1.0

    def test_cloud_motion_vectors(self):
        data = np.random.randn(3, 20, 20)
        result = SatelliteFeatures.cloud_motion_vectors(data, time_delta_minutes=15.0,
                                                        search_window=2)
        assert "u_wind" in result


class TestTemporal:
    def test_build_pandas(self):
        tf = TemporalFeatures(lags=[1, 3], windows=[6])
        df = pd.DataFrame({"temp": np.random.randn(100)},
                          index=pd.date_range("2020-01-01", periods=100, freq="h"))
        result = tf.build(df)
        assert result.shape[1] > 1

    def test_build_series(self):
        tf = TemporalFeatures(lags=[1], windows=[6])
        s = _make_series(100)
        result = tf.build(s)
        assert isinstance(result, pd.DataFrame)

    def test_build_xarray(self):
        tf = TemporalFeatures(lags=[1], windows=[6])
        times = np.arange(100)
        ds = xr.Dataset({
            "temp": xr.DataArray(np.random.randn(100), dims=["time"],
                                 coords={"time": times}),
        })
        result = tf.build(ds)
        assert len(result.data_vars) > 1

    def test_custom_stats(self):
        tf = TemporalFeatures(lags=[1], windows=[6], stats=["mean", "ema"])
        df = pd.DataFrame({"x": np.random.randn(100)},
                          index=pd.date_range("2020-01-01", periods=100, freq="h"))
        result = tf.build(df)
        assert result.shape[1] > 1

    def test_build_short_pandas_df(self):
        # Series shorter than the default windows must not crash
        # (triples-sigfast rolling_average raises if len < window).
        df = pd.DataFrame({"t": np.linspace(20.0, 30.0, 10)},
                          index=pd.date_range("2020-01-01", periods=10, freq="h"))
        result = TemporalFeatures().build(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 10
        assert "t_lag_1" in result.columns

    def test_build_short_series(self):
        s = pd.Series(np.linspace(20.0, 30.0, 10),
                      index=pd.date_range("2020-01-01", periods=10, freq="h"))
        result = TemporalFeatures().build(s)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 10

    def test_build_short_xarray(self):
        ds = xr.Dataset(
            {"t": ("time", np.linspace(20.0, 30.0, 10))},
            coords={"time": np.arange(10)},
        )
        result = TemporalFeatures().build(ds)
        assert len(result.data_vars) > 1

    def test_long_series_keeps_full_windows(self):
        df = pd.DataFrame({"t": np.random.randn(300)},
                          index=pd.date_range("2020-01-01", periods=300, freq="h"))
        result = TemporalFeatures().build(df)
        assert "t_rollmean_168" in result.columns
        assert "t_rolling_168" in result.columns


class TestClimate:
    def test_hdd(self):
        result = ClimateFeatures.hdd(np.array([10.0, 15.0, 25.0]))
        assert result is not None

    def test_hdd_warm(self):
        assert ClimateFeatures.hdd(np.array([25.0])) == 0.0

    def test_cdd(self):
        result = ClimateFeatures.cdd(np.array([25.0, 30.0, 35.0]))
        assert result is not None

    def test_cdd_cold(self):
        assert ClimateFeatures.cdd(np.array([5.0])) == 0.0

    def test_gdd(self):
        result = ClimateFeatures.gdd(np.array([20.0, 25.0, 30.0]))
        assert result is not None

    def test_dry_days(self):
        precip = np.array([0.0, 0.0, 5.0, 0.0, 0.0])
        result = ClimateFeatures.dry_days(precip, window_days=3)
        assert result is not None

    def test_frost_days(self):
        result = ClimateFeatures.frost_days(np.array([-2.0, 5.0, 0.0]))
        assert result[0] == True
        assert result[1] == False
        assert result[2] == True

    def test_heatwave_days(self):
        temps = np.array([36, 37, 38, 36, 30])
        result = ClimateFeatures.heatwave_days(temps, threshold_celsius=35.0, consecutive_days=3)
        assert result[0] == True
        assert result[1] == True
        assert result[2] == True


class TestAnomaly:
    def test_zscore_anomaly(self):
        data = np.array([30.0, 32.0, 34.0])
        mean = np.array([25.0, 25.0, 25.0])
        std = np.array([5.0, 5.0, 5.0])
        result = AnomalyFeatures.zscore_anomaly(data, mean, std)
        assert np.all(result > 0)

    def test_zscore_zero_std(self):
        result = AnomalyFeatures.zscore_anomaly(
            np.array([1.0]), np.array([0.0]), np.array([0.0]))
        assert np.isnan(result[0])

    def test_percentile_rank(self):
        data = np.array([50.0])
        hist = np.arange(100, dtype=float)
        rank = AnomalyFeatures.percentile_rank(data, hist)
        assert 40 <= rank <= 60

    def test_departure_from_normal(self):
        result = AnomalyFeatures.departure_from_normal(30.0, 25.0)
        assert result == pytest.approx(5.0)

    def test_spi(self):
        precip = np.random.exponential(5, 300).astype(float)
        result = AnomalyFeatures.spi(precip, window_days=30)
        assert result is not None
