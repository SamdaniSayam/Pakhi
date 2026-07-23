"""Naive persistence baseline model.

The persistence (or "persistence forecast") simply repeats the last observed
value for every future time step.  This is the *absolute floor* that every
skillful model must beat.  In operational NWP, "persistence" is the standard
zero-skill reference for short-range forecasts.
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, compute_metrics

__all__ = ["PersistenceModel"]

logger = logging.getLogger(__name__)


class PersistenceModel(BaseModel):
    """Naive persistence baseline: forecast = last observed value.

    For each feature, the most recent observation is repeated N steps into
    the future.  This model requires no training and serves as the
    minimum-skill reference for all other models.

    Parameters
    ----------
    forecast_horizon : int
        Number of future time steps to forecast (default 1).
    n_features : int, optional
        Number of features.  Inferred on first ``fit`` call if not set.

    Examples
    --------
    >>> model = PersistenceModel(forecast_horizon=7)
    >>> model.fit(X_train, y_train)
    >>> result = model.predict(X_test)
    """

    def __init__(
        self,
        forecast_horizon: int = 1,
        n_features: int | None = None,
    ) -> None:
        self.forecast_horizon = forecast_horizon
        self.n_features = n_features
        self._last_values: np.ndarray | None = None
        self._fitted = False

    # -- core interface ----------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> PersistenceModel:
        """Store the last observed value from the training set.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
        y : array of shape ``(n_samples,)`` or ``(n_samples, horizon)``
        X_val, y_val : ignored
            Present for API compatibility.
        """
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        if X.size == 0:
            raise ValueError("Training data X is empty.")

        if y.ndim == 1:
            self._last_values = np.array([y[-1]])
        else:
            self._last_values = y[-1].copy()

        self.n_features = self._last_values.shape[0]
        self._fitted = True
        logger.info(
            "PersistenceModel fitted: last values = %s (shape=%s)",
            self._last_values,
            self._last_values.shape,
        )
        return self

    def predict(self, X: np.ndarray) -> ForecastResult:
        """Repeat the last observed value for every row in *X*.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
            The shape of *X* determines the number of output rows.

        Returns
        -------
        ForecastResult
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        n = X.shape[0]

        # Tile the last values across all samples and forecast steps.
        deterministic = np.tile(self._last_values, (n, 1))

        return ForecastResult(
            deterministic=deterministic,
            quantiles={},
            skill_scores={},
            metadata={"model": "persistence", "last_values": self._last_values},
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Probabilistic persistence (deterministic = all quantiles).

        Persistence has zero uncertainty by construction, so every
        quantile equals the deterministic forecast.
        """
        result = self.predict(X)
        for q in quantiles:
            label = f"q{q}"
            result.quantiles[label] = result.deterministic.copy()
        return result

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
    ) -> dict[str, float]:
        """Evaluate persistence against observations."""
        result = self.predict(X)
        return compute_metrics(y, result.deterministic, metrics=metrics)

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        return f"PersistenceModel(forecast_horizon={self.forecast_horizon}, status={status})"
