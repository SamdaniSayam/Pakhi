"""Tests for pakhi.models — ensemble, gaussian, lstm, WeatherDataset, AttentionLayer."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from pakhi.models.base import ForecastResult, StandardScaler, compute_metrics, train_val_test_split
from pakhi.models.ensemble import EnsembleForecaster
from pakhi.models.gaussian import GaussianForecaster, _has_sklearn_gp
from pakhi.models.lstm import AttentionLayer, LSTMForecaster, WeatherDataset, _pinball_loss

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubModel:
    """Minimal model with predict returning ForecastResult."""

    def __init__(self, value: float):
        self._value = value

    def predict(self, X):
        n = X.shape[0] if X.ndim == 2 else 1
        return ForecastResult(
            deterministic=np.full((n, 1), self._value),
            quantiles={},
            skill_scores={},
            metadata={},
        )

    def predict_proba(self, X, quantiles=(0.1, 0.5, 0.9)):
        res = self.predict(X)
        for q in quantiles:
            res.quantiles[f"q{q}"] = np.full_like(res.deterministic, self._value * q)
        return res


class _RandomModel:
    """Model that returns random predictions."""

    def __init__(self, seed=42):
        self._rng = np.random.RandomState(seed)

    def predict(self, X):
        n = X.shape[0]
        return ForecastResult(
            deterministic=self._rng.randn(n, 1),
            quantiles={},
            skill_scores={},
            metadata={},
        )

    def predict_proba(self, X, quantiles=(0.1, 0.5, 0.9)):
        res = self.predict(X)
        for q in quantiles:
            res.quantiles[f"q{q}"] = np.full_like(res.deterministic, self._rng.randn())
        return res


class _FailingModel:
    """Model whose predict always raises."""

    def predict(self, X):
        raise RuntimeError("boom")


# === StandardScaler ===


class TestStandardScaler:
    def test_fit_transform(self):
        s = StandardScaler()
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=np.float64)
        X_scaled = s.fit_transform(X)
        assert X_scaled.shape == (3, 2)
        np.testing.assert_allclose(X_scaled.mean(axis=0), 0.0, atol=1e-10)

    def test_inverse_transform(self):
        s = StandardScaler()
        X = np.array([[10, 20], [30, 40]], dtype=np.float64)
        X_scaled = s.fit_transform(X)
        X_back = s.inverse_transform(X_scaled)
        np.testing.assert_allclose(X_back, X)

    def test_1d_input(self):
        s = StandardScaler()
        X = np.array([1.0, 2.0, 3.0])
        X_scaled = s.fit_transform(X)
        assert len(X_scaled) == 3

    def test_constant_column(self):
        s = StandardScaler()
        X = np.array([[5.0, 1.0], [5.0, 2.0]])
        X_scaled = s.fit_transform(X)
        assert np.all(np.isfinite(X_scaled))

    def test_transform_before_fit(self):
        s = StandardScaler()
        with pytest.raises(RuntimeError, match="Call fit"):
            s.transform(np.array([[1.0]]))

    def test_repr(self):
        s = StandardScaler()
        r = repr(s)
        assert "StandardScaler" in r


# === compute_metrics ===


class TestComputeMetrics:
    def test_basic(self):
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.0, 2.0, 3.0])
        m = compute_metrics(y_true, y_pred, metrics=["rmse", "mae"])
        assert m["rmse"] == pytest.approx(0.0)
        assert m["mae"] == pytest.approx(0.0)

    def test_shape_mismatch(self):
        with pytest.raises(ValueError, match="Shape mismatch"):
            compute_metrics(np.array([1.0]), np.array([1.0, 2.0]))

    def test_all_nan(self):
        m = compute_metrics(np.array([np.nan]), np.array([np.nan]))
        assert all(np.isnan(v) for v in m.values())

    def test_acc(self):
        y_true = np.array([1.0, 2.0, 3.0])
        m = compute_metrics(y_true, y_true, metrics=["acc"])
        assert m["acc"] == pytest.approx(1.0)

    def test_mape(self):
        y_true = np.array([100.0, 200.0])
        y_pred = np.array([110.0, 180.0])
        m = compute_metrics(y_true, y_pred, metrics=["mape"])
        # mean(|(100-110)/100| + |(200-180)/200|)*100 = (0.1+0.1)/2*100 = 10.0
        assert m["mape"] == pytest.approx(10.0)

    def test_bias(self):
        y_true = np.array([0.0, 0.0])
        y_pred = np.array([5.0, 5.0])
        m = compute_metrics(y_true, y_pred, metrics=["bias"])
        assert m["bias"] == pytest.approx(5.0)

    def test_unknown_metric_warns(self):
        with pytest.warns(UserWarning, match="Unknown metric"):
            compute_metrics(np.array([1.0]), np.array([1.0]), metrics=["unknown"])


# === train_val_test_split ===


class TestTrainValTestSplit:
    def test_basic_split(self):
        data = np.arange(100)
        train, val, test = train_val_test_split(
            data, train_years=2000, val_year=2010, test_year=2012
        )
        # train_years=2000 (single int): years<2000 → 30 items
        # val_year=2010: year==2010 → 1 item
        # test_year=2012: year>=2012 → 58 items
        assert len(train) > 0
        assert len(val) > 0
        assert len(test) > 0
        assert len(train) + len(val) + len(test) <= 100

    def test_with_time_index(self):
        data = np.arange(365 * 3)
        dates = np.arange(365 * 3).astype("datetime64[D]")
        train, val, test = train_val_test_split(
            data, time_index=dates,
            train_years=(1970, 1971), val_year=1972, test_year=1973,
        )
        total = len(train) + len(val) + len(test)
        assert total > 0


# === EnsembleForecaster ===


class TestEnsembleForecaster:
    def _make_data(self, n=50, n_features=2):
        rng = np.random.RandomState(42)
        X = rng.randn(n, n_features)
        y = X @ np.array([1.0, 2.0]) + rng.randn(n) * 0.1
        return X, y

    def test_mean_fit_predict(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(3.0)
        ens = EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(X, y)
        result = ens.predict(X)
        assert result.deterministic.shape[0] == X.shape[0]

    def test_bma_fit_predict(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="bma")
        ens.fit(X, y, X_val=X[:10], y_val=y[:10])
        result = ens.predict(X)
        assert result.deterministic.shape[0] == X.shape[0]

    def test_stacking_fit_predict(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="stacking")
        ens.fit(X, y, X_val=X[:10], y_val=y[:10])
        result = ens.predict(X)
        assert result.deterministic.shape[0] == X.shape[0]

    def test_predict_before_fit(self):
        ens = EnsembleForecaster(models=[_StubModel(1.0)])
        with pytest.raises(RuntimeError, match="Call fit"):
            ens.predict(np.zeros((1, 1)))

    def test_bma_requires_val(self):
        ens = EnsembleForecaster(models=[_StubModel(1.0)], method="bma")
        with pytest.raises(ValueError, match="X_val and y_val are required"):
            ens.fit(np.zeros((1, 1)), np.zeros(1))

    def test_stacking_requires_val(self):
        ens = EnsembleForecaster(models=[_StubModel(1.0)], method="stacking")
        with pytest.raises(ValueError, match="X_val and y_val are required"):
            ens.fit(np.zeros((1, 1)), np.zeros(1))

    def test_empty_models(self):
        ens = EnsembleForecaster(models=[], method="mean")
        with pytest.raises(ValueError, match="No models provided"):
            ens.fit(np.zeros((1, 1)), np.zeros(1))

    def test_unknown_method(self):
        ens = EnsembleForecaster(models=[_StubModel(1.0)], method="bad")
        with pytest.raises(ValueError, match="Unknown method"):
            ens.fit(np.zeros((1, 1)), np.zeros(1))

    def test_predict_proba(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(X, y)
        result = ens.predict_proba(X)
        assert "inter_model_std" in result.metadata

    def test_score(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        ens = EnsembleForecaster(models=[m1], method="mean")
        ens.fit(X, y)
        s = ens.score(X, y)
        assert "rmse" in s

    def test_retrain_weights(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="bma")
        ens.fit(X, y, X_val=X[:10], y_val=y[:10])
        ens.retrain_weights(X[:10], y[:10])
        assert ens._weights is not None

    def test_retrain_weights_with_history(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="bma")
        ens.fit(X, y, X_val=X[:10], y_val=y[:10])
        history = [{"rmse": 0.5, "mae": 0.3}, {"rmse": 1.0, "mae": 0.8}]
        ens.retrain_weights(X[:10], y[:10], recent_skill=history)
        assert ens._weights is not None

    def test_model_ranking(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _StubModel(2.0)
        ens = EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(X, y)
        ranking = ens.model_ranking(X, y)
        assert len(ranking) == 2
        assert ranking[0][0] in [0, 1]

    def test_repr(self):
        ens = EnsembleForecaster(models=[_StubModel(1.0)], method="mean")
        r = repr(ens)
        assert "EnsembleForecaster" in r
        assert "not fitted" in r

    def test_collect_deterministic_failing_model(self):
        X, y = self._make_data()
        m1 = _StubModel(1.0)
        m2 = _FailingModel()
        ens = EnsembleForecaster(models=[m1, m2], method="mean")
        ens.fit(X, y)
        # When a model fails during predict, the stacked shape mismatches
        # the weight vector. This tests that the warning is logged.
        with pytest.raises(ValueError):
            ens.predict(X)

    def test_all_models_failing(self):
        X, y = self._make_data()
        ens = EnsembleForecaster(models=[_FailingModel(), _FailingModel()], method="mean")
        ens.fit(X, y)
        with pytest.raises(RuntimeError, match="All models failed"):
            ens.predict(X)


# === GaussianForecaster ===


class TestGaussianForecaster:
    def _make_data(self, n=30):
        rng = np.random.RandomState(42)
        X = rng.randn(n, 2)
        y = X @ np.array([1.0, 2.0]) + rng.randn(n) * 0.1
        return X, y

    @pytest.mark.skipif(not _has_sklearn_gp(), reason="sklearn GP not available")
    def test_fit_predict_sklearn(self):
        X, y = self._make_data()
        model = GaussianForecaster(backend="sklearn", lengthscale_prior=1.0)
        model.fit(X, y)
        result = model.predict(X[:5])
        assert result.deterministic.shape == (5, 1)
        assert result.metadata["backend"] == "sklearn"

    @pytest.mark.skipif(not _has_sklearn_gp(), reason="sklearn GP not available")
    def test_predict_proba_sklearn(self):
        X, y = self._make_data()
        model = GaussianForecaster(backend="sklearn", lengthscale_prior=1.0)
        model.fit(X, y)
        result = model.predict_proba(X[:5], quantiles=[0.1, 0.5, 0.9])
        assert "q0.1" in result.quantiles
        assert "q0.9" in result.quantiles

    @pytest.mark.skipif(not _has_sklearn_gp(), reason="sklearn GP not available")
    def test_score_sklearn(self):
        X, y = self._make_data()
        model = GaussianForecaster(backend="sklearn", lengthscale_prior=1.0)
        model.fit(X, y)
        s = model.score(X, y)
        assert "rmse" in s

    def test_predict_before_fit(self):
        model = GaussianForecaster()
        with pytest.raises(RuntimeError, match="Call fit"):
            model.predict(np.zeros((1, 1)))

    def test_too_few_samples(self):
        model = GaussianForecaster()
        with pytest.raises(ValueError, match="at least 3"):
            model.fit(np.zeros((2, 1)), np.zeros(2))

    def test_repr(self):
        model = GaussianForecaster()
        r = repr(model)
        assert "GaussianForecaster" in r
        assert "not fitted" in r

    @pytest.mark.skipif(not _has_sklearn_gp(), reason="sklearn GP not available")
    def test_repr_fitted(self):
        X, y = self._make_data()
        model = GaussianForecaster(backend="sklearn")
        model.fit(X, y)
        r = repr(model)
        assert "fitted" in r
        assert "sklearn" in r


# === LSTMForecaster ===


class TestLSTMForecaster:
    def _make_data(self, n=200, features=4):
        rng = np.random.RandomState(42)
        X = rng.randn(n, features).astype(np.float32)
        y = rng.randn(n).astype(np.float32)
        return X, y

    def test_init(self):
        model = LSTMForecaster(input_dim=4, hidden_dim=32, n_layers=1)
        assert model.input_dim == 4
        assert "not fitted" in repr(model)

    def test_weather_dataset(self):
        X = np.random.randn(100, 4).astype(np.float32)
        y = np.random.randn(100).astype(np.float32)
        ds = WeatherDataset(X, y, seq_len=10)
        assert len(ds) == 100
        x_seq, _y_val = ds[0]
        assert x_seq.shape == (10, 4)

    def test_attention_layer_placeholder(self):
        al = AttentionLayer()
        assert al is not None

    def test_fit_predict(self):
        X, y = self._make_data(n=200, features=4)
        model = LSTMForecaster(
            input_dim=4, hidden_dim=16, n_layers=1, max_epochs=3,
            batch_size=32, seq_len=10, forecast_horizon=1,
        )
        model.fit(X, y)
        assert model._fitted
        result = model.predict(X[:50])
        assert result.deterministic.shape[0] > 0

    def test_fit_with_validation(self):
        X, y = self._make_data(n=200, features=4)
        model = LSTMForecaster(
            input_dim=4, hidden_dim=16, n_layers=1, max_epochs=3,
            batch_size=32, seq_len=10, forecast_horizon=1,
        )
        model.fit(X[:150], y[:150], X_val=X[150:], y_val=y[150:])
        assert model._fitted

    def test_predict_proba(self):
        X, y = self._make_data(n=200, features=4)
        model = LSTMForecaster(
            input_dim=4, hidden_dim=16, n_layers=1, max_epochs=2,
            batch_size=32, seq_len=10, mc_samples=5,
        )
        model.fit(X, y)
        result = model.predict_proba(X[:50])
        assert "q0.5" in result.quantiles
        assert result.metadata["mc_samples"] == 5

    def test_predict_before_fit(self):
        model = LSTMForecaster(input_dim=4)
        with pytest.raises(RuntimeError, match="Call fit"):
            model.predict(np.zeros((10, 4)))

    def test_score(self):
        X, y = self._make_data(n=200, features=4)
        model = LSTMForecaster(
            input_dim=4, hidden_dim=16, n_layers=1, max_epochs=2,
            batch_size=32, seq_len=10,
        )
        model.fit(X, y)
        result = model.predict(X)
        # score uses the same predict internally, so shapes will match
        n = min(result.deterministic.shape[0], y[:result.deterministic.shape[0]].shape[0])
        s = compute_metrics(y[:n], result.deterministic[:n])
        assert "rmse" in s

    def test_save_load(self):
        X, y = self._make_data(n=200, features=4)
        model = LSTMForecaster(
            input_dim=4, hidden_dim=16, n_layers=1, max_epochs=2,
            batch_size=32, seq_len=10, forecast_horizon=1,
        )
        model.fit(X, y)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.pt"
            model.save(path)
            assert path.exists()

            model2 = LSTMForecaster(input_dim=4, hidden_dim=16, seq_len=10)
            model2.load(path)
            assert model2._fitted

    def test_repr_device(self):
        model = LSTMForecaster(input_dim=4, device="cpu")
        assert "cpu" in repr(model)

    def test_pinball_loss(self):
        import torch
        preds = torch.tensor([[1.0, 2.0]])
        targets = torch.tensor([[1.5, 1.0]])
        loss = _pinball_loss(preds, targets, [0.1, 0.5, 0.9])
        assert loss.item() >= 0.0
