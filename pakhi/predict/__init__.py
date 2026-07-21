"""Prediction module — deterministic, probabilistic, and multi-step forecasting.

Submodules
----------
deterministic
    Point forecasts via direct, recursive, and multi-output strategies.
probabilistic
    Ensemble, MC dropout, and quantile-based uncertainty estimation.
multi_step
    Autoregressive rollout with momentum/decay and progressive blurring.
verification
    Standard forecast verification metrics (RMSE, ACC, Brier, CRPS, etc.).
"""

from __future__ import annotations

from pakhi.predict.deterministic import DeterministicPredictor, ForecastResult
from pakhi.predict.multi_step import MultiStepForecaster, RolloutResult
from pakhi.predict.probabilistic import ProbabilisticPredictor
from pakhi.predict.verification import (
    acc,
    bias,
    brier_score,
    brier_skill_score,
    discrimination,
    mae,
    mape,
    reliability_diagram,
    rmse,
    roc_auc,
)

__all__ = [
    "DeterministicPredictor",
    "ForecastResult",
    "MultiStepForecaster",
    "ProbabilisticPredictor",
    "RolloutResult",
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
