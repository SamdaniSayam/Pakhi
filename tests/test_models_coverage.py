"""Comprehensive tests for all pakhi.models modules — coverage gaps."""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

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
from pakhi.models.persistence import PersistenceModel

# ---------------------------------------------------------------------------
# Helper: simple concrete BaseModel subclass
# ---------------------------------------------------------------------------


class _DummyModel(BaseModel):
    def __init__(self, pred_value: float = 1.0):
        self.pred_value = pred_value
        self._fitted = False

    def fit(self, X, y, X_val=None, y_val=None):
        self._fitted = True
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=np.float64)
        return ForecastResult(
            deterministic=np.full((X.shape[0], 1), self.pred_value),
            quantiles={},
            skill_scores={},
            metadata={},
        )


# ===================================================================
# base.py
# ===================================================================


class TestBaseModelSubclass:
    def test_fit_and_predict(self):
        m = _DummyModel(pred_value=42.0)
        m.fit(np.zeros((5, 3)), np.zeros(5))
        res = m.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)
        np.testing.assert_allclose(res.deterministic[:, 0], 42.0)

    def test_predict_proba_default_implementation(self):
        m = _DummyModel(pred_value=5.0)
        m.fit(np.zeros((5, 3)), np.zeros(5))
        res = m.predict_proba(np.ones((3, 3)), quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in res.quantiles
        assert "q0.5" in res.quantiles
        assert "q0.9" in res.quantiles
        for q in ["q0.1", "q0.5", "q0.9"]:
            np.testing.assert_allclose(res.quantiles[q][:, 0], 5.0)

    def test_predict_proba_preserves_existing_quantiles(self):
        """predict_proba calls predict() internally, so it starts fresh."""
        m = _DummyModel(pred_value=5.0)
        m.fit(np.zeros((5, 3)), np.zeros(5))
        # predict_proba adds all requested quantiles
        res = m.predict_proba(np.ones((3, 3)), quantiles=[0.5])
        assert "q0.5" in res.quantiles
        np.testing.assert_allclose(res.quantiles["q0.5"][:, 0], 5.0)

    def test_score(self):
        m = _DummyModel(pred_value=3.0)
        m.fit(np.zeros((5, 3)), np.zeros(5))
        scores = m.score(np.ones((5, 3)), np.full(5, 3.0))
        assert "rmse" in scores
        assert scores["rmse"] == pytest.approx(0.0)


class TestStandardScalerExtended:
    def test_1d_input(self):
        scaler = StandardScaler()
        X = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        X_scaled = scaler.fit_transform(X)
        # 1D input stays 1D after transform since fit reshapes internally
        assert scaler.n_features_in_ == 1
        assert X_scaled.ndim == 1
        assert X_scaled.shape[0] == 5

    def test_with_mean_false(self):
        scaler = StandardScaler(with_mean=False, with_std=True)
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=float)
        X_scaled = scaler.fit_transform(X)
        assert scaler.mean_ is not None
        np.testing.assert_allclose(scaler.mean_, 0.0)
        assert np.all(np.abs(X_scaled.mean(axis=0)) > 0)

    def test_with_std_false(self):
        scaler = StandardScaler(with_mean=True, with_std=False)
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=float)
        X_scaled = scaler.fit_transform(X)
        np.testing.assert_allclose(scaler.std_, np.ones(2))
        np.testing.assert_allclose(X_scaled.mean(axis=0), 0.0, atol=1e-10)

    def test_with_both_false(self):
        scaler = StandardScaler(with_mean=False, with_std=False)
        X = np.array([[1, 2], [3, 4]], dtype=float)
        X_scaled = scaler.fit_transform(X)
        np.testing.assert_allclose(X_scaled, X)

    def test_constant_column(self):
        scaler = StandardScaler()
        X = np.array([[5, 1], [5, 2], [5, 3]], dtype=float)
        X_scaled = scaler.fit_transform(X)
        np.testing.assert_allclose(X_scaled[:, 0], 0.0, atol=1e-10)
        assert scaler.std_[0] == 1.0

    def test_inverse_transform_before_fit_raises(self):
        scaler = StandardScaler()
        with pytest.raises(RuntimeError, match="Call fit"):
            scaler.inverse_transform(np.zeros((3, 2)))

    def test_repr(self):
        scaler = StandardScaler()
        scaler.fit(np.zeros((3, 2)))
        r = repr(scaler)
        assert "StandardScaler" in r
        assert "n_features_in_=2" in r

    def test_nan_handling(self):
        scaler = StandardScaler()
        X = np.array([[1, np.nan], [3, 4], [5, 6]], dtype=float)
        X_scaled = scaler.fit_transform(X)
        assert X_scaled.shape == (3, 2)


class TestTrainValTestSplitExtended:
    def test_single_int_train_years(self):
        dates = np.array([np.datetime64(f"{y}-01-01") for y in range(2010, 2022)])
        data = np.arange(len(dates))
        train, _val, test = train_val_test_split(
            data,
            train_years=2018,
            val_year=2019,
            test_year=2020,
            time_index=dates,
        )
        assert len(train) > 0
        assert len(test) > 0

    def test_tuple_test_year(self):
        dates = np.array([np.datetime64(f"{y}-01-01") for y in range(2010, 2023)])
        data = np.arange(len(dates))
        train, _val, test = train_val_test_split(
            data,
            train_years=(2010, 2018),
            val_year=2019,
            test_year=(2020, 2021),
            time_index=dates,
        )
        assert len(train) > 0
        assert len(test) > 0

    def test_axis_parameter(self):
        data = np.random.randn(100, 3, 4)
        time_index = np.array(
            [np.datetime64("2010-01-01") + np.timedelta64(i, "D") for i in range(100)]
        )
        train, _val, _test = train_val_test_split(
            data,
            time_index=time_index,
            axis=0,
        )
        assert train.shape[0] > 0

    def test_no_time_index(self):
        data = np.arange(200)
        train, _val, _test = train_val_test_split(data)
        assert len(train) >= 0


class TestComputeMetricsExtended:
    def test_all_nan(self):
        y_true = np.array([np.nan, np.nan, np.nan])
        y_pred = np.array([1.0, 2.0, 3.0])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            metrics = compute_metrics(y_true, y_pred, metrics=["rmse", "mae"])
        assert np.isnan(metrics["rmse"])
        assert np.isnan(metrics["mae"])

    def test_mape_all_zeros(self):
        y_true = np.array([0.0, 0.0, 0.0])
        y_pred = np.array([1.0, 2.0, 3.0])
        metrics = compute_metrics(y_true, y_pred, metrics=["mape"])
        assert np.isnan(metrics["mape"])

    def test_unknown_metric_warns(self):
        y = np.array([1.0, 2.0, 3.0])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            metrics = compute_metrics(y, y, metrics=["bogus_metric"])
            assert "bogus_metric" not in metrics
            assert any("Unknown metric" in str(x.message) for x in w)

    def test_acc_zero_denominator(self):
        y_true = np.array([5.0, 5.0, 5.0])
        y_pred = np.array([5.0, 5.0, 5.0])
        metrics = compute_metrics(y_true, y_pred, metrics=["acc"], climatology_mean=5.0)
        assert metrics["acc"] == 0.0

    def test_acc_with_climatology_mean(self):
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.1, 2.1, 3.1])
        metrics = compute_metrics(y_true, y_pred, metrics=["acc"], climatology_mean=2.0)
        assert metrics["acc"] > 0.9

    def test_bias(self):
        y_true = np.array([0.0, 0.0])
        y_pred = np.array([1.0, 3.0])
        metrics = compute_metrics(y_true, y_pred, metrics=["bias"])
        assert metrics["bias"] == pytest.approx(2.0)


# ===================================================================
# persistence.py
# ===================================================================


class TestPersistenceModelExtended:
    def test_score_perfect(self):
        X = np.random.randn(10, 3)
        y = np.full(10, 7.0)
        m = PersistenceModel()
        m.fit(X, y)
        scores = m.score(X, y)
        assert scores["rmse"] == pytest.approx(0.0)

    def test_score_with_different_metrics(self):
        X = np.random.randn(10, 3)
        y = np.random.randn(10)
        m = PersistenceModel()
        m.fit(X, y)
        scores = m.score(X, y, metrics=["rmse", "mae", "mape", "bias"])
        assert "mape" in scores
        assert "bias" in scores

    def test_predict_1d_x(self):
        X = np.array([1.0, 2.0, 3.0])
        y = np.array([10.0, 20.0, 30.0])
        m = PersistenceModel()
        m.fit(X.reshape(-1, 1), y)
        result = m.predict(X)
        assert result.deterministic.shape[0] == 1

    def test_predict_proba_all_quantiles(self):
        X = np.random.randn(5, 2)
        y = np.random.randn(10)
        m = PersistenceModel()
        m.fit(X, y)
        result = m.predict_proba(X, quantiles=[0.1, 0.25, 0.5, 0.75, 0.9])
        for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
            np.testing.assert_allclose(result.quantiles[f"q{q}"][:, 0], result.deterministic[:, 0])

    def test_metadata(self):
        X = np.random.randn(5, 2)
        y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        m = PersistenceModel()
        m.fit(X, y)
        result = m.predict(X)
        assert result.metadata["model"] == "persistence"
        np.testing.assert_allclose(result.metadata["last_values"], [5.0])


# ===================================================================
# climatology.py
# ===================================================================


class TestSeasonalClimatology:
    def test_basic(self):
        data = np.array([10.0, 20.0, 30.0, 40.0])
        doy = np.array([1, 1, 2, 2])
        clim = seasonal_climatology(data, day_of_year=doy)
        assert clim[1][0] == pytest.approx(15.0)
        assert clim[2][0] == pytest.approx(35.0)

    def test_2d_data(self):
        data = np.array([[10, 100], [20, 200], [30, 300], [40, 400]])
        doy = np.array([1, 1, 2, 2])
        clim = seasonal_climatology(data, day_of_year=doy)
        assert 1 in clim
        assert 2 in clim

    def test_no_day_of_year(self):
        data = np.array([10.0, 20.0, 30.0, 40.0])
        clim = seasonal_climatology(data)
        assert len(clim) == 4

    def test_single_observation_per_day(self):
        data = np.array([10.0, 20.0])
        doy = np.array([1, 2])
        clim = seasonal_climatology(data, day_of_year=doy)
        assert clim[1][1] == 0.0  # std=0 for single obs
        assert clim[2][1] == 0.0

    def test_period_daily(self):
        data = np.array([1.0, 2.0, 3.0])
        clim = seasonal_climatology(data, period="daily")
        assert len(clim) == 3


class TestAnomaliesFromClimatology:
    def test_basic(self):
        data = np.array([10.0, 20.0, 30.0, 40.0])
        doy = np.array([1, 1, 2, 2])
        clim = seasonal_climatology(data, day_of_year=doy)
        anomalies = anomalies_from_climatology(data, clim, day_of_year=doy)
        assert anomalies.shape == (4, 1)
        np.testing.assert_allclose(anomalies[0, 0], 10.0 - 15.0, atol=1e-10)
        np.testing.assert_allclose(anomalies[1, 0], 20.0 - 15.0, atol=1e-10)

    def test_no_day_of_year(self):
        data = np.array([10.0, 20.0, 30.0])
        clim = seasonal_climatology(data)
        anomalies = anomalies_from_climatology(data, clim)
        assert anomalies.shape == (3, 1)

    def test_2d_data(self):
        data = np.array([[10, 100], [20, 200]])
        doy = np.array([1, 1])
        clim = seasonal_climatology(data, day_of_year=doy)
        anomalies = anomalies_from_climatology(data, clim, day_of_year=doy)
        assert anomalies.shape == (2, 2)

    def test_missing_doy_uses_global_mean(self):
        data = np.array([10.0, 20.0, 30.0])
        clim = {1: (100.0, 5.0)}  # only day 1 in climatology
        doy = np.array([1, 99, 99])
        anomalies = anomalies_from_climatology(data, clim, day_of_year=doy)
        assert anomalies.shape == (3, 1)


class TestClimatologyModelExtended:
    def _make_data(self, n=100):
        rng = np.random.default_rng(42)
        y = 10.0 + 5.0 * np.sin(2 * np.pi * np.arange(n) / 365.0) + rng.normal(0, 1, n)
        doy = (np.arange(n) % 365) + 1
        X = np.zeros((n, 1))
        return X, y, doy

    def test_predict_proba(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel(n_sigma=2.0)
        m.fit(X, y, day_of_year=doy)
        result = m.predict_proba(X[:5], quantiles=[0.1, 0.5, 0.9], day_of_year=doy[:5])
        assert "q0.1" in result.quantiles
        assert "q0.5" in result.quantiles
        assert "q0.9" in result.quantiles
        # q0.1 < q0.5 < q0.9
        assert np.all(result.quantiles["q0.1"] <= result.quantiles["q0.5"] + 1e-6)
        assert np.all(result.quantiles["q0.5"] <= result.quantiles["q0.9"] + 1e-6)

    def test_predict_proba_no_day_of_year(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel()
        m.fit(X, y, day_of_year=doy)
        result = m.predict_proba(X[:5], quantiles=[0.5])
        assert result.quantiles["q0.5"].shape[0] == 5

    def test_score(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel()
        m.fit(X, y, day_of_year=doy)
        scores = m.score(X[:20], y[:20], day_of_year=doy[:20])
        assert "rmse" in scores
        assert "mae" in scores
        assert "acc" in scores
        assert scores["rmse"] >= 0

    def test_score_different_metrics(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel()
        m.fit(X, y, day_of_year=doy)
        scores = m.score(X[:20], y[:20], metrics=["rmse", "mape", "bias"], day_of_year=doy[:20])
        assert "mape" in scores
        assert "bias" in scores

    def test_anomaly_correction_enabled(self):
        # Use repeated days so climatology != last value, making anomaly nonzero
        rng = np.random.default_rng(7)
        n = 200
        doy = (np.arange(n) % 10) + 1  # only 10 unique days → repeats
        y = 10.0 + 5.0 * np.sin(2 * np.pi * doy / 10.0) + rng.normal(0, 0.5, n)
        X = np.zeros((n, 1))
        m = ClimatologyModel(use_anomaly_correction=True)
        m.fit(X, y, day_of_year=doy)
        assert m._last_anomaly is not None
        assert np.any(m._last_anomaly != 0)  # anomaly should be nonzero
        result = m.predict(X[:5], day_of_year=doy[:5])
        result_no_corr = ClimatologyModel(use_anomaly_correction=False)
        result_no_corr.fit(X, y, day_of_year=doy)
        result2 = result_no_corr.predict(X[:5], day_of_year=doy[:5])
        # Anomaly correction shifts the forecast
        assert not np.allclose(result.deterministic, result2.deterministic)

    def test_too_few_samples_raises(self):
        X = np.zeros((1, 1))
        y = np.array([5.0])
        m = ClimatologyModel()
        with pytest.raises(ValueError, match="at least 2"):
            m.fit(X, y)

    def test_predict_no_day_of_year(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel()
        m.fit(X, y, day_of_year=doy)
        result = m.predict(X[:5])
        assert result.deterministic.shape == (5, 1)
        assert result.metadata["model"] == "climatology"

    def test_repr_fitted(self):
        m = ClimatologyModel()
        assert "not fitted" in repr(m)
        X, y, doy = self._make_data()
        m.fit(X, y, day_of_year=doy)
        assert "fitted" in repr(m)

    def test_inferred_day_of_year(self):
        X = np.zeros((10, 1))
        y = np.arange(10, dtype=float)
        m = ClimatologyModel()
        m.fit(X, y)
        result = m.predict(X)
        assert result.deterministic.shape == (10, 1)

    def test_anomaly_correction_default(self):
        X, y, doy = self._make_data()
        m = ClimatologyModel(use_anomaly_correction=False)
        m.fit(X, y, day_of_year=doy)
        assert m._last_anomaly is None


# ===================================================================
# gradient.py
# ===================================================================


class TestGradientForecasterExtended:
    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            import lightgbm  # noqa: F401

            self.has_lgb = True
        except ImportError:
            self.has_lgb = False
        try:
            import xgboost  # noqa: F401

            self.has_xgb = True
        except ImportError:
            self.has_xgb = False

        rng = np.random.default_rng(42)
        self.X = rng.random((200, 5)).astype(np.float32)
        self.y = (self.X @ rng.random(5) + rng.normal(0, 0.1, 200)).astype(np.float32)
        self.X_val = rng.random((50, 5)).astype(np.float32)
        self.y_val = (self.X_val @ rng.random(5) + rng.normal(0, 0.1, 50)).astype(np.float32)

    def test_lgb_deterministic(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, self.y)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 1)
        assert res.metadata["model"] == "gradient_lightgbm"

    def test_xgb_deterministic(self):
        if not self.has_xgb:
            pytest.skip("xgboost not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="xgboost", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, self.y)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 1)

    def test_lgb_with_early_stopping(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm", n_estimators=200, max_depth=3, early_stopping_rounds=10
        )
        m.fit(self.X, self.y, X_val=self.X_val, y_val=self.y_val)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 1)

    def test_xgb_with_early_stopping(self):
        if not self.has_xgb:
            pytest.skip("xgboost not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="xgboost", n_estimators=200, max_depth=3, early_stopping_rounds=10
        )
        m.fit(self.X, self.y, X_val=self.X_val, y_val=self.y_val)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 1)

    def test_quantile_objective_lgb(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm",
            n_estimators=20,
            max_depth=3,
            objective="quantile",
            quantiles=[0.1, 0.5, 0.9],
            early_stopping_rounds=None,
        )
        m.fit(self.X, self.y)
        res = m.predict_proba(self.X[:10], quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in res.quantiles
        assert "q0.5" in res.quantiles
        assert "q0.9" in res.quantiles
        assert res.quantiles["q0.1"].shape == (10, 1)

    def test_quantile_objective_xgb(self):
        if not self.has_xgb:
            pytest.skip("xgboost not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="xgboost",
            n_estimators=20,
            max_depth=3,
            objective="quantile",
            quantiles=[0.1, 0.5, 0.9],
            early_stopping_rounds=None,
        )
        m.fit(self.X, self.y)
        res = m.predict_proba(self.X[:10], quantiles=[0.1, 0.5, 0.9])
        assert "q0.5" in res.quantiles

    def test_predict_proba_non_quantile_model(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, self.y)
        res = m.predict_proba(self.X[:10], quantiles=[0.1, 0.25, 0.5, 0.75, 0.9])
        # Non-quantile model: all quantiles fall back to deterministic
        for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
            np.testing.assert_allclose(res.quantiles[f"q{q}"], res.deterministic)

    def test_feature_importance(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm",
            n_estimators=20,
            max_depth=3,
            feature_names=["a", "b", "c", "d", "e"],
            early_stopping_rounds=None,
        )
        m.fit(self.X, self.y)
        fi = m.feature_importance
        assert isinstance(fi, dict)
        assert len(fi) == 5
        top = m.feature_importance_top(3)
        assert len(top) == 3
        assert top[0][1] >= top[1][1]

    def test_feature_importance_top_n(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm", n_estimators=20, max_depth=3)
        m.fit(self.X, self.y)
        top = m.feature_importance_top(100)
        assert len(top) <= 100

    def test_score(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(
            backend="lightgbm", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, self.y)
        scores = m.score(self.X[:20], self.y[:20])
        assert "rmse" in scores
        assert scores["rmse"] >= 0

    def test_predict_before_fit_raises(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm")
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict(self.X[:5])

    def test_predict_proba_before_fit_raises(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm")
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict_proba(self.X[:5])

    def test_multi_output(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        rng = np.random.default_rng(99)
        y_multi = rng.random((200, 3)).astype(np.float32)
        m = GradientForecaster(
            backend="lightgbm", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, y_multi)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 3)

    def test_multi_output_predict_proba(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        rng = np.random.default_rng(99)
        y_multi = rng.random((200, 3)).astype(np.float32)
        m = GradientForecaster(
            backend="lightgbm", n_estimators=20, max_depth=3, early_stopping_rounds=None
        )
        m.fit(self.X, y_multi)
        res = m.predict_proba(self.X[:10], quantiles=[0.1, 0.5, 0.9])
        # Multi-output falls back to deterministic for all quantiles
        for q in [0.1, 0.5, 0.9]:
            np.testing.assert_allclose(res.quantiles[f"q{q}"], res.deterministic)

    def test_2d_x_raises(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm")
        X_1d = np.array([1, 2, 3], dtype=np.float32)
        with pytest.raises(ValueError, match="2-D"):
            m.fit(X_1d, np.array([1, 2, 3], dtype=np.float32))

    def test_repr(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm", n_estimators=100)
        assert "not fitted" in repr(m)
        m.fit(self.X[:20], self.y[:20])
        assert "fitted" in repr(m)

    def test_importance_no_names(self):
        if not self.has_lgb:
            pytest.skip("lightgbm not installed")
        from pakhi.models.gradient import GradientForecaster

        m = GradientForecaster(backend="lightgbm", n_estimators=20, max_depth=3)
        m.fit(self.X, self.y)
        fi = m.feature_importance
        for key in fi:
            assert key.startswith("feature_")


# ===================================================================
# gaussian.py
# ===================================================================


class TestGaussianForecasterExtended:
    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from sklearn.gaussian_process import GaussianProcessRegressor  # noqa: F401

            self.has_sklearn_gp = True
        except ImportError:
            self.has_sklearn_gp = False

        try:
            import gpytorch  # noqa: F401

            self.has_gpytorch = True
        except ImportError:
            self.has_gpytorch = False

        self.rng = np.random.default_rng(42)
        self.X = self.rng.random((50, 3))
        self.y = self.X @ self.rng.random(3) + self.rng.normal(0, 0.1, 50)

    def test_sklearn_backend_fit_predict(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn", lengthscale_prior=1.0)
        m.fit(self.X, self.y)
        res = m.predict(self.X[:10])
        assert res.deterministic.shape == (10, 1)
        assert "lower_95" in res.metadata
        assert "upper_95" in res.metadata
        assert res.metadata["backend"] == "sklearn"

    def test_predict_proba_sklearn(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        m.fit(self.X, self.y)
        res = m.predict_proba(self.X[:10], quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in res.quantiles
        assert "q0.5" in res.quantiles
        assert "q0.9" in res.quantiles
        assert res.quantiles["q0.1"].shape == (10, 1)

    def test_score_sklearn(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        m.fit(self.X, self.y)
        scores = m.score(self.X[:10], self.y[:10])
        assert "rmse" in scores
        assert scores["rmse"] >= 0

    def test_score_custom_metrics(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        m.fit(self.X, self.y)
        scores = m.score(self.X[:10], self.y[:10], metrics=["rmse", "mae", "bias"])
        assert "bias" in scores

    def test_too_few_samples(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        with pytest.raises(ValueError, match="at least 3"):
            m.fit(np.array([[1, 2, 3]]), np.array([1.0]))

    def test_two_samples(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        with pytest.raises(ValueError, match="at least 3"):
            m.fit(np.array([[1, 2, 3], [4, 5, 6]]), np.array([1.0, 2.0]))

    def test_predict_before_fit(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict(self.X[:5])

    def test_predict_proba_before_fit(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict_proba(self.X[:5])

    def test_repr(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        assert "not fitted" in repr(m)
        m.fit(self.X, self.y)
        assert "fitted" in repr(m)
        assert "sklearn" in repr(m)

    def test_lengthscale_prior(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn", lengthscale_prior=5.0)
        m.fit(self.X, self.y)
        res = m.predict(self.X[:5])
        assert res.deterministic.shape == (5, 1)

    def test_val_ignored(self):
        if not self.has_sklearn_gp:
            pytest.skip("sklearn GP not installed")
        from pakhi.models.gaussian import GaussianForecaster

        m = GaussianForecaster(backend="sklearn")
        X_val = self.rng.random((10, 3))
        y_val = self.rng.random(10)
        m.fit(self.X, self.y, X_val=X_val, y_val=y_val)
        res = m.predict(self.X[:5])
        assert res.deterministic.shape == (5, 1)


# ===================================================================
# ensemble.py
# ===================================================================


class TestEnsembleForecasterExtended:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from pakhi.models.ensemble import EnsembleForecaster

        self.EnsembleForecaster = EnsembleForecaster

    def _make_model(self, val):
        return _DummyModel(pred_value=val)

    def test_empty_models_raises(self):
        ens = self.EnsembleForecaster(models=[])
        with pytest.raises(ValueError, match="No models"):
            ens.fit(np.zeros((5, 3)), np.zeros(5))

    def test_mean_method(self):
        m1 = self._make_model(2.0)
        m2 = self._make_model(4.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        res = ens.predict(np.ones((3, 3)))
        np.testing.assert_allclose(res.deterministic[:, 0], 3.0)
        assert res.metadata["n_models"] == 2

    def test_bma_method(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens = self.EnsembleForecaster(models=[m1, m2], method="bma")
        ens.fit(X_val, y_val, X_val=X_val, y_val=y_val)
        res = ens.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)

    def test_bma_requires_val(self):
        m1 = self._make_model(1.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1], method="bma")
        with pytest.raises(ValueError, match="X_val and y_val"):
            ens.fit(np.zeros((5, 3)), np.zeros(5))

    def test_stacking_method(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens = self.EnsembleForecaster(models=[m1, m2], method="stacking")
        ens.fit(X_val, y_val, X_val=X_val, y_val=y_val)
        res = ens.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)
        assert ens._meta_coefs is not None

    def test_stacking_requires_val(self):
        m1 = self._make_model(1.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1], method="stacking")
        with pytest.raises(ValueError, match="X_val and y_val"):
            ens.fit(np.zeros((5, 3)), np.zeros(5))

    def test_unknown_method_raises(self):
        m1 = self._make_model(1.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1], method="invalid")
        with pytest.raises(ValueError, match="Unknown method"):
            ens.fit(np.zeros((5, 3)), np.zeros(5))

    def test_predict_before_fit(self):
        m1 = self._make_model(1.0)
        ens = self.EnsembleForecaster(models=[m1], method="mean")
        with pytest.raises(RuntimeError, match="Call fit"):
            ens.predict(np.ones((3, 3)))

    def test_predict_proba(self):
        m1 = self._make_model(2.0)
        m2 = self._make_model(4.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        res = ens.predict_proba(np.ones((3, 3)), quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in res.quantiles
        assert "q0.5" in res.quantiles
        assert "q0.9" in res.quantiles
        assert "inter_model_std" in res.metadata

    def test_predict_proba_before_fit(self):
        m1 = self._make_model(1.0)
        ens = self.EnsembleForecaster(models=[m1], method="mean")
        with pytest.raises(RuntimeError, match="Call fit"):
            ens.predict_proba(np.ones((3, 3)))

    def test_retrain_weights(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens.retrain_weights(X_val, y_val)
        assert ens._weights is not None
        assert len(ens._weights) == 2

    def test_retrain_weights_with_recent_skill(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean", decay=0.95)
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        recent = [{"rmse": 0.5}, {"rmse": 1.5}]
        ens.retrain_weights(X_val, y_val, recent_skill=recent)
        assert ens._weights is not None
        assert len(ens._weights) == 2

    def test_retrain_weights_empty_models(self):
        ens = self.EnsembleForecaster(models=[])
        with pytest.raises(ValueError, match="No models"):
            ens.retrain_weights(np.ones((5, 3)), np.zeros(5))

    def test_model_ranking(self):
        m1 = self._make_model(10.0)
        m2 = self._make_model(1.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ranking = ens.model_ranking(X_val, y_val)
        assert len(ranking) == 2
        assert ranking[0][2] <= ranking[1][2]

    def test_score(self):
        m1 = self._make_model(2.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        scores = ens.score(np.ones((5, 3)), np.full(5, 2.0))
        assert scores["rmse"] == pytest.approx(0.0)

    def test_repr(self):
        ens = self.EnsembleForecaster(models=[], method="mean")
        assert "not fitted" in repr(ens)

    def test_predict_proba_with_model_failure(self):
        class _PredictProbaFailModel:
            """Works for predict but fails for predict_proba."""

            def predict(self, X):
                X = np.asarray(X, dtype=np.float64)
                return ForecastResult(
                    deterministic=np.full((X.shape[0], 1), 999.0),
                    quantiles={},
                )

            def predict_proba(self, X, quantiles=None):
                raise RuntimeError("predict_proba failed")

        m1 = self._make_model(2.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        fail_m = _PredictProbaFailModel()
        ens = self.EnsembleForecaster(models=[m1, fail_m], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        res = ens.predict_proba(np.ones((3, 3)), quantiles=[0.5])
        assert "q0.5" in res.quantiles

    def test_collect_deterministic_all_fail(self):
        class _FailingModel:
            def predict(self, X):
                raise RuntimeError("fail")

            def predict_proba(self, X, quantiles=None):
                raise RuntimeError("fail")

        ens = self.EnsembleForecaster(models=[_FailingModel(), _FailingModel()], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        with pytest.raises(RuntimeError, match="All models failed"):
            ens._collect_deterministic(np.ones((3, 3)))

    def test_predict_with_failed_model(self):
        class _FailingModel:
            def predict(self, X):
                raise RuntimeError("fail")

            def predict_proba(self, X, quantiles=None):
                raise RuntimeError("fail")

        m1 = self._make_model(5.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        # Only one model — the failing one is never added
        ens = self.EnsembleForecaster(models=[m1], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        res = ens.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)

    def test_stacking_predict_with_fallback(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens = self.EnsembleForecaster(models=[m1, m2], method="stacking")
        ens.fit(X_val, y_val, X_val=X_val, y_val=y_val)
        ens._meta_coefs = None
        res = ens.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)

    def test_retrain_weights_all_zero_rmse(self):
        m1 = self._make_model(0.0)
        m2 = self._make_model(0.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((5, 3))
        y_val = np.zeros(5)
        recent = [{"rmse": 100.0}, {"rmse": 100.0}]
        ens.retrain_weights(X_val, y_val, recent_skill=recent)
        assert ens._weights is not None

    def test_weights_fallback_when_none(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(2.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        ens._weights = None
        res = ens.predict(np.ones((3, 3)))
        assert res.deterministic.shape == (3, 1)

    def test_stacking_predict_proba(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens = self.EnsembleForecaster(models=[m1, m2], method="stacking")
        ens.fit(X_val, y_val, X_val=X_val, y_val=y_val)
        res = ens.predict_proba(np.ones((3, 3)), quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in res.quantiles
        assert "inter_model_std" in res.metadata

    def test_retrain_weights_empty_recent_skill(self):
        m1 = self._make_model(1.0)
        m2 = self._make_model(3.0)
        m1.fit(np.zeros((5, 3)), np.zeros(5))
        m2.fit(np.zeros((5, 3)), np.zeros(5))
        ens = self.EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(np.zeros((5, 3)), np.zeros(5))
        X_val = np.ones((10, 3))
        y_val = np.full(10, 2.0)
        ens.retrain_weights(X_val, y_val, recent_skill=[])
        assert ens._weights is not None


# ===================================================================
# __init__.py — lazy imports & __getattr__
# ===================================================================


class TestModelPackageInit:
    def test_import_base_models(self):
        from pakhi.models import BaseModel, ForecastResult, StandardScaler

        assert BaseModel is not None
        assert ForecastResult is not None
        assert StandardScaler is not None

    def test_import_persistence(self):
        from pakhi.models import PersistenceModel

        assert PersistenceModel is not None

    def test_import_climatology(self):
        from pakhi.models import ClimatologyModel, anomalies_from_climatology, seasonal_climatology

        assert ClimatologyModel is not None
        assert anomalies_from_climatology is not None
        assert seasonal_climatology is not None

    def test_import_gradient(self):
        from pakhi.models import GradientForecaster

        assert GradientForecaster is not None

    def test_import_compute_metrics(self):
        from pakhi.models import compute_metrics, train_val_test_split

        assert compute_metrics is not None
        assert train_val_test_split is not None

    def test_lazy_import_lstm(self):
        from pakhi.models import LSTMForecaster

        assert LSTMForecaster is not None

    def test_lazy_import_gaussian(self):
        from pakhi.models import GaussianForecaster

        assert GaussianForecaster is not None

    def test_lazy_import_ensemble(self):
        from pakhi.models import EnsembleForecaster

        assert EnsembleForecaster is not None

    def test_invalid_attribute_raises(self):
        import pakhi.models as models_mod

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = models_mod.NonExistentModel

    def test_all_exports(self):
        import pakhi.models as models_mod

        for name in models_mod.__all__:
            assert hasattr(models_mod, name), f"{name} listed in __all__ but not accessible"


# ===================================================================
# lstm.py
# ===================================================================


class TestLSTMForecasterExtended:
    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            import torch  # noqa: F401

            self.has_torch = True
        except ImportError:
            self.has_torch = False

    def _make_data(self, n=200, input_dim=5, horizon=1):
        rng = np.random.default_rng(42)
        X = rng.random((n, input_dim)).astype(np.float32)
        y = rng.random((n, horizon)).astype(np.float32)
        return X, y

    @pytest.mark.slow
    def test_fit_predict(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=10,
            batch_size=32,
            max_epochs=5,
            mc_samples=5,
            patience=3,
        )
        m.fit(X, y)
        res = m.predict(X[:50])
        assert res.deterministic.shape[0] > 0
        assert res.metadata["model"] == "lstm_bilstm_attention"

    @pytest.mark.slow
    def test_predict_proba(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=10,
            batch_size=32,
            max_epochs=5,
            mc_samples=5,
            patience=3,
        )
        m.fit(X, y)
        res = m.predict_proba(X[:50], quantiles=[0.1, 0.5, 0.9])
        assert res.deterministic.shape[0] > 0
        assert "q0.1" in res.quantiles
        assert "q0.5" in res.quantiles
        assert "q0.9" in res.quantiles
        assert res.metadata["mc_samples"] == 5

    @pytest.mark.slow
    def test_score(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        seq_len = 10
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=seq_len,
            batch_size=32,
            max_epochs=5,
            mc_samples=3,
            patience=3,
        )
        m.fit(X, y)
        # predict returns n_samples rows due to padding in sliding window
        n_input = 50
        scores = m.score(X[:n_input], y[:n_input])
        assert "rmse" in scores
        assert scores["rmse"] >= 0

    @pytest.mark.slow
    def test_save_load(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=10,
            batch_size=32,
            max_epochs=3,
            mc_samples=3,
            patience=3,
        )
        m.fit(X, y)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pt"
            m.save(path)
            assert path.exists()

            m2 = LSTMForecaster(input_dim=3, hidden_dim=32, n_layers=1)
            m2.load(path)
            assert m2._fitted
            assert m2.input_dim == 3
            assert m2.hidden_dim == 32

    @pytest.mark.slow
    def test_load_missing_state(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        with tempfile.TemporaryDirectory() as tmp:
            import torch

            path = Path(tmp) / "model.pt"
            torch.save(
                {
                    "net_state": None,
                    "x_scaler_mean": np.zeros(3),
                    "x_scaler_std": np.ones(3),
                    "y_scaler_mean": np.zeros(1),
                    "y_scaler_std": np.ones(1),
                    "config": {
                        "input_dim": 3,
                        "hidden_dim": 32,
                        "n_layers": 1,
                        "dropout": 0.2,
                        "mc_dropout": 0.2,
                        "forecast_horizon": 1,
                        "seq_len": 10,
                        "quantiles": [0.1, 0.5, 0.9],
                    },
                },
                path,
            )
            m = LSTMForecaster()
            m.load(path)
            assert m._fitted

    @pytest.mark.slow
    def test_device_property_explicit(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster(device="cpu")
        assert m.device == "cpu"

    @pytest.mark.slow
    def test_device_property_auto(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster()
        dev = m.device
        assert dev in ("cpu", "cuda")

    @pytest.mark.slow
    def test_predict_before_fit(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster(input_dim=3, seq_len=10)
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict(np.ones((50, 3)))

    @pytest.mark.slow
    def test_predict_proba_before_fit(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster(input_dim=3, seq_len=10)
        with pytest.raises(RuntimeError, match="Call fit"):
            m.predict_proba(np.ones((50, 3)))

    @pytest.mark.slow
    def test_repr(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster(input_dim=3, hidden_dim=64, n_layers=2, device="cpu")
        assert "not fitted" in repr(m)
        assert "input_dim=3" in repr(m)
        assert "hidden_dim=64" in repr(m)
        assert "device='cpu'" in repr(m)

    @pytest.mark.slow
    def test_fit_with_validation(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=10,
            batch_size=32,
            max_epochs=5,
            mc_samples=3,
            patience=3,
        )
        X_val, y_val = self._make_data(n=100, input_dim=3)
        m.fit(X, y, X_val=X_val, y_val=y_val)
        res = m.predict(X[:50])
        assert res.deterministic.shape[0] > 0

    @pytest.mark.slow
    def test_save_export_onnx(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            forecast_horizon=1,
            seq_len=10,
            batch_size=32,
            max_epochs=3,
            patience=3,
        )
        m.fit(X, y)
        with tempfile.TemporaryDirectory() as tmp:
            onnx_path = Path(tmp) / "model.onnx"
            try:
                m.export_onnx(onnx_path)
                assert onnx_path.exists()
            except Exception:
                pytest.skip("ONNX export failed (torch.onnx may not be available)")

    @pytest.mark.slow
    def test_repr_fitted(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        X, y = self._make_data(n=300, input_dim=3)
        m = LSTMForecaster(
            input_dim=3,
            hidden_dim=32,
            n_layers=1,
            seq_len=10,
            max_epochs=3,
            patience=3,
        )
        m.fit(X, y)
        assert "fitted" in repr(m)

    @pytest.mark.slow
    def test_save_before_fit_raises(self):
        if not self.has_torch:
            pytest.skip("torch not installed")
        from pakhi.models.lstm import LSTMForecaster

        m = LSTMForecaster(input_dim=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pt"
            m.save(path)
            # net_state is None, but save should still work


# ===================================================================
# Edge cases for ForecastResult
# ===================================================================


class TestForecastResult:
    def test_defaults(self):
        r = ForecastResult(deterministic=np.array([1.0]))
        assert r.quantiles == {}
        assert r.skill_scores == {}
        assert r.metadata == {}

    def test_custom(self):
        r = ForecastResult(
            deterministic=np.array([1.0]),
            quantiles={"q0.5": np.array([1.0])},
            skill_scores={"rmse": 0.1},
            metadata={"model": "test"},
        )
        assert r.quantiles["q0.5"].shape == (1,)
        assert r.skill_scores["rmse"] == 0.1
        assert r.metadata["model"] == "test"


# === Deep Gaussian Process tests ===
class TestGaussianGPyTorch:
    """Test GPyTorch backend paths of GaussianForecaster."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            import gpytorch  # noqa: F401
        except ImportError:
            pytest.skip("gpytorch not installed")

    def test_gpytorch_backend_direct(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="gpytorch", n_inducing=20, max_optim_iter=2)
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        assert model._fitted

    def test_gpytorch_predict(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="gpytorch", n_inducing=20, max_optim_iter=2)
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        result = model.predict(X[:5])
        assert result.deterministic.shape[0] == 5

    def test_gpytorch_predict_proba(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="gpytorch", n_inducing=20, max_optim_iter=2)
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        result = model.predict_proba(X[:5], quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in result.quantiles
        assert "q0.5" in result.quantiles

    def test_gpytorch_score(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="gpytorch", n_inducing=20, max_optim_iter=2)
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        scores = model.score(X[:10], y[:10])
        assert "rmse" in scores

    def test_gpytorch_repr(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="gpytorch")
        assert "not fitted" in repr(model)
        model._init_backend()
        assert "gpytorch" in repr(model)

    def test_sklearn_backend_direct(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="sklearn")
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        result = model.predict(X[:5])
        assert result.deterministic.shape[0] == 5

    def test_sklearn_predict_proba(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="sklearn")
        X = np.random.randn(50, 3)
        y = np.random.randn(50)
        model.fit(X, y)
        result = model.predict_proba(X[:5], quantiles=[0.1, 0.5, 0.9])
        assert "q0.5" in result.quantiles

    def test_sklearn_repr(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="sklearn")
        model._init_backend()
        assert "sklearn" in repr(model)

    def test_no_backend_available(self):
        from pakhi.models.gaussian import GaussianForecaster

        model = GaussianForecaster(backend="sklearn")
        with (
            patch("pakhi.models.gaussian._has_sklearn_gp", return_value=False),
            pytest.raises(ImportError),
        ):
            model._init_backend()
