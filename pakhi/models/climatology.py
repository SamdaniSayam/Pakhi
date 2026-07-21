"""Climatology baseline model and helper utilities.

Climatology is the second standard reference forecast (after persistence).
It predicts the historical daily-of-year mean, optionally corrected by the
most recent anomaly.  Like persistence, a skillful model *must* beat it
for the Brier Skill Score to be positive.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, compute_metrics

__all__ = [
    "ClimatologyModel",
    "anomalies_from_climatology",
    "seasonal_climatology",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def seasonal_climatology(
    data: np.ndarray,
    day_of_year: np.ndarray | None = None,
    period: str = "daily",
) -> dict[int, tuple[float, float]]:
    """Compute the seasonal (daily-of-year) mean and standard deviation.

    Parameters
    ----------
    data : array of shape ``(n_days,)`` or ``(n_days, n_vars)``
        Time series indexed by day-of-year.
    day_of_year : array of int, shape ``(n_days,)``
        Day-of-year (1-366) for each row.  If ``None`` a sequential index
        is used.
    period : str
        Aggregation period.  Currently only ``"daily"`` is supported.

    Returns
    -------
    dict[int, (mean, std)]
        Mapping from day-of-year to ``(mean, std)``.
    """
    data = np.asarray(data, dtype=np.float64)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    if day_of_year is None:
        day_of_year = np.arange(1, data.shape[0] + 1)
    day_of_year = np.asarray(day_of_year, dtype=int)

    clim: dict[int, tuple[float, float]] = {}
    for doy in np.unique(day_of_year):
        mask = day_of_year == doy
        subset = data[mask]
        clim[int(doy)] = (
            float(np.nanmean(subset, axis=0).mean()),
            float(np.nanstd(subset, axis=0, ddof=1).mean()) if mask.sum() > 1 else 0.0,
        )
    return clim


def anomalies_from_climatology(
    data: np.ndarray,
    climatology: dict[int, tuple[float, float]],
    day_of_year: np.ndarray | None = None,
) -> np.ndarray:
    """Subtract the climatological mean from *data*.

    Parameters
    ----------
    data : array of shape ``(n_days,)`` or ``(n_days, n_vars)``
    climatology : dict
        As returned by :func:`seasonal_climatology`.
    day_of_year : array of int

    Returns
    -------
    array
        Anomaly time series.
    """
    data = np.asarray(data, dtype=np.float64)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    if day_of_year is None:
        day_of_year = np.arange(1, data.shape[0] + 1)
    day_of_year = np.asarray(day_of_year, dtype=int)

    clim_mean = np.array([climatology.get(d, (np.nanmean(data),))[0] for d in day_of_year])
    return data - clim_mean.reshape(-1, 1)


# ---------------------------------------------------------------------------
# Model class
# ---------------------------------------------------------------------------


class ClimatologyModel(BaseModel):
    """Forecast based on the historical daily-of-year mean and uncertainty.

    During ``fit`` the model computes the daily climatological mean and
    standard deviation from the training data.  ``predict`` returns the
    climatological mean repeated for each forecast row; ``predict_proba``
    wraps this with ±k·σ bands.

    Parameters
    ----------
    n_sigma : float
        Number of standard deviations used to build quantile bands from
        the climatological std.  Default ``1.0``.
    use_anomaly_correction : bool
        If ``True``, the most recent anomaly (deviation from climatology)
        is added to the climatological forecast.

    Examples
    --------
    >>> model = ClimatologyModel()
    >>> model.fit(X_train, y_train, day_of_year=doy_train)
    >>> result = model.predict(X_test, day_of_year=doy_test)
    """

    def __init__(
        self,
        n_sigma: float = 1.0,
        use_anomaly_correction: bool = False,
    ) -> None:
        self.n_sigma = n_sigma
        self.use_anomaly_correction = use_anomaly_correction
        self._climatology: dict[int, tuple[float, float]] = {}
        self._last_anomaly: np.ndarray | None = None
        self._fitted = False

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _extract_doy(kwargs: dict[str, Any], X: np.ndarray) -> np.ndarray:
        """Pull ``day_of_year`` from kwargs or infer from X's row count."""
        if "day_of_year" in kwargs:
            return np.asarray(kwargs.pop("day_of_year"), dtype=int)
        return np.arange(1, X.shape[0] + 1)

    # -- core interface ----------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        day_of_year: np.ndarray | None = None,
    ) -> ClimatologyModel:
        """Compute the daily climatology from training data.

        Parameters
        ----------
        X : array
            Features (used only to determine sample count).
        y : array of shape ``(n_samples,)`` or ``(n_samples, n_vars)``
            Target variable whose climatology we compute.
        day_of_year : array of int, optional
            Day-of-year (1-366) for each sample.  If ``None``, a simple
            sequential index is assumed.
        """
        y = np.asarray(y, dtype=np.float64)
        if y.ndim == 1:
            y = y.reshape(-1, 1)

        if y.shape[0] < 2:
            raise ValueError("Need at least 2 samples to compute climatology.")

        if day_of_year is None:
            # Infer from row count — assume 365-day years.
            day_of_year = (np.arange(y.shape[0]) % 365) + 1
        day_of_year = np.asarray(day_of_year, dtype=int)

        self._climatology = seasonal_climatology(y, day_of_year=day_of_year)

        # Store last anomaly for correction.
        if self.use_anomaly_correction:
            last_doy = int(day_of_year[-1])
            clim_mean = self._climatology.get(last_doy, (0.0,))[0]
            self._last_anomaly = y[-1] - clim_mean

        self._fitted = True
        logger.info(
            "ClimatologyModel fitted: %d unique days, use_anomaly=%s",
            len(self._climatology),
            self.use_anomaly_correction,
        )
        return self

    def predict(
        self,
        X: np.ndarray,
        day_of_year: np.ndarray | None = None,
    ) -> ForecastResult:
        """Return the climatological mean forecast.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
        day_of_year : array of int, optional
            Day-of-year for each row in *X*.

        Returns
        -------
        ForecastResult
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float64)
        doy = np.asarray(
            day_of_year if day_of_year is not None else (np.arange(X.shape[0]) % 365) + 1,
            dtype=int,
        )

        n = X.shape[0]
        deterministic = np.zeros(n, dtype=np.float64)
        for i, d in enumerate(doy):
            clim_mean = self._climatology.get(
                int(d), (np.nanmean(list(c[0] for c in self._climatology.values())),)
            )[0]
            deterministic[i] = clim_mean

        if self.use_anomaly_correction and self._last_anomaly is not None:
            deterministic = deterministic + float(self._last_anomaly.mean())

        deterministic = deterministic.reshape(-1, 1)
        return ForecastResult(
            deterministic=deterministic,
            quantiles={},
            skill_scores={},
            metadata={"model": "climatology", "n_days_in_clim": len(self._climatology)},
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
        day_of_year: np.ndarray | None = None,
    ) -> ForecastResult:
        """Probabilistic climatology using historical std.

        Quantiles are built assuming a normal distribution centred on the
        climatological mean with the historical standard deviation.
        """
        from scipy.stats import norm  # lazy import

        result = self.predict(X, day_of_year=day_of_year)
        det = result.deterministic

        doy = np.asarray(
            day_of_year if day_of_year is not None else (np.arange(X.shape[0]) % 365) + 1,
            dtype=int,
        )

        stds = np.array([self._climatology.get(int(d), (0.0, 1.0))[1] for d in doy]).reshape(-1, 1)

        for q in quantiles:
            label = f"q{q}"
            z = norm.ppf(q)
            result.quantiles[label] = det + z * stds

        return result

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
        day_of_year: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Evaluate the climatological forecast."""
        result = self.predict(X, day_of_year=day_of_year)
        return compute_metrics(y, result.deterministic, metrics=metrics)

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        return (
            f"ClimatologyModel(n_sigma={self.n_sigma}, "
            f"use_anomaly={self.use_anomaly_correction}, status={status})"
        )
