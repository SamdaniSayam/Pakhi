"""Probabilistic prediction module for weather quant forecasting.

Provides ensemble averaging, MC dropout, quantile regression, calibration
analysis, and the Continuous Ranked Probability Score (CRPS).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import numpy as np
from scipy import stats as sp_stats

__all__ = ["ProbabilisticPredictor"]

logger = logging.getLogger(__name__)


class SupportsPredict(Protocol):
    """Protocol for models with a scikit-learn-style predict method."""

    def predict(self, X: np.ndarray) -> np.ndarray: ...


class SupportsDropout(Protocol):
    """Protocol for PyTorch-style models with train/eval modes and dropout."""

    def train(self, mode: bool = True) -> Any: ...

    def eval(self) -> Any: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...


class ProbabilisticPredictor:
    """Probabilistic forecasting: ensembles, MC dropout, quantile regression.

    Examples
    --------
    >>> prob = ProbabilisticPredictor()
    >>> result = prob.ensemble_predict(models, features, weights=[0.5, 0.5])
    >>> result = prob.mc_dropout_predict(model, features, n_forward=100)
    """

    __all__ = [
        "ensemble_predict",
        "mc_dropout_predict",
        "quantile_regression_predict",
        "calibration_curve",
        "crps",
    ]

    def ensemble_predict(
        self,
        models: list[SupportsPredict],
        features: np.ndarray,
        weights: list[float] | None = None,
    ) -> Any:
        """Weighted ensemble average over multiple models.

        Parameters
        ----------
        models : list of fitted models
            Each model must expose ``predict(X)``.
        features : array of shape ``(n_features,)`` or ``(1, n_features)``
            Input features.
        weights : list of float, optional
            Ensemble weights. Normalised to sum to 1. Uniform if ``None``.

        Returns
        -------
        ForecastResult
            Contains mean prediction and quantile spread.
        """
        from pakhi.predict.deterministic import ForecastResult

        if not models:
            raise ValueError("At least one model is required.")

        X = np.atleast_2d(np.asarray(features, dtype=np.float64))
        n_models = len(models)

        if weights is None:
            weights = np.ones(n_models) / n_models
        else:
            w = np.asarray(weights, dtype=np.float64)
            if w.sum() <= 0:
                raise ValueError("Sum of weights must be positive.")
            weights = w / w.sum()

        preds = np.array([m.predict(X).ravel()[0] for m in models], dtype=np.float64)
        weighted_mean = float(np.dot(weights, preds))
        member_std = float(np.std(preds, ddof=1)) if n_models > 1 else 0.0

        quantile_levels = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        quantiles = weighted_mean + sp_stats.norm.ppf(quantile_levels) * max(member_std, 1e-12)

        return ForecastResult(
            values=np.array([weighted_mean]),
            step_ahead=np.array([1], dtype=np.intp),
            lower=quantiles[:2],
            upper=quantiles[3:],
            metadata={
                "method": "ensemble",
                "n_models": n_models,
                "member_predictions": preds.tolist(),
                "member_std": member_std,
                "quantile_levels": quantile_levels.tolist(),
                "quantiles": quantiles.tolist(),
            },
        )

    def mc_dropout_predict(
        self,
        model: SupportsDropout,
        features: np.ndarray,
        n_forward: int = 50,
    ) -> Any:
        """Monte Carlo Dropout prediction for uncertainty estimation.

        Activates dropout at inference time to generate a distribution of
        predictions.

        Parameters
        ----------
        model : PyTorch-like model
            Must support ``train(mode)``, ``eval()``, and ``predict(X)``.
        features : array of shape ``(n_features,)`` or ``(1, n_features)``
            Input features.
        n_forward : int
            Number of stochastic forward passes. Default 50.

        Returns
        -------
        ForecastResult
            Mean prediction with quantile uncertainty bounds.
        """
        from pakhi.predict.deterministic import ForecastResult

        X = np.atleast_2d(np.asarray(features, dtype=np.float64))
        predictions = np.zeros(n_forward, dtype=np.float64)

        for i in range(n_forward):
            model.train(mode=True)
            predictions[i] = float(model.predict(X).ravel()[0])

        model.eval()

        mean_pred = float(np.mean(predictions))
        std_pred = float(np.std(predictions, ddof=1)) if n_forward > 1 else 0.0

        quantile_levels = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        quantiles = mean_pred + sp_stats.norm.ppf(quantile_levels) * max(std_pred, 1e-12)

        return ForecastResult(
            values=np.array([mean_pred]),
            step_ahead=np.array([1], dtype=np.intp),
            lower=quantiles[:2],
            upper=quantiles[3:],
            metadata={
                "method": "mc_dropout",
                "n_forward": n_forward,
                "mean": mean_pred,
                "std": std_pred,
                "quantile_levels": quantile_levels.tolist(),
                "quantiles": quantiles.tolist(),
                "raw_predictions": predictions.tolist(),
            },
        )

    def quantile_regression_predict(
        self,
        model: Any,
        features: np.ndarray,
        quantiles: list[float] | None = None,
    ) -> Any:
        """Generate quantile predictions from a quantile regression model.

        Parameters
        ----------
        model : fitted quantile regressor
            Must expose ``predict(X)`` returning quantile predictions.
        features : array of shape ``(n_features,)`` or ``(1, n_features)``
            Input features.
        quantiles : list of float, optional
            Quantile levels. Default ``[0.1, 0.25, 0.5, 0.75, 0.9]``.

        Returns
        -------
        ForecastResult
            Predictions with quantile bounds.
        """
        from pakhi.predict.deterministic import ForecastResult

        if quantiles is None:
            quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]

        X = np.atleast_2d(np.asarray(features, dtype=np.float64))
        preds = model.predict(X)
        preds = np.asarray(preds, dtype=np.float64).ravel()

        median_idx = len(quantiles) // 2
        median_pred = (
            float(preds[median_idx]) if len(preds) > median_idx else float(np.median(preds))
        )

        lower = preds[:median_idx] if median_idx > 0 else None
        upper = preds[median_idx + 1 :] if median_idx + 1 < len(preds) else None

        return ForecastResult(
            values=np.array([median_pred]),
            step_ahead=np.array([1], dtype=np.intp),
            lower=lower,
            upper=upper,
            metadata={
                "method": "quantile_regression",
                "quantile_levels": quantiles,
                "quantile_values": preds.tolist(),
            },
        )

    def calibration_curve(
        self,
        predictions: np.ndarray,
        observations: np.ndarray,
        n_bins: int = 10,
    ) -> dict[str, Any]:
        """Compute the reliability (calibration) curve.

        Parameters
        ----------
        predictions : array of shape ``(n_samples,)``
            Predicted probabilities.
        observations : array of shape ``(n_samples,)``
            Binary observed outcomes (0 or 1).
        n_bins : int
            Number of probability bins.

        Returns
        -------
        dict
            ``"bin_edges"``: edges of probability bins.
            ``"bin_centers"``: midpoints of bins.
            ``"observed_freq"``: observed event frequency per bin.
            ``"predicted_prob"``: mean predicted probability per bin.
            ``"counts"``: number of samples per bin.
        """
        predictions = np.asarray(predictions, dtype=np.float64).ravel()
        observations = np.asarray(observations, dtype=np.float64).ravel()

        mask = ~(np.isnan(predictions) | np.isnan(observations))
        predictions = predictions[mask]
        observations = observations[mask]

        if len(predictions) == 0:
            return {
                "bin_edges": np.linspace(0, 1, n_bins + 1),
                "bin_centers": np.linspace(0.5 / n_bins, 1 - 0.5 / n_bins, n_bins),
                "observed_freq": np.zeros(n_bins),
                "predicted_prob": np.linspace(0.5 / n_bins, 1 - 0.5 / n_bins, n_bins),
                "counts": np.zeros(n_bins, dtype=int),
            }

        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

        observed_freq = np.zeros(n_bins, dtype=np.float64)
        predicted_prob = np.zeros(n_bins, dtype=np.float64)
        counts = np.zeros(n_bins, dtype=int)

        for i in range(n_bins):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            if i == n_bins - 1:
                in_bin = (predictions >= lo) & (predictions <= hi)
            else:
                in_bin = (predictions >= lo) & (predictions < hi)

            counts[i] = int(np.sum(in_bin))
            if counts[i] > 0:
                observed_freq[i] = float(np.mean(observations[in_bin]))
                predicted_prob[i] = float(np.mean(predictions[in_bin]))
            else:
                observed_freq[i] = bin_centers[i]
                predicted_prob[i] = bin_centers[i]

        return {
            "bin_edges": bin_edges,
            "bin_centers": bin_centers,
            "observed_freq": observed_freq,
            "predicted_prob": predicted_prob,
            "counts": counts,
        }

    def crps(
        self,
        predictions: np.ndarray,
        observations: np.ndarray,
    ) -> float:
        """Continuous Ranked Probability Score (CRPS).

        For deterministic forecasts, CRPS reduces to MAE.  For probabilistic
        forecasts (ensemble or distributional), it evaluates the full CDF.

        Parameters
        ----------
        predictions : array of shape ``(n_samples,)`` or ``(n_samples, n_members)``
            Ensemble predictions. If 1-D, treated as deterministic.
        observations : array of shape ``(n_samples,)``
            Observed values.

        Returns
        -------
        float
            Mean CRPS over all samples.
        """
        predictions = np.asarray(predictions, dtype=np.float64)
        observations = np.asarray(observations, dtype=np.float64).ravel()

        mask = ~(np.isnan(observations))
        if predictions.ndim == 2:
            mask = mask & ~np.any(np.isnan(predictions), axis=1)
        else:
            mask = mask & ~np.isnan(predictions)

        predictions = predictions[mask]
        observations = observations[mask]

        if len(observations) == 0:
            return np.nan

        if predictions.ndim == 1:
            return float(np.mean(np.abs(predictions - observations)))

        n_samples, _n_members = predictions.shape
        total = 0.0

        for i in range(n_samples):
            obs = observations[i]
            ens = predictions[i]
            n = len(ens)

            term1 = np.mean(np.abs(ens - obs))

            abs_diffs = np.abs(ens[:, None] - ens[None, :])
            term2 = np.sum(abs_diffs) / (2 * n * n)

            total += term1 - term2

        return float(total / n_samples)
