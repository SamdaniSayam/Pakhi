"""ML forecasting models for Pakhi.

Every model in this package implements the :class:`BaseModel` interface
(``fit`` → ``predict`` → ``predict_proba`` → ``score``) so they can be
swapped freely inside the ensemble or pipeline layers.

Submodules
----------
base        – Abstract interface, scaling, splitting, metrics
persistence – Naive persistence baseline
climatology – 30-year daily mean baseline
gradient    – XGBoost / LightGBM gradient-boosted trees
lstm        – BiLSTM with temporal attention (PyTorch)
gaussian    – Gaussian Process with GPyTorch / sklearn fallback
ensemble    – Mean, BMA, and stacking ensemble combiner
"""

from __future__ import annotations

from pakhi.models.base import (
    BaseModel,
    ForecastResult,
    StandardScaler,
    compute_metrics,
    train_val_test_split,
)
from pakhi.models.climatology import (
    ClimatologyModel,
    anomalies_from_climatology,
    seasonal_climatology,
)
from pakhi.models.gradient import GradientForecaster
from pakhi.models.persistence import PersistenceModel


# Lazy imports — these pull in heavy optional dependencies.
def __getattr__(name: str):
    if name == "LSTMForecaster":
        from pakhi.models.lstm import LSTMForecaster

        return LSTMForecaster
    if name == "GaussianForecaster":
        from pakhi.models.gaussian import GaussianForecaster

        return GaussianForecaster
    if name == "EnsembleForecaster":
        from pakhi.models.ensemble import EnsembleForecaster

        return EnsembleForecaster
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseModel",
    "ClimatologyModel",
    "EnsembleForecaster",
    "ForecastResult",
    "GaussianForecaster",
    "GradientForecaster",
    "LSTMForecaster",
    "PersistenceModel",
    "StandardScaler",
    "anomalies_from_climatology",
    "compute_metrics",
    "seasonal_climatology",
    "train_val_test_split",
]
