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

# NOAA Big Data Program mirror (as-published operational archive). NOMADS only
# retains ~10 days of cycles; this S3 bucket holds the full archive back to 2021.
AWS_GFS_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"

GFS_VARIABLE_MAP: dict[str, dict[str, Any]] = {
    "temperature_2m": {
        "var": "TMP",
        "lev": "2 m above ground",
        "shortName": "2t",
    },
    "wind_10m": {
        "var": "UGRD:VGRD",
        "lev": "10 m above ground",
        "shortName": "10u",
    },
    "wind_10m_u": {
        "var": "UGRD",
        "lev": "10 m above ground",
        "shortName": "10u",
    },
    "wind_10m_v": {
        "var": "VGRD",
        "lev": "10 m above ground",
        "shortName": "10v",
    },
    "precipitation": {
        "var": "PRATE",
        "lev": "surface",
        "shortName": "prate",
    },
    "msl_pressure": {
        "var": "MSLET",
        "lev": "mean sea level",
        "shortName": "msl",
    },
    "geopotential_500": {
        "var": "HGT",
        "lev": "500 mb",
        "shortName": "z",
    },
    "humidity": {
        "var": "RH",
        "lev": "2 m above ground",
        "shortName": "r",
    },
    "specific_humidity": {
        "var": "SPFH",
        "lev": "2 m above ground",
        "shortName": "q",
    },
    "temperature_850": {
        "var": "TMP",
        "lev": "850 mb",
        "shortName": "t",
    },
    "temperature_500": {
        "var": "TMP",
        "lev": "500 mb",
        "shortName": "t",
    },
    "wind_250": {
        "var": "UGRD:VGRD",
        "lev": "250 mb",
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
        """Build the NOMADS filter URL for a single GRIB2 variable.

        NOMADS filter_gfs_{res}.pl (v1.2) expects checkbox-style parameters:
        ``var_<ABBREV>=on`` and ``lev_<level>=on``. The ``subregion`` parameter
        must be present (even when empty) to activate the bounding-box subset.
        """
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

        for var in var_cfg["var"].split(":"):
            params[f"var_{var}"] = "on"
        lev = var_cfg.get("lev")
        if lev:
            params[f"lev_{lev.replace(' ', '_')}"] = "on"

        url = NOMADS_GFS_URL.format(res=self.resolution)
        query_parts = [f"{k}={v}" for k, v in params.items()]
        return url + "?" + "&".join(query_parts)

    def _object_url(self, date: str, cycle: str, forecast_hour: int) -> str:
        """Return the NOAA AWS archive object URL for a GFS cycle file."""
        file = f"gfs.t{cycle}z.pgrb2.{self.resolution}.f{forecast_hour:03d}"
        return f"{AWS_GFS_URL}/gfs.{date}/{cycle}/atmos/{file}"

    def _idx_offsets(self, url: str) -> list[tuple[int, str, str, str]]:
        """Fetch a GRIB index and return (byte_start, variable, level, ftype) rows."""
        resp = self._session.get(url + ".idx", timeout=self.timeout)
        resp.raise_for_status()
        rows: list[tuple[int, str, str, str]] = []
        for line in resp.text.splitlines():
            parts = line.split(":")
            if len(parts) >= 5:
                ftype = parts[5] if len(parts) > 5 else ""
                rows.append((int(parts[1]), parts[3], parts[4], ftype))
        return rows

    def _fetch_archive_cycle(
        self,
        date: str,
        cycle: str,
        forecast_hour: int = 0,
    ) -> xr.Dataset:
        """Fetch a historical GFS cycle via byte-range extraction from AWS.

        The NOAA archive stores full 0.25° GRIB2 files (~120 MB). Using the
        GRIB index byte offsets we Range-GET only the messages this connector
        needs (~1 MB/level), assemble per-level GRIB2 files, and parse with
        cfgrib — a ~20x reduction that makes multi-year backfills tractable.
        """
        obj = self._object_url(date, cycle, forecast_hour)
        rows = self._idx_offsets(obj)
        rows.sort(key=lambda r: r[0])
        starts = [r[0] for r in rows]

        wanted: set[tuple[str, str]] = set()
        for var_name in self.variables:
            cfg = GFS_VARIABLE_MAP[var_name]
            for abbrev in cfg["var"].split(":"):
                wanted.add((abbrev, cfg["lev"]))

        # Prefer instantaneous records over averaged ones (e.g. PRATE appears
        # both as "N hour fcst" and "N-M hour ave fcst" at f024+).
        matches: dict[tuple[str, str], list[int]] = {}
        for i, (_start, var, lev, _ftype) in enumerate(rows):
            if (var, lev) in wanted:
                matches.setdefault((var, lev), []).append(i)
        selected: list[tuple[int, str, str]] = []
        for (var, lev), idxs in matches.items():
            idxs = sorted(idxs, key=lambda j: "ave" in rows[j][3].lower())
            i = idxs[0]
            selected.append((starts[i], var, lev))
        selected.sort(key=lambda r: r[0])

        if not selected:
            raise RuntimeError(f"No requested variables found in {obj}")

        # end offset of each selected message = next message start in the file
        end_by_start: dict[int, int | None] = {}
        for i, start in enumerate(starts):
            end_by_start[start] = starts[i + 1] - 1 if i + 1 < len(starts) else None

        paths: list[Path] = []
        seen_levels: set[str] = set()
        for start, var, lev in selected:
            if lev in seen_levels:
                continue
            seen_levels.add(lev)
            spans = [(s, end_by_start[s]) for s, v, l in selected if l == lev]
            safe = lev.replace(" ", "_")
            dest = self.cache_dir / f"aws_{date}_{cycle}z_f{forecast_hour:03d}_{safe}.grib2"
            if not (dest.exists() and dest.stat().st_size > 0):
                blob = bytearray()
                for span_start, end in spans:
                    headers = (
                        {"Range": f"bytes={span_start}-{end}"}
                        if end is not None
                        else {"Range": f"bytes={span_start}-"}
                    )
                    resp = self._range_get_with_retry(obj, headers)
                    blob.extend(resp.content)
                dest.write_bytes(bytes(blob))
            paths.append(dest)

        return self._open_grib(paths)

    def _range_get_with_retry(self, url: str, headers: dict[str, str]) -> requests.Response:
        """GET a byte range with retry and exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                logger.debug("Range GET attempt %d/%d failed: %s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** (attempt - 1)))
        raise ConnectionError(f"Failed to fetch byte range from {url}") from last_exc

    def _subset_bbox(self, ds: xr.Dataset) -> xr.Dataset:
        """Subset a full-grid Dataset to the configured bounding box."""
        w, s, e, n = self.bbox
        if "longitude" in ds.coords:
            lon0, lon1 = (w, e) if w >= 0 else (w + 360, e + 360)
            ds = ds.sel(longitude=slice(lon0, lon1))
        if "latitude" in ds.coords:
            lat = ds.latitude.values
            descending = len(lat) > 1 and lat[0] > lat[-1]
            lat0, lat1 = (n, s) if descending else (s, n)
            ds = ds.sel(latitude=slice(lat0, lat1))
        return ds

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
        source: Literal["auto", "nomads", "aws"] = "auto",
    ) -> xr.Dataset:
        """Fetch archived GFS data for model training.

        Args:
            start: Start date as "YYYY-MM-DD".
            end: End date as "YYYY-MM-DD".
            forecast_hour: Forecast lead time in hours.
            source: "auto" (NOMADS first, AWS fallback), "nomads", or "aws".

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
                    if source == "aws":
                        ds = self._fetch_archive_cycle(date_str, cycle_str, forecast_hour)
                    else:
                        try:
                            ds = self._fetch_forecast(date_str, cycle_str, forecast_hour)
                        except ConnectionError:
                            if source == "nomads":
                                raise
                            logger.warning(
                                "NOMADS miss %s %sZ — falling back to AWS archive",
                                date_str,
                                cycle_str,
                            )
                            ds = self._fetch_archive_cycle(date_str, cycle_str, forecast_hour)
                    ds = self._subset_bbox(ds)
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
