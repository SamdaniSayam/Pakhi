"""Multi-step forecasting with momentum/decay and progressive blurring.

Implements autoregressive rollout with divergence-prevention mechanisms
suitable for weather-to-market pipelines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

__all__ = ["MultiStepForecaster"]

logger = logging.getLogger(__name__)


class SupportsPredict(Protocol):
    """Protocol for models with a scikit-learn-style predict method."""

    def predict(self, X: np.ndarray) -> np.ndarray: ...


@dataclass
class RolloutResult:
    """Container for multi-step rollout output.

    Attributes
    ----------
    values : np.ndarray
        Predicted values at each step, shape ``(n_steps,)``.
    uncertainties : np.ndarray
        Growing uncertainty estimate (std) per step.
    steps : np.ndarray
        Step indices.
    """

    values: np.ndarray
    uncertainties: np.ndarray
    steps: np.ndarray = field(default_factory=lambda: np.arange(1, 1))

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=np.float64)
        self.uncertainties = np.asarray(self.uncertainties, dtype=np.float64)
        self.steps = np.asarray(self.steps, dtype=np.intp)


class MultiStepForecaster:
    """Autoregressive rollout with momentum/decay and progressive blurring.

    Parameters
    ----------
    momentum : float
        Decay factor applied to predictions to prevent divergence at long
        lead times.  Value in ``(0, 1]``.  1.0 means no momentum damping.
    decay_rate : float
        Per-step exponential decay toward the last observed value.
        0.0 means no decay.  Typical range: ``0.001–0.05``.
    blur_growth : float
        Per-step increase in the uncertainty std.  Models progressive
        loss of skill with lead time.
    clip_range : tuple of float or None
        ``(min, max)`` bounds for predicted values.  Prevents
        unphysical values (e.g. negative precipitation).

    Examples
    --------
    >>> forecaster = MultiStepForecaster(momentum=0.98, decay_rate=0.01)
    >>> result = forecaster.rollout(model, initial_features, n_steps=168)
    """

    __all__ = ["rollout"]

    def __init__(
        self,
        momentum: float = 0.98,
        decay_rate: float = 0.01,
        blur_growth: float = 0.02,
        clip_range: tuple[float, float] | None = None,
    ) -> None:
        if not 0.0 < momentum <= 1.0:
            raise ValueError(f"momentum must be in (0, 1], got {momentum}")
        if decay_rate < 0:
            raise ValueError(f"decay_rate must be >= 0, got {decay_rate}")
        if blur_growth < 0:
            raise ValueError(f"blur_growth must be >= 0, got {blur_growth}")

        self.momentum = momentum
        self.decay_rate = decay_rate
        self.blur_growth = blur_growth
        self.clip_range = clip_range

    def rollout(
        self,
        model: SupportsPredict,
        initial_features: np.ndarray,
        n_steps: int = 168,
        method: str = "recursive",
        climatology: float | None = None,
    ) -> RolloutResult:
        """Perform a multi-step autoregressive rollout.

        Parameters
        ----------
        model : fitted model
            A model with ``predict(X)`` where X is ``(1, n_features)``.
        initial_features : array of shape ``(n_features,)`` or ``(1, n_features)``
            The most recent observed feature vector.
        n_steps : int
            Number of future steps. Default 168 (= 7 days × 24 hours).
        method : {"recursive", "momentum"}
            ``"recursive"``: standard autoregressive rollout.
            ``"momentum"``: applies momentum damping and decay.
        climatology : float, optional
            Climatological mean.  Used as the decay anchor for
            momentum mode.  If ``None``, the first prediction serves
            as the anchor.

        Returns
        -------
        RolloutResult
            Predictions and growing uncertainties per step.
        """
        if n_steps <= 0:
            raise ValueError(f"n_steps must be positive, got {n_steps}")

        X = np.atleast_2d(np.asarray(initial_features, dtype=np.float64)).copy()

        values = np.zeros(n_steps, dtype=np.float64)
        uncertainties = np.zeros(n_steps, dtype=np.float64)
        anchor = float(climatology) if climatology is not None else None

        ema_pred = None

        for h in range(n_steps):
            raw_pred = float(model.predict(X)[0])

            if method == "momentum":
                if anchor is None:
                    anchor = raw_pred
                if ema_pred is None:
                    ema_pred = raw_pred

                ema_pred = self.momentum * ema_pred + (1.0 - self.momentum) * raw_pred
                decayed = ema_pred + (anchor - ema_pred) * (
                    1.0 - np.exp(-self.decay_rate * (h + 1))
                )
                pred = decayed
            else:
                pred = raw_pred

            if self.clip_range is not None:
                pred = np.clip(pred, self.clip_range[0], self.clip_range[1])

            values[h] = pred
            uncertainties[h] = self.blur_growth * (h + 1)

            new_row = np.roll(X, -1, axis=1)
            new_row[0, -1] = pred
            X = new_row

        steps = np.arange(1, n_steps + 1, dtype=np.intp)

        logger.debug(
            "Rollout complete: %d steps, method=%s, final_pred=%.4f, final_unc=%.4f",
            n_steps,
            method,
            values[-1],
            uncertainties[-1],
        )

        return RolloutResult(
            values=values,
            uncertainties=uncertainties,
            steps=steps,
        )
