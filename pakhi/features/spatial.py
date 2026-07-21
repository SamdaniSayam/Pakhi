"""Spatial feature engineering for gridded weather data.

Provides distance-weighted interpolation, spatial gradients, wind
convergence, and approximate coastline distance calculations.
"""

from __future__ import annotations

import logging

import numpy as np
import xarray as xr

__all__ = ["SpatialFeatures"]

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6_371.0
DEG_TO_RAD = np.pi / 180.0


class SpatialFeatures:
    """Spatial feature engineering for gridded meteorological data.

    All methods operate on xarray Datasets/DataArrays with latitude
    and longitude coordinates.
    """

    __all__ = [
        "distance_weighted_average",
        "gradient",
        "convergence",
        "distance_to_coast",
    ]

    @staticmethod
    def distance_weighted_average(
        data: xr.Dataset | xr.DataArray,
        target_lat: float,
        target_lon: float,
        max_distance_km: float = 500.0,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        power: float = 2.0,
    ) -> xr.Dataset | xr.DataArray:
        """Inverse-distance-weighted average from grid points to a target location.

        Parameters
        ----------
        data : xr.Dataset or xr.DataArray
            Gridded data with latitude and longitude coordinates.
        target_lat : float
            Target latitude in degrees.
        target_lon : float
            Target longitude in degrees.
        max_distance_km : float
            Maximum distance to include (km). Grid points farther
            than this are excluded. Default 500.
        lat_dim, lon_dim : str
            Dimension/coordinate names for latitude and longitude.
        power : float
            Inverse-distance power. Default 2.0 (IDW²).

        Returns
        -------
        xr.Dataset or xr.DataArray
            Interpolated values at the target location.
        """
        lats = np.asarray(data[lat_dim].values, dtype=np.float64)
        lons = np.asarray(data[lon_dim].values, dtype=np.float64)

        lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
        distances = SpatialFeatures._haversine(lat_grid, lon_grid, target_lat, target_lon)

        mask = distances <= max_distance_km
        if not np.any(mask):
            raise ValueError(
                f"No grid points within {max_distance_km} km of ({target_lat}, {target_lon})"
            )

        weights = np.where(mask, 1.0 / np.maximum(distances, 1e-6) ** power, 0.0)
        weight_sum = weights.sum(axis=(-2, -1))

        def _weighted_sum(arr: np.ndarray) -> np.ndarray:
            return np.sum(arr * weights, axis=(-2, -1)) / np.where(
                weight_sum > 0, weight_sum, np.nan
            )

        if isinstance(data, xr.DataArray):
            return xr.apply_ufunc(
                _weighted_sum,
                data,
                input_core_dims=[[lat_dim, lon_dim]],
                output_core_dims=[[]],
                dask="parallelized",
                dask_gufunc_kwargs={"allow_rechunk": True},
            )

        result: dict[str, xr.DataArray] = {}
        for var in data.data_vars:
            result[var] = xr.apply_ufunc(
                _weighted_sum,
                data[var],
                input_core_dims=[[lat_dim, lon_dim]],
                output_core_dims=[[]],
                dask="parallelized",
                dask_gufunc_kwargs={"allow_rechunk": True},
            )
        return xr.Dataset(result)

    @staticmethod
    def gradient(
        data: xr.Dataset | xr.DataArray,
        dx_km: float | None = None,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        variable: str | None = None,
    ) -> dict[str, xr.DataArray]:
        """Compute spatial gradient (e.g. pressure gradient force).

        Parameters
        ----------
        data : xr.Dataset or xr.DataArray
            Gridded scalar field.
        dx_km : float, optional
            Grid spacing in km. If ``None``, inferred from coordinates.
        lat_dim, lon_dim : str
            Coordinate names.
        variable : str, optional
            If *data* is a Dataset, which variable to differentiate.

        Returns
        -------
        dict
            ``{"d_dx": ..., "d_dy": ..., "magnitude": ..., "direction": ...}``
        """
        if isinstance(data, xr.Dataset):
            if variable is None:
                variable = next(iter(data.data_vars))
            arr = data[variable]
        else:
            arr = data

        if dx_km is None:
            lats = np.asarray(arr[lat_dim].values, dtype=np.float64)
            lons = np.asarray(arr[lon_dim].values, dtype=np.float64)
            lat_res = abs(float(np.mean(np.diff(lats)))) * DEG_TO_RAD * EARTH_RADIUS_KM
            lon_res = abs(float(np.mean(np.diff(lons)))) * DEG_TO_RAD * EARTH_RADIUS_KM
        else:
            lat_res = dx_km
            lon_res = dx_km

        d_dx = arr.differentiate(lon_dim) / lon_res
        d_dy = arr.differentiate(lat_dim) / lat_res

        magnitude = np.sqrt(d_dx**2 + d_dy**2)
        direction = np.arctan2(d_dy, d_dx)

        return {"d_dx": d_dx, "d_dy": d_dy, "magnitude": magnitude, "direction": direction}

    @staticmethod
    def convergence(
        data: xr.Dataset,
        u_var: str = "u",
        v_var: str = "v",
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        dx_km: float | None = None,
    ) -> xr.Dataset:
        """Compute wind convergence / divergence.

        Uses the formula:  div = du/dx + dv/dy.

        Parameters
        ----------
        data : xr.Dataset
            Dataset containing *u* and *v* wind components.
        u_var, v_var : str
            Variable names for the zonal and meridional components.
        lat_dim, lon_dim : str
            Coordinate names.
        dx_km : float, optional
            Grid spacing in km. Inferred from coordinates if ``None``.

        Returns
        -------
        xr.Dataset
            Dataset with ``convergence`` and ``divergence`` variables.
        """
        u = data[u_var]
        v = data[v_var]

        if dx_km is None:
            lats = np.asarray(data[lat_dim].values, dtype=np.float64)
            lons = np.asarray(data[lon_dim].values, dtype=np.float64)
            lat_res = abs(float(np.mean(np.diff(lats)))) * DEG_TO_RAD * EARTH_RADIUS_KM
            lon_res = abs(float(np.mean(np.diff(lons)))) * DEG_TO_RAD * EARTH_RADIUS_KM
        else:
            lat_res = dx_km
            lon_res = dx_km

        du_dx = u.differentiate(lon_dim) / lon_res
        dv_dy = v.differentiate(lat_dim) / lat_res

        div = du_dx + dv_dy

        return xr.Dataset(
            {
                "divergence": div,
                "convergence": -div,
            }
        )

    @staticmethod
    def distance_to_coast(
        lat: float | np.ndarray,
        lon: float | np.ndarray,
        coastline_data: np.ndarray | None = None,
    ) -> np.ndarray:
        """Approximate distance to coastline.

        Uses a simplified coastline model. When ``coastline_data`` is
        ``None``, employs a lookup table of major continental outlines
        to estimate distance.

        Parameters
        ----------
        lat, lon : float or np.ndarray
            Point(s) to evaluate.
        coastline_data : np.ndarray, optional
            Array of shape ``(N, 2)`` with ``(lat, lon)`` coastline
            points. If ``None``, uses a basic approximation based on
            whether the point is over ocean or land using latitude
            thresholds.

        Returns
        -------
        np.ndarray
            Distance to coast in km.
        """
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        scalar_input = lat.ndim == 0

        if coastline_data is not None:
            coast = np.asarray(coastline_data, dtype=np.float64)
            min_dist = np.full_like(lat, np.inf)
            for clat, clon in coast:
                dist = SpatialFeatures._haversine(lat, lon, clat, clon)
                min_dist = np.minimum(min_dist, dist)
            if scalar_input:
                return float(min_dist)
            return min_dist

        land_mask = SpatialFeatures._approx_land_mask(lat, lon)
        dist = np.where(land_mask, 0.0, SpatialFeatures._approx_ocean_distance(lat, lon))
        if scalar_input:
            return float(dist)
        return dist

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _haversine(
        lat1: float | np.ndarray,
        lon1: float | np.ndarray,
        lat2: float,
        lon2: float,
    ) -> np.ndarray:
        lat1 = np.asarray(lat1, dtype=np.float64) * DEG_TO_RAD
        lon1 = np.asarray(lon1, dtype=np.float64) * DEG_TO_RAD
        lat2 = float(lat2) * DEG_TO_RAD
        lon2 = float(lon2) * DEG_TO_RAD

        dlat = lat1 - lat2
        dlon = lon1 - lon2

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        return EARTH_RADIUS_KM * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(1.0 - a, 0.0)))

    @staticmethod
    def _approx_land_mask(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        mask = np.zeros_like(lat, dtype=bool)
        mask |= (lat > 15) & (lat < 72) & (lon > -130) & (lon < -60)
        mask |= (lat > 25) & (lat < 50) & (lon > -10) & (lon < 40)
        mask |= (lat > -40) & (lat < 15) & (lon > -20) & (lon < 55)
        mask |= (lat > -10) & (lat < 20) & (lon > 95) & (lon < 140)
        mask |= (lat > 20) & (lat < 55) & (lon > 60) & (lon < 145)
        mask |= (lat > -45) & (lat < -10) & (lon > 110) & (lon < 155)
        mask |= (lat > -5) & (lat < 10) & (lon > -85) & (lon < -60)
        return mask

    @staticmethod
    def _approx_ocean_distance(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        coast_lats = np.array(
            [
                35.0,
                40.0,
                45.0,
                50.0,
                55.0,
                60.0,
                25.0,
                30.0,
                35.0,
                40.0,
            ]
        )
        coast_lons = np.array(
            [
                -75.0,
                -70.0,
                -65.0,
                -55.0,
                -50.0,
                -40.0,
                10.0,
                10.0,
                10.0,
                10.0,
            ]
        )
        min_dist = np.full_like(lat, 99999.0)
        for clat, clon in zip(coast_lats, coast_lons, strict=False):
            dist = SpatialFeatures._haversine(lat, lon, float(clat), float(clon))
            min_dist = np.minimum(min_dist, dist)
        return np.clip(min_dist, 0, 1000.0)
