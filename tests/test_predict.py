"""Tests for pakhi.predict — deterministic, multi_step, probabilistic, verification."""
from __future__ import annotations

import numpy as np
import pytest

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


class _LinModel:
    def __init__(self, coef=None, intercept=0.0):
        self.coef_ = np.asarray(coef) if coef is not None else np.array([1.0])
        self.intercept_ = intercept

    def predict(self, X):
        return X @ self.coef_ + self.intercept_

    def fit(self, X, y):
        return _LinModel(coef=np.ones(X.shape[1]), intercept=0.0)

    def get_params(self, deep=True):
        return {"coef": self.coef_, "intercept": self.intercept_}

    def set_params(self, **params):
        for k, v in params.items():
            setattr(self, k, v)
        return self


class _ProbModel:
    def __init__(self, scores):
        self._scores = np.asarray(scores)

    def predict_proba(self, X):
        n = X.shape[0]
        p1 = self._scores[:n]
        return np.column_stack([1 - p1, p1])

    def fit(self, X, y):
        return self


class _DecisionModel:
    def __init__(self, scores):
        self._scores = np.asarray(scores)

    def decision_function(self, X):
        return self._scores[: X.shape[0]]


# === ForecastResult ===


class TestForecastResult:
    def test_basic_construction(self):
        r = ForecastResult(values=[1.0, 2.0], step_ahead=[1, 2], metadata={"method": "test"})
        assert r.values.dtype == np.float64
        assert r.step_ahead.dtype == np.intp
        assert r.lower is None
        assert r.upper is None

    def test_with_bounds(self):
        r = ForecastResult(values=[1.0], step_ahead=[1], lower=[0.5], upper=[1.5])
        assert r.lower is not None
        assert r.upper is not None

    def test_coerces_types(self):
        r = ForecastResult(values=[1, 2, 3], step_ahead=[1, 2, 3])
        assert r.values.dtype == np.float64
        assert r.step_ahead.dtype == np.intp


# === DeterministicPredictor ===


class TestDeterministicPredictor:
    def setup_method(self):
        self.dp = DeterministicPredictor()

    def test_predict_single(self):
        model = _LinModel(coef=np.array([2.0]), intercept=1.0)
        result = self.dp.predict_single(model, np.array([3.0]), forecast_horizon=5)
        assert isinstance(result, ForecastResult)
        assert result.values.shape == (5,)
        np.testing.assert_allclose(result.values, 7.0)
        np.testing.assert_array_equal(result.step_ahead, np.arange(1, 6))

    def test_predict_single_2d_input(self):
        model = _LinModel(coef=np.array([1.0, 2.0]), intercept=0.0)
        result = self.dp.predict_single(model, np.array([[1.0, 2.0]]), forecast_horizon=3)
        assert result.values.shape == (3,)
        np.testing.assert_allclose(result.values, 5.0)

    def test_predict_multi_step_direct(self):
        model = _LinModel(coef=np.array([1.0]))
        X_train = np.random.randn(50, 1)
        y_train = np.random.randn(50)
        result = self.dp.predict_multi_step(
            model, np.array([[0.0]]), steps=5, method="direct",
            y_train=y_train, X_train=X_train,
        )
        assert result.values.shape == (5,)
        assert result.metadata["method"] == "direct"

    def test_predict_multi_step_direct_requires_data(self):
        model = _LinModel()
        with pytest.raises(ValueError, match="y_train and X_train are required"):
            self.dp.predict_multi_step(model, np.array([[0.0]]), steps=5, method="direct")

    def test_predict_multi_step_recursive(self):
        model = _LinModel(coef=np.array([0.5]))
        result = self.dp.predict_multi_step(model, np.array([[1.0]]), steps=4, method="recursive")
        assert result.values.shape == (4,)
        np.testing.assert_allclose(result.values, [0.5, 0.25, 0.125, 0.0625], atol=1e-10)

    def test_predict_multi_step_multi_output(self):
        model = _LinModel(coef=np.array([1.0]))
        n = 30
        X_train = np.random.randn(n, 1)
        y_train = np.random.randn(n)
        result = self.dp.predict_multi_step(
            model, np.array([[0.0]]), steps=3, method="multi_output",
            y_train=y_train, X_train=X_train,
        )
        assert isinstance(result, ForecastResult)

    def test_predict_multi_step_multi_output_requires_data(self):
        model = _LinModel()
        with pytest.raises(ValueError, match="y_train and X_train are required"):
            self.dp.predict_multi_step(model, np.array([[0.0]]), steps=3, method="multi_output")

    def test_predict_multi_step_unknown_method(self):
        model = _LinModel()
        with pytest.raises(ValueError, match="Unknown method"):
            self.dp.predict_multi_step(model, np.array([[0.0]]), steps=3, method="magic")

    def test_optimize_threshold_predict_proba(self):
        np.random.seed(42)
        scores = np.random.uniform(0, 1, 100)
        y = (scores > 0.5).astype(float)
        model = _ProbModel(scores)
        t = self.dp.optimize_threshold(model, np.zeros((100, 1)), y, metric="f1")
        assert 0.0 <= t <= 1.0

    def test_optimize_threshold_decision_function(self):
        scores = np.array([0.1, 0.3, 0.6, 0.8, 0.9])
        y = np.array([0, 0, 1, 1, 1])
        model = _DecisionModel(scores)
        t = self.dp.optimize_threshold(model, np.zeros((5, 1)), y, metric="accuracy")
        assert 0.0 <= t <= 1.0

    def test_optimize_threshold_no_proba_or_decision(self):
        model = _LinModel()
        with pytest.raises(TypeError, match="Model must have"):
            self.dp.optimize_threshold(model, np.zeros((5, 1)), np.zeros(5))

    def test_compute_metric_accuracy(self):
        y_true = np.array([1, 0, 1, 1, 0])
        y_pred = np.array([1, 0, 0, 1, 0])
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "accuracy") == pytest.approx(0.8)

    def test_compute_metric_precision(self):
        y_true = np.array([1, 0, 1, 1, 0])
        y_pred = np.array([1, 0, 0, 1, 0])
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "precision") == pytest.approx(1.0)

    def test_compute_metric_recall(self):
        y_true = np.array([1, 0, 1, 1, 0])
        y_pred = np.array([1, 0, 0, 1, 0])
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "recall") == pytest.approx(2 / 3)

    def test_compute_metric_f1(self):
        y_true = np.array([1, 0, 1, 1, 0])
        y_pred = np.array([1, 0, 0, 1, 0])
        assert DeterministicPredictor._compute_metric(y_true, y_pred, "f1") == pytest.approx(4 / 5)

    def test_compute_metric_unknown(self):
        with pytest.raises(ValueError, match="Unknown metric"):
            DeterministicPredictor._compute_metric(np.array([0]), np.array([0]), "foo")


# === MultiStepForecaster ===


class TestMultiStepForecaster:
    def test_invalid_momentum(self):
        with pytest.raises(ValueError, match="momentum must be in"):
            MultiStepForecaster(momentum=0.0)

    def test_invalid_decay_rate(self):
        with pytest.raises(ValueError, match="decay_rate must be"):
            MultiStepForecaster(decay_rate=-0.1)

    def test_invalid_blur_growth(self):
        with pytest.raises(ValueError, match="blur_growth must be"):
            MultiStepForecaster(blur_growth=-0.01)

    def test_rollout_recursive(self):
        model = _LinModel(coef=np.array([0.9]))
        fc = MultiStepForecaster(momentum=0.98, decay_rate=0.01)
        result = fc.rollout(model, np.array([1.0]), n_steps=5, method="recursive")
        assert isinstance(result, RolloutResult)
        assert result.values.shape == (5,)
        assert result.uncertainties.shape == (5,)
        np.testing.assert_array_equal(result.steps, np.arange(1, 6))
        np.testing.assert_allclose(result.uncertainties, [0.02, 0.04, 0.06, 0.08, 0.10])

    def test_rollout_momentum(self):
        model = _LinModel(coef=np.array([0.9]))
        fc = MultiStepForecaster(momentum=0.9, decay_rate=0.05, blur_growth=0.0)
        result = fc.rollout(model, np.array([1.0]), n_steps=10, method="momentum", climatology=5.0)
        assert result.values.shape == (10,)
        assert np.all(np.isfinite(result.values))

    def test_rollout_clip_range(self):
        model = _LinModel(coef=np.array([10.0]))
        fc = MultiStepForecaster(clip_range=(0.0, 5.0))
        result = fc.rollout(model, np.array([1.0]), n_steps=5, method="recursive")
        assert np.all(result.values >= 0.0)
        assert np.all(result.values <= 5.0)

    def test_rollout_zero_steps(self):
        fc = MultiStepForecaster()
        with pytest.raises(ValueError, match="n_steps must be positive"):
            fc.rollout(_LinModel(), np.array([1.0]), n_steps=0)

    def test_rollout_momentum_no_climatology(self):
        model = _LinModel(coef=np.array([0.9]))
        fc = MultiStepForecaster(momentum=0.95, decay_rate=0.01)
        result = fc.rollout(model, np.array([1.0]), n_steps=5, method="momentum")
        assert result.values.shape == (5,)

    def test_rollout_result_post_init(self):
        r = RolloutResult(values=[1, 2], uncertainties=[0.1, 0.2], steps=[1, 2])
        assert r.values.dtype == np.float64
        assert r.steps.dtype == np.intp


# === ProbabilisticPredictor ===


class TestProbabilisticPredictor:
    def setup_method(self):
        self.pp = ProbabilisticPredictor()

    def test_ensemble_predict_basic(self):
        m1 = _LinModel(coef=np.array([1.0]))
        m2 = _LinModel(coef=np.array([2.0]))
        result = self.pp.ensemble_predict([m1, m2], np.array([1.0]))
        assert isinstance(result, ForecastResult)
        assert result.values[0] == pytest.approx(1.5)

    def test_ensemble_predict_weighted(self):
        m1 = _LinModel(coef=np.array([1.0]))
        m2 = _LinModel(coef=np.array([3.0]))
        result = self.pp.ensemble_predict([m1, m2], np.array([1.0]), weights=[0.25, 0.75])
        assert result.values[0] == pytest.approx(2.5)

    def test_ensemble_predict_empty_models(self):
        with pytest.raises(ValueError, match="At least one model"):
            self.pp.ensemble_predict([], np.array([1.0]))

    def test_ensemble_predict_zero_weights(self):
        m1 = _LinModel()
        with pytest.raises(ValueError, match="Sum of weights must be positive"):
            self.pp.ensemble_predict([m1], np.array([1.0]), weights=[0.0])

    def test_ensemble_predict_quantiles(self):
        m1 = _LinModel(coef=np.array([1.0]))
        m2 = _LinModel(coef=np.array([2.0]))
        m3 = _LinModel(coef=np.array([1.5]))
        result = self.pp.ensemble_predict([m1, m2, m3], np.array([1.0]))
        assert result.lower is not None
        assert result.upper is not None

    def test_mc_dropout_predict(self):
        class _MCDropModel:
            def __init__(self):
                self._train_mode = False

            def train(self, mode=True):
                self._train_mode = mode

            def eval(self):
                self._train_mode = False

            def predict(self, X):
                if self._train_mode:
                    return np.array([np.random.randn()])
                return np.array([0.0])

        model = _MCDropModel()
        result = self.pp.mc_dropout_predict(model, np.array([1.0]), n_forward=20)
        assert result.values.shape == (1,)
        assert result.lower is not None
        assert result.metadata["method"] == "mc_dropout"

    def test_quantile_regression_predict(self):
        class _QuantileModel:
            def predict(self, X):
                return np.array([0.1, 0.25, 0.5, 0.75, 0.9])

        result = self.pp.quantile_regression_predict(_QuantileModel(), np.array([1.0]))
        assert result.values.shape == (1,)

    def test_calibration_curve_basic(self):
        np.random.seed(42)
        probs = np.random.uniform(0, 1, 200)
        obs = (probs > 0.5).astype(float)
        result = self.pp.calibration_curve(probs, obs, n_bins=10)
        assert len(result["bin_centers"]) == 10
        assert len(result["bin_edges"]) == 11

    def test_calibration_curve_empty(self):
        result = self.pp.calibration_curve(np.array([]), np.array([]))
        assert np.all(result["counts"] == 0)

    def test_calibration_curve_with_nan(self):
        probs = np.array([0.1, np.nan, 0.9, 0.5])
        obs = np.array([0, 1, 1, 0])
        result = self.pp.calibration_curve(probs, obs, n_bins=5)
        assert np.sum(result["counts"]) == 3

    def test_crps_deterministic(self):
        preds = np.array([1.0, 2.0, 3.0])
        obs = np.array([1.0, 2.0, 3.0])
        assert self.pp.crps(preds, obs) == pytest.approx(0.0)

    def test_crps_ensemble(self):
        preds = np.array([[1.0, 1.5], [2.0, 2.5], [3.0, 3.5]])
        obs = np.array([1.0, 2.0, 3.0])
        crps = self.pp.crps(preds, obs)
        assert crps >= 0.0
        assert np.isfinite(crps)

    def test_crps_with_nan(self):
        preds = np.array([1.0, np.nan, 3.0])
        obs = np.array([1.0, 2.0, np.nan])
        crps = self.pp.crps(preds, obs)
        assert np.isfinite(crps)

    def test_crps_empty(self):
        assert np.isnan(self.pp.crps(np.array([]), np.array([])))


# === Verification metrics ===


class TestVerification:
    def test_rmse_perfect(self):
        y = np.array([1.0, 2.0, 3.0])
        assert rmse(y, y) == pytest.approx(0.0)

    def test_rmse_basic(self):
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.0, 3.0, 2.0])
        assert rmse(y_true, y_pred) == pytest.approx(np.sqrt(2.0 / 3))

    def test_rmse_with_nan(self):
        y_true = np.array([1.0, np.nan, 3.0])
        y_pred = np.array([1.0, 2.0, 4.0])
        # nan filtered: y_true=[1,3], y_pred=[1,4], diff=[0,1], rmse=sqrt(0.5)
        assert rmse(y_true, y_pred) == pytest.approx(np.sqrt(0.5))

    def test_rmse_all_nan(self):
        assert np.isnan(rmse(np.array([np.nan]), np.array([np.nan])))

    def test_mae_perfect(self):
        y = np.array([1.0, 2.0])
        assert mae(y, y) == pytest.approx(0.0)

    def test_mae_basic(self):
        assert mae(np.array([0, 10]), np.array([5, 5])) == pytest.approx(5.0)

    def test_mae_all_nan(self):
        assert np.isnan(mae(np.array([np.nan]), np.array([np.nan])))

    def test_mape_basic(self):
        y_true = np.array([100.0, 200.0])
        y_pred = np.array([110.0, 180.0])
        expected = (0.1 + 0.1) / 2
        assert mape(y_true, y_pred) == pytest.approx(expected)

    def test_mape_with_zeros(self):
        y_true = np.array([0.0, 10.0])
        y_pred = np.array([1.0, 12.0])
        assert mape(y_true, y_pred) == pytest.approx(0.2)

    def test_mape_all_zeros(self):
        assert np.isnan(mape(np.array([0.0, 0.0]), np.array([1.0, 2.0])))

    def test_bias_perfect(self):
        y = np.array([1.0, 2.0])
        assert bias(y, y) == pytest.approx(0.0)

    def test_bias_positive(self):
        assert bias(np.array([0, 0]), np.array([5, 5])) == pytest.approx(5.0)

    def test_bias_all_nan(self):
        assert np.isnan(bias(np.array([np.nan]), np.array([np.nan])))

    def test_acc_perfect(self):
        y_true = np.array([1.0, 2.0, 3.0])
        assert acc(y_true, y_true, climatology=0.0) == pytest.approx(1.0)

    def test_acc_no_skill(self):
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([3.0, 2.0, 1.0])
        result = acc(y_true, y_pred, climatology=2.0)
        assert result == pytest.approx(-1.0)

    def test_acc_with_nan(self):
        y_true = np.array([1.0, np.nan, 3.0])
        y_pred = np.array([1.0, 2.0, 3.0])
        result = acc(y_true, y_pred, climatology=2.0)
        assert np.isfinite(result)

    def test_acc_climatology_array(self):
        y_true = np.array([1.0, 2.0, 3.0])
        clim = np.array([1.5, 2.0, 2.5])
        result = acc(y_true, y_true, climatology=clim)
        assert result == pytest.approx(1.0)

    def test_acc_too_few(self):
        assert np.isnan(acc(np.array([1.0]), np.array([2.0]), climatology=0.0))

    def test_brier_score_perfect(self):
        assert brier_score(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == pytest.approx(0.0)

    def test_brier_score_imperfect(self):
        bs = brier_score(np.array([0.8, 0.2]), np.array([1.0, 0.0]))
        expected = (0.2**2 + 0.2**2) / 2
        assert bs == pytest.approx(expected)

    def test_brier_score_empty(self):
        assert np.isnan(brier_score(np.array([]), np.array([])))

    def test_brier_skill_score_perfect(self):
        y_prob = np.array([1.0, 0.0, 1.0])
        y_obs = np.array([1.0, 0.0, 1.0])
        bss = brier_skill_score(y_prob, y_obs, climatology_prob=0.5)
        assert bss == pytest.approx(1.0)

    def test_brier_skill_score_no_skill(self):
        y_prob = np.array([0.5, 0.5, 0.5])
        y_obs = np.array([1.0, 0.0, 1.0])
        bss = brier_skill_score(y_prob, y_obs, climatology_prob=0.5)
        assert bss == pytest.approx(0.0)

    def test_roc_auc_perfect(self):
        y_prob = np.array([0.9, 0.8, 0.3, 0.1])
        y_obs = np.array([1, 1, 0, 0])
        assert roc_auc(y_prob, y_obs) == pytest.approx(1.0)

    def test_roc_auc_random(self):
        np.random.seed(42)
        y_prob = np.random.uniform(0, 1, 200)
        y_obs = (np.random.uniform(0, 1, 200) > 0.5).astype(float)
        auc = roc_auc(y_prob, y_obs)
        assert 0.0 <= auc <= 1.0

    def test_roc_auc_all_pos(self):
        assert np.isnan(roc_auc(np.array([1.0, 1.0]), np.array([1, 1])))

    def test_roc_auc_all_neg(self):
        assert np.isnan(roc_auc(np.array([0.0, 0.0]), np.array([0, 0])))

    def test_roc_auc_empty(self):
        assert np.isnan(roc_auc(np.array([]), np.array([])))

    def test_discrimination(self):
        y_prob = np.array([0.1, 0.3, 0.7, 0.9, 0.2, 0.8])
        y_obs = np.array([0, 0, 1, 1, 0, 1])
        result = discrimination(y_prob, y_obs, n_bins=5)
        assert "bin_edges" in result
        assert "event_hist" in result
        assert "no_event_hist" in result
        assert len(result["bin_edges"]) == 6

    def test_reliability_diagram(self):
        np.random.seed(42)
        probs = np.random.uniform(0, 1, 200)
        obs = (probs > 0.5).astype(float)
        result = reliability_diagram(probs, obs, n_bins=10)
        assert "bin_centers" in result
        assert "observed_freq" in result
        assert "perfection" in result
        np.testing.assert_array_equal(result["bin_centers"], result["perfection"])
