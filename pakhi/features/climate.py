"""Climate indices and degree-day features for weather quant applications.

Provides heating/cooling/growing degree days, dry-day streaks,
frost-day counts, and heatwave detection.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import xarray as xr

__all__ = ["ClimateFeatures"]

logger = logging.getLogger(__name__)


class ClimateFeatures:
    """Climate and agricultural feature computations.

    All methods accept numpy arrays, pandas Series, or xarray DataArrays
    and return the same type.
    """

    __all__ = [
        "hdd",
        "cdd",
        "gdd",
        "dry_days",
        "frost_days",
        "heatwave_days",
    ]

    @staticmethod
    def hdd(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        base_celsius: float = 18.3,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Heating Degree Days.

        Parameters
        ----------
        temperature : array-like
            Daily mean temperature in °C.
        base_celsius : float
            Base temperature. Default 18.3 °C (ASHRAE standard).

        Returns
        -------
        Same type as input
            HDD = max(base - temperature, 0).
        """
        return ClimateFeatures._degree_days(temperature, base_celsius, mode="heating")

    @staticmethod
    def cdd(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        base_celsius: float = 18.3,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Cooling Degree Days.

        Parameters
        ----------
        temperature : array-like
            Daily mean temperature in °C.
        base_celsius : float
            Base temperature. Default 18.3 °C (ASHRAE standard).

        Returns
        -------
        Same type as input
            CDD = max(temperature - base, 0).
        """
        return ClimateFeatures._degree_days(temperature, base_celsius, mode="cooling")

    @staticmethod
    def gdd(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        base_celsius: float = 10.0,
        max_celsius: float = 30.0,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Growing Degree Days.

        Temperature is clamped to [base, max] before differencing.

        Parameters
        ----------
        temperature : array-like
            Daily mean temperature in °C.
        base_celsius : float
            Base temperature for crop growth. Default 10.0 °C.
        max_celsius : float
            Upper cutoff. Default 30.0 °C.

        Returns
        -------
        Same type as input
            GDD = clamp(T, base, max) - base.
        """
        if isinstance(temperature, xr.DataArray):
            t = temperature.clip(min=base_celsius, max=max_celsius)
            return t - base_celsius
        if isinstance(temperature, pd.Series):
            t = temperature.clip(lower=base_celsius, upper=max_celsius)
            return t - base_celsius
        t = np.asarray(temperature, dtype=np.float64)
        return np.clip(t, base_celsius, max_celsius) - base_celsius

    @staticmethod
    def dry_days(
        precipitation: float | np.ndarray | pd.Series | xr.DataArray,
        threshold_mm: float = 1.0,
        window_days: int = 30,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Count consecutive dry days within rolling windows.

        A day is "dry" when precipitation < *threshold_mm*.

        Parameters
        ----------
        precipitation : array-like
            Daily precipitation in mm.
        threshold_mm : float
            Threshold below which a day is considered dry. Default 1.0 mm.
        window_days : int
            Rolling window in days. Default 30.

        Returns
        -------
        Same type as input
            Fraction of dry days in each rolling window.
        """
        is_dry = precipitation < threshold_mm

        if isinstance(is_dry, xr.DataArray):
            time_dim = "time" if "time" in is_dry.dims else next(iter(is_dry.dims))
            return is_dry.rolling({time_dim: window_days}, min_periods=1).mean()

        if isinstance(is_dry, pd.Series):
            return is_dry.astype(float).rolling(window_days, min_periods=1).mean()

        arr = np.asarray(is_dry, dtype=np.float64)
        out = np.full_like(arr, np.nan)
        for i in range(len(arr)):
            start = max(0, i - window_days + 1)
            window = arr[start : i + 1]
            out[i] = np.nanmean(window)
        return out

    @staticmethod
    def frost_days(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        threshold_celsius: float = 0.0,
    ) -> int | np.ndarray | pd.Series | xr.DataArray:
        """Count or flag frost days (temperature <= 0 °C).

        Parameters
        ----------
        temperature : array-like
            Daily minimum or mean temperature in °C.
        threshold_celsius : float
            Frost threshold. Default 0.0 °C.

        Returns
        -------
        int, np.ndarray, pd.Series, or xr.DataArray
            Boolean array where ``True`` indicates a frost day, or an
            integer count for scalar input.
        """
        is_frost = temperature <= threshold_celsius

        if isinstance(is_frost, xr.DataArray):
            return is_frost.astype(bool)

        if isinstance(is_frost, pd.Series):
            return is_frost.astype(bool)

        arr = np.asarray(is_frost, dtype=bool)
        if arr.ndim == 0:
            return bool(arr)
        return arr

    @staticmethod
    def heatwave_days(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        threshold_celsius: float = 35.0,
        consecutive_days: int = 3,
    ) -> np.ndarray | pd.Series | xr.DataArray:
        """Detect heatwave days (consecutive days above threshold).

        Parameters
        ----------
        temperature : array-like
            Daily maximum temperature in °C.
        threshold_celsius : float
            Heatwave threshold. Default 35.0 °C.
        consecutive_days : int
            Minimum consecutive days above threshold. Default 3.

        Returns
        -------
        Same type as input (bool)
            ``True`` for days that are part of a heatwave streak.
        """
        is_hot = temperature > threshold_celsius

        if isinstance(is_hot, xr.DataArray):
            streak = ClimateFeatures._streak_xr(is_hot, consecutive_days)
            return streak

        if isinstance(is_hot, pd.Series):
            streak = ClimateFeatures._streak_pd(is_hot, consecutive_days)
            return streak

        arr = np.asarray(is_hot, dtype=bool)
        streak = ClimateFeatures._streak_np(arr, consecutive_days)
        return streak

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _degree_days(
        temperature: float | np.ndarray | pd.Series | xr.DataArray,
        base: float,
        mode: str,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        if mode == "heating":
            diff = lambda t, b: np.maximum(b - t, 0.0)  # noqa: E731
        else:
            diff = lambda t, b: np.maximum(t - b, 0.0)  # noqa: E731

        if isinstance(temperature, xr.DataArray):
            return diff(temperature, base)
        if isinstance(temperature, pd.Series):
            return diff(temperature, base)

        arr = np.asarray(temperature, dtype=np.float64)
        result = diff(arr, base)
        if result.ndim == 0:
            return float(result)
        return result

    @staticmethod
    def _streak_np(mask: np.ndarray, min_length: int) -> np.ndarray:
        result = np.zeros_like(mask, dtype=bool)
        count = 0
        start = 0
        for i, val in enumerate(mask):
            if val:
                if count == 0:
                    start = i
                count += 1
            else:
                if count >= min_length:
                    result[start:i] = True
                count = 0
        if count >= min_length:
            result[start:] = True
        return result

    @staticmethod
    def _streak_pd(series: pd.Series, min_length: int) -> pd.Series:
        arr = np.asarray(series, dtype=bool)
        result = ClimateFeatures._streak_np(arr, min_length)
        return pd.Series(result, index=series.index, dtype=bool)

    @staticmethod
    def _streak_xr(da: xr.DataArray, min_length: int) -> xr.DataArray:
        arr = np.asarray(da, dtype=bool)
        result = ClimateFeatures._streak_np(arr, min_length)
        return xr.DataArray(result, coords=da.coords, dims=da.dims, dtype=bool)
