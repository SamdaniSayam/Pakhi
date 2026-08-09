"""NOAA GFS (Global Forecast System) data connector.

Downloads GFS GRIB2 data from NOAA NOMADS, parses with cfgrib/xarray,
and returns xarray Datasets with proper variable naming.

Example:
    >>> from pakhi.src.noaa import GFSConnector
    >>> gfs = GFSConnector(variables=["temperature_2m", "wind_10m"])
    >>> ds = gfs.latest()
"""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import requests
import xarray as xr

__all__ = ["GFSConnector"]

logger = logging.getLogger(__name__)

NOMADS_GFS_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_{res}.pl"

GFS_VARIABLE_MAP: dict[str, dict[str, Any]] = {
    "temperature_2m": {
        "file": "t2m",
        "lev": None,
        "var": "TMP",
        "level": "surface",
        "shortName": "2t",
    },
    "wind_10m": {
        "file": "u10/v10",
        "lev": None,
        "var": "UGRD:VGRD",
        "level": "10 m above ground",
        "shortName": "10u",
    },
    "wind_10m_u": {
        "file": "u10",
        "lev": None,
        "var": "UGRD",
        "level": "10 m above ground",
        "shortName": "10u",
    },
    "wind_10m_v": {
        "file": "v10",
        "lev": None,
        "var": "VGRD",
        "level": "10 m above ground",
        "shortName": "10v",
    },
    "precipitation": {
        "file": "apcp",
        "lev": None,
        "var": "APCP",
        "level": "surface",
        "shortName": "tp",
    },
    "msl_pressure": {
        "file": "mslet",
        "lev": None,
        "var": "MSLET",
        "level": "mean sea level",
        "shortName": "msl",
    },
    "geopotential_500": {
        "file": "hgt",
        "lev": "500 mb",
        "var": "HGT",
        "level": "500 mb",
        "shortName": "z",
    },
    "humidity": {
        "file": "rh",
        "lev": "2_m_above_ground",
        "var": "RH",
        "level": "2 m above ground",
        "shortName": "r",
    },
    "specific_humidity": {
        "file": "sh",
        "lev": "2_m_above_ground",
        "var": "SPFH",
        "level": "2 m above ground",
        "shortName": "q",
    },
    "temperature_850": {
        "file": "t850",
        "lev": "850 mb",
        "var": "TMP",
        "level": "850 mb",
        "shortName": "t",
    },
    "temperature_500": {
        "file": "t500",
        "lev": "500 mb",
        "var": "TMP",
        "level": "500 mb",
        "shortName": "t",
    },
    "wind_250": {
        "file": "u250/v250",
        "lev": "250 mb",
        "var": "UGRD:VGRD",
        "level": "250 mb",
        "shortName": "u",
    },
}

GFS_RESOLUTIONS = Literal["0p25", "0p50", "1p00"]

# GFS model run cycles
VALID_CYCLES = [0, 6, 12, 18]


class GFSConnector:
    """Connector for NOAA GFS GRIB2 data via NOMADS.

    Downloads subsetting GFS forecast data from the NOAA NOMADS HTTP server,
    parses GRIB2 files with cfgrib, and returns xarray Datasets.

    Args:
        variables: List of variable names from GFS_VARIABLE_MAP.
        bbox: Bounding box [west, south, east, north] in degrees.
        resolution: GFS grid resolution — "0p25" (0.25°), "0p50", or "1p00".
        cache_dir: Directory for caching downloaded GRIB2 files.
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum number of retry attempts for failed downloads.
        retry_delay: Base delay between retries in seconds (exponential backoff).

    Example:
        >>> gfs = GFSConnector(
        ...     variables=["temperature_2m", "wind_10m"],
        ...     bbox=[-125, 24, -66, 50],
        ... )
        >>> ds = gfs.latest()
        >>> print(ds)
    """

    def __init__(
        self,
        variables: list[str] | None = None,
        bbox: list[float] | None = None,
        resolution: GFS_RESOLUTIONS = "0p25",
        cache_dir: str | Path | None = None,
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> None:
        if variables is None:
            variables = ["temperature_2m", "wind_10m", "precipitation"]
        for v in variables:
            if v not in GFS_VARIABLE_MAP:
                raise ValueError(
                    f"Unknown variable '{v}'. Available: {sorted(GFS_VARIABLE_MAP.keys())}"
                )
        self.variables = variables
        self.bbox = bbox if bbox is not None else [-125, 24, -66, 50]
        if len(self.bbox) != 4:
            raise ValueError("bbox must be [west, south, east, north]")
        self.resolution = resolution
        self.cache_dir = (
            Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "pakhi_gfs_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "pakhi-weather-quant/0.1"})

    def _latest_cycle(self, ref_time: datetime | None = None) -> tuple[str, str]:
        """Determine the most recent GFS cycle available.

        GFS runs at 00Z, 06Z, 12Z, 18Z with ~3.5h publication lag.
        """
        now = ref_time or datetime.now(timezone.utc)
        for hours_back in range(0, 24, 6):
            candidate = now - timedelta(hours=hours_back)
            cycle_hour = (candidate.hour // 6) * 6
            cycle_time = candidate.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)
            publication_time = cycle_time + timedelta(hours=3, minutes=30)
            if now >= publication_time:
                date_str = cycle_time.strftime("%Y%m%d")
                cycle_str = f"{cycle_time.hour:02d}"
                return date_str, cycle_str
        fallback = now - timedelta(hours=12)
        return fallback.strftime("%Y%m%d"), f"{(fallback.hour // 6) * 6:02d}"

    def _build_url(
        self,
        date: str,
        cycle: str,
        forecast_hour: int,
        var_cfg: dict[str, Any],
    ) -> str:
        """Build the NOMADS filter URL for a single GRIB2 variable."""
        params: dict[str, str] = {
            "file": f"gfs.t{cycle}z.pgrb2.{self.resolution}.f{forecast_hour:03d}",
            "dir": f"/gfs.{date}/{cycle}/atmos",
        }
        w, s, e, n = self.bbox
        params["subregion"] = ""
        params["leftlon"] = str(w)
        params["rightlon"] = str(e)
        params["toplat"] = str(n)
        params["bottomlat"] = str(s)

        params["var"] = var_cfg["var"]
        if var_cfg["lev"] is not None:
            params["lev"] = var_cfg["lev"]

        url = NOMADS_GFS_URL.format(res=self.resolution)
        query_parts = [f"{k}={v}" for k, v in params.items() if v != ""]
        return url + "?" + "&".join(query_parts)

    def _download_with_retry(self, url: str, dest: Path) -> Path:
        """Download a URL with retry and exponential backoff."""
        if dest.exists() and dest.stat().st_size > 0:
            logger.debug("Using cached file: %s", dest)
            return dest

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug("Download attempt %d/%d: %s", attempt, self.max_retries, dest.name)
                resp = self._session.get(url, timeout=self.timeout, stream=True)
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                if dest.stat().st_size > 0:
                    return dest
                logger.warning("Empty response for %s", dest.name)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Attempt %d failed for %s: %s", attempt, dest.name, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** (attempt - 1)))
        raise ConnectionError(
            f"Failed to download after {self.max_retries} attempts: {dest.name}"
        ) from last_exc

    def _open_grib(self, paths: list[Path]) -> xr.Dataset:
        """Open GRIB2 files with cfgrib engine."""
        import cfgrib  # noqa: F401 — ensures cfgrib engine is registered

        datasets: list[xr.Dataset] = []
        for p in paths:
            try:
                ds = xr.open_dataset(
                    p,
                    engine="cfgrib",
                    backend_kwargs={"indexpath": ""},
                )
                datasets.append(ds)
            except Exception:
                try:
                    ds = xr.open_dataset(p, engine="cfgrib")
                    datasets.append(ds)
                except Exception as exc:
                    logger.error("Failed to parse %s: %s", p, exc)
                    continue
        if not datasets:
            raise RuntimeError("No GRIB2 files could be parsed")
        return xr.merge(datasets, compat="override")

    def _fetch_forecast(
        self,
        date: str | None = None,
        cycle: str | None = None,
        forecast_hour: int = 0,
    ) -> xr.Dataset:
        """Fetch GFS forecast data for a specific cycle and forecast hour."""
        if date is None or cycle is None:
            date, cycle = self._latest_cycle()

        grib_files: list[Path] = []
        for var_name in self.variables:
            var_cfg = GFS_VARIABLE_MAP[var_name]
            url = self._build_url(date, cycle, forecast_hour, var_cfg)
            safe_name = f"gfs_{date}_{cycle}z_f{forecast_hour:03d}_{var_name}.grib2"
            dest = self.cache_dir / safe_name
            self._download_with_retry(url, dest)
            grib_files.append(dest)

        return self._open_grib(grib_files)

    def latest(self, forecast_hour: int = 0) -> xr.Dataset:
        """Fetch the most recent GFS forecast.

        Args:
            forecast_hour: Forecast lead time in hours (0 = analysis).

        Returns:
            xarray.Dataset with requested variables.
        """
        date, cycle = self._latest_cycle()
        logger.info("Fetching GFS latest: %s %sZ f%03d", date, cycle, forecast_hour)
        return self._fetch_forecast(date, cycle, forecast_hour)

    def forecast(self, steps: list[int] | None = None) -> xr.Dataset:
        """Fetch multiple forecast lead times and merge.

        Args:
            steps: List of forecast hours, e.g. [0, 6, 12, 24, 48, 72, 168].
                   Defaults to [0, 6, 12, 24, 48, 72, 120, 168].

        Returns:
            xarray.Dataset with a 'step' dimension.
        """
        if steps is None:
            steps = [0, 6, 12, 24, 48, 72, 120, 168]
        date, cycle = self._latest_cycle()
        datasets: list[xr.Dataset] = []
        for fh in steps:
            try:
                ds = self._fetch_forecast(date, cycle, fh)
                ds = ds.expand_dims(dim={"step": [fh]})
                datasets.append(ds)
            except Exception as exc:
                logger.warning("Failed for f%03d: %s", fh, exc)
                continue
        if not datasets:
            raise RuntimeError("No forecast steps could be fetched")
        return xr.concat(datasets, dim="step")

    def archive(
        self,
        start: str,
        end: str,
        forecast_hour: int = 0,
    ) -> xr.Dataset:
        """Fetch archived GFS data for model training.

        Args:
            start: Start date as "YYYY-MM-DD".
            end: End date as "YYYY-MM-DD".
            forecast_hour: Forecast lead time in hours.

        Returns:
            xarray.Dataset with a time dimension.
        """
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        datasets: list[xr.Dataset] = []
        current = start_dt
        while current <= end_dt:
            date_str = current.strftime("%Y%m%d")
            for cycle_hour in VALID_CYCLES:
                cycle_str = f"{cycle_hour:02d}"
                try:
                    ds = self._fetch_forecast(date_str, cycle_str, forecast_hour)
                    ds = ds.expand_dims(
                        dim={"time": [np.datetime64(current.replace(hour=cycle_hour))]}
                    )
                    datasets.append(ds)
                    logger.debug("Archived: %s %sZ", date_str, cycle_str)
                except Exception as exc:
                    logger.warning("Archive miss: %s %sZ — %s", date_str, cycle_str, exc)
            current += timedelta(days=1)
        if not datasets:
            raise RuntimeError(f"No archive data found for {start} to {end}")
        return xr.concat(datasets, dim="time")

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> GFSConnector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
