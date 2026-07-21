"""Spatial subsetting operations for gridded data.

Provides routines to extract subsets of gridded meteorological data by
bounding box, polygon, circular neighbourhood, or country boundary.
"""

from __future__ import annotations

import warnings

import numpy as np
import xarray as xr

__all__ = [
    "subset_bbox",
    "subset_country",
    "subset_point",
    "subset_polygon",
]

_EARTH_RADIUS_KM = 6371.0


def subset_bbox(
    data: xr.DataArray,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> xr.DataArray:
    """Extract a rectangular bounding-box subset.

    Parameters
    ----------
    data : xr.DataArray
        Data with ``latitude`` and ``longitude`` coordinates.
    lat_min, lat_max : float
        Southern and northern bounds (degrees north).
    lon_min, lon_max : float
        Western and eastern bounds (degrees east).

    Returns
    -------
    xr.DataArray
        Subsetted data.  If the bounding box extends beyond the grid the
        result is clipped to the available range.
    """
    lat_name = _find_coord(data, "latitude")
    lon_name = _find_coord(data, "longitude")

    lat_vals = np.asarray(data.coords[lat_name].values, dtype=np.float64)
    lon_vals = np.asarray(data.coords[lon_name].values, dtype=np.float64)

    lat_mask = (lat_vals >= lat_min) & (lat_vals <= lat_max)
    lon_mask = (lon_vals >= lon_min) & (lon_vals <= lon_max)

    if not np.any(lat_mask):
        warnings.warn(
            f"No latitude values in [{lat_min}, {lat_max}]. "
            f"Data range: [{lat_vals.min()}, {lat_vals.max()}].",
            stacklevel=2,
        )
    if not np.any(lon_mask):
        warnings.warn(
            f"No longitude values in [{lon_min}, {lon_max}]. "
            f"Data range: [{lon_vals.min()}, {lon_vals.max()}].",
            stacklevel=2,
        )

    subset = data.sel({lat_name: lat_vals[lat_mask], lon_name: lon_vals[lon_mask]})
    return subset


def subset_polygon(
    data: xr.DataArray,
    polygon_lat: np.ndarray,
    polygon_lon: np.ndarray,
) -> xr.DataArray:
    """Extract grid points falling inside an arbitrary polygon.

    Uses a ray-casting point-in-polygon test so no external geometry
    library is required.

    Parameters
    ----------
    data : xr.DataArray
        Data with latitude/longitude coordinates.
    polygon_lat, polygon_lon : array-like
        Vertices of the polygon (need not be closed; the function closes
        the loop automatically).

    Returns
    -------
    xr.DataArray
        Only grid points whose centres lie inside the polygon are retained.
        Other grid points are set to NaN.
    """
    lat_name = _find_coord(data, "latitude")
    lon_name = _find_coord(data, "longitude")

    poly_lat = np.asarray(polygon_lat, dtype=np.float64).ravel()
    poly_lon = np.asarray(polygon_lon, dtype=np.float64).ravel()

    if poly_lat.size < 3:
        raise ValueError("Polygon needs at least 3 vertices.")

    if poly_lat[0] != poly_lat[-1] or poly_lon[0] != poly_lon[-1]:
        poly_lat = np.append(poly_lat, poly_lat[0])
        poly_lon = np.append(poly_lon, poly_lon[0])

    lat_vals = np.asarray(data.coords[lat_name].values, dtype=np.float64)
    lon_vals = np.asarray(data.coords[lon_name].values, dtype=np.float64)

    lon_grid, lat_grid = np.meshgrid(lon_vals, lat_vals)
    inside = _point_in_polygon(lat_grid.ravel(), lon_grid.ravel(), poly_lat, poly_lon)
    mask = inside.reshape(lat_grid.shape)

    result = data.copy()
    result_values = result.values.astype(np.float64)
    if result_values.ndim == 2:
        result_values[~mask] = np.nan
    elif result_values.ndim == 3:
        result_values[:, ~mask] = np.nan
    else:
        raise NotImplementedError(f"Cannot subset {result_values.ndim}-D array with polygon mask.")

    result.data = result_values
    return result


def subset_point(
    data: xr.DataArray,
    lat: float,
    lon: float,
    radius_km: float = 50.0,
) -> xr.DataArray:
    """Extract grid points within *radius_km* of a given location.

    The nearest grid point is always included even if it falls slightly
    outside the radius.

    Parameters
    ----------
    data : xr.DataArray
        Data with latitude/longitude coordinates.
    lat, lon : float
        Centre point in degrees.
    radius_km : float
        Search radius in kilometres (default 50 km).

    Returns
    -------
    xr.DataArray
        Masked copy of *data* where points outside the radius are NaN.
    """
    lat_name = _find_coord(data, "latitude")
    lon_name = _find_coord(data, "longitude")

    lat_vals = np.asarray(data.coords[lat_name].values, dtype=np.float64)
    lon_vals = np.asarray(data.coords[lon_name].values, dtype=np.float64)

    lon_grid, lat_grid = np.meshgrid(lon_vals, lat_vals)
    d_km = _haversine_km(lat, lon, lat_grid.ravel(), lon_grid.ravel())
    d_km = d_km.reshape(lat_grid.shape)

    mask = d_km <= radius_km

    nearest_i, nearest_j = np.unravel_index(np.argmin(d_km), d_km.shape)
    mask[nearest_i, nearest_j] = True

    result = data.copy()
    result_values = result.values.astype(np.float64)

    if result_values.ndim == 2:
        result_values[~mask] = np.nan
    elif result_values.ndim == 3:
        result_values[:, ~mask] = np.nan
    else:
        raise NotImplementedError(f"Cannot subset {result_values.ndim}-D array with point mask.")

    result.data = result_values
    return result


def subset_country(
    data: xr.DataArray,
    country_code: str,
) -> xr.DataArray:
    """Mask data to an approximate country boundary by ISO 3166-1 alpha-2 code.

    This uses a lightweight built-in lookup table of bounding boxes for
    major countries.  For full polygon boundaries, supply a shapefile to
    :func:`subset_polygon` instead.

    Parameters
    ----------
    data : xr.DataArray
        Data with latitude/longitude coordinates.
    country_code : str
        Two-letter ISO country code (e.g. ``"US"``, ``"IN"``, ``"BR"``).

    Returns
    -------
    xr.DataArray
        Data outside the country bounding box is set to NaN.
    """
    code = country_code.upper().strip()
    bbox = _COUNTRY_BBOX.get(code)
    if bbox is None:
        available = sorted(_COUNTRY_BBOX.keys())
        raise ValueError(
            f"Country code '{country_code}' not in built-in lookup. "
            f"Available codes: {available}. "
            "Use subset_polygon() with a shapefile for precise boundaries."
        )

    lat_min, lat_max, lon_min, lon_max = bbox
    subset = subset_bbox(data, lat_min, lat_max, lon_min, lon_max)

    mask = _get_country_mask(subset, lat_min, lat_max, lon_min, lon_max, code)
    result = subset.copy()
    result_values = result.values.astype(np.float64)

    if result_values.ndim == 2:
        result_values[~mask] = np.nan
    elif result_values.ndim == 3:
        result_values[:, ~mask] = np.nan

    result.data = result_values
    result.attrs["country_code"] = code
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_coord(da: xr.DataArray, kind: str) -> str:
    """Return the actual coordinate name for *kind* (latitude / longitude)."""
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


def _haversine_km(
    lat1: float | np.ndarray,
    lon1: float | np.ndarray,
    lat2: float | np.ndarray,
    lon2: float | np.ndarray,
) -> np.ndarray:
    """Haversine great-circle distance in km."""
    lat1 = np.asarray(lat1, dtype=np.float64)
    lon1 = np.asarray(lon1, dtype=np.float64)
    lat2 = np.asarray(lat2, dtype=np.float64)
    lon2 = np.asarray(lon2, dtype=np.float64)

    lat1_r, lat2_r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _point_in_polygon(
    test_lat: np.ndarray,
    test_lon: np.ndarray,
    poly_lat: np.ndarray,
    poly_lon: np.ndarray,
) -> np.ndarray:
    """Ray-casting point-in-polygon test for arrays of points."""
    n = len(poly_lat) - 1
    inside = np.zeros(test_lat.shape, dtype=bool)

    for i in range(n):
        lat_i, lat_j = poly_lat[i], poly_lat[i + 1]
        lon_i, lon_j = poly_lon[i], poly_lon[i + 1]

        cond = (lat_i > test_lat) != (lat_j > test_lat)
        denom = lat_j - lat_i
        if denom == 0:
            continue
        x_intersect = lon_i + (test_lat - lat_i) * (lon_j - lon_i) / denom
        crosses = cond & (test_lon < x_intersect)
        inside ^= crosses

    return inside


def _get_country_mask(
    data: xr.DataArray,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    country_code: str,
) -> np.ndarray:
    """Build a boolean mask keeping the bounding-box region.

    For more precision one could load a Natural Earth shapefile, but for
    the built-in lookup table the bounding-box is a reasonable
    approximation.  The mask returned is simply *all True* inside the
    already-subsetted region.
    """
    lat_name = _find_coord(data, "latitude")
    lon_name = _find_coord(data, "longitude")
    lat_vals = np.asarray(data.coords[lat_name].values, dtype=np.float64)
    lon_vals = np.asarray(data.coords[lon_name].values, dtype=np.float64)

    lon_grid, lat_grid = np.meshgrid(lon_vals, lat_vals)

    mask = (
        (lat_grid >= lat_min)
        & (lat_grid <= lat_max)
        & (lon_grid >= lon_min)
        & (lon_grid <= lon_max)
    )
    return mask


# ---------------------------------------------------------------------------
# Built-in bounding-box lookup (approximate)
# ---------------------------------------------------------------------------

_COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "AF": (29.4, 38.5, 60.5, 74.9),
    "AL": (39.6, 42.7, 19.3, 21.1),
    "DZ": (19.0, 37.1, -8.7, 11.9),
    "AR": (-55.1, -21.8, -73.6, -53.6),
    "AU": (-44.0, -10.0, 112.9, 154.3),
    "AT": (46.4, 49.0, 9.5, 17.2),
    "BD": (20.6, 26.6, 88.0, 92.7),
    "BE": (49.5, 51.5, 2.5, 6.4),
    "BR": (-33.8, 5.3, -74.0, -34.8),
    "CA": (41.7, 83.1, -141.0, -52.6),
    "CL": (-56.0, -17.5, -75.6, -66.9),
    "CN": (18.2, 53.6, 73.6, 134.8),
    "CO": (-4.2, 12.5, -79.0, -66.9),
    "HR": (42.4, 46.6, 13.5, 19.4),
    "CZ": (48.6, 51.1, 12.1, 18.9),
    "DK": (54.6, 57.8, 8.1, 15.2),
    "EG": (22.0, 31.7, 24.7, 37.0),
    "FI": (59.8, 70.1, 20.5, 31.6),
    "FR": (42.3, 51.1, -5.1, 9.6),
    "DE": (47.3, 55.1, 5.9, 15.0),
    "GR": (34.8, 41.7, 19.4, 29.7),
    "HU": (45.7, 48.6, 16.1, 22.9),
    "IS": (63.3, 66.6, -24.5, -13.5),
    "IN": (6.8, 35.5, 68.2, 97.4),
    "ID": (-11.0, 5.9, 95.0, 141.0),
    "IR": (25.1, 39.8, 44.1, 63.3),
    "IQ": (29.1, 37.4, 38.8, 48.6),
    "IE": (51.4, 55.4, -10.5, -6.0),
    "IL": (29.5, 33.3, 34.3, 35.9),
    "IT": (36.6, 47.1, 6.6, 18.5),
    "JP": (24.2, 45.5, 122.9, 154.0),
    "JO": (29.2, 33.4, 34.9, 39.3),
    "KE": (-4.7, 5.0, 33.9, 41.9),
    "KR": (33.1, 38.6, 125.9, 129.6),
    "MX": (14.5, 32.7, -118.4, -86.7),
    "MA": (27.7, 35.9, -13.2, -0.6),
    "NL": (50.8, 53.7, 3.4, 7.2),
    "NZ": (-47.3, -34.4, 165.8, 178.6),
    "NG": (4.3, 13.9, 2.7, 14.7),
    "NO": (58.0, 71.2, 4.6, 31.1),
    "PK": (23.7, 37.1, 60.9, 77.8),
    "PE": (-18.3, -0.0, -81.3, -68.7),
    "PH": (4.6, 21.1, 116.9, 127.1),
    "PL": (49.0, 54.8, 14.1, 24.2),
    "PT": (36.9, 42.2, -9.5, -6.2),
    "RO": (43.6, 48.3, 20.3, 29.7),
    "RU": (41.2, 81.8, 27.5, 169.0),
    "SA": (16.4, 32.2, 34.6, 55.7),
    "ZA": (-34.8, -22.1, 16.5, 32.9),
    "ES": (36.0, 43.8, -9.3, 4.3),
    "SE": (55.3, 69.1, 11.1, 24.2),
    "CH": (45.8, 47.8, 5.9, 10.5),
    "TW": (21.9, 25.3, 120.2, 121.9),
    "TH": (5.6, 20.5, 97.3, 105.6),
    "TR": (35.8, 42.1, 25.7, 44.8),
    "UA": (44.4, 52.4, 22.1, 40.2),
    "AE": (22.6, 26.1, 51.6, 56.4),
    "GB": (49.9, 58.7, -8.2, 1.8),
    "US": (24.5, 49.4, -125.0, -66.9),
    "VE": (0.6, 12.2, -73.4, -59.8),
    "VN": (8.5, 23.4, 102.1, 109.5),
}
