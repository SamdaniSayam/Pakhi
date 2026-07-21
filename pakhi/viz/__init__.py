"""Visualisation module — maps, time-series, ensemble plumes, and terminal dashboards.

Submodules
----------
maps
    Geospatial forecast maps, hurricane tracks, and heatmaps.
timeseries
    Forecast-vs-observation line plots, ensemble spaghetti plots, and
    signal overlays.
ensemble
    Fan charts with quantile bands and model comparison bar charts.
dashboard
    Terminal dashboard using plotext / rich for real-time display.
"""

from __future__ import annotations

try:
    from pakhi.viz.dashboard import TerminalDashboard
    from pakhi.viz.ensemble import plot_ensemble_plume, plot_model_comparison
    from pakhi.viz.maps import plot_forecast_map, plot_heatmap, plot_track
    from pakhi.viz.timeseries import (
        plot_ensemble_spread,
        plot_forecast_vs_obs,
        plot_signal_history,
    )
except ImportError:
    pass  # matplotlib or other viz deps not available

__all__ = [
    "TerminalDashboard",
    "plot_ensemble_plume",
    "plot_ensemble_spread",
    "plot_forecast_map",
    "plot_forecast_vs_obs",
    "plot_heatmap",
    "plot_model_comparison",
    "plot_signal_history",
    "plot_track",
]
