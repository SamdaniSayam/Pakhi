"""Abstract model interface and shared utilities for Pakhi forecasting models.

Defines the contract every model must follow and provides common helpers
for scaling, splitting, and evaluation.
"""

from __future__ import annotations

import abc
import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

__all__ = [
    "BaseModel",
    "ForecastResult",
    "StandardScaler",
    "compute_metrics",
    "train_val_test_split",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ForecastResult:
    """Container returned by every model's ``predict`` / ``predict_proba``.

    Attributes
    ----------
    deterministic : np.ndarray
        Point forecast array of shape ``(n,)`` or ``(n, horizon)``.
    quantiles : dict[str, np.ndarray]
        Mapping from quantile label (e.g. ``"q0.1"``) to array of the same
        shape as *deterministic*.
    skill_scores : dict[str, float]
        Evaluation metrics computed against ground truth (may be empty if
        truth was not available).
    metadata : dict[str, Any]
        Arbitrary model-specific metadata (e.g. feature importances, training
        info).
    """

    deterministic: np.ndarray
    quantiles: dict[str, np.ndarray] = field(default_factory=dict)
    skill_scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseModel(abc.ABC):
    """Abstract interface every Pakhi forecasting model must implement.

    Sub-classes **must** override at least ``fit`` and ``predict``.
    ``predict_proba`` and ``score`` have default implementations that fall
    back to ``predict``.
    """

    # -- abstract ----------------------------------------------------------

    @abc.abstractmethod
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> None:
        """Train the model.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
            Training features.
        y : array of shape ``(n_samples,)`` or ``(n_samples, horizon)``
            Training targets.
        X_val, y_val : array, optional
            Validation data used for early stopping / hyperparameter tuning.
        """

    @abc.abstractmethod
    def predict(self, X: np.ndarray) -> ForecastResult:
        """Generate a deterministic forecast.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
            Input features.

        Returns
        -------
        ForecastResult
        """

    # -- concrete defaults -------------------------------------------------

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Generate probabilistic (quantile) forecast.

        The default implementation calls ``predict`` and returns it as the
        median (q0.5) quantile with no additional spread.  Models that
        support native quantile regression or MC dropout should override.
        """
        result = self.predict(X)
        for q in quantiles:
            label = f"q{q}"
            if label not in result.quantiles:
                result.quantiles[label] = result.deterministic.copy()
        return result

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
    ) -> dict[str, float]:
        """Evaluate model on a test set.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
        y : array of shape ``(n_samples,)`` or ``(n_samples, horizon)``
        metrics : sequence of str
            Any combination of ``"rmse"``, ``"mae"``, ``"acc"``, ``"mape"``.

        Returns
        -------
        dict[str, float]
        """
        result = self.predict(X)
        return compute_metrics(y, result.deterministic, metrics=metrics)


# ---------------------------------------------------------------------------
# StandardScaler (numpy-only, works on 1-D and 2-D)
# ---------------------------------------------------------------------------


class StandardScaler:
    """Feature scaler that mimics sklearn's ``StandardScaler`` but uses only
    NumPy so it has no hard dependency on scikit-learn.

    Parameters
    ----------
    with_mean : bool
        Center features to zero mean.
    with_std : bool
        Scale features to unit variance.
    """

    def __init__(self, with_mean: bool = True, with_std: bool = True) -> None:
        self.with_mean = with_mean
        self.with_std = with_std
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.n_features_in_: int | None = None

    def fit(self, X: np.ndarray) -> StandardScaler:
        """Compute mean and std from training data.

        Parameters
        ----------
        X : array of shape ``(n_samples,)`` or ``(n_samples, n_features)``
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        self.n_features_in_ = X.shape[1]
        self.mean_ = np.nanmean(X, axis=0) if self.with_mean else np.zeros(X.shape[1])
        std = np.nanstd(X, axis=0, ddof=0)
        std[std == 0] = 1.0  # avoid division by zero for constant columns
        self.std_ = std if self.with_std else np.ones(X.shape[1])
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Apply scaling to *X*."""
        X = np.asarray(X, dtype=np.float64)
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Call fit() before transform().")
        return (X - self.mean_) / self.std_

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        """Fit and transform in one step."""
        return self.fit(X).transform(X)

    def inverse_transform(self, X: np.ndarray) -> np.ndarray:
        """Reverse the scaling."""
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Call fit() before inverse_transform().")
        return X * self.std_ + self.mean_

    def __repr__(self) -> str:
        return (
            f"StandardScaler(with_mean={self.with_mean}, "
            f"with_std={self.with_std}, n_features_in_={self.n_features_in_})"
        )


# ---------------------------------------------------------------------------
# Temporal train / val / test split
# ---------------------------------------------------------------------------


def train_val_test_split(
    data: np.ndarray,
    *,
    train_years: int | tuple[int, int] = (2010, 2018),
    val_year: int = 2019,
    test_year: int | tuple[int, int] = 2020,
    time_index: np.ndarray | None = None,
    axis: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Temporal split that respects chronological order.

    If *time_index* is ``None`` the arrays are split by positional index
    assuming the first axis is time.  When *time_index* is supplied it
    should be an array of ``np.datetime64`` values; the split is then done
    on the year component.

    Parameters
    ----------
    data : array
        Data to split.
    train_years : int or (int, int)
        Year(s) for the training set.  If a single int *Y* is given the
        training range is everything **before** *Y*.
    val_year : int
        Year used for the validation set.
    test_year : int or (int, int)
        Year(s) for the test set.  If a single int *Y* is given the test
        range is everything **on or after** *Y*.
    time_index : array of np.datetime64, optional
        Time coordinate aligned to *axis*.
    axis : int
        Along which axis the temporal dimension lies.

    Returns
    -------
    (X_train, X_val, X_test) : tuple of arrays
    """
    data = np.asarray(data)
    if time_index is None:
        time_index = np.arange(data.shape[axis])

    time_index = np.asarray(time_index)
    years = time_index.astype("datetime64[Y]").astype(int) + 1970

    if isinstance(train_years, int):
        train_mask = years < train_years
    else:
        train_mask = (years >= train_years[0]) & (years <= train_years[1])

    val_mask = years == val_year

    if isinstance(test_year, int):
        test_mask = years >= test_year
    else:
        test_mask = (years >= test_year[0]) & (years <= test_year[1])

    def _take(mask: np.ndarray) -> np.ndarray:
        if axis == 0:
            return data[mask]
        # General case: move axis to front, slice, move back
        data_moved = np.moveaxis(data, axis, 0)
        sliced = data_moved[mask]
        return np.moveaxis(sliced, 0, axis)

    return _take(train_mask), _take(val_mask), _take(test_mask)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

_METRIC_ALIASES: dict[str, str] = {
    "rmse": "rmse",
    "mae": "mae",
    "mape": "mape",
    "acc": "acc",
    "bias": "bias",
}


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metrics: Sequence[str] = ("rmse", "mae", "acc"),
    climatology_mean: float | None = None,
) -> dict[str, float]:
    """Compute standard forecast verification metrics.

    Parameters
    ----------
    y_true, y_pred : array
        Ground truth and forecast.  NaN values are masked out.
    metrics : sequence of str
        Requested metrics.  Supported: ``"rmse"``, ``"mae"``, ``"mape"``,
        ``"acc"`` (anomaly correlation coefficient), ``"bias"``.
    climatology_mean : float, optional
        Long-term climatological mean for ACC computation.  If ``None``,
        uses the sample mean of *y_true* (less accurate but functional).

    Returns
    -------
    dict[str, float]
    """
    y_true = np.asarray(y_true, dtype=np.float64).ravel()
    y_pred = np.asarray(y_pred, dtype=np.float64).ravel()

    if y_true.shape[0] != y_pred.shape[0]:
        raise ValueError(
            f"Shape mismatch: y_true has {y_true.shape[0]} elements, y_pred has {y_pred.shape[0]}."
        )

    valid = ~(np.isnan(y_true) | np.isnan(y_pred))
    yt = y_true[valid]
    yp = y_pred[valid]

    if yt.size == 0:
        logger.warning("All values are NaN; returning NaN metrics.")
        return {m: float("nan") for m in metrics}

    results: dict[str, float] = {}
    for m in metrics:
        key = _METRIC_ALIASES.get(m, m)
        if key == "rmse":
            results[m] = float(np.sqrt(np.mean((yt - yp) ** 2)))
        elif key == "mae":
            results[m] = float(np.mean(np.abs(yt - yp)))
        elif key == "mape":
            nonzero = yt != 0
            if nonzero.sum() == 0:
                results[m] = float("nan")
            else:
                results[m] = float(np.mean(np.abs((yt[nonzero] - yp[nonzero]) / yt[nonzero])) * 100)
        elif key == "bias":
            results[m] = float(np.mean(yp - yt))
        elif key == "acc":
            # Anomaly correlation coefficient (Pearson on anomalies from climatology).
            y_bar = climatology_mean if climatology_mean is not None else np.mean(yt)
            num = np.sum((yt - y_bar) * (yp - y_bar))
            den = np.sqrt(np.sum((yt - y_bar) ** 2) * np.sum((yp - y_bar) ** 2))
            results[m] = float(num / den) if den > 0 else 0.0
        else:
            warnings.warn(f"Unknown metric '{m}', skipping.", stacklevel=2)
    return results
