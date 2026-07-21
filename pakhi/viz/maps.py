"""Geospatial visualisation — forecast maps, hurricane tracks, and heatmaps.

Uses cartopy for map projections when available, falls back to plain
matplotlib ``pcolormesh`` otherwise.
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except ImportError:
    raise ImportError(
        "matplotlib is required for pakhi.viz. Install it with: pip install 'pakhi[viz]'"
    )

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    _HAS_CARTOPY = True
except ImportError:
    _HAS_CARTOPY = False

__all__ = [
    "plot_forecast_map",
    "plot_heatmap",
    "plot_track",
]

logger = logging.getLogger(__name__)


def plot_forecast_map(
    data: np.ndarray,
    lats: np.ndarray | None = None,
    lons: np.ndarray | None = None,
    variable: str = "temperature_2m",
    title: str = "Weather Forecast Map",
    cmap: str = "RdYlBu_r",
) -> Figure:
    """Plot a gridded forecast field on a map.

    Parameters
    ----------
    data : array of shape ``(ny, nx)``
        2-D field to plot.
    lats : array of shape ``(ny,)``, optional
        Latitude coordinates.  Auto-generated if ``None``.
    lons : array of shape ``(nx,)``, optional
        Longitude coordinates.  Auto-generated if ``None``.
    variable : str
        Variable name for the colour-bar label.
    title : str
        Plot title.
    cmap : str
        Matplotlib colormap name.

    Returns
    -------
    matplotlib.figure.Figure
    """
    ny, nx = data.shape[-2], data.shape[-1]

    if lats is None:
        lats = np.linspace(-90, 90, ny)
    if lons is None:
        lons = np.linspace(0, 360, nx)

    if _HAS_CARTOPY:
        fig, ax = plt.subplots(
            figsize=(12, 6),
            subplot_kw={"projection": ccrs.PlateCarree()},
        )
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.add_feature(cfeature.BORDERS, linewidth=0.3)
        ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

        lon_grid, lat_grid = np.meshgrid(lons, lats)
        cf = ax.pcolormesh(
            lon_grid,
            lat_grid,
            data,
            cmap=cmap,
            transform=ccrs.PlateCarree(),
            shading="auto",
        )
        ax.set_title(title, fontsize=13, fontweight="bold")
    else:
        fig, ax = plt.subplots(figsize=(12, 6))
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        cf = ax.pcolormesh(lon_grid, lat_grid, data, cmap=cmap, shading="auto")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(title, fontsize=13, fontweight="bold")

    cbar = fig.colorbar(cf, ax=ax, shrink=0.7, pad=0.05)
    cbar.set_label(variable, fontsize=10)

    fig.tight_layout()
    return fig


def plot_track(
    cone_lats: np.ndarray,
    cone_lons: np.ndarray,
    track_lats: np.ndarray,
    track_lons: np.ndarray,
    title: str = "Hurricane Track",
    cone_color: str = "red",
    track_color: str = "black",
) -> Figure:
    """Plot a hurricane track with cone of uncertainty.

    Parameters
    ----------
    cone_lats, cone_lons : array of shape ``(n_vertices,)``
        Polygon vertices defining the forecast cone.
    track_lats, track_lons : array of shape ``(n_points,)``
        Best-track / forecast centre positions.
    title : str
        Plot title.
    cone_color : str
        Fill colour for the cone.
    track_color : str
        Colour for the track line.

    Returns
    -------
    matplotlib.figure.Figure
    """
    cone_lats = np.asarray(cone_lats)
    cone_lons = np.asarray(cone_lons)
    track_lats = np.asarray(track_lats)
    track_lons = np.asarray(track_lons)

    if _HAS_CARTOPY:
        fig, ax = plt.subplots(
            figsize=(10, 8),
            subplot_kw={"projection": ccrs.PlateCarree()},
        )
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.add_feature(cfeature.BORDERS, linewidth=0.3)
        ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

        from matplotlib.patches import Polygon

        cone_xy = np.column_stack([cone_lons, cone_lats])
        cone_poly = Polygon(
            cone_xy,
            closed=True,
            facecolor=cone_color,
            alpha=0.25,
            edgecolor=cone_color,
            linewidth=1.0,
            transform=ccrs.PlateCarree(),
        )
        ax.add_patch(cone_poly)
        ax.plot(
            track_lons,
            track_lats,
            color=track_color,
            linewidth=2,
            marker="o",
            markersize=4,
            transform=ccrs.PlateCarree(),
        )
        ax.set_title(title, fontsize=13, fontweight="bold")
    else:
        fig, ax = plt.subplots(figsize=(10, 8))
        cone_xy = np.column_stack([cone_lons, cone_lats])
        from matplotlib.patches import Polygon

        cone_poly = Polygon(
            cone_xy,
            closed=True,
            facecolor=cone_color,
            alpha=0.25,
            edgecolor=cone_color,
            linewidth=1.0,
        )
        ax.add_patch(cone_poly)
        ax.plot(
            track_lons,
            track_lats,
            color=track_color,
            linewidth=2,
            marker="o",
            markersize=4,
        )
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_aspect("equal")

    fig.tight_layout()
    return fig


def plot_heatmap(
    data: np.ndarray,
    x_labels: Sequence[str] | None = None,
    y_labels: Sequence[str] | None = None,
    title: str = "Heatmap",
    cmap: str = "RdBu_r",
    vmin: float | None = None,
    vmax: float | None = None,
    annotate: bool = True,
) -> Figure:
    """Plot a heatmap (correlation matrix, feature importance, etc.).

    Parameters
    ----------
    data : array of shape ``(ny, nx)``
        Values to display.
    x_labels : sequence of str, optional
        Tick labels for the x-axis.
    y_labels : sequence of str, optional
        Tick labels for the y-axis.
    title : str
        Plot title.
    cmap : str
        Matplotlib colormap name.
    vmin, vmax : float, optional
        Colour scale range.  Auto-scaled if ``None``.
    annotate : bool
        If ``True``, write the data value in each cell.

    Returns
    -------
    matplotlib.figure.Figure
    """
    data = np.asarray(data, dtype=np.float64)
    ny, nx = data.shape

    fig_height = max(4, ny * 0.45)
    fig, ax = plt.subplots(figsize=(max(6, nx * 0.8), fig_height))

    kwargs: dict = {"cmap": cmap}
    if vmin is not None:
        kwargs["vmin"] = vmin
    if vmax is not None:
        kwargs["vmax"] = vmax

    im = ax.imshow(data, aspect="auto", **kwargs)

    if annotate:
        for i in range(ny):
            for j in range(nx):
                val = data[i, j]
                text = f"{val:.2f}" if abs(val) < 10 else f"{val:.1f}"
                ax.text(
                    j,
                    i,
                    text,
                    ha="center",
                    va="center",
                    fontsize=max(6, min(10, 120 // max(ny, nx))),
                    color="white" if abs(val) > (kwargs.get("vmax", 1.0) or 1.0) * 0.6 else "black",
                )

    if x_labels is not None:
        ax.set_xticks(range(nx))
        ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=9)
    if y_labels is not None:
        ax.set_yticks(range(ny))
        ax.set_yticklabels(y_labels, fontsize=9)

    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(title, fontsize=13, fontweight="bold")
    fig.tight_layout()
    return fig
