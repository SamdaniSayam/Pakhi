"""GOES satellite data connector via AWS S3.

Fetches GOES-16/17/18 ABI data from the NOAA open-data S3 buckets,
supports water vapor and IR bands, CONUS/FullDisk/Meso sectors, and
derives cloud motion vectors for wind estimation.

Example:
    >>> from pakhi.src.satellite import GOESConnector
    >>> goes = GOESConnector(satellite="GOES-16", bands=["band_13"], sector="CONUS")
    >>> image = goes.latest()
    >>> vectors = goes.cloud_motion(minutes=60)
"""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr

__all__ = ["GOESConnector"]

logger = logging.getLogger(__name__)

GOES_SATelliteS = ["GOES-16", "GOES-17", "GOES-18"]
GOES_S3_BUCKETS = {
    "GOES-16": "noaa-goes16",
    "GOES-17": "noaa-goes17",
    "GOES-18": "noaa-goes18",
}
S3_BASE = "https://{bucket}.s3.amazonaws.com"

SECTORS = ["CONUS", "FullDisk", "Meso-scale"]
SECTOR_PRODUCT_MAP = {
    "CONUS": "ABI-L2-CMIPF",
    "FullDisk": "ABI-L2-CMIPF",
    "Meso-scale": "ABI-L2-CMIPF",
}

BAND_INFO: dict[str, dict[str, Any]] = {
    "band_07": {"wavelength_um": 3.9, "channel": 7, "name": "Shortwave Window", "type": "IR"},
    "band_08": {
        "wavelength_um": 6.2,
        "channel": 8,
        "name": "Upper-Level Water Vapor",
        "type": "WV",
    },
    "band_09": {"wavelength_um": 6.9, "channel": 9, "name": "Mid-Level Water Vapor", "type": "WV"},
    "band_10": {
        "wavelength_um": 7.3,
        "channel": 10,
        "name": "Lower-Level Water Vapor",
        "type": "WV",
    },
    "band_11": {"wavelength_um": 8.4, "channel": 11, "name": "Cloud/Ice", "type": "IR"},
    "band_12": {"wavelength_um": 9.6, "channel": 12, "name": "Ozone", "type": "IR"},
    "band_13": {"wavelength_um": 10.3, "channel": 13, "name": "Clean IR Longwave", "type": "IR"},
    "band_14": {"wavelength_um": 11.2, "channel": 14, "name": "IR Longwave Window", "type": "IR"},
    "band_15": {"wavelength_um": 12.3, "channel": 15, "name": "Dirty IR Longwave", "type": "IR"},
    "band_16": {"wavelength_um": 13.3, "channel": 16, "name": "CO2 Longwave", "type": "IR"},
}

# GOES ABI band scaling and calibration constants
ABI_DQF_VALID = 0  # Data Quality Flag = 0 means valid


class GOESConnector:
    """Connector for GOES ABI data from NOAA AWS S3 buckets.

    Supports GOES-16, GOES-17, and GOES-18 with water vapor (bands 8-10)
    and infrared (bands 13-14) channels for weather analysis.

    Args:
        satellite: Which GOES satellite — "GOES-16", "GOES-17", or "GOES-18".
        bands: List of band identifiers, e.g. ["band_13", "band_14"].
        sector: Observation sector — "CONUS", "FullDisk", or "Meso-scale".
        cache_dir: Directory for caching downloaded NetCDF files.
        timeout: HTTP timeout in seconds.
        max_retries: Max download retry attempts.

    Example:
        >>> goes = GOESConnector(
        ...     satellite="GOES-16",
        ...     bands=["band_13", "band_14"],
        ...     sector="CONUS",
        ... )
        >>> image = goes.latest()
    """

    def __init__(
        self,
        satellite: str = "GOES-16",
        bands: list[str] | None = None,
        sector: str = "CONUS",
        cache_dir: str | Path | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        if satellite not in GOES_SATelliteS:
            raise ValueError(f"satellite must be one of {GOES_SATelliteS}")
        if sector not in SECTORS:
            raise ValueError(f"sector must be one of {SECTORS}")
        if bands is None:
            bands = ["band_13", "band_14"]
        for b in bands:
            if b not in BAND_INFO:
                raise ValueError(f"Unknown band '{b}'. Available: {sorted(BAND_INFO.keys())}")

        self.satellite = satellite
        self.bands = bands
        self.sector = sector
        self.s3_bucket = GOES_S3_BUCKETS[satellite]
        self.cache_dir = (
            Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "pakhi_satellite"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "pakhi-weather-quant/0.1"})

    def _s3_prefix(self, dt: datetime, band: str) -> str:
        """Build S3 object prefix for a given timestamp and band."""
        year = dt.strftime("%Y")
        day_of_year = dt.strftime("%j")
        hour = dt.strftime("%H")
        channel = BAND_INFO[band]["channel"]
        product = "ABI-L2-CMIPF" if self.sector != "Meso-scale" else "ABI-L2-CMIPF"
        return (
            f"{product}/{year}/{day_of_year}/{hour}/"
            f"OR_{self.sector}-{product[4:]}-M{channel}"
            f"C{channel:02d}_G{self.satellite[-2:]}_s{dt.strftime('%Y%j%H%M')}"
        )

    def _list_s3_objects(self, prefix: str) -> list[str]:
        """List objects in the S3 bucket with a given prefix."""
        url = f"https://{self.s3_bucket}.s3.amazonaws.com/"
        params = {"prefix": prefix, "delimiter": "/"}
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            import xml.etree.ElementTree as ET

            root = ET.fromstring(resp.content)
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            keys = []
            for contents in root.findall(".//s3:Contents", ns):
                key_el = contents.find("s3:Key", ns)
                if key_el is not None and key_el.text:
                    keys.append(key_el.text)
            return sorted(keys)
        except Exception as exc:
            logger.warning("S3 list failed for prefix %s: %s", prefix, exc)
            return []

    def _find_latest_file(self, band: str) -> str | None:
        """Find the most recent GOES file for a band by probing recent hours."""
        now = datetime.now(timezone.utc)
        for hours_back in range(0, 6):
            dt = now - timedelta(hours=hours_back)
            # Round down to nearest 15-minute slot
            minute_slot = (dt.minute // 15) * 15
            dt = dt.replace(minute=minute_slot, second=0, microsecond=0)
            prefix = self._s3_prefix(dt, band)
            keys = self._list_s3_objects(prefix)
            if keys:
                # Find the .nc file
                nc_keys = [k for k in keys if k.endswith(".nc")]
                if nc_keys:
                    return nc_keys[-1]
        return None

    def _download_s3_file(self, key: str) -> Path:
        """Download a file from S3 with retry."""
        filename = Path(key).name
        dest = self.cache_dir / filename
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        url = f"https://{self.s3_bucket}.s3.amazonaws.com/{key}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout, stream=True)
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                if dest.stat().st_size > 0:
                    return dest
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Download attempt %d failed for %s: %s", attempt, filename, exc)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
        raise ConnectionError(
            f"Failed to download {key} after {self.max_retries} attempts"
        ) from last_exc

    def _open_netcdf(self, path: Path) -> xr.Dataset:
        """Open a GOES NetCDF file and extract the primary variable."""
        try:
            import netCDF4  # noqa: F401

            ds = xr.open_dataset(path, engine="netcdf4")
        except Exception:
            ds = xr.open_dataset(path)

        # GOES ABI files often have a single data variable (CMI)
        data_vars = list(ds.data_vars)
        if len(data_vars) == 1:
            var_name = data_vars[0]
            ds = ds.rename({var_name: "brightness_temperature"})

        # Apply scale factor and add offset if present
        if "brightness_temperature" in ds:
            bt = ds["brightness_temperature"]
            if hasattr(bt, "attrs"):
                scale = bt.attrs.get("scale_factor", 1.0)
                offset = bt.attrs.get("add_offset", 0.0)
                if scale != 1.0 or offset != 0.0:
                    ds["brightness_temperature"] = bt * scale + offset

        return ds

    def latest(self) -> xr.Dataset:
        """Fetch the most recent GOES image for all configured bands.

        Returns:
            xarray.Dataset with brightness temperature data for each band.
        """
        datasets: list[xr.Dataset] = []
        for band in self.bands:
            key = self._find_latest_file(band)
            if key is None:
                logger.warning("No data found for %s %s", self.satellite, band)
                continue
            path = self._download_s3_file(key)
            ds = self._open_netcdf(path)
            ds = ds.expand_dims(dim={"band": [band]})
            datasets.append(ds)

        if not datasets:
            raise RuntimeError(f"No GOES data available for {self.satellite} bands {self.bands}")

        combined = xr.concat(datasets, dim="band")
        combined.attrs["satellite"] = self.satellite
        combined.attrs["sector"] = self.sector
        combined.attrs["bands"] = self.bands
        return combined

    def cloud_motion(self, minutes: int = 60) -> xr.Dataset:
        """Compute cloud motion vectors from sequential IR images.

        Uses block-matching between consecutive brightness temperature
        images to estimate cloud displacement vectors. The time window
        determines the temporal baseline for the motion estimate.

        Args:
            minutes: Temporal baseline in minutes (must be ≥ 15).

        Returns:
            xarray.Dataset with u/v wind components derived from cloud motion.

        Note:
            Returns upper-level wind estimates (not surface). Best with
            water vapor bands (8-10) or clean IR (band 13).
        """
        if minutes < 15:
            raise ValueError("Minimum temporal baseline is 15 minutes (GOES scan interval)")

        now = datetime.now(timezone.utc)
        n_images = max(2, minutes // 15 + 1)

        timestamps = [now - timedelta(minutes=i * 15) for i in range(n_images)]

        images: list[np.ndarray] = []
        for ts in reversed(timestamps):
            try:
                for band in self.bands:
                    key = self._find_latest_file(band)
                    if key is None:
                        continue
                    path = self._download_s3_file(key)
                    ds = self._open_netcdf(path)
                    try:
                        if "brightness_temperature" in ds:
                            bt = ds["brightness_temperature"].values
                            if bt.ndim > 2:
                                bt = bt.squeeze()
                            images.append(np.asarray(bt, dtype=np.float32))
                            break
                    finally:
                        ds.close()
            except Exception as exc:
                logger.warning("Failed to load image at %s: %s", ts, exc)
                continue

        if len(images) < 2:
            logger.warning(
                "Only %d image(s) available for cloud motion — returning zero vectors. "
                "Need at least 2 timestamps for motion estimation.",
                len(images),
            )
            ref_shape = images[0].shape if images else (1000, 1000)
            h, w = ref_shape
            block_size = 32
            n_blocks_y = h // block_size
            n_blocks_x = w // block_size
            return xr.Dataset(
                {
                    "u_cloud_motion": (
                        ["y", "x"],
                        np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32),
                    ),
                    "v_cloud_motion": (
                        ["y", "x"],
                        np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32),
                    ),
                    "confidence": (
                        ["y", "x"],
                        np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32),
                    ),
                },
                coords={
                    "y": np.arange(n_blocks_y),
                    "x": np.arange(n_blocks_x),
                },
                attrs={
                    "satellite": self.satellite,
                    "sector": self.sector,
                    "temporal_baseline_minutes": minutes,
                    "block_size_pixels": block_size,
                    "method": "zero_fallback",
                },
            )

        ref = images[0]
        h, w = ref.shape
        block_size = 32
        n_blocks_y = h // block_size
        n_blocks_x = w // block_size

        u_field = np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32)
        v_field = np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32)
        confidence = np.zeros((n_blocks_y, n_blocks_x), dtype=np.float32)

        prev = images[0]
        for img in images[1:]:
            for by in range(n_blocks_y):
                for bx in range(n_blocks_x):
                    y0 = by * block_size
                    x0 = bx * block_size
                    block = prev[y0 : y0 + block_size, x0 : x0 + block_size]
                    search_r = 8
                    best_dx, best_dy = 0, 0
                    best_corr = -1.0
                    for dy in range(-search_r, search_r + 1):
                        for dx in range(-search_r, search_r + 1):
                            sy = y0 + dy
                            sx = x0 + dx
                            if sy < 0 or sx < 0 or sy + block_size > h or sx + block_size > w:
                                continue
                            target = img[sy : sy + block_size, sx : sx + block_size]
                            if block.shape != target.shape:
                                continue
                            corr = np.corrcoef(block.ravel(), target.ravel())[0, 1]
                            if corr > best_corr:
                                best_corr = corr
                                best_dx, best_dy = dx, dy
                    u_field[by, bx] = best_dx
                    v_field[by, bx] = best_dy
                    confidence[by, bx] = max(best_corr, 0.0)
            prev = img

        # Scale block-level vectors to per-pixel and assign to grid coords
        lat_res = 0.14  # approximate GOES ABI pixel spacing in degrees at nadir
        lon_res = 0.14
        u_wind = u_field * block_size * lat_res * 60.0 / (minutes)  # approx deg/hr → m/s proxy
        v_wind = v_field * block_size * lon_res * 60.0 / (minutes)

        ds = xr.Dataset(
            {
                "u_cloud_motion": (["y", "x"], u_wind),
                "v_cloud_motion": (["y", "x"], v_wind),
                "confidence": (["y", "x"], confidence),
            },
            coords={
                "y": np.arange(n_blocks_y),
                "x": np.arange(n_blocks_x),
            },
            attrs={
                "satellite": self.satellite,
                "sector": self.sector,
                "temporal_baseline_minutes": minutes,
                "block_size_pixels": block_size,
                "method": "block_matching_correlation",
            },
        )
        return ds

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> GOESConnector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
