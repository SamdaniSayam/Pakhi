import contextlib

import numpy as np

from pakhi.models.gaussian import GaussianForecaster, _has_sklearn_gp


def test_has_sklearn_gp_missing(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "sklearn.gaussian_process":
            raise ImportError("mock error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    assert _has_sklearn_gp() is False


def test_gaussian_fit_gpytorch_iter():
    X = np.random.rand(10, 2)
    y = np.random.rand(10)
    # 20 iterations will trigger the logger.info on line 127
    model = GaussianForecaster(n_inducing=5, max_optim_iter=20, backend="gpytorch")
    with contextlib.suppress(ImportError):
        # If gpytorch isn't installed, skip
        model.fit(X, y)
