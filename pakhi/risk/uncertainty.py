"""Uncertainty quantification metrics for probabilistic forecasts.

Measures the quality of uncertainty estimates: ensemble spread,
calibration error, sharpness, and coverage.
"""

from __future__ import annotations

import logging

import numpy as np

__all__ = [
    "calibration_error",
    "coverage",
    "ensemble_spread",
    "sharpness",
]

logger = logging.getLogger(__name__)


def ensemble_spread(ensemble_forecasts: np.ndarray) -> float:
    """Standard deviation across ensemble members.

    A measure of forecast disagreement / uncertainty.

    Parameters
    ----------
    ensemble_forecasts : array of shape ``(n_members,)`` or ``(n_samples, n_members)``
        Ensemble forecasts.

    Returns
    -------
    float
        Mean ensemble spread (std across members), or per-sample spread
        array.
    """
    arr = np.asarray(ensemble_forecasts, dtype=np.float64)
    arr = arr[np.isfinite(arr)]

    if arr.size == 0:
        return np.nan

    if arr.ndim == 1:
        if len(arr) < 2:
            return 0.0
        return float(np.std(arr, ddof=1))

    spreads = np.std(arr, axis=1, ddof=1)
    return float(np.mean(spreads))


def calibration_error(
    predicted_probs: np.ndarray,
    observed_freq: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error (ECE).

    Parameters
    ----------
    predicted_probs : array-like
        Mean predicted probability per bin.
    observed_freq : array-like
        Observed frequency per bin.
    n_bins : int
        Number of bins used.

    Returns
    -------
    float
        Mean absolute difference between predicted and observed
        frequencies, weighted by bin counts (if provided) or unweighted.
    """
    pred = np.asarray(predicted_probs, dtype=np.float64)
    obs = np.asarray(observed_freq, dtype=np.float64)

    mask = np.isfinite(pred) & np.isfinite(obs)
    pred = pred[mask]
    obs = obs[mask]

    if len(pred) == 0:
        return np.nan

    if n_bins == 0:
        return 0.0

    return float(np.mean(np.abs(pred - obs)))


def sharpness(forecast_quantiles: np.ndarray) -> float:
    """Sharpness: width of prediction intervals.

    Narrower intervals indicate sharper (more precise) forecasts.
    This is the width of the central 80% interval (10th–90th percentile).

    Parameters
    ----------
    forecast_quantiles : array-like
        Quantile values, typically ``[q10, q25, q50, q75, q90]``.

    Returns
    -------
    float
        Width of the central 80% prediction interval.
    """
    q = np.asarray(forecast_quantiles, dtype=np.float64)
    q = q[np.isfinite(q)]

    if len(q) < 2:
        return np.nan

    if len(q) >= 5:
        return float(q[-1] - q[0])
    return float(q[-1] - q[0])


def coverage(
    forecast_quantiles_lower: np.ndarray,
    forecast_quantiles_upper: np.ndarray,
    observations: np.ndarray,
) -> float:
    """Empirical coverage of prediction intervals.

    Fraction of observations falling within the predicted interval.

    Parameters
    ----------
    forecast_quantiles_lower : array-like
        Lower bound of prediction interval per sample.
    forecast_quantiles_upper : array-like
        Upper bound of prediction interval per sample.
    observations : array-like
        Observed values.

    Returns
    -------
    float
        Coverage fraction in ``[0, 1]``.
    """
    lower = np.asarray(forecast_quantiles_lower, dtype=np.float64)
    upper = np.asarray(forecast_quantiles_upper, dtype=np.float64)
    obs = np.asarray(observations, dtype=np.float64)

    mask = np.isfinite(lower) & np.isfinite(upper) & np.isfinite(obs)
    lower = lower[mask]
    upper = upper[mask]
    obs = obs[mask]

    if len(obs) == 0:
        return np.nan

    within = np.sum((obs >= lower) & (obs <= upper))
    return float(within / len(obs))
