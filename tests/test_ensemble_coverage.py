import numpy as np

from pakhi.models.base import ForecastResult
from pakhi.models.ensemble import EnsembleForecaster


class DummyModel1D:
    def predict(self, X):
        return ForecastResult(
            deterministic=np.ones(len(X)), quantiles={}, skill_scores={}, metadata={}
        )


def test_ensemble_collect_deterministic_1d():
    ens = EnsembleForecaster(models=[DummyModel1D()], method="mean")
    X = np.zeros((3, 2))
    res = ens._collect_deterministic(X)
    assert res.shape == (1, 3, 1)


class DummyModelException:
    def predict(self, X):
        raise ValueError("mock error")


def test_ensemble_bma_exception():
    ens = EnsembleForecaster(models=[DummyModelException()], method="bma")
    X = np.zeros((3, 2))
    y = np.zeros(3)
    # The first model raises, so rmse = 1e6
    w = ens._compute_bma_weights(X, y)
    assert len(w) == 1


class DummyModelNoQuantiles:
    def predict(self, X):
        return ForecastResult(
            deterministic=np.ones((len(X), 1)), quantiles={}, skill_scores={}, metadata={}
        )

    def predict_proba(self, X, quantiles):
        # returns result but without quantiles populated
        return ForecastResult(
            deterministic=np.ones((len(X), 1)), quantiles={}, skill_scores={}, metadata={}
        )


def test_ensemble_predict_proba_no_quantiles():
    ens = EnsembleForecaster(models=[DummyModelNoQuantiles()], method="mean")
    ens.fit(np.zeros((3, 2)), np.zeros(3))
    res = ens.predict_proba(np.zeros((3, 2)), quantiles=[0.5])
    assert "q0.5" in res.quantiles


def test_ensemble_retrain_weights_zero_sum():
    # hist_w.sum() == 0 if recent_skill rmse is huge
    ens = EnsembleForecaster(models=[DummyModel1D(), DummyModel1D()], method="mean")
    # current_w doesn't matter, we want hist_w to sum to 0. exp(-1000) = 0
    ens.retrain_weights(
        np.zeros((3, 2)), np.zeros(3), recent_skill=[{"rmse": 1000}, {"rmse": 1000}]
    )
    assert len(ens._weights) == 2
