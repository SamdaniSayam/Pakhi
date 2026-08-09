"""Deterministic prediction module for weather quant forecasting.

Provides single-step and multi-step deterministic forecasting with
threshold optimization for binary event prediction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import numpy as np

__all__ = ["DeterministicPredictor", "ForecastResult"]

logger = logging.getLogger(__name__)


class SupportsPredict(Protocol):
    """Protocol for models that support scikit-learn-style predict."""

    def predict(self, X: np.ndarray) -> np.ndarray: ...


class SupportsFitPredict(Protocol):
    """Protocol for models that support fit and predict."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> Any: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...


@dataclass
class ForecastResult:
    """Container for deterministic forecast output.

    Attributes
    ----------
    values : np.ndarray
        Point predictions of shape ``(n_steps,)`` or ``(n_steps, n_features)``.
    step_ahead : np.ndarray
        Step-ahead indices corresponding to each prediction.
    metadata : dict
        Arbitrary metadata (model name, method used, etc.).
    lower : np.ndarray or None
        Optional lower bound (e.g. from ensembles).
    upper : np.ndarray or None
        Optional upper bound.
    """

    values: np.ndarray
    step_ahead: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)
    lower: np.ndarray | None = None
    upper: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=np.float64)
        self.step_ahead = np.asarray(self.step_ahead, dtype=np.intp)
        if self.lower is not None:
            self.lower = np.asarray(self.lower, dtype=np.float64)
        if self.upper is not None:
            self.upper = np.asarray(self.upper, dtype=np.float64)


class DeterministicPredictor:
    """Deterministic forecasting with direct, recursive, and multi-output strategies.

    Examples
    --------
    >>> predictor = DeterministicPredictor()
    >>> result = predictor.predict_single(model, features, forecast_horizon=24)
    >>> result = predictor.predict_multi_step(model, features, steps=168, method="recursive")
    """

    __all__ = ["predict_single", "predict_multi_step", "optimize_threshold"]

    def predict_single(
        self,
        model: SupportsPredict,
        features: np.ndarray,
        forecast_horizon: int,
    ) -> ForecastResult:
        """Generate a single-step-ahead prediction repeated for *forecast_horizon*.

        Parameters
        ----------
        model : fitted model
            A model with a ``predict(X)`` method.
        features : array of shape ``(n_features,)`` or ``(1, n_features)``
            Input feature vector.
        forecast_horizon : int
            Number of future time steps to produce (repeated point forecast).

        Returns
        -------
        ForecastResult
            The same point forecast repeated *forecast_horizon* times.
        """
        X = np.atleast_2d(np.asarray(features, dtype=np.float64))
        pred = model.predict(X)
        values = np.full(forecast_horizon, float(pred[0]), dtype=np.float64)
        steps = np.arange(1, forecast_horizon + 1, dtype=np.intp)
        return ForecastResult(
            values=values,
            step_ahead=steps,
            metadata={"method": "single", "horizon": forecast_horizon},
        )

    def predict_multi_step(
        self,
        model: SupportsFitPredict,
        features: np.ndarray,
        steps: int,
        method: Literal["direct", "recursive", "multi_output"] = "direct",
        y_train: np.ndarray | None = None,
        X_train: np.ndarray | None = None,
    ) -> ForecastResult:
        """Multi-step-ahead forecasting using one of three strategies.

        Parameters
        ----------
        model : model instance
            A model with ``fit`` and ``predict`` methods.
        features : array of shape ``(n_features,)`` or ``(1, n_features)``
            Current feature vector.
        steps : int
            Number of future time steps.
        method : {"direct", "recursive", "multi_output"}
            Forecasting strategy.

            - ``"direct"``: fit a separate model per lead time.
            - ``"recursive"``: autoregressive — feed each prediction as input.
            - ``"multi_output"``: single model predicting all steps at once.
        y_train : array of shape ``(n_samples,)``, optional
            Training targets (required for direct and multi_output).
        X_train : array of shape ``(n_samples, n_features)``, optional
            Training features (required for direct and multi_output).

        Returns
        -------
        ForecastResult
            Predictions for each step ahead.
        """
        features = np.atleast_2d(np.asarray(features, dtype=np.float64)).copy()
        n_features = features.shape[1]

        if method == "direct":
            values = self._direct_forecast(model, features, steps, y_train, X_train)
        elif method == "recursive":
            values = self._recursive_forecast(model, features, steps)
        elif method == "multi_output":
            values = self._multi_output_forecast(model, features, steps, y_train, X_train)
        else:
            raise ValueError(
                f"Unknown method: {method!r}. Use 'direct', 'recursive', or 'multi_output'."
            )

        step_ahead = np.arange(1, steps + 1, dtype=np.intp)
        return ForecastResult(
            values=values,
            step_ahead=step_ahead,
            metadata={"method": method, "steps": steps, "n_features": n_features},
        )

    def optimize_threshold(
        self,
        model: SupportsFitPredict,
        X_val: np.ndarray,
        y_val: np.ndarray,
        metric: Literal["f1", "precision", "recall", "accuracy"] = "f1",
    ) -> float:
        """Find the optimal classification threshold on validation data.

        Parameters
        ----------
        model : fitted classifier
            A model with ``predict_proba(X)`` or ``decision_function(X)``.
        X_val : array of shape ``(n_samples, n_features)``
            Validation features.
        y_val : array of shape ``(n_samples,)``
            Validation binary labels.
        metric : {"f1", "precision", "recall", "accuracy"}
            Metric to optimise.

        Returns
        -------
        float
            Threshold that maximises the chosen metric.
        """
        X_val = np.asarray(X_val, dtype=np.float64)
        y_val = np.asarray(y_val, dtype=np.float64)

        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(X_val)
            if scores.ndim == 2:
                scores = scores[:, 1]
        elif hasattr(model, "decision_function"):
            scores = model.decision_function(X_val)
        else:
            raise TypeError("Model must have predict_proba or decision_function.")

        thresholds = np.linspace(0.0, 1.0, 201)
        best_threshold = 0.5
        best_score = -np.inf

        for t in thresholds:
            preds = (scores >= t).astype(np.float64)
            score = self._compute_metric(y_val, preds, metric)
            if score > best_score:
                best_score = score
                best_threshold = float(t)

        logger.debug(
            "Optimal threshold for %s: %.4f (score=%.4f)", metric, best_threshold, best_score
        )
        return best_threshold

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _direct_forecast(
        self,
        model: SupportsFitPredict,
        features: np.ndarray,
        steps: int,
        y_train: np.ndarray | None,
        X_train: np.ndarray | None,
    ) -> np.ndarray:
        """Direct strategy: fit a separate model per lead time."""
        if y_train is None or X_train is None:
            raise ValueError("y_train and X_train are required for the 'direct' method.")

        X_train = np.asarray(X_train, dtype=np.float64)
        y_train = np.asarray(y_train, dtype=np.float64)
        n = len(y_train)
        values = np.zeros(steps, dtype=np.float64)

        for h in range(1, steps + 1):
            if h >= n:
                values[h - 1] = np.nan
                continue
            y_h = y_train[h:]
            X_h = X_train[: len(y_h)]
            model_copy = self._clone_model(model)
            model_copy.fit(X_h, y_h)
            values[h - 1] = float(model_copy.predict(features)[0])

        return values

    def _recursive_forecast(
        self,
        model: SupportsPredict,
        features: np.ndarray,
        steps: int,
    ) -> np.ndarray:
        """Recursive (autoregressive) strategy: feed prediction as next input."""
        current = features.copy()
        values = np.zeros(steps, dtype=np.float64)

        for h in range(steps):
            pred = float(model.predict(current)[0])
            values[h] = pred
            new_row = np.roll(current, -1, axis=1)
            new_row[0, -1] = pred
            current = new_row

        return values

    def _multi_output_forecast(
        self,
        model: SupportsFitPredict,
        features: np.ndarray,
        steps: int,
        y_train: np.ndarray | None,
        X_train: np.ndarray | None,
    ) -> np.ndarray:
        """Multi-output strategy: single model predicting all steps at once."""
        if y_train is None or X_train is None:
            raise ValueError("y_train and X_train are required for the 'multi_output' method.")

        X_train = np.asarray(X_train, dtype=np.float64)
        y_train = np.asarray(y_train, dtype=np.float64)
        n = len(y_train)

        Y_matrix = np.zeros((n - steps + 1, steps), dtype=np.float64)
        for h in range(steps):
            Y_matrix[:, h] = y_train[h : h + n - steps + 1]

        X_trimmed = X_train[: n - steps + 1]
        model_copy = self._clone_model(model)
        model_copy.fit(X_trimmed, Y_matrix)
        preds = model_copy.predict(features)
        return np.asarray(preds, dtype=np.float64).ravel()[:steps]

    @staticmethod
    def _clone_model(model: Any) -> Any:
        """Clone a model via scikit-learn if available, else deepcopy."""
        try:
            from sklearn.base import clone

            return clone(model)
        except ImportError:
            import copy

            return copy.deepcopy(model)

    @staticmethod
    def _compute_metric(y_true: np.ndarray, y_pred: np.ndarray, metric: str) -> float:
        """Compute a classification metric."""
        tp = float(np.sum((y_pred == 1) & (y_true == 1)))
        fp = float(np.sum((y_pred == 1) & (y_true == 0)))
        fn = float(np.sum((y_pred == 0) & (y_true == 1)))
        tn = float(np.sum((y_pred == 0) & (y_true == 0)))

        if metric == "accuracy":
            return (tp + tn) / max(tp + fp + fn + tn, 1.0)
        elif metric == "precision":
            return tp / max(tp + fp, 1e-12)
        elif metric == "recall":
            return tp / max(tp + fn, 1e-12)
        elif metric == "f1":
            prec = tp / max(tp + fp, 1e-12)
            rec = tp / max(tp + fn, 1e-12)
            return 2 * prec * rec / max(prec + rec, 1e-12)
        else:
            raise ValueError(f"Unknown metric: {metric!r}")
