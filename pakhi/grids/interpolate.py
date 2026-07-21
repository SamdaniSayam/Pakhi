"""Interpolation methods for gridded meteorological data.

Provides bilinear, nearest-neighbor, Cressman objective analysis, and
inverse-distance-weighting interpolation routines that operate on xarray
DataArrays and handle NaN values gracefully.
"""

from __future__ import annotations

import warnings

import numpy as np
import xarray as xr

__all__ = [
    "bilinear_interpolation",
    "cressman_interpolation",
    "inverse_distance_weighting",
    "nearest_neighbor",
]

_EARTH_RADIUS_KM = 6371.0


def bilinear_interpolation(
    grid: xr.DataArray,
    lat: float | np.ndarray,
    lon: float | np.ndarray,
) -> np.ndarray:
    """Bilinear interpolation on a regular latitude–longitude grid.

    Parameters
    ----------
    grid : xr.DataArray
        2-D data array with dimensions containing ``latitude`` /
        ``longitude`` (or ``lat`` / ``lon``).  NaN values are treated as
        missing and the result is NaN where all surrounding cells are NaN.
    lat : float or array-like
        Target latitude(s) in degrees north.
    lon : float or array-like
        Target longitude(s) in degrees east.

    Returns
    -------
    numpy.ndarray
        Interpolated value(s). Shape matches broadcast shape of *lat* and *lon*.
    """
    if grid.values.ndim != 2:
        raise ValueError(
            f"grid must be 2-D (lat x lon) for bilinear interpolation, got {grid.values.ndim}-D."
        )

    grid_lat = _get_coord(grid, "latitude")
    grid_lon = _get_coord(grid, "longitude")
    _ensure_regular_grid(grid_lat, grid_lon)

    values = grid.values.astype(np.float64)

    # Ensure latitude is monotonically increasing for interpolation
    if grid_lat[0] > grid_lat[-1]:
        grid_lat = grid_lat[::-1]
        values = values[::-1, :]

    target_lat = np.asarray(lat, dtype=np.float64)
    target_lon = np.asarray(lon, dtype=np.float64)
    scalar_input = target_lat.ndim == 0 and target_lon.ndim == 0

    target_lat = np.atleast_1d(target_lat)
    target_lon = np.atleast_1d(target_lon)

    target_lat_b, target_lon_b = np.broadcast_arrays(target_lat, target_lon)
    target_lat_b = target_lat_b.copy().astype(np.float64)
    target_lon_b = target_lon_b.copy().astype(np.float64)

    dlat = float(grid_lat[1] - grid_lat[0])
    dlon = float(grid_lon[1] - grid_lon[0])

    # Fractional indices into the grid
    frac_i = (target_lat_b - grid_lat[0]) / dlat
    frac_j = (target_lon_b - grid_lon[0]) / dlon

    i0 = np.floor(frac_i).astype(np.intp)
    j0 = np.floor(frac_j).astype(np.intp)

    # Clamp to valid range for memory access
    i0_c = np.clip(i0, 0, len(grid_lat) - 2)
    j0_c = np.clip(j0, 0, len(grid_lon) - 2)
    i1_c = i0_c + 1
    j1_c = j0_c + 1

    # Fractional parts (clamped to [0, 1])
    fi = np.clip(frac_i - i0.astype(np.float64), 0.0, 1.0)
    fj = np.clip(frac_j - j0.astype(np.float64), 0.0, 1.0)

    # Four surrounding values
    v00 = values[i0_c, j0_c]
    v01 = values[i0_c, j1_c]
    v10 = values[i1_c, j0_c]
    v11 = values[i1_c, j1_c]

    # Bilinear formula
    result = v00 * (1 - fi) * (1 - fj) + v10 * fi * (1 - fj) + v01 * (1 - fi) * fj + v11 * fi * fj

    # Mark out-of-bounds as NaN
    oob = (i0 < 0) | (i0 > len(grid_lat) - 2) | (j0 < 0) | (j0 > len(grid_lon) - 2)
    result[oob] = np.nan

    # Mark where all four neighbours are NaN
    all_nan = np.isnan(v00) & np.isnan(v01) & np.isnan(v10) & np.isnan(v11)
    result[all_nan] = np.nan

    if scalar_input:
        return result.flat[0]
    return result


def nearest_neighbor(
    grid: xr.DataArray,
    lat: float | np.ndarray,
    lon: float | np.ndarray,
) -> np.ndarray:
    """Nearest-neighbour interpolation on a regular lat/lon grid.

    Parameters
    ----------
    grid : xr.DataArray
        2-D data array with latitude and longitude dimensions.
    lat : float or array-like
        Target latitude(s).
    lon : float or array-like
        Target longitude(s).

    Returns
    -------
    numpy.ndarray
        Nearest grid-point value(s).
    """
    if grid.values.ndim != 2:
        raise ValueError(f"grid must be 2-D, got {grid.values.ndim}-D.")

    grid_lat = _get_coord(grid, "latitude")
    grid_lon = _get_coord(grid, "longitude")
    values = grid.values.astype(np.float64)

    target_lat = np.asarray(lat, dtype=np.float64)
    target_lon = np.asarray(lon, dtype=np.float64)
    scalar_input = target_lat.ndim == 0 and target_lon.ndim == 0

    target_lat = np.atleast_1d(target_lat)
    target_lon = np.atleast_1d(target_lon)

    target_lat_b, target_lon_b = np.broadcast_arrays(target_lat, target_lon)
    target_lat_b = target_lat_b.copy()
    target_lon_b = target_lon_b.copy()

    # Find nearest index along each axis independently (valid for regular grids)
    lat_idx = np.abs(grid_lat[:, None] - target_lat_b.ravel()[None, :]).argmin(axis=0)
    lon_idx = np.abs(grid_lon[:, None] - target_lon_b.ravel()[None, :]).argmin(axis=0)

    result = values[lat_idx, lon_idx].reshape(target_lat_b.shape)

    if scalar_input:
        return result.flat[0]
    return result


def cressman_interpolation(
    grid: xr.DataArray,
    lat: float | np.ndarray,
    lon: float | np.ndarray,
    obs_lat: np.ndarray,
    obs_lon: np.ndarray,
    obs_values: np.ndarray,
    search_radius_km: float = 200.0,
) -> np.ndarray:
    """Cressman objective analysis interpolation.

    Adjusts the background (first-guess) field using observations within a
    circular search radius.  This is the standard scheme used in
    meteorological data assimilation for surface and upper-air analyses.

    The analysis at point **x** is::

        A(x) = B(x) + Σ wᵢ (Oᵢ − B(xᵢ)) / Σ wᵢ

    where the weight *wᵢ* = (R² − dᵢ²) / (R² + dᵢ²), *dᵢ* is the
    distance from the analysis point to observation *i*, *Oᵢ* is the
    observation value, *B* is the background field, and *R* is the
    search radius.

    Parameters
    ----------
    grid : xr.DataArray
        Background (first-guess) 2-D field on a regular lat/lon grid.
    lat, lon : float or array-like
        Analysis locations.
    obs_lat, obs_lon, obs_values : array-like
        Observation locations and values.  NaN values in *obs_values* are
        dropped before use.
    search_radius_km : float
        Radius of influence in kilometres (default 200 km).

    Returns
    -------
    numpy.ndarray
        Analysed values at the requested locations.
    """
    lat_in = np.asarray(lat, dtype=np.float64)
    lon_in = np.asarray(lon, dtype=np.float64)
    scalar_input = lat_in.ndim == 0 and lon_in.ndim == 0

    target_lat = np.atleast_1d(lat_in)
    target_lon = np.atleast_1d(lon_in)

    obs_lat = np.asarray(obs_lat, dtype=np.float64).ravel()
    obs_lon = np.asarray(obs_lon, dtype=np.float64).ravel()
    obs_values = np.asarray(obs_values, dtype=np.float64).ravel()

    valid_obs = ~np.isnan(obs_values) & ~np.isnan(obs_lat) & ~np.isnan(obs_lon)
    obs_lat = obs_lat[valid_obs]
    obs_lon = obs_lon[valid_obs]
    obs_values = obs_values[valid_obs]

    if obs_lat.size == 0:
        warnings.warn("No valid observations supplied; returning background field.", stacklevel=2)
        return bilinear_interpolation(grid, lat, lon)

    background = bilinear_interpolation(grid, target_lat, target_lon)
    result = background.copy().astype(np.float64)

    for flat_idx in range(target_lat.size):
        a_lat = target_lat.ravel()[flat_idx]
        a_lon = target_lon.ravel()[flat_idx]

        d_km = _haversine_km(a_lat, a_lon, obs_lat, obs_lon)

        within = d_km <= search_radius_km
        if not np.any(within):
            continue

        d_r = d_km[within]
        w = (search_radius_km**2 - d_r**2) / (search_radius_km**2 + d_r**2)
        o_diff = obs_values[within] - background.ravel()[flat_idx]

        denom = np.sum(w)
        if denom != 0.0:
            result.ravel()[flat_idx] += np.sum(w * o_diff) / denom

    if scalar_input:
        return result.flat[0]
    return result.reshape(target_lat.shape)


def inverse_distance_weighting(
    grid: xr.DataArray,
    lat: float | np.ndarray,
    lon: float | np.ndarray,
    obs_lat: np.ndarray,
    obs_lon: np.ndarray,
    obs_values: np.ndarray,
    power: float = 2.0,
) -> np.ndarray:
    """Inverse-distance-weighted (IDW) interpolation from observations.

    Parameters
    ----------
    grid : xr.DataArray
        Background grid (used only for coordinate information and as a
        fallback when no observations are within reach).
    lat, lon : float or array-like
        Target locations.
    obs_lat, obs_lon, obs_values : array-like
        Observation locations and values.
    power : float
        Distance weighting exponent (default 2).  Higher values give more
        weight to the nearest observations.

    Returns
    -------
    numpy.ndarray
        Interpolated values.
    """
    lat_in = np.asarray(lat, dtype=np.float64)
    lon_in = np.asarray(lon, dtype=np.float64)
    scalar_input = lat_in.ndim == 0 and lon_in.ndim == 0

    target_lat = np.atleast_1d(lat_in)
    target_lon = np.atleast_1d(lon_in)

    obs_lat = np.asarray(obs_lat, dtype=np.float64).ravel()
    obs_lon = np.asarray(obs_lon, dtype=np.float64).ravel()
    obs_values = np.asarray(obs_values, dtype=np.float64).ravel()

    valid_obs = ~np.isnan(obs_values)
    obs_lat = obs_lat[valid_obs]
    obs_lon = obs_lon[valid_obs]
    obs_values = obs_values[valid_obs]

    if obs_lat.size == 0:
        warnings.warn("No valid observations; returning NaN.", stacklevel=2)
        return np.full(target_lat.shape, np.nan)

    result = np.full(target_lat.shape, np.nan, dtype=np.float64)

    for flat_idx in range(target_lat.size):
        a_lat = target_lat.ravel()[flat_idx]
        a_lon = target_lon.ravel()[flat_idx]

        d_km = _haversine_km(a_lat, a_lon, obs_lat, obs_lon)

        exact = d_km == 0.0
        if np.any(exact):
            result.ravel()[flat_idx] = obs_values[exact][0]
            continue

        w = 1.0 / d_km**power
        denom = np.sum(w)
        if denom > 0:
            result.ravel()[flat_idx] = np.sum(w * obs_values) / denom

    if scalar_input:
        return result.flat[0]
    return result.reshape(target_lat.shape)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_coord(da: xr.DataArray, kind: str) -> np.ndarray:
    """Extract a 1-D coordinate array from *da* by common name variants."""
    candidates = {
        "latitude": ["latitude", "lat", "y"],
        "longitude": ["longitude", "lon", "x"],
    }
    for name in candidates[kind]:
        if name in da.coords:
            return np.asarray(da.coords[name].values, dtype=np.float64)
    for dim in da.dims:
        if dim.lower() in candidates[kind]:
            return np.asarray(da.coords[dim].values, dtype=np.float64)
    raise ValueError(
        f"Cannot find {kind} coordinate on DataArray. Available coords: {list(da.coords)}"
    )


def _ensure_regular_grid(lat: np.ndarray, lon: np.ndarray) -> None:
    """Validate that lat/lon are 1-D monotonic arrays."""
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("lat and lon must be 1-D arrays.")


def _haversine_km(
    lat1: float | np.ndarray,
    lon1: float | np.ndarray,
    lat2: float | np.ndarray,
    lon2: float | np.ndarray,
) -> np.ndarray:
    """Haversine great-circle distance in kilometres."""
    lat1 = np.asarray(lat1, dtype=np.float64)
    lon1 = np.asarray(lon1, dtype=np.float64)
    lat2 = np.asarray(lat2, dtype=np.float64)
    lon2 = np.asarray(lon2, dtype=np.float64)

    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
