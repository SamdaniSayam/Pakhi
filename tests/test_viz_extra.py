"""Tests for pakhi.viz — dashboard, ensemble, maps, timeseries."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from pakhi.viz.dashboard import TerminalDashboard
from pakhi.viz.ensemble import plot_ensemble_plume
from pakhi.viz.timeseries import (
    plot_ensemble_spread,
    plot_forecast_vs_obs,
    plot_signal_history,
)
from pakhi.viz.maps import (
    plot_forecast_map,
    plot_heatmap,
    plot_track,
)


def _make_series(n=100):
    return pd.Series(np.random.randn(n), index=pd.date_range("2020-01-01", periods=n))


def _make_array(n=100):
    return np.random.randn(n)


def _make_da():
    import xarray as xr
    return xr.DataArray(np.random.randn(10, 10), dims=["latitude", "longitude"],
                        coords={"latitude": np.linspace(30, 35, 10),
                                "longitude": np.linspace(-90, -85, 10)})


class TestTerminalDashboard:
    @patch("pakhi.viz.dashboard.Console")
    def test_instantiation(self, MockConsole):
        d = TerminalDashboard(use_plotext=False)
        assert d is not None

    @patch("pakhi.viz.dashboard.Console")
    def test_display_current_weather(self, MockConsole):
        d = TerminalDashboard(use_plotext=False)
        d.display_current_weather(temp=32.5, wind=15.2, pressure=1012.3)
        assert True

    @patch("pakhi.viz.dashboard.Console")
    def test_display_current_weather_full(self, MockConsole):
        d = TerminalDashboard(use_plotext=False)
        d.display_current_weather(temp=32.5, wind=15.2, pressure=1012.3,
                                 humidity=65.0, description="Sunny")
        assert True


class TestEnsembleViz:
    def test_plot_ensemble_plume(self):
        forecast = {
            "q0.1": np.random.randn(100).cumsum(),
            "q0.25": np.random.randn(100).cumsum(),
            "q0.5": np.random.randn(100).cumsum(),
            "q0.75": np.random.randn(100).cumsum(),
            "q0.9": np.random.randn(100).cumsum(),
        }
        fig = plot_ensemble_plume(forecast)
        assert fig is not None

    def test_plot_ensemble_plume_with_obs(self):
        forecast = {
            "q0.1": np.random.randn(50).cumsum(),
            "q0.5": np.random.randn(50).cumsum(),
            "q0.9": np.random.randn(50).cumsum(),
        }
        obs = np.random.randn(50).cumsum()
        fig = plot_ensemble_plume(forecast, observation=obs)
        assert fig is not None


class TestTimeseriesViz:
    def test_plot_forecast_vs_obs(self):
        fc = np.random.randn(100).cumsum()
        obs = np.random.randn(100).cumsum()
        fig = plot_forecast_vs_obs(fc, obs)
        assert fig is not None

    def test_plot_forecast_vs_obs_with_bands(self):
        fc = np.random.randn(50).cumsum()
        obs = np.random.randn(50).cumsum()
        fig = plot_forecast_vs_obs(fc, obs,
                                   confidence_lower=fc - 1.0,
                                   confidence_upper=fc + 1.0)
        assert fig is not None

    def test_plot_ensemble_spread(self):
        members = [np.random.randn(50) for _ in range(5)]
        obs = np.random.randn(50)
        fig = plot_ensemble_spread(members, obs)
        assert fig is not None

    def test_plot_signal_history(self):
        signals = np.random.randn(100)
        prices = np.random.randn(100).cumsum() + 100
        fig = plot_signal_history(signals, prices)
        assert fig is not None


class TestMapsViz:
    def test_plot_forecast_map(self):
        data = np.random.randn(10, 10)
        fig = plot_forecast_map(data)
        assert fig is not None

    def test_plot_forecast_map_with_coords(self):
        data = np.random.randn(10, 10)
        lats = np.linspace(30, 35, 10)
        lons = np.linspace(-90, -85, 10)
        fig = plot_forecast_map(data, lats=lats, lons=lons)
        assert fig is not None

    def test_plot_heatmap(self):
        data = np.random.randn(10, 10)
        fig = plot_heatmap(data)
        assert fig is not None

    def test_plot_track(self):
        cone_lats = np.array([15.0, 18.0, 22.0, 26.0, 30.0])
        cone_lons = np.array([-60.0, -65.0, -70.0, -75.0, -80.0])
        track_lats = np.array([16.0, 19.0, 23.0, 27.0, 31.0])
        track_lons = np.array([-61.0, -66.0, -71.0, -76.0, -81.0])
        fig = plot_track(cone_lats, cone_lons, track_lats, track_lons)
        assert fig is not None
