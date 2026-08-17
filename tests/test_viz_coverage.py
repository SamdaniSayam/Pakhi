"""Comprehensive tests for pakhi.viz — dashboard, ensemble, and maps.

Targets coverage gaps in:
  - dashboard.py (no rich path, display_signals, plotext path, close)
  - ensemble.py (plot_model_comparison, _get_quantile, missing quantiles)
  - maps.py (plot_heatmap, plot_track, plot_forecast_map with/without cartopy)
"""

from __future__ import annotations

import importlib.util
import sys
from unittest.mock import MagicMock, patch


def _have(module: str) -> bool:
    """Detect whether a dependency is actually importable in this environment."""
    return importlib.util.find_spec(module) is not None


import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# dashboard.py
# ---------------------------------------------------------------------------


class TestDashboardNoRich:
    """Tests for TerminalDashboard when rich is NOT available."""

    def test_display_current_weather_no_rich(self, capsys):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            d.display_current_weather(temp=22.5, wind=10.3, pressure=1013.2)
        captured = capsys.readouterr()
        assert "Current Weather" in captured.out
        assert "22.5" in captured.out
        assert "10.3" in captured.out
        assert "1013.2" in captured.out

    def test_display_current_weather_with_humidity_and_desc(self, capsys):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            d.display_current_weather(
                temp=5.0, wind=20.0, pressure=1005.0, humidity=80.0, description="Cloudy"
            )
        captured = capsys.readouterr()
        assert "80.0" in captured.out
        assert "Cloudy" in captured.out

    def test_display_forecast_table_no_rich(self, capsys):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            forecast = [
                {
                    "date": "Mon",
                    "temp_high": 30.0,
                    "temp_low": 18.0,
                    "wind": 12.0,
                    "precip_prob": 0.3,
                    "description": "Sunny",
                },
                {
                    "date": "Tue",
                    "temp_high": 28.0,
                    "temp_low": 16.0,
                    "wind": 8.0,
                    "precip_prob": 0.6,
                    "description": "Rain",
                },
            ]
            d.display_forecast_table(forecast)
        captured = capsys.readouterr()
        assert "7-Day Forecast" in captured.out
        assert "Mon" in captured.out
        assert "Tue" in captured.out

    def test_display_signal_status_no_rich(self, capsys):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            signals = [
                {
                    "instrument": "NG",
                    "action": "LONG",
                    "confidence": 0.8,
                    "size": 0.1,
                    "reasoning": "Freeze",
                },
                {
                    "instrument": "CL",
                    "action": "SHORT",
                    "confidence": 0.6,
                    "size": 0.05,
                    "reasoning": "Demand drop",
                },
                {
                    "instrument": "HG",
                    "action": "FLAT",
                    "confidence": 0.1,
                    "size": 0.0,
                    "reasoning": "No signal",
                },
            ]
            d.display_signal_status(signals)
        captured = capsys.readouterr()
        assert "Active Signals" in captured.out
        assert "LONG" in captured.out
        assert "SHORT" in captured.out
        assert "NG" in captured.out

    def test_display_current_weather_minimal(self, capsys):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            d.display_current_weather(temp=0.0, wind=0.0, pressure=1000.0)
        captured = capsys.readouterr()
        assert "1000.0" in captured.out

    def test_plot_terminal_chart_no_plotext(self):
        import pakhi.viz.dashboard as dash_mod

        with (
            patch.object(dash_mod, "_HAS_RICH", False),
            patch.object(dash_mod, "_HAS_PLOTEXT", False),
        ):
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            d.plot_terminal_chart(np.array([1.0, 2.0, 3.0]))


class TestDashboardWithRich:
    """Tests for TerminalDashboard when rich IS available."""

    def test_display_current_weather_with_rich(self):
        dash_mod = sys.modules.get("pakhi.viz.dashboard")
        if dash_mod is None:
            pytest.skip("dashboard module not loaded")

        from pakhi.viz.dashboard import TerminalDashboard

        d = TerminalDashboard(use_plotext=False)
        if not _have("rich"):
            pytest.skip("rich not installed")

        # Should not raise
        d.display_current_weather(temp=10.0, wind=5.0, pressure=1010.0)
        d.display_current_weather(
            temp=10.0, wind=5.0, pressure=1010.0, humidity=50.0, description="Clear"
        )

    def test_display_signal_status_with_rich(self):
        from pakhi.viz.dashboard import TerminalDashboard

        d = TerminalDashboard(use_plotext=False)
        if not _have("rich"):
            pytest.skip("rich not installed")
        signals = [
            {
                "instrument": "NG",
                "action": "LONG",
                "confidence": 0.9,
                "size": 0.2,
                "reasoning": "Freeze incoming",
            },
        ]
        d.display_signal_status(signals)

    def test_display_forecast_table_with_rich(self):
        from pakhi.viz.dashboard import TerminalDashboard

        d = TerminalDashboard(use_plotext=False)
        if not _have("rich"):
            pytest.skip("rich not installed")
        d.display_forecast_table(
            [
                {
                    "date": "Mon",
                    "temp_high": 25.0,
                    "temp_low": 15.0,
                    "wind": 10.0,
                    "precip_prob": 0.1,
                    "description": "Nice",
                },
            ]
        )


# ---------------------------------------------------------------------------
# ensemble.py
# ---------------------------------------------------------------------------


class TestEnsemblePlume:
    def test_basic_plume(self):
        from pakhi.viz.ensemble import plot_ensemble_plume

        n = 48
        ef = {
            "q0.1": np.linspace(0, 5, n) - 3,
            "q0.25": np.linspace(0, 5, n) - 1.5,
            "q0.5": np.linspace(0, 5, n),
            "q0.75": np.linspace(0, 5, n) + 1.5,
            "q0.9": np.linspace(0, 5, n) + 3,
        }
        fig = plot_ensemble_plume(ef)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_plume_with_observation(self):
        from pakhi.viz.ensemble import plot_ensemble_plume

        n = 30
        ef = {
            "q0.1": np.zeros(n) - 2,
            "q0.25": np.zeros(n) - 1,
            "q0.5": np.zeros(n),
            "q0.75": np.zeros(n) + 1,
            "q0.9": np.zeros(n) + 2,
        }
        obs = np.random.default_rng(0).normal(0, 0.5, n)
        fig = plot_ensemble_plume(ef, observation=obs, dates=np.arange(n))
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_plume_missing_quantiles_extrapolated(self):
        from pakhi.viz.ensemble import plot_ensemble_plume

        n = 20
        ef = {
            "q0.25": np.linspace(0, 10, n),
            "q0.5": np.linspace(0, 10, n) + 5,
            "q0.75": np.linspace(0, 10, n) + 10,
        }
        fig = plot_ensemble_plume(ef)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_plume_single_quantile_only(self):
        from pakhi.viz.ensemble import plot_ensemble_plume

        n = 10
        ef = {"q0.5": np.ones(n)}
        fig = plot_ensemble_plume(ef, base_color="red")
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)


class TestGetQuantile:
    def test_exact_key_found(self):
        from pakhi.viz.ensemble import _get_quantile

        q_dict = {"q0.1": np.array([1.0]), "q0.5": np.array([2.0])}
        result = _get_quantile(q_dict, 0.1)
        np.testing.assert_array_almost_equal(result, [1.0])

    def test_closest_key_fallback(self):
        from pakhi.viz.ensemble import _get_quantile

        q_dict = {"q0.25": np.array([10.0]), "q0.75": np.array([20.0])}
        result = _get_quantile(q_dict, 0.5)
        np.testing.assert_array_almost_equal(result, [10.0])

    def test_no_quantiles_raises(self):
        from pakhi.viz.ensemble import _get_quantile

        with pytest.raises(KeyError, match="Cannot find quantile"):
            _get_quantile({"foo": np.array([1.0])}, 0.5)

    def test_empty_dict_raises(self):
        from pakhi.viz.ensemble import _get_quantile

        with pytest.raises(KeyError):
            _get_quantile({}, 0.5)

    def test_single_quantile_closest(self):
        from pakhi.viz.ensemble import _get_quantile

        q_dict = {"q0.9": np.array([42.0])}
        result = _get_quantile(q_dict, 0.1)
        np.testing.assert_array_almost_equal(result, [42.0])

    def test_numeric_array_converted(self):
        from pakhi.viz.ensemble import _get_quantile

        q_dict = {"q0.5": [1, 2, 3]}
        result = _get_quantile(q_dict, 0.5)
        assert result.dtype == np.float64
        assert result.shape == (3,)


class TestModelComparison:
    def test_basic_comparison(self):
        from pakhi.viz.ensemble import plot_model_comparison

        models = ["XGB", "LSTM", "Persistence"]
        metrics = {"RMSE": [1.2, 0.9, 2.1], "MAE": [0.8, 0.6, 1.5]}
        fig = plot_model_comparison(models, metrics)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_single_metric(self):
        from pakhi.viz.ensemble import plot_model_comparison

        fig = plot_model_comparison(["A", "B"], {"ACC": [0.9, 0.85]})
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_single_model(self):
        from pakhi.viz.ensemble import plot_model_comparison

        fig = plot_model_comparison(["OnlyModel"], {"RMSE": [1.0]})
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_empty_metrics_raises(self):
        from pakhi.viz.ensemble import plot_model_comparison

        with pytest.raises(ValueError, match="metrics dict"):
            plot_model_comparison(["A", "B"], {})

    def test_many_models(self):
        from pakhi.viz.ensemble import plot_model_comparison

        n = 20
        models = [f"m{i}" for i in range(n)]
        metrics = {"RMSE": list(range(n))}
        fig = plot_model_comparison(models, metrics, bar_width=0.2)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)


# ---------------------------------------------------------------------------
# maps.py
# ---------------------------------------------------------------------------


class TestPlotHeatmap:
    def test_basic_heatmap(self):
        from pakhi.viz.maps import plot_heatmap

        data = np.array([[1.0, 2.0], [3.0, 4.0]])
        fig = plot_heatmap(data)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_heatmap_with_labels(self):
        from pakhi.viz.maps import plot_heatmap

        data = np.array([[0.5, 0.3], [0.2, 0.8], [0.1, 0.9]])
        fig = plot_heatmap(
            data,
            x_labels=["A", "B"],
            y_labels=["X", "Y", "Z"],
            title="Correlation Matrix",
            vmin=0.0,
            vmax=1.0,
        )
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_heatmap_no_annotate(self):
        from pakhi.viz.maps import plot_heatmap

        data = np.random.default_rng(42).random((5, 5))
        fig = plot_heatmap(data, annotate=False)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_heatmap_large_values(self):
        from pakhi.viz.maps import plot_heatmap

        data = np.array([[100.0, 200.0], [300.0, 400.0]])
        fig = plot_heatmap(data)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)


class TestPlotTrack:
    def test_basic_track(self):
        from pakhi.viz.maps import plot_track

        cone_lats = np.array([20, 22, 25, 28, 30, 28, 25, 22, 20])
        cone_lons = np.array([-80, -82, -84, -86, -88, -90, -88, -86, -84])
        track_lats = np.array([20, 23, 26, 29])
        track_lons = np.array([-80, -83, -86, -88])
        fig = plot_track(cone_lats, cone_lons, track_lats, track_lons)
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_track_custom_colors(self):
        from pakhi.viz.maps import plot_track

        fig = plot_track(
            cone_lats=np.array([10, 12, 14, 12, 10]),
            cone_lons=np.array([-60, -62, -64, -62, -60]),
            track_lats=np.array([10, 12, 14]),
            track_lons=np.array([-60, -62, -64]),
            title="My Hurricane",
            cone_color="blue",
            track_color="white",
        )
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)


class TestPlotForecastMap:
    def test_basic_forecast_map_no_cartopy(self):
        from pakhi.viz import maps as maps_mod

        old_cartopy = maps_mod._HAS_CARTOPY
        maps_mod._HAS_CARTOPY = False
        try:
            data = np.random.default_rng(0).random((10, 20))
            fig = maps_mod.plot_forecast_map(data)
            assert isinstance(fig, matplotlib.figure.Figure)
            plt.close(fig)
        finally:
            maps_mod._HAS_CARTOPY = old_cartopy

    def test_forecast_map_custom_coords(self):
        from pakhi.viz import maps as maps_mod

        old_cartopy = maps_mod._HAS_CARTOPY
        maps_mod._HAS_CARTOPY = False
        try:
            data = np.random.default_rng(1).random((5, 8))
            lats = np.linspace(30, 50, 5)
            lons = np.linspace(-100, -80, 8)
            fig = maps_mod.plot_forecast_map(
                data,
                lats=lats,
                lons=lons,
                variable="precipitation",
                title="Rain Map",
            )
            assert isinstance(fig, matplotlib.figure.Figure)
            plt.close(fig)
        finally:
            maps_mod._HAS_CARTOPY = old_cartopy

    def test_forecast_map_cartopy_path(self):
        """Test cartopy path if cartopy is available."""
        from pakhi.viz import maps as maps_mod

        if not _have("cartopy"):
            pytest.skip("cartopy not installed")
        data = np.random.default_rng(2).random((8, 12))
        fig = maps_mod.plot_forecast_map(data, title="Cartopy Map")
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)

    def test_track_cartopy_path(self):
        from pakhi.viz import maps as maps_mod

        if not _have("cartopy"):
            pytest.skip("cartopy not installed")
        fig = maps_mod.plot_track(
            cone_lats=np.array([10, 12, 14, 12, 10]),
            cone_lons=np.array([-60, -62, -64, -62, -60]),
            track_lats=np.array([10, 12, 14]),
            track_lons=np.array([-60, -62, -64]),
        )
        assert isinstance(fig, matplotlib.figure.Figure)
        plt.close(fig)


class TestDashboardDisplayCurrentWeatherRichPath:
    """Test the rich path for display_current_weather by enabling _HAS_RICH."""

    def test_rich_path_with_all_options(self):
        import pakhi.viz.dashboard as dash_mod

        old_has_rich = dash_mod._HAS_RICH
        dash_mod._HAS_RICH = True
        try:
            from pakhi.viz.dashboard import TerminalDashboard

            d = TerminalDashboard(use_plotext=False)
            if d._console is not None:
                d.display_current_weather(
                    temp=35.0, wind=25.0, pressure=998.0, humidity=90.0, description="Stormy"
                )
        finally:
            dash_mod._HAS_RICH = old_has_rich


class TestPlotTerminalChart:
    """Test plot_terminal_chart when plotext IS available."""

    def test_plotext_available(self):
        import pakhi.viz.dashboard as dash_mod

        old_has = dash_mod._HAS_PLOTEXT
        dash_mod._HAS_PLOTEXT = True
        try:
            with patch.object(dash_mod, "plt_term") as mock_plt:
                mock_plt.clear_figure = MagicMock()
                mock_plt.plot = MagicMock()
                mock_plt.title = MagicMock()
                mock_plt.show = MagicMock()
                from pakhi.viz.dashboard import TerminalDashboard

                d = TerminalDashboard(use_plotext=True)
                assert d.use_plotext is True
                d.plot_terminal_chart(np.array([1, 2, 3]), title="Test", label="val")
                mock_plt.clear_figure.assert_called_once()
                mock_plt.show.assert_called_once()
        finally:
            dash_mod._HAS_PLOTEXT = old_has
