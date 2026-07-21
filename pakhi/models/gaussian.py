"""Gaussian Process forecaster with GPyTorch (preferred) or sklearn fallback.

Provides principled Bayesian uncertainty quantification with a Matérn 5/2
kernel — the standard choice for smooth-but-not-too-smooth weather fields.

If GPyTorch is available the model uses a sparse GP approximation with
inducing points for scalability.  Otherwise it falls back to
``sklearn.gaussian_process.GaussianProcessRegressor``.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, StandardScaler, compute_metrics

__all__ = ["GaussianForecaster"]

logger = logging.getLogger(__name__)


def _has_gpytorch() -> bool:
    try:
        import gpytorch  # noqa: F401

        return True
    except ImportError:
        return False


def _has_sklearn_gp() -> bool:
    try:
        from sklearn.gaussian_process import GaussianProcessRegressor  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# GPyTorch implementation
# ---------------------------------------------------------------------------


class _GPyTorchModel:
    """Sparse GP with Matérn 5/2 via GPyTorch."""

    def __init__(
        self,
        n_inducing: int = 500,
        noise_prior: str = "log_normal",
        lengthscale_prior: float = 1.0,
        max_optim_iter: int = 100,
    ) -> None:
        import gpytorch
        import torch

        self.gpytorch = gpytorch
        self.torch = torch
        self.n_inducing = n_inducing
        self.noise_prior = noise_prior
        self.lengthscale_prior = lengthscale_prior
        self.max_optim_iter = max_optim_iter
        self.model: Any = None
        self.likelihood: Any = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        gpytorch = self.gpytorch
        torch = self.torch

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32).squeeze()

        n_ind = min(self.n_inducing, X_t.shape[0])

        class _SparseGPModel(gpytorch.models.ApproximateGP):
            def __init__(self, inducing_points):
                variational_distribution = gpytorch.variational.CholeskyVariationalDistribution(
                    inducing_points.size(0)
                )
                variational_strategy = gpytorch.variational.VariationalStrategy(
                    self, inducing_points, variational_distribution, learn_inducing_locations=True
                )
                super().__init__(variational_strategy)

            # We'll assign the likelihood and kernel outside.

        inducing = X_t[:n_ind]
        self.model = _SparseGPModel(inducing)
        self.likelihood = gpytorch.likelihoods.GaussianLikelihood()

        kernel = gpytorch.kernels.MaternKernel(nu=2.5)
        kernel.lengthscale = torch.tensor([self.lengthscale_prior] * X_t.shape[1])
        self.model.covar_module = kernel

        self.model.mean_module = gpytorch.means.ConstantMean()

        device = X_t.device
        self.model = self.model.to(device)
        self.likelihood = self.likelihood.to(device)

        self.model.train()
        self.likelihood.train()

        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.01)
        mll = gpytorch.mlls.VariationalELBO(self.likelihood, self.model, num_data=X_t.shape[0])

        for i in range(self.max_optim_iter):
            optimizer.zero_grad()
            output = self.model(X_t)
            loss = -mll(output, y_t)
            loss.backward()
            optimizer.step()
            if (i + 1) % 20 == 0:
                logger.info(
                    "GPyTorch optim iter %d/%d  loss=%.4f", i + 1, self.max_optim_iter, loss.item()
                )

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns (mean, lower, upper)."""
        gpytorch = self.gpytorch
        torch = self.torch

        self.model.eval()
        self.likelihood.eval()

        X_t = torch.tensor(X, dtype=torch.float32)
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            pred = self.likelihood(self.model(X_t))
            mean = pred.mean.cpu().numpy()
            lower, upper = pred.confidence_region()
            lower = lower.cpu().numpy()
            upper = upper.cpu().numpy()

        return mean, lower, upper

    def sample(self, X: np.ndarray, n_samples: int = 50) -> np.ndarray:
        """Draw posterior samples. Returns (n_samples, n)."""
        torch = self.torch

        self.model.eval()
        X_t = torch.tensor(X, dtype=torch.float32)
        with torch.no_grad():
            pred = self.model(X_t)
            samples = pred.rsample(torch.Size([n_samples]))
            return samples.cpu().numpy()


# ---------------------------------------------------------------------------
# Sklearn fallback
# ---------------------------------------------------------------------------


class _SklearnGPModel:
    """Thin wrapper around sklearn's ``GaussianProcessRegressor``."""

    def __init__(self, lengthscale_prior: float = 1.0) -> None:
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern

        kernel = Matern(length_scale=lengthscale_prior, nu=2.5)
        self.model = GaussianProcessRegressor(
            kernel=kernel,
            n_restarts_optimizer=5,
            alpha=1e-6,
            normalize_y=True,
        )

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.model.fit(X, y.ravel())

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        mean, std = self.model.predict(X, return_std=True)
        return mean, mean - 1.96 * std, mean + 1.96 * std

    def sample(self, X: np.ndarray, n_samples: int = 50) -> np.ndarray:
        samples = self.model.sample_y(X, n_samples=n_samples)
        return samples.T  # (n_samples, n)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class GaussianForecaster(BaseModel):
    """Gaussian Process forecaster with true Bayesian confidence intervals.

    When GPyTorch is installed, uses a sparse GP with Matérn 5/2 kernel
    and variational inference (scalable to ~10k points).  Falls back to
    sklearn's exact GP otherwise (limited to ~5k points).

    Parameters
    ----------
    n_inducing : int
        Number of inducing points (GPyTorch only).
    noise_prior : str
        Prior on the noise variance (``"log_normal"``).
    lengthscale_prior : float
        Initial lengthscale for the Matérn kernel.
    max_optim_iter : int
        Maximum optimisation iterations (GPyTorch only).
    backend : ``"gpytorch"`` or ``"auto"``
        Force a specific backend or let the model choose automatically.

    Examples
    --------
    >>> model = GaussianForecaster(n_inducing=500)
    >>> model.fit(X_train, y_train)
    >>> result = model.predict_proba(X_test, quantiles=[0.1, 0.5, 0.9])
    """

    def __init__(
        self,
        n_inducing: int = 500,
        noise_prior: str = "log_normal",
        lengthscale_prior: float = 1.0,
        max_optim_iter: int = 100,
        backend: str = "auto",
    ) -> None:
        self.n_inducing = n_inducing
        self.noise_prior = noise_prior
        self.lengthscale_prior = lengthscale_prior
        self.max_optim_iter = max_optim_iter
        self.backend = backend

        self._x_scaler = StandardScaler()
        self._y_scaler = StandardScaler()
        self._gp: _GPyTorchModel | _SklearnGPModel | None = None
        self._fitted = False

    def _init_backend(self) -> None:
        if self.backend == "gpytorch" or (self.backend == "auto" and _has_gpytorch()):
            self._gp = _GPyTorchModel(
                n_inducing=self.n_inducing,
                noise_prior=self.noise_prior,
                lengthscale_prior=self.lengthscale_prior,
                max_optim_iter=self.max_optim_iter,
            )
        elif _has_sklearn_gp():
            logger.warning(
                "GPyTorch not found, falling back to sklearn GaussianProcessRegressor. "
                "Install gpytorch for sparse GP support."
            )
            self._gp = _SklearnGPModel(lengthscale_prior=self.lengthscale_prior)
        else:
            raise ImportError(
                "Neither GPyTorch nor scikit-learn GaussianProcessRegressor is available. "
                "Install with: pip install pakhi[ml]"
            )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> GaussianForecaster:
        """Fit the Gaussian Process.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
        y : array of shape ``(n_samples,)``
        X_val, y_val : ignored (GP has no concept of epoch-based early stopping).
        """
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64).ravel()

        if X.shape[0] < 3:
            raise ValueError(f"Need at least 3 samples, got {X.shape[0]}.")

        X_scaled = self._x_scaler.fit_transform(X)
        y_scaled = self._y_scaler.fit_transform(y.reshape(-1, 1)).ravel()

        self._init_backend()
        assert self._gp is not None
        self._gp.fit(X_scaled, y_scaled)
        self._fitted = True
        return self

    def predict(self, X: np.ndarray) -> ForecastResult:
        """Deterministic GP prediction (posterior mean)."""
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float64)
        X_scaled = self._x_scaler.transform(X)

        assert self._gp is not None
        mean, lower, upper = self._gp.predict(X_scaled)
        mean = self._y_scaler.inverse_transform(mean.reshape(-1, 1)).ravel()
        lower = self._y_scaler.inverse_transform(lower.reshape(-1, 1)).ravel()
        upper = self._y_scaler.inverse_transform(upper.reshape(-1, 1)).ravel()

        return ForecastResult(
            deterministic=mean.reshape(-1, 1),
            quantiles={},
            skill_scores={},
            metadata={
                "model": "gaussian_process",
                "lower_95": lower,
                "upper_95": upper,
                "backend": "gpytorch"
                if _has_gpytorch() and self.backend != "sklearn"
                else "sklearn",
            },
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Probabilistic GP forecast via posterior samples or confidence region."""
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        X = np.asarray(X, dtype=np.float64)
        X_scaled = self._x_scaler.transform(X)

        assert self._gp is not None
        mean, _lower, _upper = self._gp.predict(X_scaled)

        # Draw posterior samples for quantile estimation.
        samples = self._gp.sample(X_scaled, n_samples=100)  # (100, n)
        # Inverse-transform each sample.
        samples_inv = np.stack(
            [self._y_scaler.inverse_transform(s.reshape(-1, 1)).ravel() for s in samples], axis=0
        )

        det = self._y_scaler.inverse_transform(mean.reshape(-1, 1)).ravel()

        result = ForecastResult(
            deterministic=det.reshape(-1, 1),
            quantiles={},
            skill_scores={},
            metadata={"model": "gaussian_process"},
        )

        for q in quantiles:
            label = f"q{q}"
            result.quantiles[label] = np.quantile(samples_inv, q, axis=0).reshape(-1, 1)

        return result

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
    ) -> dict[str, float]:
        result = self.predict(X)
        return compute_metrics(y, result.deterministic, metrics=metrics)

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        backend_name = "auto"
        if self._gp is not None:
            backend_name = "gpytorch" if isinstance(self._gp, _GPyTorchModel) else "sklearn"
        return (
            f"GaussianForecaster(backend='{backend_name}', "
            f"n_inducing={self.n_inducing}, status={status})"
        )
