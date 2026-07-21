"""Tests for ML models in pakhi.models."""

from __future__ import annotations

import numpy as np
import pytest

from pakhi.models.base import (
    ForecastResult,
    StandardScaler,
    compute_metrics,
    train_val_test_split,
)
from pakhi.models.climatology import ClimatologyModel, seasonal_climatology
from pakhi.models.persistence import PersistenceModel

# ---------------------------------------------------------------------------
# PersistenceModel
# ---------------------------------------------------------------------------


class TestPersistenceModel:
    def test_fit_predict(self):
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model = PersistenceModel(forecast_horizon=1)
        model.fit(X, y)

        X_test = np.random.randn(10, 3)
        result = model.predict(X_test)
        assert isinstance(result, ForecastResult)
        assert result.deterministic.shape == (10, 1)
        # All rows should equal the last y value
        np.testing.assert_allclose(result.deterministic[:, 0], y[-1], rtol=1e-10)

    def test_fit_multi_target(self):
        X = np.random.randn(50, 3)
        y = np.random.randn(50, 2)
        model = PersistenceModel()
        model.fit(X, y)
        result = model.predict(np.random.randn(5, 3))
        assert result.deterministic.shape == (5, 2)
        np.testing.assert_allclose(result.deterministic[0], y[-1])

    def test_predict_before_fit_raises(self):
        model = PersistenceModel()
        with pytest.raises(RuntimeError, match="Call fit"):
            model.predict(np.zeros((5, 3)))

    def test_fit_empty_raises(self):
        model = PersistenceModel()
        with pytest.raises(ValueError, match="empty"):
            model.fit(np.array([]), np.array([]))

    def test_predict_proba(self):
        X = np.random.randn(10, 3)
        y = np.random.randn(20)
        model = PersistenceModel()
        model.fit(X, y)
        result = model.predict_proba(X)
        assert "q0.5" in result.quantiles

    def test_repr(self):
        model = PersistenceModel()
        assert "not fitted" in repr(model)
        model.fit(np.zeros((5, 1)), np.zeros(5))
        assert "fitted" in repr(model)


# ---------------------------------------------------------------------------
# ClimatologyModel
# ---------------------------------------------------------------------------


class TestClimatologyModel:
    def test_fit_predict(self):
        rng = np.random.default_rng(42)
        y = 10.0 + 5.0 * np.sin(2 * np.pi * np.arange(100) / 365.0) + rng.normal(0, 1, 100)
        doy = (np.arange(100) % 365) + 1
        X = np.zeros((100, 1))

        model = ClimatologyModel()
        model.fit(X, y, day_of_year=doy)
        result = model.predict(X[:5], day_of_year=doy[:5])
        assert result.deterministic.shape == (5, 1)

    def test_predict_before_fit_raises(self):
        model = ClimatologyModel()
        with pytest.raises(RuntimeError, match="Call fit"):
            model.predict(np.zeros((5, 1)))

    def test_seasonal_climatology(self):
        data = np.array([10.0, 20.0, 30.0, 10.0, 20.0, 30.0])
        doy = np.array([1, 1, 1, 2, 2, 2])
        clim = seasonal_climatology(data, day_of_year=doy)
        assert 1 in clim
        assert 2 in clim
        assert clim[1][0] == pytest.approx(20.0)
        assert clim[2][0] == pytest.approx(20.0)

    def test_anomaly_correction(self):
        rng = np.random.default_rng(0)
        y = 10.0 + rng.normal(0, 1, 50)
        doy = (np.arange(50) % 365) + 1
        X = np.zeros((50, 1))
        model = ClimatologyModel(use_anomaly_correction=True)
        model.fit(X, y, day_of_year=doy)
        result = model.predict(X[:5], day_of_year=doy[:5])
        assert result.deterministic.shape == (5, 1)

    def test_repr(self):
        model = ClimatologyModel()
        assert "not fitted" in repr(model)


# ---------------------------------------------------------------------------
# StandardScaler
# ---------------------------------------------------------------------------


class TestStandardScaler:
    def test_fit_transform(self):
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=float)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        assert X_scaled.shape == X.shape
        np.testing.assert_allclose(X_scaled.mean(axis=0), 0.0, atol=1e-10)

    def test_inverse_transform(self):
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=float)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        X_back = scaler.inverse_transform(X_scaled)
        np.testing.assert_allclose(X_back, X, atol=1e-10)

    def test_transform_before_fit_raises(self):
        scaler = StandardScaler()
        with pytest.raises(RuntimeError, match="Call fit"):
            scaler.transform(np.zeros((3, 2)))


# ---------------------------------------------------------------------------
# train_val_test_split
# ---------------------------------------------------------------------------


class TestTrainValTestSplit:
    def test_basic_split(self):
        data = np.arange(1000)
        train, val, test = train_val_test_split(
            data,
            train_years=(2010, 2018),
            val_year=2019,
            test_year=2020,
        )
        assert len(train) > 0
        assert len(val) > 0
        assert len(test) > 0

    def test_shapes_2d(self):
        data = np.random.randn(1000, 5)
        train, val, test = train_val_test_split(data)
        assert train.shape[1] == 5
        assert val.shape[1] == 5
        assert test.shape[1] == 5

    def test_chronological_order(self):
        data = np.arange(1000)
        time_index = np.array(
            np.datetime64("2010-01-01") + np.arange(1000) * np.timedelta64(1, "D")
        )
        train, val, test = train_val_test_split(
            data,
            time_index=time_index,
        )
        if len(train) > 0 and len(val) > 0:
            assert train[-1] < val[0]
        if len(val) > 0 and len(test) > 0:
            assert val[-1] < test[0]


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def test_identity(self):
        y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        metrics = compute_metrics(y, y)
        assert metrics["rmse"] == pytest.approx(0.0)
        assert metrics["mae"] == pytest.approx(0.0)

    def test_known_rmse(self):
        y_true = np.array([0.0, 0.0, 0.0])
        y_pred = np.array([1.0, -1.0, 0.0])
        metrics = compute_metrics(y_true, y_pred)
        assert metrics["rmse"] == pytest.approx(np.sqrt(2.0 / 3.0))

    def test_bias(self):
        y_true = np.array([10.0, 10.0, 10.0])
        y_pred = np.array([12.0, 12.0, 12.0])
        metrics = compute_metrics(y_true, y_pred, metrics=["bias"])
        assert metrics["bias"] == pytest.approx(2.0)

    def test_nan_handling(self):
        y_true = np.array([1.0, np.nan, 3.0])
        y_pred = np.array([1.0, 2.0, 3.0])
        metrics = compute_metrics(y_true, y_pred)
        assert metrics["rmse"] == pytest.approx(0.0)

    def test_mape(self):
        y_true = np.array([100.0, 200.0])
        y_pred = np.array([110.0, 190.0])
        metrics = compute_metrics(y_true, y_pred, metrics=["mape"])
        assert metrics["mape"] == pytest.approx(7.5)

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="Shape mismatch"):
            compute_metrics(np.array([1, 2]), np.array([1, 2, 3]))

    def test_acc(self):
        y = np.array([1, 2, 3, 4, 5.0])
        metrics = compute_metrics(y, y, metrics=["acc"])
        assert metrics["acc"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# GradientForecaster (skip if not installed)
# ---------------------------------------------------------------------------


class TestGradientForecaster:
    def test_import_error(self):
        try:
            import xgboost  # noqa: F401

            has_xgb = True
        except ImportError:
            has_xgb = False

        if not has_xgb:
            pytest.skip("xgboost not installed")

        from pakhi.models.gradient import GradientForecaster

        rng = np.random.default_rng(42)
        X = rng.random((100, 5))
        y = X @ rng.random(5) + rng.normal(0, 0.1, 100)
        model = GradientForecaster(backend="xgboost", n_estimators=10, max_depth=3)
        model.fit(X, y)
        result = model.predict(X[:10])
        assert result.deterministic.shape == (10, 1)

    def test_invalid_backend_raises(self):
        try:
            from pakhi.models.gradient import GradientForecaster

            with pytest.raises(ValueError, match="backend must be"):
                GradientForecaster(backend="invalid")
        except ImportError:
            pytest.skip("gradient module not importable")
