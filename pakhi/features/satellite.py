"""Satellite-derived features for weather quant applications.

Provides cloud motion vector estimation, brightness temperature
conversion, and cloud fraction computation from IR imagery.
"""

from __future__ import annotations

import logging

import numpy as np
import xarray as xr
from scipy import ndimage

__all__ = ["SatelliteFeatures"]

logger = logging.getLogger(__name__)

STEFAN_BOLTZMANN = 5.670374419e-8  # W m⁻² K⁻⁴
BOLTZMANN_K = 1.380649e-23  # J K⁻¹
PLANCK_H = 6.62607015e-34  # J s
C_SPEED = 2.998e8  # m s⁻¹

# Central wavelengths for common GOES IR channels (micrometres)
BAND_WAVELENGTHS: dict[int, float] = {
    2: 3.9,  # Shortwave IR
    3: 6.2,  # Water vapour
    4: 10.3,  # Clean IR
    5: 12.3,  # Dirty IR
    6: 13.3,  # CO₂
}


class SatelliteFeatures:
    """Satellite imagery feature extraction.

    Methods operate on xarray DataArrays or numpy arrays representing
    gridded satellite imagery.
    """

    __all__ = [
        "cloud_motion_vectors",
        "brightness_temperature",
        "cloud_fraction",
    ]

    @staticmethod
    def cloud_motion_vectors(
        ir_images: xr.DataArray | np.ndarray,
        time_delta_minutes: float,
        time_dim: str = "time",
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
        search_window: int = 10,
    ) -> xr.Dataset:
        """Derive atmospheric motion vectors from cloud tracking.

        Uses a local cross-correlation (trackability) approach to
        estimate cloud displacement between consecutive IR images.

        Parameters
        ----------
        ir_images : xr.DataArray or np.ndarray
            Sequence of IR brightness temperature images.
            Shape ``(time, lat, lon)``.
        time_delta_minutes : float
            Time between consecutive frames in minutes.
        time_dim, lat_dim, lon_dim : str
            Dimension names.
        search_window : int
            Half-size of the search neighbourhood (pixels).

        Returns
        -------
        xr.Dataset
            ``u_wind`` (m s⁻¹), ``v_wind`` (m s⁻¹), and
            ``motion_confidence`` (0–1).
        """
        if isinstance(ir_images, xr.DataArray):
            time_dim = "time" if "time" in ir_images.dims else next(iter(ir_images.dims))
            lat_dim = "latitude" if "latitude" in ir_images.dims else list(ir_images.dims)[1]
            lon_dim = "longitude" if "longitude" in ir_images.dims else list(ir_images.dims)[2]

            data = ir_images.values
            coords = ir_images.coords
            dims = ir_images.dims
        else:
            data = ir_images
            coords = None
            dims = None

        if data.ndim != 3:
            raise ValueError(f"Expected 3D array (time, lat, lon), got {data.ndim}D")

        n_times, n_lat, n_lon = data.shape
        if n_times < 2:
            raise ValueError("Need at least 2 time steps for motion vectors")

        u_vec = np.full((n_times - 1, n_lat, n_lon), np.nan, dtype=np.float64)
        v_vec = np.full((n_times - 1, n_lat, n_lon), np.nan, dtype=np.float64)
        confidence = np.full((n_times - 1, n_lat, n_lon), np.nan, dtype=np.float64)

        dt_seconds = time_delta_minutes * 60.0

        for t in range(n_times - 1):
            frame1 = data[t]
            frame2 = data[t + 1]

            if np.all(np.isnan(frame1)) or np.all(np.isnan(frame2)):
                continue

            valid1 = np.nan_to_num(frame1, nan=np.nanmean(frame1))
            valid2 = np.nan_to_num(frame2, nan=np.nanmean(frame2))

            for i in range(search_window, n_lat - search_window):
                for j in range(search_window, n_lon - search_window):
                    patch1 = valid1[
                        i - search_window : i + search_window + 1,
                        j - search_window : j + search_window + 1,
                    ]
                    search_area = valid2[
                        i - 2 * search_window : i + 2 * search_window + 1,
                        j - 2 * search_window : j + 2 * search_window + 1,
                    ]

                    if (
                        search_area.shape[0] < patch1.shape[0]
                        or search_area.shape[1] < patch1.shape[1]
                    ):
                        continue

                    corr = ndimage.correlate(
                        search_area - search_area.mean(), patch1 - patch1.mean(), mode="constant"
                    )
                    peak = np.unravel_index(np.argmax(corr), corr.shape)

                    di = peak[0] - 2 * search_window
                    dj = peak[1] - 2 * search_window

                    max_corr = corr[peak] / (
                        np.std(patch1) * np.std(search_area) * patch1.size + 1e-10
                    )

                    # Approximate grid spacing (degrees to km)
                    lat_res_km = 111.0
                    lon_res_km = 111.0 * np.cos(np.deg2rad(30))  # rough mid-latitude

                    u_vec[t, i, j] = (dj * lon_res_km * 1000.0) / dt_seconds
                    v_vec[t, i, j] = (di * lat_res_km * 1000.0) / dt_seconds
                    confidence[t, i, j] = float(np.clip(abs(max_corr), 0, 1))

        if coords is not None and dims is not None:
            result_time = coords[time_dim][:-1] if time_dim in coords else np.arange(n_times - 1)
            base = {
                time_dim: result_time,
                lat_dim: coords[lat_dim],
                lon_dim: coords[lon_dim],
            }
            return xr.Dataset(
                {
                    "u_wind": xr.DataArray(u_vec, coords=base, dims=[time_dim, lat_dim, lon_dim]),
                    "v_wind": xr.DataArray(v_vec, coords=base, dims=[time_dim, lat_dim, lon_dim]),
                    "motion_confidence": xr.DataArray(
                        confidence, coords=base, dims=[time_dim, lat_dim, lon_dim]
                    ),
                }
            )

        return xr.Dataset(
            {
                "u_wind": xr.DataArray(u_vec, dims=["time", "latitude", "longitude"]),
                "v_wind": xr.DataArray(v_vec, dims=["time", "latitude", "longitude"]),
                "motion_confidence": xr.DataArray(
                    confidence, dims=["time", "latitude", "longitude"]
                ),
            }
        )

    @staticmethod
    def brightness_temperature(
        band_data: float | np.ndarray | xr.DataArray,
        band_number: int,
    ) -> float | np.ndarray | xr.DataArray:
        """Convert raw satellite counts to brightness temperature.

        Uses Planck's law inverse with typical GOES-R calibration
        coefficients for the specified band.

        Parameters
        ----------
        band_data : array-like
            Raw radiance values in W m⁻² sr⁻¹ μm⁻¹, or digit counts
            (values > 1000 are assumed to be radiance).
        band_number : int
            GOES-R ABI band number (2–6).

        Returns
        -------
        Same type as input
            Brightness temperature in Kelvin.

        Notes
        -----
        For digit counts, a linear calibration is applied:
        ``radiance = slope * count + intercept`` using standard
        coefficients. If values appear to already be radiances
        (> 1000), they are used directly.
        """
        wavelength_um = BAND_WAVELENGTHS.get(band_number, 10.3)
        wavelength_m = wavelength_um * 1e-6

        c1 = 2.0 * PLANCK_H * C_SPEED**2 / wavelength_m**5
        c2 = PLANCK_H * C_SPEED / (BOLTZMANN_K * wavelength_m)

        def _planck_inv(radiance: np.ndarray) -> np.ndarray:
            valid = radiance > 0
            result = np.full_like(radiance, np.nan, dtype=np.float64)
            result[valid] = c2 / (wavelength_m * np.log(c1 / radiance[valid] + 1.0))
            return result

        if isinstance(band_data, xr.DataArray):
            values = band_data.values.astype(np.float64)
            values = np.where(values < 1000, np.maximum(values, 0.1), values)
            tb = _planck_inv(values)
            return xr.DataArray(
                tb, coords=band_data.coords, dims=band_data.dims, name=f"bt_band{band_number}"
            )

        arr = np.asarray(band_data, dtype=np.float64)
        arr = np.where(arr < 1000, np.maximum(arr, 0.1), arr)
        return _planck_inv(arr)

    @staticmethod
    def cloud_fraction(
        ir_data: float | np.ndarray | xr.DataArray,
        threshold_k: float = 260.0,
        lat_dim: str = "latitude",
        lon_dim: str = "longitude",
    ) -> float | np.ndarray | xr.DataArray:
        """Fractional cloud cover from IR brightness temperature.

        Pixels colder than *threshold_k* are classified as cloudy.

        Parameters
        ----------
        ir_data : array-like
            Brightness temperature in Kelvin (2D or 3D).
        threshold_k : float
            Cloud-top temperature threshold. Default 260 K.
        lat_dim, lon_dim : str
            Spatial dimension names for xarray input.

        Returns
        -------
        float, np.ndarray, or xr.DataArray
            Cloud fraction in [0, 1]. For 3D input, returns
            the fraction along the spatial axes.
        """
        if isinstance(ir_data, xr.DataArray):
            is_cloudy = ir_data < threshold_k
            spatial_dims = [
                d for d in ir_data.dims if d in (lat_dim, lon_dim, "latitude", "longitude")
            ]
            if spatial_dims:
                result = is_cloudy.mean(dim=spatial_dims)
            else:
                result = is_cloudy.mean()
            result.name = "cloud_fraction"
            return result.astype(np.float64)

        arr = np.asarray(ir_data, dtype=np.float64)
        is_cloudy = arr < threshold_k
        return is_cloudy.mean(axis=(-2, -1) if arr.ndim >= 2 else None)
