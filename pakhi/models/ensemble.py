"""Ensemble forecaster — mean, BMA, stacking, and dynamic weighting.

Combines predictions from multiple fitted models to produce forecasts
that are typically more skilful and better calibrated than any single
component model.
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol, Sequence, runtime_checkable

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, compute_metrics

__all__ = ["EnsembleForecaster"]

logger = logging.getLogger(__name__)

Method = Literal["mean", "bma", "stacking"]


@runtime_checkable
class _ModelLike(Protocol):
    """Duck-type protocol for anything that looks like a BaseModel."""

    def predict(self, X: np.ndarray) -> ForecastResult: ...
    def predict_proba(self, X: np.ndarray, quantiles: Sequence[float] = ...) -> ForecastResult: ...


class EnsembleForecaster(BaseModel):
    """Combine multiple fitted models into a single forecast.

    Supported combination methods:

    * **mean** — simple arithmetic average of deterministic predictions.
    * **bma** — Bayesian Model Averaging; weights are proportional to the
      inverse RMSE of each component on a validation set (softmax-normalised).
    * **stacking** — a ridge-regression meta-learner is trained on the
      component predictions.

    Additional features:

    * **Dynamic weighting** — exponential-decay reweighting based on
      recent forecast skill.
    * **Cross-validated weight optimisation**.

    Parameters
    ----------
    models : list
        Pre-fitted model instances (must implement ``predict``).
    method : ``"mean"``, ``"bma"``, or ``"stacking"``
        Combination strategy.
    quantiles : sequence of float
        Quantile levels to propagate from component models.
    decay : float
        Exponential decay factor for dynamic reweighting (0 < decay ≤ 1).
        ``1.0`` disables dynamic weighting.
    meta_alpha : float
        Regularisation strength for the stacking meta-learner.

    Examples
    --------
    >>> ens = EnsembleForecaster(models=[lstm, xgb, gp], method="bma")
    >>> ens.fit(X_train, y_train, X_val=X_val, y_val=y_val)
    >>> result = ens.predict(X_test)
    """

    def __init__(
        self,
        models: list[_ModelLike] | None = None,
        method: Method = "mean",
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
        decay: float = 0.95,
        meta_alpha: float = 1.0,
    ) -> None:
        self.models: list[_ModelLike] = list(models) if models else []
        self.method = method
        self.quantiles = list(quantiles)
        self.decay = decay
        self.meta_alpha = meta_alpha

        self._weights: np.ndarray | None = None
        self._meta_coefs: np.ndarray | None = None
        self._meta_intercept: float = 0.0
        self._fitted = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_deterministic(self, X: np.ndarray) -> np.ndarray:
        """Run each model and stack deterministic predictions.

        Returns array of shape ``(n_models, n_samples, n_targets)``.
        """
        preds = []
        for i, m in enumerate(self.models):
            try:
                res = m.predict(X)
                p = res.deterministic
                if p.ndim == 1:
                    p = p.reshape(-1, 1)
                preds.append(p)
            except Exception as exc:
                logger.warning("Model %d predict failed: %s", i, exc)
        if not preds:
            raise RuntimeError("All models failed during predict.")
        # Pad to common shape (use zeros for failed models).
        max_cols = max(p.shape[1] for p in preds)
        aligned = []
        for p in preds:
            if p.shape[1] < max_cols:
                pad = np.zeros((p.shape[0], max_cols - p.shape[1]), dtype=p.dtype)
                p = np.concatenate([p, pad], axis=1)
            aligned.append(p)
        return np.stack(aligned, axis=0)  # (n_models, n, targets)

    def _compute_bma_weights(self, X_val: np.ndarray, y_val: np.ndarray) -> np.ndarray:
        """Weights ∝ softmax(-RMSE_i)."""
        rmses = []
        for m in self.models:
            try:
                res = m.predict(X_val)
                rmse = np.sqrt(np.nanmean((y_val.ravel() - res.deterministic.ravel()) ** 2))
            except Exception:
                rmse = 1e6
            rmses.append(rmse)
        rmses = np.array(rmses, dtype=np.float64)
        # Negative softmax: lower RMSE → higher weight.
        w = np.exp(-rmses)
        w = w / w.sum()
        return w

    def _fit_stacking_meta(self, X_val: np.ndarray, y_val: np.ndarray) -> None:
        """Train a ridge-regression meta-learner on model predictions."""
        stacked = self._collect_deterministic(X_val)  # (m, n, t)
        _n_models, n_samples, n_targets = stacked.shape

        y_val_2d = y_val.reshape(n_samples, -1)
        if y_val_2d.shape[1] != n_targets:
            raise ValueError("Target shape mismatch in stacking.")

        meta_X = stacked.transpose(1, 0, 2).reshape(n_samples, -1)  # (n, m*t)

        # Ridge regression: (X^T X + αI)^{-1} X^T y
        XtX = meta_X.T @ meta_X + self.meta_alpha * np.eye(meta_X.shape[1])
        Xty = meta_X.T @ y_val_2d
        self._meta_coefs = np.linalg.solve(XtX, Xty)  # (m*t, t)
        self._meta_intercept = np.mean(y_val_2d, axis=0) - meta_X.mean(axis=0) @ self._meta_coefs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> EnsembleForecaster:
        """Fit ensemble weights (not the component models).

        Component models must already be fitted.  This method only
        computes the combination weights.

        Parameters
        ----------
        X, y : array
            Training data (used by ``"mean"`` method only for metadata).
        X_val, y_val : array, optional
            Validation data for weight estimation.  Required for
            ``"bma"`` and ``"stacking"`` methods.
        """
        if not self.models:
            raise ValueError("No models provided to ensemble.")

        if self.method == "mean":
            n = len(self.models)
            self._weights = np.ones(n) / n
        elif self.method == "bma":
            if X_val is None or y_val is None:
                raise ValueError("X_val and y_val are required for BMA.")
            self._weights = self._compute_bma_weights(X_val, y_val)
        elif self.method == "stacking":
            if X_val is None or y_val is None:
                raise ValueError("X_val and y_val are required for stacking.")
            self._fit_stacking_meta(X_val, y_val)
            # Also compute default weights for fallback.
            self._weights = self._compute_bma_weights(X_val, y_val)
        else:
            raise ValueError(f"Unknown method '{self.method}'.")

        self._fitted = True
        logger.info(
            "EnsembleForecaster fitted (%s): weights=%s",
            self.method,
            self._weights.tolist() if self._weights is not None else "stacking",
        )
        return self

    def predict(self, X: np.ndarray) -> ForecastResult:
        """Deterministic ensemble forecast.

        Returns
        -------
        ForecastResult
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        stacked = self._collect_deterministic(X)  # (m, n, t)
        n_models, n_samples, _n_targets = stacked.shape

        if self.method == "stacking" and self._meta_coefs is not None:
            meta_X = stacked.transpose(1, 0, 2).reshape(n_samples, -1)
            # Pad if needed.
            if meta_X.shape[1] < self._meta_coefs.shape[0]:
                pad = np.zeros((n_samples, self._meta_coefs.shape[0] - meta_X.shape[1]))
                meta_X = np.concatenate([meta_X, pad], axis=1)
            det = meta_X @ self._meta_coefs + self._meta_intercept  # (n, t)
        else:
            w = self._weights
            if w is None:
                w = np.ones(n_models) / n_models
            det = np.tensordot(w, stacked, axes=1)  # (n, t)

        return ForecastResult(
            deterministic=det,
            quantiles={},
            skill_scores={},
            metadata={
                "model": f"ensemble_{self.method}",
                "weights": self._weights.tolist() if self._weights is not None else None,
                "n_models": n_models,
            },
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Probabilistic ensemble forecast.

        For ``"mean"`` / ``"bma"``: combines the component models' quantile
        predictions using the same weights.  The ensemble spread is
        additionally estimated from inter-model disagreement.
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        result = self.predict(X)

        # Collect per-model quantile predictions.
        all_q: dict[str, list[np.ndarray]] = {f"q{q}": [] for q in quantiles}
        weights_used: list[float] = []
        for i, m in enumerate(self.models):
            try:
                res_q = m.predict_proba(X, quantiles=quantiles)
                for q in quantiles:
                    label = f"q{q}"
                    if label in res_q.quantiles:
                        all_q[label].append(res_q.quantiles[label].ravel())
                    else:
                        all_q[label].append(res_q.deterministic.ravel())
                w = self._weights[i] if self._weights is not None else 1.0 / len(self.models)
                weights_used.append(w)
            except Exception as exc:
                logger.warning("Model %d predict_proba failed: %s", i, exc)

        w_arr = np.array(weights_used, dtype=np.float64)
        if w_arr.sum() > 0:
            w_arr = w_arr / w_arr.sum()

        for q in quantiles:
            label = f"q{q}"
            if all_q[label]:
                stacked_q = np.stack(all_q[label], axis=0)  # (m, n)
                result.quantiles[label] = np.tensordot(w_arr, stacked_q, axes=1).reshape(-1, 1)
            else:
                result.quantiles[label] = result.deterministic.copy()

        # Inter-model spread as additional metadata.
        stacked_det = self._collect_deterministic(X)
        inter_std = np.std(stacked_det, axis=0)
        result.metadata["inter_model_std"] = inter_std

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
    # Dynamic weighting
    # ------------------------------------------------------------------

    def retrain_weights(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        recent_skill: list[dict[str, float]] | None = None,
    ) -> None:
        """Update ensemble weights based on recent validation performance.

        Parameters
        ----------
        X_val, y_val : array
            Recent validation data.
        recent_skill : list of dict, optional
            Historical skill scores per model.  When provided, the final
            weights blend current RMSE-based weights with exponentially
            decaying historical weights.
        """
        if not self.models:
            raise ValueError("No models to reweight.")

        current_w = self._compute_bma_weights(X_val, y_val)

        if recent_skill is not None and len(recent_skill) > 0:
            hist_w = np.array([s.get("rmse", 1.0) for s in recent_skill], dtype=np.float64)
            hist_w = np.exp(-hist_w)
            if hist_w.sum() > 0:
                hist_w = hist_w / hist_w.sum()
            else:
                hist_w = np.ones(len(self.models)) / len(self.models)
            blended = self.decay * hist_w + (1 - self.decay) * current_w
            self._weights = blended / blended.sum()
        else:
            self._weights = current_w

        logger.info("Ensemble weights updated: %s", self._weights.tolist())

    def model_ranking(self, X_val: np.ndarray, y_val: np.ndarray) -> list[tuple[int, str, float]]:
        """Rank component models by RMSE on a validation set.

        Returns
        -------
        list of (index, model_repr, rmse)
            Sorted ascending by RMSE.
        """
        ranking = []
        for i, m in enumerate(self.models):
            try:
                res = m.predict(X_val)
                rmse = float(np.sqrt(np.nanmean((y_val.ravel() - res.deterministic.ravel()) ** 2)))
            except Exception:
                rmse = float("inf")
            ranking.append((i, repr(m), rmse))
        return sorted(ranking, key=lambda t: t[2])

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        return (
            f"EnsembleForecaster(n_models={len(self.models)}, "
            f"method='{self.method}', status={status})"
        )
