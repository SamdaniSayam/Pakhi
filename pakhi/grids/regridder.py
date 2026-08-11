"""Regridding utilities for gridded meteorological data.

Provides routines to reproject data between grids of different resolutions
and projections, and to create uniform latitude/longitude grids.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import xarray as xr

__all__ = [
    "create_regular_grid",
    "regrid",
    "regrid_to_regular",
]

_Method = Literal["bilinear", "nearest", "conservative"]


def create_regular_grid(
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    resolution_deg: float = 0.25,
) -> xr.DataArray:
    """Create a uniform latitude/longitude grid.

    Parameters
    ----------
    lat_range : (lat_min, lat_max)
        Inclusive bounds in degrees north.
    lon_range : (lon_min, lon_max)
        Inclusive bounds in degrees east.
    resolution_deg : float
        Grid spacing in degrees (default 0.25°).

    Returns
    -------
    xr.DataArray
        Empty 2-D ``latitude × longitude`` array filled with NaN.  Useful
        as a *target_grid* for :func:`regrid`.
    """
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range

    if lat_min > lat_max:
        raise ValueError(f"lat_min ({lat_min}) must be <= lat_max ({lat_max}).")
    if lon_min > lon_max:
        raise ValueError(f"lon_min ({lon_min}) must be <= lon_max ({lon_max}).")
    if resolution_deg <= 0:
        raise ValueError(f"resolution_deg must be positive, got {resolution_deg}.")

    lats = np.arange(lat_min, lat_max + resolution_deg * 0.5, resolution_deg)
    lons = np.arange(lon_min, lon_max + resolution_deg * 0.5, resolution_deg)

    data = np.full((len(lats), len(lons)), np.nan, dtype=np.float64)

    return xr.DataArray(
        data,
        dims=["latitude", "longitude"],
        coords={"latitude": lats, "longitude": lons},
        attrs={"resolution_deg": resolution_deg, "grid_type": "regular_lonlat"},
    )


def regrid(
    source: xr.DataArray,
    target_grid: xr.DataArray,
    method: _Method = "bilinear",
) -> xr.DataArray:
    """Regrid *source* onto the coordinates of *target_grid*.

    Parameters
    ----------
    source : xr.DataArray
        Source data with ``latitude`` and ``longitude`` dimensions (or
        ``lat`` / ``lon``).
    target_grid : xr.DataArray
        Template array whose coordinates define the target grid.  Its data
        values are ignored.
    method : {"bilinear", "nearest", "conservative"}
        Interpolation method.

    Returns
    -------
    xr.DataArray
        Source data regridded onto the target grid.
    """
    method = method.lower().strip()
    if method not in ("bilinear", "nearest", "conservative"):
        raise ValueError(
            f"Unknown method '{method}'. Use 'bilinear', 'nearest', or 'conservative'."
        )

    target_lat = np.asarray(
        target_grid.coords[_find_coord_name(target_grid, "latitude")].values, dtype=np.float64
    )
    target_lon = np.asarray(
        target_grid.coords[_find_coord_name(target_grid, "longitude")].values, dtype=np.float64
    )

    source_lat = np.asarray(
        source.coords[_find_coord_name(source, "latitude")].values, dtype=np.float64
    )
    source_lon = np.asarray(
        source.coords[_find_coord_name(source, "longitude")].values, dtype=np.float64
    )

    source_vals = source.values.astype(np.float64)

    if source_vals.ndim == 2:
        result_vals = _regrid_2d(
            source_vals, source_lat, source_lon, target_lat, target_lon, method
        )
    else:
        raise NotImplementedError(
            f"Regridding for {source_vals.ndim}-D arrays is not yet supported. "
            "Squeeze or select a single slice first."
        )

    return xr.DataArray(
        result_vals,
        dims=["latitude", "longitude"],
        coords={"latitude": target_lat, "longitude": target_lon},
        attrs=source.attrs.copy(),
    )


def regrid_to_regular(
    data: xr.DataArray,
    target_resolution: float = 0.25,
    method: _Method = "bilinear",
) -> xr.DataArray:
    """Regrid *data* to a regular lat/lon grid at *target_resolution*.

    A target grid is automatically constructed from the bounding box of
    the source data.

    Parameters
    ----------
    data : xr.DataArray
        Source data with latitude/longitude dimensions.
    target_resolution : float
        Desired grid spacing in degrees (default 0.25°).
    method : {"bilinear", "nearest", "conservative"}

    Returns
    -------
    xr.DataArray
    """
    src_lat = np.asarray(data.coords[_find_coord_name(data, "latitude")].values, dtype=np.float64)
    src_lon = np.asarray(data.coords[_find_coord_name(data, "longitude")].values, dtype=np.float64)

    lat_range = (float(np.nanmin(src_lat)), float(np.nanmax(src_lat)))
    lon_range = (float(np.nanmin(src_lon)), float(np.nanmax(src_lon)))

    target = create_regular_grid(lat_range, lon_range, target_resolution)
    return regrid(data, target, method=method)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_coord_name(da: xr.DataArray, kind: str) -> str:
    """Return the actual coordinate name used for latitude or longitude."""
    candidates = {
        "latitude": ["latitude", "lat", "y"],
        "longitude": ["longitude", "lon", "x"],
    }
    for name in candidates[kind]:
        if name in da.coords:
            return name
    for dim in da.dims:
        if dim.lower() in candidates[kind]:
            return dim
    raise ValueError(f"Cannot find {kind} coordinate on DataArray with coords {list(da.coords)}")


def _regrid_2d(
    source_vals: np.ndarray,
    src_lat: np.ndarray,
    src_lon: np.ndarray,
    tgt_lat: np.ndarray,
    tgt_lon: np.ndarray,
    method: str,
) -> np.ndarray:
    """Core 2-D regridding implementation."""
    if method == "bilinear":
        return _regrid_bilinear(source_vals, src_lat, src_lon, tgt_lat, tgt_lon)
    if method == "nearest":
        return _regrid_nearest(source_vals, src_lat, src_lon, tgt_lat, tgt_lon)
    if method == "conservative":
        return _regrid_conservative(source_vals, src_lat, src_lon, tgt_lat, tgt_lon)
    raise ValueError(f"Unknown method '{method}'.")


def _regrid_bilinear(
    sv: np.ndarray,
    slat: np.ndarray,
    slon: np.ndarray,
    tlat: np.ndarray,
    tlon: np.ndarray,
) -> np.ndarray:
    """Bilinear regridding using sorted source coordinates."""
    inc_lat = slat[0] < slat[-1]
    inc_lon = slon[0] < slon[-1]

    s_lat = slat if inc_lat else slat[::-1]
    s_lon = slon if inc_lon else slon[::-1]
    s_vals = sv if (inc_lat and inc_lon) else (sv if inc_lat else sv[::-1, :])
    s_vals = s_vals if inc_lon else s_vals[:, ::-1]

    dlat = float(np.abs(np.diff(s_lat).mean())) if len(s_lat) > 1 else 1.0
    dlon = float(np.abs(np.diff(s_lon).mean())) if len(s_lon) > 1 else 1.0

    tgt_lat_b, tgt_lon_b = np.meshgrid(tlat, tlon, indexing="ij")

    fi = (tgt_lat_b - s_lat[0]) / dlat
    fj = (tgt_lon_b - s_lon[0]) / dlon

    i0 = np.clip(np.floor(fi).astype(np.intp), 0, len(s_lat) - 2)
    j0 = np.clip(np.floor(fj).astype(np.intp), 0, len(s_lon) - 2)
    i1 = i0 + 1
    j1 = j0 + 1

    wi = np.clip(fi - i0.astype(np.float64), 0, 1)
    wj = np.clip(fj - j0.astype(np.float64), 0, 1)

    result = (
        s_vals[i0, j0] * (1 - wi) * (1 - wj)
        + s_vals[i1, j0] * wi * (1 - wj)
        + s_vals[i0, j1] * (1 - wi) * wj
        + s_vals[i1, j1] * wi * wj
    )

    valid_mask = (fi >= 0) & (fi <= len(s_lat) - 1) & (fj >= 0) & (fj <= len(s_lon) - 1)
    result[~valid_mask] = np.nan

    all_nan = (
        np.isnan(s_vals[i0, j0])
        & np.isnan(s_vals[i1, j0])
        & np.isnan(s_vals[i0, j1])
        & np.isnan(s_vals[i1, j1])
    )
    result[all_nan] = np.nan

    return result


def _regrid_nearest(
    sv: np.ndarray,
    slat: np.ndarray,
    slon: np.ndarray,
    tlat: np.ndarray,
    tlon: np.ndarray,
) -> np.ndarray:
    """Nearest-neighbour regridding."""
    n_tlat = len(tlat)
    n_tlon = len(tlon)

    i_idx = np.abs(slat[:, None] - tlat.ravel()[None, :]).argmin(axis=0)
    j_idx = np.abs(slon[:, None] - tlon.ravel()[None, :]).argmin(axis=0)

    i_2d = i_idx.reshape(n_tlat, 1)
    j_2d = j_idx.reshape(1, n_tlon)

    return sv[i_2d, j_2d]


def _regrid_conservative(
    sv: np.ndarray,
    slat: np.ndarray,
    slon: np.ndarray,
    tlat: np.ndarray,
    tlon: np.ndarray,
) -> np.ndarray:
    """Conservative (area-weighted) regridding.

    Computes the overlap fraction between each source and target cell and
    uses those fractions as weights.  This preserves spatial integrals and
    is the standard for flux quantities (precipitation, radiation, etc.).
    """
    n_tgt_lat = len(tlat)
    n_tgt_lon = len(tlon)
    n_src_lat = len(slat)
    n_src_lon = len(slon)

    result = np.full((n_tgt_lat, n_tgt_lon), np.nan, dtype=np.float64)

    src_dlat = float(np.abs(np.diff(slat).mean())) if n_src_lat > 1 else 1.0
    src_dlon = float(np.abs(np.diff(slon).mean())) if n_src_lon > 1 else 1.0

    tgt_dlat = float(np.abs(np.diff(tlat).mean())) if n_tgt_lat > 1 else 1.0
    tgt_dlon = float(np.abs(np.diff(tlon).mean())) if n_tgt_lon > 1 else 1.0

    src_lat_edges_lo = slat - src_dlat / 2
    src_lat_edges_hi = slat + src_dlat / 2
    src_lon_edges_lo = slon - src_dlon / 2
    src_lon_edges_hi = slon + src_dlon / 2

    tgt_lat_edges_lo = tlat - tgt_dlat / 2
    tgt_lat_edges_hi = tlat + tgt_dlat / 2
    tgt_lon_edges_lo = tlon - tgt_dlon / 2
    tgt_lon_edges_hi = tlon + tgt_dlon / 2

    cos_lat_src = np.cos(np.radians(slat))

    lat_overlap = np.maximum(
        0,
        np.minimum(src_lat_edges_hi[:, None], tgt_lat_edges_hi[None, :])
        - np.maximum(src_lat_edges_lo[:, None], tgt_lat_edges_lo[None, :]),
    )

    lon_overlap = np.maximum(
        0,
        np.minimum(src_lon_edges_hi[:, None], tgt_lon_edges_hi[None, :])
        - np.maximum(src_lon_edges_lo[:, None], tgt_lon_edges_lo[None, :]),
    )

    for ti in range(n_tgt_lat):
        for tj in range(n_tgt_lon):
            lat_w = lat_overlap[:, ti] / tgt_dlat
            lon_w = lon_overlap[:, tj] / tgt_dlon
            weights = np.outer(lat_w, lon_w) * cos_lat_src[:, None]
            valid = ~np.isnan(sv) & (weights > 0)
            total_w = weights[valid].sum()
            if total_w > 0:
                result[ti, tj] = (sv[valid] * weights[valid]).sum() / total_w

    return result
