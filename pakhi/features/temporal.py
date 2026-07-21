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
from triples_sigfast import detect_anomalies, ema, rolling_average

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
        for w in self.windows:
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
        for w in self.windows:
            slope = (
                arr.rolling({time_dim: w}, min_periods=max(3, w // 2))
                .construct(time_dim)
                .polyfit(dim=time_dim, deg=1)["polyfit_coefficients"]
                .sel(degree=1)
            )
            features[f"{name}_trend_{w}"] = slope
        return features

    def _anomaly_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for w in self.windows:
            roll_mean = rolling_average(arr, w)
            std = arr.rolling({time_dim: w}, min_periods=max(1, w // 2)).std()
            std = std.where(std > 0, np.nan)
            features[f"{name}_anomaly_{w}"] = (arr - roll_mean) / std
            detect_result = detect_anomalies(arr, 3.0)
            features[f"{name}_is_anomaly_{w}"] = detect_result
        return features

    def _ema_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for span in self.ema_spans:
            features[f"{name}_ema_{span}"] = ema(arr, span, dim=time_dim)
        return features

    def _rolling_xr(self, arr: xr.DataArray, name: str, time_dim: str) -> dict[str, xr.DataArray]:
        features: dict[str, xr.DataArray] = {}
        for w in self.windows:
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
        for w in self.windows:
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
        for w in self.windows:

            def _slope(window: np.ndarray) -> float:
                if len(window) < 2 or np.all(np.isnan(window)):
                    return np.nan
                x = np.arange(len(window), dtype=np.float64)
                mask = ~np.isnan(window)
                if mask.sum() < 2:
                    return np.nan
                coeffs = np.polyfit(x[mask], window[mask], 1)
                return float(coeffs[0])

            cols[f"{name}_trend_{w}"] = series.rolling(w, min_periods=3).apply(_slope, raw=True)
        return pd.DataFrame(cols, index=series.index)

    def _anomaly_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self.windows:
            roll_mean = series.rolling(w, min_periods=max(1, w // 2)).mean()
            roll_std = series.rolling(w, min_periods=max(1, w // 2)).std()
            roll_std = roll_std.replace(0, np.nan)
            cols[f"{name}_anomaly_{w}"] = (series - roll_mean) / roll_std
            arr_np = series.values.astype(np.float64)
            detect_result = detect_anomalies(xr.DataArray(arr_np, dims=["time"]), 3.0)
            cols[f"{name}_is_anomaly_{w}"] = pd.Series(
                detect_result.values, index=series.index, dtype=bool
            )
        return pd.DataFrame(cols, index=series.index)

    def _ema_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for span in self.ema_spans:
            arr_xr = xr.DataArray(series.values, dims=["time"])
            ema_result = ema(arr_xr, span, dim="time")
            cols[f"{name}_ema_{span}"] = pd.Series(ema_result.values, index=series.index)
        return pd.DataFrame(cols, index=series.index)

    def _rolling_pd(self, series: pd.Series, name: str) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        for w in self.windows:
            arr_xr = xr.DataArray(series.values, dims=["time"])
            ra = rolling_average(arr_xr, w)
            cols[f"{name}_rolling_{w}"] = pd.Series(ra.values, index=series.index)
        return pd.DataFrame(cols, index=series.index)
