"""Tests for pakhi.models.gradient — gradient boosting models."""

from __future__ import annotations

import numpy as np
import pytest

from pakhi.models.gradient import GradientForecaster


def _make_data(n=200):
    np.random.seed(42)
    X = np.random.randn(n, 5)
    y = X @ np.array([1.0, 2.0, 0.5, -1.0, 0.3]) + np.random.randn(n) * 0.1
    return X, y


class TestGradientForecaster:
    def test_init_default(self):
        model = GradientForecaster()
        assert model is not None
        assert model.backend == "lightgbm"

    def test_init_xgboost(self):
        model = GradientForecaster(backend="xgboost")
        assert model.backend == "xgboost"

    def test_init_invalid_backend(self):
        with pytest.raises(ValueError, match="backend must be"):
            GradientForecaster(backend="bad")

    def test_fit_predict(self):
        X, y = _make_data()
        model = GradientForecaster(n_estimators=50, random_state=42)
        model.fit(X, y)
        result = model.predict(X)
        assert result is not None
        assert len(result.deterministic) == len(y)

    def test_score(self):
        X, y = _make_data()
        model = GradientForecaster(n_estimators=50, random_state=42)
        model.fit(X, y)
        scores = model.score(X, y)
        assert "rmse" in scores

    def test_predict_before_fit(self):
        X, _y = _make_data()
        model = GradientForecaster()
        with pytest.raises(RuntimeError):
            model.predict(X)

    def test_fit_with_nan(self):
        X, y = _make_data()
        X[10:20, 0] = np.nan
        model = GradientForecaster(n_estimators=50, random_state=42)
        model.fit(X, y)
        result = model.predict(X)
        assert result is not None

    def test_multioutput_refit_clears_stale_flag(self):
        """Refitting single-target after a multi-output fit must return (n, 1)."""
        X = np.random.randn(20, 3)
        y_multi = np.random.randn(20, 2)
        y_single = np.random.randn(20)

        class _Mock:
            def __init__(self):
                self.y = None

            def fit(self, X, y, **kwargs):
                self.y = np.asarray(y).ravel()
                return self

            def predict(self, X):
                return np.full(len(X), float(np.mean(self.y)))

            def set_params(self, **kwargs):
                return self

            @property
            def feature_importances_(self):
                return np.ones(3)

        model = GradientForecaster(n_estimators=10, random_state=42)
        model._build_model = lambda n_targets=1: _Mock()

        model.fit(X, y_multi)
        assert model.predict(X).deterministic.shape == (20, 2)

        model.fit(X, y_single)
        result = model.predict(X)
        assert result.deterministic.shape == (20, 1)
