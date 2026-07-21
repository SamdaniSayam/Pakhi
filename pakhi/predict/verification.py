"""Forecast verification metrics for weather quant applications.

Standard deterministic and probabilistic scoring functions used to
evaluate forecast skill against observations.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

__all__ = [
    "acc",
    "bias",
    "brier_score",
    "brier_skill_score",
    "discrimination",
    "mae",
    "mape",
    "reliability_diagram",
    "rmse",
    "roc_auc",
]

logger = logging.getLogger(__name__)


def _sanitize(a: np.ndarray, b: np.ndarray | None = None) -> tuple[np.ndarray, ...]:
    """Remove NaN/Inf and return cleaned arrays."""
    a = np.asarray(a, dtype=np.float64)
    if b is not None:
        b = np.asarray(b, dtype=np.float64)
        mask = np.isfinite(a) & np.isfinite(b)
        return a[mask], b[mask]
    return a[np.isfinite(a)]


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error.

    Parameters
    ----------
    y_true, y_pred : array-like
        Observed and predicted values.

    Returns
    -------
    float
        RMSE.
    """
    y_true, y_pred = _sanitize(y_true, y_pred)
    if len(y_true) == 0:
        return np.nan
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error.

    Parameters
    ----------
    y_true, y_pred : array-like
        Observed and predicted values.

    Returns
    -------
    float
        MAE.
    """
    y_true, y_pred = _sanitize(y_true, y_pred)
    if len(y_true) == 0:
        return np.nan
    return float(np.mean(np.abs(y_true - y_pred)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error.

    Parameters
    ----------
    y_true, y_pred : array-like
        Observed and predicted values.

    Returns
    -------
    float
        MAPE as a fraction (e.g. 0.05 = 5%).  Returns ``nan`` if any
        true value is zero.
    """
    y_true, y_pred = _sanitize(y_true, y_pred)
    if len(y_true) == 0:
        return np.nan
    mask = y_true != 0
    if not np.any(mask):
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def bias(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Error (bias).

    Positive bias means the forecast systematically over-predicts.

    Parameters
    ----------
    y_true, y_pred : array-like
        Observed and predicted values.

    Returns
    -------
    float
        Mean error.
    """
    y_true, y_pred = _sanitize(y_true, y_pred)
    if len(y_true) == 0:
        return np.nan
    return float(np.mean(y_pred - y_true))


def acc(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    climatology: np.ndarray | float,
) -> float:
    """Anomaly Correlation Coefficient (ACC).

    Parameters
    ----------
    y_true, y_pred : array-like
        Observed and predicted values.
    climatology : array-like or float
        Climatological mean (scalar or array broadcastable to y_true).

    Returns
    -------
    float
        ACC in ``[-1, 1]``.
    """
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    clim = np.asarray(climatology, dtype=np.float64)

    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if clim.ndim > 0:
        mask = mask & np.isfinite(clim)
    y_true = y_true[mask]
    y_pred = y_pred[mask]
    if clim.ndim > 0:
        clim = clim[mask]

    if len(y_true) < 2:
        return np.nan

    anom_true = y_true - clim
    anom_pred = y_pred - clim

    denom = np.sqrt(np.sum(anom_true**2) * np.sum(anom_pred**2))
    if denom < 1e-15:
        return np.nan

    return float(np.sum(anom_true * anom_pred) / denom)


def brier_score(y_prob: np.ndarray, y_obs: np.ndarray) -> float:
    """Brier Score for binary probabilistic forecasts.

    Lower is better.  Perfect score = 0.

    Parameters
    ----------
    y_prob : array-like
        Predicted probabilities of event.
    y_obs : array-like
        Binary observations (0 or 1).

    Returns
    -------
    float
        Brier Score.
    """
    y_prob, y_obs = _sanitize(y_prob, y_obs)
    if len(y_prob) == 0:
        return np.nan
    return float(np.mean((y_prob - y_obs) ** 2))


def brier_skill_score(
    y_prob: np.ndarray,
    y_obs: np.ndarray,
    climatology_prob: float,
) -> float:
    """Brier Skill Score relative to a climatological forecast.

    BSS = 1 - BS / BS_clim.  1 is perfect, 0 is no skill.

    Parameters
    ----------
    y_prob : array-like
        Predicted probabilities of event.
    y_obs : array-like
        Binary observations (0 or 1).
    climatology_prob : float
        Climatological probability of the event.

    Returns
    -------
    float
        Brier Skill Score.
    """
    bs = brier_score(y_prob, y_obs)
    if np.isnan(bs):
        return np.nan
    bs_clim = brier_score(
        np.full_like(np.asarray(y_prob, dtype=np.float64), climatology_prob),
        y_obs,
    )
    if abs(bs_clim) < 1e-15:
        return np.nan
    return float(1.0 - bs / bs_clim)


def reliability_diagram(
    y_prob: np.ndarray,
    y_obs: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute data for a reliability diagram.

    Parameters
    ----------
    y_prob : array-like
        Predicted probabilities.
    y_obs : array-like
        Binary observations.
    n_bins : int
        Number of probability bins.

    Returns
    -------
    dict
        Keys: ``"bin_centers"``, ``"observed_freq"``, ``"counts"``,
        ``"bin_edges"``, ``"perfection"``.
    """
    from pakhi.predict.probabilistic import ProbabilisticPredictor

    prob = ProbabilisticPredictor()
    cal = prob.calibration_curve(y_prob, y_obs, n_bins=n_bins)

    return {
        "bin_centers": cal["bin_centers"],
        "observed_freq": cal["observed_freq"],
        "counts": cal["counts"],
        "bin_edges": cal["bin_edges"],
        "perfection": cal["bin_centers"],
    }


def roc_auc(y_prob: np.ndarray, y_obs: np.ndarray) -> float:
    """Area Under the Receiver Operating Characteristic Curve.

    Parameters
    ----------
    y_prob : array-like
        Predicted probabilities.
    y_obs : array-like
        Binary observations.

    Returns
    -------
    float
        AUC in ``[0, 1]``.
    """
    y_prob, y_obs = _sanitize(y_prob, y_obs)
    if len(y_prob) == 0:
        return np.nan

    n_pos = int(np.sum(y_obs == 1))
    n_neg = int(np.sum(y_obs == 0))
    if n_pos == 0 or n_neg == 0:
        return np.nan

    order = np.argsort(y_prob)[::-1]
    y_sorted = y_obs[order]

    tpr = np.zeros(len(y_sorted) + 1)
    fpr = np.zeros(len(y_sorted) + 1)

    for i in range(len(y_sorted)):
        if y_sorted[i] == 1:
            tpr[i + 1] = tpr[i] + 1.0 / n_pos
            fpr[i + 1] = fpr[i]
        else:
            tpr[i + 1] = tpr[i]
            fpr[i + 1] = fpr[i] + 1.0 / n_neg

    tpr[-1] = 1.0
    fpr[-1] = 1.0

    auc = float(np.trapezoid(tpr, fpr))
    return max(auc, 0.0)


def discrimination(
    y_prob: np.ndarray,
    y_obs: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Discrimination diagram: separates events from non-events.

    Returns histograms of predicted probabilities for event and
    non-event cases.

    Parameters
    ----------
    y_prob : array-like
        Predicted probabilities.
    y_obs : array-like
        Binary observations.
    n_bins : int
        Number of probability bins.

    Returns
    -------
    dict
        ``"bin_edges"``, ``"event_hist"``, ``"no_event_hist"``.
    """
    y_prob, y_obs = _sanitize(y_prob, y_obs)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    event_probs = y_prob[y_obs == 1]
    no_event_probs = y_prob[y_obs == 0]

    event_hist, _ = np.histogram(event_probs, bins=bin_edges, density=True)
    no_event_hist, _ = np.histogram(no_event_probs, bins=bin_edges, density=True)

    return {
        "bin_edges": bin_edges,
        "event_hist": event_hist,
        "no_event_hist": no_event_hist,
    }
