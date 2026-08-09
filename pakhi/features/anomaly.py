"""Anomaly detection features for weather data.

Provides standardized anomalies, percentile ranks, departures from
normal, and the Standardized Precipitation Index (SPI).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import xarray as xr
from scipy import stats

__all__ = ["AnomalyFeatures"]

logger = logging.getLogger(__name__)


class AnomalyFeatures:
    """Anomaly and departure-based feature engineering.

    All methods handle NaN values transparently using masked operations.
    """

    __all__ = [
        "zscore_anomaly",
        "percentile_rank",
        "departure_from_normal",
        "spi",
    ]

    @staticmethod
    def zscore_anomaly(
        data: float | np.ndarray | pd.Series | xr.DataArray,
        climatology_mean: float | np.ndarray | pd.Series | xr.DataArray,
        climatology_std: float | np.ndarray | pd.Series | xr.DataArray,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Standardized anomaly (z-score).

        Parameters
        ----------
        data : array-like
            Observed values.
        climatology_mean : array-like
            Climatological mean (same shape or broadcastable).
        climatology_std : array-like
            Climatological standard deviation.

        Returns
        -------
        Same type as input
            ``(data - climatology_mean) / climatology_std``.
            Where std is zero or NaN the result is NaN.
        """
        if isinstance(data, xr.DataArray):
            std = climatology_std.where(climatology_std > 0, np.nan)
            return (data - climatology_mean) / std

        if isinstance(data, pd.Series):
            std = np.where(climatology_std > 0, climatology_std, np.nan)
            return (data - climatology_mean) / std

        arr = np.asarray(data, dtype=np.float64)
        mean = np.asarray(climatology_mean, dtype=np.float64)
        std = np.asarray(climatology_std, dtype=np.float64)
        std = np.where(std > 0, std, np.nan)
        return (arr - mean) / std

    @staticmethod
    def percentile_rank(
        data: float | np.ndarray | pd.Series | xr.DataArray,
        historical_data: np.ndarray | pd.Series | xr.DataArray,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Percentile rank of *data* within *historical_data*.

        NaN values are excluded from the historical distribution.

        Parameters
        ----------
        data : array-like
            Value(s) to rank.
        historical_data : array-like
            Historical distribution to rank against.

        Returns
        -------
        Same type as input
            Percentile rank in [0, 100].
        """
        hist_flat = np.asarray(historical_data, dtype=np.float64).ravel()
        hist_flat = hist_flat[~np.isnan(hist_flat)]

        if len(hist_flat) == 0:
            return np.nan if np.ndim(data) == 0 else np.full_like(data, np.nan)

        if isinstance(data, xr.DataArray):
            result = xr.apply_ufunc(
                lambda x: stats.percentileofscore(hist_flat, x),
                data,
                dask="parallelized",
                output_dtypes=[float],
            )
            return result

        if isinstance(data, pd.Series):
            return data.apply(lambda x: stats.percentileofscore(hist_flat, x))

        arr = np.asarray(data, dtype=np.float64)
        scalar = arr.ndim == 0
        arr = np.atleast_1d(arr)
        result = np.array([stats.percentileofscore(hist_flat, v) for v in arr.ravel()])
        result = result.reshape(arr.shape)
        if scalar:
            return float(result[0])
        return result

    @staticmethod
    def departure_from_normal(
        data: float | np.ndarray | pd.Series | xr.DataArray,
        normal_period_mean: float | np.ndarray | pd.Series | xr.DataArray,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Simple departure from normal (anomaly).

        Parameters
        ----------
        data : array-like
            Observed values.
        normal_period_mean : array-like
            Mean of the normal/reference period.

        Returns
        -------
        Same type as input
            ``data - normal_period_mean``.
        """
        return data - normal_period_mean

    @staticmethod
    def spi(
        precipitation: float | np.ndarray | pd.Series | xr.DataArray,
        window_days: int = 30,
    ) -> float | np.ndarray | pd.Series | xr.DataArray:
        """Standardized Precipitation Index (SPI).

        Fits a gamma distribution to cumulative precipitation over
        *window_days* and transforms to standard normal.

        Parameters
        ----------
        precipitation : array-like
            Daily precipitation in mm. Must be non-negative.
        window_days : int
            Accumulation window in days. Default 30.

        Returns
        -------
        Same type as input
            SPI values (standard normal deviates). Positive = wet,
            negative = dry.

        References
        ----------
        McKee, T.B., Doesken, N.J., & Kleist, J. (1993).
        The relationship of drought frequency and duration to time scales.
        """
        if isinstance(precipitation, xr.DataArray):
            return _spi_xr(precipitation, window_days)
        if isinstance(precipitation, pd.Series):
            return _spi_pd(precipitation, window_days)
        return _spi_np(np.asarray(precipitation, dtype=np.float64), window_days)


def _spi_np(precip: np.ndarray, window: int, fit_window: int = 365) -> np.ndarray:
    """Compute SPI for a numpy array.

    Uses a rolling window for gamma distribution fitting to avoid
    data leakage — at time *t*, only data up to *t* is used.
    """
    n = len(precip)
    spi_vals = np.full(n, np.nan)

    # Accumulate precipitation over the rolling window
    accum = np.full(n, np.nan)
    for i in range(n):
        start = max(0, i - window + 1)
        vals = precip[start : i + 1]
        if np.all(np.isnan(vals)):
            continue
        accum[i] = np.nansum(vals)

    # Rolling SPI: at each time t, fit gamma using only accum[:t+1]
    min_obs = max(10, window)
    for i in range(n):
        if np.isnan(accum[i]):
            continue
        if accum[i] <= 0:
            spi_vals[i] = 0.0  # zero precipitation → near-normal
            continue

        # Use up to fit_window historical observations (no future data)
        fit_start = max(0, i - fit_window + 1)
        fit_data = accum[fit_start : i + 1]
        valid_fit = fit_data[~np.isnan(fit_data) & (fit_data > 0)]

        if len(valid_fit) < min_obs:
            continue

        try:
            shape, loc, scale = stats.gamma.fit(valid_fit, floc=0)
        except (ValueError, RuntimeError):
            continue

        cdf = stats.gamma.cdf(accum[i], a=shape, loc=loc, scale=scale)
        cdf = float(np.clip(cdf, 1e-6, 1 - 1e-6))
        spi_vals[i] = float(stats.norm.ppf(cdf))

    return spi_vals


def _spi_pd(precip: pd.Series, window: int) -> pd.Series:
    result = _spi_np(precip.values.astype(np.float64), window)
    return pd.Series(result, index=precip.index, name=f"spi_{window}")


def _spi_xr(precip: xr.DataArray, window: int) -> xr.DataArray:
    time_dim = "time" if "time" in precip.dims else next(iter(precip.dims))

    def _apply_spi(arr: np.ndarray) -> np.ndarray:
        original_shape = arr.shape
        time_len = original_shape[-1]
        flat = arr.reshape(-1, time_len)
        result = np.empty_like(flat)
        for i in range(flat.shape[0]):
            result[i] = _spi_np(flat[i], window)
        return result.reshape(original_shape)

    result = xr.apply_ufunc(
        _apply_spi,
        precip,
        input_core_dims=[[time_dim]],
        output_core_dims=[[time_dim]],
        dask="parallelized",
        dask_gufunc_kwargs={"allow_rechunk": True},
        output_dtypes=[float],
    )
    result.name = f"spi_{window}"
    return result
