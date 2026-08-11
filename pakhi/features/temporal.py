"""Temporal feature engineering for weather time series.

Builds lags, rolling statistics, trends, and anomaly features using
triples-sigfast primitives (rolling_average, ema, detect_anomalies).
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr
from triples_sigfast import ema, rolling_average

__all__ = ["TemporalFeatures"]

logger = logging.getLogger(__name__)

DEFAULT_LAGS = [1, 3, 6, 12, 24, 48, 72, 168]
DEFAULT_WINDOWS = [6, 12, 24, 48, 168]
DEFAULT_STATS = ["mean", "std", "min", "max", "trend", "anomaly", "ema", "rolling"]


class TemporalFeatures:
    """Comprehensive temporal feature engineering for weather variables.

    Parameters
    ----------
    lags : list of int, optional
        Lag horizons in hours. Default ``[1, 3, 6, 12, 24, 48, 72, 168]``.
    windows : list of int, optional
        Rolling window sizes in hours. Default ``[6, 12, 24, 48, 168]``.
    stats : list of str, optional
        Which statistics to compute. Subset of
        ``["mean", "std", "min", "max", "trend", "anomaly", "ema", "rolling"]``.
    ema_spans : list of int, optional
        Span values for EMA features. Default ``[12, 24, 48]``.
    """

    __all__ = ["build"]

    def __init__(
        self,
        lags: Sequence[int] | None = None,
        windows: Sequence[int] | None = None,
        stats: Sequence[str] | None = None,
        ema_spans: Sequence[int] | None = None,
    ) -> None:
        self.lags = list(lags) if lags is not None else list(DEFAULT_LAGS)
        self.windows = list(windows) if windows is not None else list(DEFAULT_WINDOWS)
        self.stats = list(stats) if stats is not None else list(DEFAULT_STATS)
        self.ema_spans = list(ema_spans) if ema_spans is not None else [12, 24, 48]
        self._warned_lengths: set[int] = set()

    def build(
        self,
        data: xr.Dataset | pd.DataFrame | pd.Series,
        variables: list[str] | None = None,
    ) -> xr.Dataset | pd.DataFrame:
        """Build temporal features for the given data.

        Parameters
        ----------
        data : xr.Dataset, pd.DataFrame, or pd.Series
            Input time series. Must have a time dimension/index.
        variables : list of str, optional
            Variables to engineer. If ``None``, uses all data variables
            (for xarray) or the single column (for pandas).

        Returns
        -------
        xr.Dataset or pd.DataFrame
            Dataset/DataFrame with all engineered features appended.
        """
        if isinstance(data, (pd.DataFrame, pd.Series)):
            return self._build_pandas(data, variables)
        return self._build_xarray(data, variables)

    def _build_xarray(self, ds: xr.Dataset, variables: list[str] | None) -> xr.Dataset:
        time_dim = "time" if "time" in ds.dims else next(iter(ds.dims))
        if variables is None:
            variables = list(ds.data_vars)

        features: dict[str, xr.DataArray] = {}

        for var in variables:
            arr = ds[var]
            if time_dim not in arr.dims:
                continue
            base = arr.astype(np.float64)

            features.update(self._lag_features_xr(base, var, time_dim))
            if (
                "mean" in self.stats
                or "std" in self.stats
                or "min" in self.stats
                or "max" in self.stats
            ):
                features.update(self._window_stats_xr(base, var, time_dim))
            if "trend" in self.stats:
                features.update(self._trend_xr(base, var, time_dim))
            if "anomaly" in self.stats:
                features.update(self._anomaly_xr(base, var, time_dim))
            if "ema" in self.stats:
                features.update(self._ema_xr(base, var, time_dim))
            if "rolling" in self.stats:
                features.update(self._rolling_xr(base, var, time_dim))

        return ds.assign(features)

    def _windows_for(self, n: int) -> list[int]:
        """Return the configured windows that fit a series of length ``n``.

        Windows larger than the series produce meaningless features and trip
        triples-sigfast's ``rolling_average`` length guard, so they are
        skipped with a warning instead of raising.
        """
        too_large = [w for w in self.windows if w > n]
        if too_large and n not in self._warned_lengths:
            self._warned_lengths.add(n)
            logger.warning(
                "Skipping windows %s: data length %d is shorter than the window size",
                too_large,
                n,
            )
        return [w for w in self.windows if w <= n]

    def _build_pandas(
        self, df: pd.DataFrame | pd.Series, variables: list[str] | None
    ) -> pd.DataFrame:
        if isinstance(df, pd.Series):
            df = df.to_frame(name=df.name or "value")

        if variables is None:
            variables = list(df.columns)

        result = df.copy()

        for var in variables:
            if var not in result.columns:
                continue
            series = result[var].astype(np.float64)

            result = pd.concat([result, self._lag_features_pd(series, var)], axis=1)
            if any(s in self.stats for s in ("mean", "std", "min", "max")):
                result = pd.concat([result, self._window_stats_pd(series, var)], axis=1)
            if "trend" in self.stats:
                result = pd.concat([result, self._trend_pd(series, var)], axis=1)
            if "anomaly" in self.stats:
                result = pd.concat([result, self._anomaly_pd(series, var)], axis=1)
            if "ema" in self.stats:
                result = pd.concat([result, self._ema_pd(series, var)], axis=1)
            if "rolling" in self.stats:
                result = pd.concat([result, self._rolling_pd(series, var)], axis=1)

        return result

    # ------------------------------------------------------------------ #
    # xarray helpers                                                       #
    # ------------------------------------------------------------------ #

    def _lag_features_xr(
        self, arr: xr.DataArray, name: str, time_dim: str
    ) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for lag in self.lags:
            features[f"{name}_lag_{lag}"] = arr.shift({time_dim: lag})
        return features

    def _window_stats_xr(
        self, arr: xr.DataArray, name: str, time_dim: str
    ) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for w in self._windows_for(arr.sizes[time_dim]):
            if "mean" in self.stats:
                features[f"{name}_rollmean_{w}"] = rolling_average(arr, w)
            if "std" in self.stats:
                features[f"{name}_rollstd_{w}"] = arr.rolling(
                    {time_dim: w}, min_periods=max(1, w // 2)
                ).std()
            if "min" in self.stats:
                features[f"{name}_rollmin_{w}"] = arr.rolling({time_dim: w}, min_periods=1).min()
            if "max" in self.stats:
                features[f"{name}_rollmax_{w}"] = arr.rolling({time_dim: w}, min_periods=1).max()
        return features

    def _trend_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        axis = arr.dims.index(time_dim)

        for w in self._windows_for(arr.sizes[time_dim]):

            def _apply_trend(a, _w=w):
                out = np.full(a.shape, np.nan)
                for i in range(_w - 1, len(a)):
                    window = a[max(0, i - _w + 1) : i + 1]
                    valid = ~np.isnan(window)
                    if valid.sum() >= 2:
                        t = np.arange(len(window))
                        coeffs = np.polyfit(t[valid], window[valid], 1)
                        out[i] = coeffs[0]
                return out

            res_values = np.apply_along_axis(_apply_trend, axis=axis, arr=arr.values)
            features[f"{name}_trend_{w}"] = xr.DataArray(
                res_values, dims=arr.dims, coords=arr.coords
            )
        return features

    def _anomaly_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for w in self._windows_for(arr.sizes[time_dim]):
            roll_mean = arr.rolling({time_dim: w}, min_periods=max(1, w // 2)).mean()
            std = arr.rolling({time_dim: w}, min_periods=max(1, w // 2)).std()
            std = std.where(std > 0, np.nan)
            zscore = (arr - roll_mean) / std
            features[f"{name}_anomaly_{w}"] = zscore
            features[f"{name}_is_anomaly_{w}"] = np.abs(zscore) > 3.0
        return features

    def _ema_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for span in self.ema_spans:
            features[f"{name}_ema_{span}"] = ema(arr, span)
        return features

    def _rolling_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for w in self._windows_for(arr.sizes[time_dim]):
            features[f"{name}_rolling_{w}"] = rolling_average(arr, w)
        return features

    # ------------------------------------------------------------------ #
    # pandas helpers                                                       #
    # ------------------------------------------------------------------ #

    def _lag_features_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for lag in self.lags:
            cols[f"{name}_lag_{lag}"] = series.shift(lag)
        return pd.DataFrame(cols, index=series.index)

    def _window_stats_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self._windows_for(len(series)):
            roll = series.rolling(w, min_periods=max(1, w // 2))
            if "mean" in self.stats:
                cols[f"{name}_rollmean_{w}"] = roll.mean()
            if "std" in self.stats:
                cols[f"{name}_rollstd_{w}"] = roll.std()
            if "min" in self.stats:
                cols[f"{name}_rollmin_{w}"] = roll.min()
            if "max" in self.stats:
                cols[f"{name}_rollmax_{w}"] = roll.max()
        return pd.DataFrame(cols, index=series.index)

    def _trend_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self._windows_for(len(series)):
            x = np.arange(w, dtype=np.float64)
            sum_x = x.sum()
            sum_x2 = (x**2).sum()
            n = float(w)
            denom = n * sum_x2 - sum_x**2

            if abs(denom) < 1e-15:
                cols[f"{name}_trend_{w}"] = pd.Series(np.nan, index=series.index)
            else:
                sum_xy = series.rolling(w, min_periods=3).apply(
                    lambda y, x=x: np.dot(x[: len(y)], y), raw=True
                )
                sum_y = series.rolling(w, min_periods=3).sum()
                cols[f"{name}_trend_{w}"] = (n * sum_xy - sum_x * sum_y) / denom
        return pd.DataFrame(cols, index=series.index)

    def _anomaly_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self._windows_for(len(series)):
            roll_mean = series.rolling(w, min_periods=max(1, w // 2)).mean()
            roll_std = series.rolling(w, min_periods=max(1, w // 2)).std()
            roll_std = roll_std.replace(0, np.nan)
            zscore = (series - roll_mean) / roll_std
            cols[f"{name}_anomaly_{w}"] = zscore
            # Use rolling z-score for detection (no future data leakage)
            cols[f"{name}_is_anomaly_{w}"] = zscore.abs() > 3.0
        return pd.DataFrame(cols, index=series.index)

    def _ema_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for span in self.ema_spans:
            arr_xr = xr.DataArray(series.values, dims=["time"])
            ema_result = ema(arr_xr, span)
            if hasattr(ema_result, "values"):
                ema_result = ema_result.values
            cols[f"{name}_ema_{span}"] = pd.Series(ema_result, index=series.index)
        return pd.DataFrame(cols, index=series.index)

    def _rolling_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self._windows_for(len(series)):
            arr_xr = xr.DataArray(series.values, dims=["time"])
            ra = rolling_average(arr_xr, w)
            if hasattr(ra, "values"):
                ra = ra.values
            padded = np.full(len(series), np.nan)
            padded[w - 1 :] = ra[: len(series) - w + 1]
            cols[f"{name}_rolling_{w}"] = pd.Series(padded, index=series.index)
        return pd.DataFrame(cols, index=series.index)
