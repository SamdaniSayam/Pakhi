"""ERA5 reanalysis data connector via the Copernicus CDS API or Google Zarr.

Downloads ERA5 single-level and pressure-level data, supports lazy
Dask loading for large date ranges, and returns xarray Datasets.

Two data sources are supported:
1. CDS API (requires API key) — traditional download method
2. Google Cloud Zarr mirror — cloud-optimized, no API key needed

Example:
    >>> from pakhi.src.era5 import ERA5Connector
    >>> era5 = ERA5Connector(variables=["temperature_2m", "msl"])
    >>> ds = era5.fetch(start="2020-01-01", end="2020-12-31")
    >>> # Or use Google Zarr (no API key needed):
    >>> ds = era5.fetch_zarr(start="2020-01-01", end="2020-12-31")
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import xarray as xr

__all__ = ["ERA5Connector"]

logger = logging.getLogger(__name__)

ERA5_SINGLE_LEVEL_VARS: dict[str, str] = {
    "temperature_2m": "2m_temperature",
    "msl": "mean_sea_level_pressure",
    "wind_10m_u": "10m_u_component_of_wind",
    "wind_10m_v": "10m_v_component_of_wind",
    "wind_speed_10m": "10m_wind_speed",
    "precipitation": "total_precipitation",
    "specific_humidity": "specific_humidity",
    "cloud_cover": "total_cloud_cover",
    "surface_pressure": "surface_pressure",
    "soil_temperature_1": "soil_temperature_level_1",
    "snow_depth": "snow_depth",
    "visibility": "visibility",
}

ERA5_PRESSURE_LEVEL_VARS: dict[str, str] = {
    "temperature": "temperature",
    "geopotential": "geopotential",
    "wind_u": "u_component_of_wind",
    "wind_v": "v_component_of_wind",
    "specific_humidity": "specific_humidity",
    "relative_humidity": "relative_humidity",
    "vertical_velocity": "vertical_velocity",
}

ERA5_PRESSURE_LEVELS = [
    1,
    2,
    3,
    5,
    7,
    10,
    20,
    30,
    50,
    70,
    100,
    125,
    150,
    175,
    200,
    225,
    250,
    300,
    350,
    400,
    450,
    500,
    550,
    600,
    650,
    700,
    750,
    775,
    800,
    825,
    850,
    875,
    900,
    925,
    950,
    975,
    1000,
]


class ERA5Connector:
    """Connector for ERA5 reanalysis data via the CDS API.

    Supports both single-level and pressure-level ERA5 products with
    lazy Dask-backed loading for memory-efficient processing.

    Args:
        variables: Variable names — keys from ERA5_SINGLE_LEVEL_VARS
                   or ERA5_PRESSURE_LEVEL_VARS.
        pressure_levels: Pressure levels in hPa (only for pressure-level vars).
        product_type: "reanalysis" for standard ERA5.
        area: Bounding box [north, west, south, east] (CDS order).
        cache_dir: Directory for CDS downloads.
        chunks: Dask chunk specification, e.g. {"time": 365}.
        timeout: CDS API request timeout in seconds.

    Example:
        >>> era5 = ERA5Connector(
        ...     variables=["temperature_2m", "msl"],
        ...     area=[50, -125, 24, -66],
        ... )
        >>> ds = era5.fetch(start="2020-01-01", end="2020-12-31")
    """

    def __init__(
        self,
        variables: list[str] | None = None,
        pressure_levels: list[int] | None = None,
        product_type: str = "reanalysis",
        area: list[float] | None = None,
        cache_dir: str | Path | None = None,
        chunks: dict[str, int] | None = None,
        timeout: int = 600,
    ) -> None:
        if variables is None:
            variables = ["temperature_2m", "msl"]

        self.single_level_vars: list[str] = []
        self.pressure_level_vars: list[str] = []
        self._validate_variables(variables)
        self.variables = variables

        self.pressure_levels = pressure_levels or [500, 850]
        for pl in self.pressure_levels:
            if pl not in ERA5_PRESSURE_LEVELS:
                raise ValueError(f"Pressure level {pl} hPa not in standard ERA5 levels.")
        self.product_type = product_type
        self.area = area  # [N, W, S, E] — CDS convention
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "pakhi" / "era5"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.chunks = chunks or {"time": 365}
        self.timeout = timeout
        self._cds_client: Any | None = None

    def _validate_variables(self, variables: list[str]) -> None:
        """Classify variables into single-level and pressure-level."""
        for v in variables:
            if v in ERA5_SINGLE_LEVEL_VARS:
                self.single_level_vars.append(v)
            elif v in ERA5_PRESSURE_LEVEL_VARS:
                self.pressure_level_vars.append(v)
            else:
                raise ValueError(
                    f"Unknown ERA5 variable '{v}'. "
                    f"Single-level: {sorted(ERA5_SINGLE_LEVEL_VARS.keys())}. "
                    f"Pressure-level: {sorted(ERA5_PRESSURE_LEVEL_VARS.keys())}."
                )

    def _get_cds_client(self) -> Any:
        """Initialize the CDS API client (lazy import)."""
        if self._cds_client is not None:
            return self._cds_client
        try:
            import cdsapi
        except ImportError as exc:
            raise ImportError(
                "cdsapi is required for ERA5 access. Install with: pip install cdsapi"
            ) from exc

        url = os.environ.get("CDS_URL", "https://cds.climate.copernicus.eu/api/v2")
        key = os.environ.get("CDS_KEY", "")
        if not key:
            cdsrc = Path.home() / ".cdsapirc"
            if cdsrc.exists():
                logger.debug("Using CDS credentials from %s", cdsrc)

        self._cds_client = cdsapi.Client(url=url, key=key, timeout=self.timeout)
        return self._cds_client

    def _build_single_level_request(
        self,
        variables: list[str],
        dates: list[str],
    ) -> dict[str, Any]:
        """Build a CDS API request dict for single-level data."""
        cds_vars = [ERA5_SINGLE_LEVEL_VARS[v] for v in variables]
        request: dict[str, Any] = {
            "product_type": self.product_type,
            "variable": cds_vars,
            "year": sorted({d[:4] for d in dates}),
            "month": sorted({d[5:7] for d in dates}),
            "day": sorted({d[8:10] for d in dates}),
            "time": [f"{h:02d}:00" for h in range(24)],
            "format": "netcdf",
        }
        if self.area is not None:
            request["area"] = self.area
        return request

    def _build_pressure_level_request(
        self,
        variables: list[str],
        dates: list[str],
    ) -> dict[str, Any]:
        """Build a CDS API request dict for pressure-level data."""
        cds_vars = [ERA5_PRESSURE_LEVEL_VARS[v] for v in variables]
        request: dict[str, Any] = {
            "product_type": self.product_type,
            "variable": cds_vars,
            "pressure_level": [str(pl) for pl in self.pressure_levels],
            "year": sorted({d[:4] for d in dates}),
            "month": sorted({d[5:7] for d in dates}),
            "day": sorted({d[8:10] for d in dates}),
            "time": [f"{h:02d}:00" for h in range(24)],
            "format": "netcdf",
        }
        if self.area is not None:
            request["area"] = self.area
        return request

    def _generate_dates(self, start: str, end: str) -> list[str]:
        """Generate list of YYYY-MM-DD date strings."""
        from datetime import datetime, timedelta

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        dates: list[str] = []
        current = start_dt
        while current <= end_dt:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates

    def _download_dataset(
        self,
        request: dict[str, Any],
        target: str,
        product: str = "reanalysis-era5-single-levels",
    ) -> Path:
        """Download data via CDS API to a local file."""
        client = self._get_cds_client()
        out_path = self.cache_dir / target
        if out_path.exists():
            logger.debug("Using cached ERA5 file: %s", out_path)
            return out_path
        logger.info("Downloading ERA5 data to %s", out_path)
        client.retrieve(product, request, str(out_path))
        return out_path

    def fetch(
        self,
        start: str,
        end: str,
        bbox: list[float] | None = None,
        chunks: dict[str, int] | None = None,
    ) -> xr.Dataset:
        """Fetch ERA5 data for a date range.

        Args:
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".
            bbox: Override bounding box [N, W, S, E].
            chunks: Override Dask chunking.

        Returns:
            Lazy xarray.Dataset backed by Dask arrays.
        """
        if bbox is not None:
            self.area = bbox

        effective_chunks = chunks or self.chunks
        dates = self._generate_dates(start, end)
        datasets: list[xr.Dataset] = []

        if self.single_level_vars and self.pressure_level_vars:
            raise ValueError(
                "Cannot fetch single-level and pressure-level variables in one call. "
                "Use separate ERA5Connector instances for each product type."
            )

        if self.single_level_vars:
            request = self._build_single_level_request(self.single_level_vars, dates)
            var_hash = hashlib.md5(str(self.single_level_vars).encode()).hexdigest()[:8]
            target = f"era5_single_{start}_{end}_{var_hash}.nc"
            try:
                path = self._download_dataset(
                    request, target, product="reanalysis-era5-single-levels"
                )
                ds = xr.open_dataset(path, chunks=effective_chunks)
                datasets.append(ds)
            except Exception as exc:
                logger.error("Failed to download single-level ERA5: %s", exc)
                raise

        if self.pressure_level_vars:
            request = self._build_pressure_level_request(self.pressure_level_vars, dates)
            var_hash = hashlib.md5(str(self.pressure_level_vars).encode()).hexdigest()[:8]
            target = f"era5_pressure_{start}_{end}_{var_hash}.nc"
            try:
                path = self._download_dataset(
                    request, target, product="reanalysis-era5-pressure-levels"
                )
                ds = xr.open_dataset(path, chunks=effective_chunks)
                datasets.append(ds)
            except Exception as exc:
                logger.error("Failed to download pressure-level ERA5: %s", exc)
                raise

        if not datasets:
            raise RuntimeError("No data fetched — check variable names and date range")

        return datasets[0]

    def fetch_monthly(
        self,
        year: int,
        month: int,
        chunks: dict[str, int] | None = None,
    ) -> xr.Dataset:
        """Fetch a single month of ERA5 data.

        Convenience method for monthly slices.

        Args:
            year: Year (e.g. 2023).
            month: Month (1-12).
            chunks: Dask chunk specification.

        Returns:
            xarray.Dataset for the specified month.
        """
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"
        from datetime import datetime, timedelta

        end_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=1)
        return self.fetch(start, end_dt.strftime("%Y-%m-%d"), chunks=chunks)

    def fetch_zarr(
        self,
        start: str,
        end: str,
        variables: list[str] | None = None,
    ) -> xr.Dataset:
        """Fetch ERA5 data from Google's cloud-optimized Zarr mirror.

        This method does NOT require a CDS API key. Data is streamed
        directly from Google Cloud Storage.

        Args:
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".
            variables: Override variable list. If None, uses self.variables.

        Returns:
            xarray.Dataset with ERA5 data.

        Raises:
            ImportError: If zarr or gcsfs packages are not installed.
        """
        try:
            import zarr
        except ImportError as exc:
            raise ImportError(
                "zarr is required for Google Zarr access. "
                "Install with: pip install zarr"
            ) from exc

        # Google Zarr ERA5 dataset
        # https://console.cloud.google.com/storage/browser/gcp-public-data-era5

        # Map variable names to Zarr store paths
        var_mapping = {
            "temperature_2m": "era5/single_level/surface/temperature",
            "msl": "era5/single_level/surface/mean_sea_level_pressure",
            "wind_10m_u": "era5/single_level/surface/u_component_of_wind",
            "wind_10m_v": "era5/single_level/surface/v_component_of_wind",
            "wind_speed_10m": "era5/single_level/surface/wind_speed",
            "precipitation": "era5/single_level/surface/precipitation",
            "specific_humidity": "era5/single_level/surface/specific_humidity",
            "cloud_cover": "era5/single_level/surface/cloud_cover",
            "surface_pressure": "era5/single_level/surface/surface_pressure",
            "soil_temperature_1": "era5/single_level/surface/soil_temperature_level_1",
            "snow_depth": "era5/single_level/surface/snow_depth",
            "visibility": "era5/single_level/surface/visibility",
        }

        if variables is None:
            variables = self.variables

        # Filter to available variables
        available_vars = [v for v in variables if v in var_mapping]
        if not available_vars:
            raise ValueError(
                f"No variables available in Google Zarr mirror. "
                f"Available: {sorted(var_mapping.keys())}"
            )

        # Load data from Zarr stores
        datasets: list[xr.Dataset] = []
        for var in available_vars:
            store_path = var_mapping[var]
            try:
                store = zarr.storage.GCSStore(store_path)
                ds = xr.open_zarr(store, consolidated=True)

                # Slice by time
                ds = ds.sel(time=slice(start, end))
                datasets.append(ds)
            except Exception as exc:
                logger.warning("Failed to load %s from Zarr: %s", var, exc)
                continue

        if not datasets:
            raise RuntimeError(
                "No data fetched from Google Zarr. "
                "Check variable names and date range."
            )

        # Merge datasets
        if len(datasets) == 1:
            return datasets[0]
        return xr.merge(datasets, compat="override")

    def close(self) -> None:
        """Release CDS client resources."""
        self._cds_client = None

    def __enter__(self) -> ERA5Connector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
