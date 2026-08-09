"""Gradient-boosted tree forecaster (XGBoost / LightGBM).

Wraps both backends behind a single :class:`GradientForecaster` interface
with early-stopping, feature-importance ranking, quantile regression, and
NaN handling.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Sequence

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, compute_metrics

__all__ = ["GradientForecaster"]

logger = logging.getLogger(__name__)

Backend = Literal["xgboost", "lightgbm"]


def _lazy_import_xgboost():
    try:
        import xgboost as xgb

        return xgb
    except ImportError:
        raise ImportError(
            "XGBoost is required for backend='xgboost'. Install it with: pip install pakhi[ml]"
        ) from None


def _lazy_import_lightgbm():
    try:
        import lightgbm as lgb

        return lgb
    except ImportError:
        raise ImportError(
            "LightGBM is required for backend='lightgbm'. Install it with: pip install pakhi[ml]"
        ) from None


def _compute_feature_importance_summary(
    model: Any,
    feature_names: list[str] | None = None,
) -> dict[str, float]:
    """Build a normalised feature-importance ranking.

    Works for both XGBoost and LightGBM model objects.
    """
    raw: np.ndarray
    if hasattr(model, "feature_importances_"):
        raw = np.asarray(model.feature_importances_)
    elif hasattr(model, "get_score"):
        # XGBoost Booster
        scores = model.get_score(importance_type="gain")
        n_features = max(int(k.replace("f", "")) for k in scores) + 1 if scores else 0
        raw = np.zeros(n_features, dtype=np.float64)
        for k, v in scores.items():
            raw[int(k.replace("f", ""))] = v
    else:
        return {}

    total = raw.sum()
    if total == 0:
        total = 1.0
    importance = (raw / total).tolist()

    if feature_names is None or len(feature_names) != len(importance):
        feature_names = [f"feature_{i}" for i in range(len(importance))]

    ranking = dict(
        sorted(
            zip(feature_names, importance, strict=False),
            key=lambda kv: kv[1],
            reverse=True,
        )
    )
    return ranking


class GradientForecaster(BaseModel):
    """Gradient-boosted tree forecaster with a unified API.

    Supports both XGBoost and LightGBM backends and handles:

    * **NaN values natively** (tree-based models are invariant).
    * **Early stopping** via a validation set.
    * **Quantile regression** for probabilistic forecasts.
    * **Feature importance** extraction and ranking.

    Parameters
    ----------
    backend : ``"xgboost"`` or ``"lightgbm"``
        Which boosting library to use.
    n_estimators : int
        Maximum number of boosting rounds.
    max_depth : int
        Maximum tree depth.
    learning_rate : float
        Shrinkage rate.
    objective : str
        ``"reg:squarederror"`` (XGBoost) / ``"regression"`` (LightGBM) for
        deterministic, or ``"quantile"`` for quantile regression.
    quantiles : sequence of float
        Quantile levels for ``predict_proba``.
    early_stopping_rounds : int | None
        Patience for early stopping.  ``None`` disables.
    subsample : float
        Row subsampling ratio.
    colsample_bytree : float
        Feature subsampling ratio per tree.
    reg_alpha : float
        L1 regularisation.
    reg_lambda : float
        L2 regularisation.
    random_state : int | None
        Seed for reproducibility.
    feature_names : list[str], optional
        Names for each input feature (used in importance reports).

    Examples
    --------
    >>> model = GradientForecaster(backend="lightgbm", n_estimators=2000)
    >>> model.fit(X_train, y_train, X_val=X_val, y_val=y_val)
    >>> result = model.predict(X_test)
    """

    def __init__(
        self,
        backend: Backend = "lightgbm",
        n_estimators: int = 1000,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        objective: str = "regression",
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        early_stopping_rounds: int | None = 50,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 0.0,
        reg_lambda: float = 1.0,
        random_state: int | None = 42,
        feature_names: list[str] | None = None,
    ) -> None:
        if backend not in ("xgboost", "lightgbm"):
            raise ValueError(f"backend must be 'xgboost' or 'lightgbm', got '{backend}'")

        self.backend = backend
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.objective = objective
        self.quantiles = list(quantiles)
        self.early_stopping_rounds = early_stopping_rounds
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.random_state = random_state
        self.feature_names = feature_names

        self._models: dict[float, Any] = {}  # quantile → fitted model
        self._feature_importance: dict[str, float] = {}
        self._multioutput_models: list[Any] | None = None
        self._fitted = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_model(self, n_targets: int = 1) -> Any:
        """Construct an unfitted model for the chosen backend."""
        if self.backend == "xgboost":
            xgb = _lazy_import_xgboost()
            params: dict[str, Any] = {
                "max_depth": self.max_depth,
                "learning_rate": self.learning_rate,
                "subsample": self.subsample,
                "colsample_bytree": self.colsample_bytree,
                "reg_alpha": self.reg_alpha,
                "reg_lambda": self.reg_lambda,
                "n_estimators": self.n_estimators,
                "random_state": self.random_state,
                "verbosity": 0,
                "n_jobs": -1,
            }
            if self.objective == "quantile" and n_targets == 1:
                params["objective"] = "reg:quantileerror"
            elif n_targets > 1:
                params["objective"] = "reg:squarederror"
            else:
                params["objective"] = "reg:squarederror"
            return xgb.XGBRegressor(**params)
        else:
            lgb = _lazy_import_lightgbm()
            params = {
                "max_depth": self.max_depth,
                "learning_rate": self.learning_rate,
                "subsample": self.subsample,
                "colsample_bytree": self.colsample_bytree,
                "reg_alpha": self.reg_alpha,
                "reg_lambda": self.reg_lambda,
                "n_estimators": self.n_estimators,
                "random_state": self.random_state,
                "verbosity": -1,
                "n_jobs": -1,
            }
            if self.objective == "quantile" and n_targets == 1:
                params["objective"] = "quantile"
            else:
                params["objective"] = "regression"
            return lgb.LGBMRegressor(**params)

    def _fit_single_quantile(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None,
        y_val: np.ndarray | None,
        quantile: float | None = None,
    ) -> Any:
        """Fit one model for a single quantile (or the mean)."""
        model = self._build_model(n_targets=1)

        if self.backend == "xgboost" and quantile is not None:
            model.set_params(quantile_alpha=quantile)

        fit_kwargs: dict[str, Any] = {}
        if X_val is not None and y_val is not None:
            y_val_to_use = y_val.ravel() if y.ndim == 1 else y_val
            fit_kwargs["eval_set"] = [(X_val, y_val_to_use)]
            if self.early_stopping_rounds is not None:
                if self.backend == "xgboost":
                    model.set_params(early_stopping_rounds=self.early_stopping_rounds)
                    fit_kwargs["verbose"] = False
                else:
                    fit_kwargs["callbacks"] = [
                        self._lgb_early_stop(self.early_stopping_rounds),
                        self._lgb_log_evaluation(-1),
                    ]

        model.fit(X, y, **fit_kwargs)
        return model

    @staticmethod
    def _lgb_early_stop(patience: int):
        """Create a LightGBM early-stopping callback (lazy import)."""
        lgb = _lazy_import_lightgbm()
        return lgb.early_stopping(patience, verbose=False)

    @staticmethod
    def _lgb_log_evaluation(period: int):
        """Create a LightGBM log-evaluation callback (lazy import)."""
        lgb = _lazy_import_lightgbm()
        return lgb.log_evaluation(period)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> GradientForecaster:
        """Fit the gradient-boosted model.

        Parameters
        ----------
        X, y : array
            Training data.  NaN values are handled natively.
        X_val, y_val : array, optional
            Validation data for early stopping.
        """
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)

        if X.ndim != 2:
            raise ValueError(f"X must be 2-D, got shape {X.shape}")
        if y.ndim == 1:
            y = y.reshape(-1, 1)

        self._models = {}
        self._multioutput_models = None
        n_targets = y.shape[1]

        if self.objective == "quantile" and n_targets == 1:
            # Train one model per quantile.
            for q in self.quantiles:
                model = self._fit_single_quantile(X, y.ravel(), X_val, y_val, quantile=q)
                self._models[q] = model
                logger.info("Fitted quantile q=%.2f (%s)", q, self.backend)
        else:
            # Single deterministic model (possibly multi-output via chaining).
            if n_targets == 1:
                model = self._fit_single_quantile(X, y.ravel(), X_val, y_val)
                self._models[0.5] = model
            else:
                self._multioutput_models = []
                for col in range(n_targets):
                    m = self._fit_single_quantile(X, y[:, col], X_val, y_val)
                    self._multioutput_models.append(m)
                logger.info("Fitted multi-output model with %d targets", n_targets)

        # Feature importance from the median model (or the single model).
        ref_model = self._models.get(0.5, next(iter(self._models.values()), None))
        if ref_model is not None:
            self._feature_importance = _compute_feature_importance_summary(
                ref_model, self.feature_names
            )

        self._fitted = True
        return self

    def predict(self, X: np.ndarray) -> ForecastResult:
        """Deterministic forecast (median quantile or the single model).

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``

        Returns
        -------
        ForecastResult
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2:
            raise ValueError(f"X must be 2-D, got shape {X.shape}")

        if self._multioutput_models is not None:
            preds = np.column_stack([m.predict(X) for m in self._multioutput_models])
        else:
            # Use the median (0.5) model if available, else first available.
            model = self._models.get(0.5, next(iter(self._models.values())))
            preds = model.predict(X).reshape(-1, 1)

        return ForecastResult(
            deterministic=preds,
            quantiles={},
            skill_scores={},
            metadata={
                "model": f"gradient_{self.backend}",
                "feature_importance": self._feature_importance,
                "n_estimators": self.n_estimators,
            },
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Probabilistic forecast using quantile regression models.

        Parameters
        ----------
        X : array
        quantiles : sequence of float

        Returns
        -------
        ForecastResult
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float32)
        result = self.predict(X)
        result.quantiles = {}

        if self._multioutput_models is not None:
            # Multi-output doesn't support per-quantile models; return
            # deterministic as every quantile.
            for q in quantiles:
                result.quantiles[f"q{q}"] = result.deterministic.copy()
            return result

        for q in quantiles:
            label = f"q{q}"
            if q in self._models:
                pred_q = self._models[q].predict(X).reshape(-1, 1)
                result.quantiles[label] = pred_q
            else:
                # Fall back to the deterministic prediction.
                result.quantiles[label] = result.deterministic.copy()

        return result

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
    ) -> dict[str, float]:
        result = self.predict(X)
        return compute_metrics(y, result.deterministic, metrics=metrics)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def feature_importance(self) -> dict[str, float]:
        """Normalised feature importance ranking (descending)."""
        return self._feature_importance

    def feature_importance_top(self, n: int = 10) -> list[tuple[str, float]]:
        """Return the top-*n* most important features."""
        items = sorted(self._feature_importance.items(), key=lambda kv: kv[1], reverse=True)
        return items[:n]

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        return (
            f"GradientForecaster(backend='{self.backend}', "
            f"n_estimators={self.n_estimators}, status={status})"
        )
