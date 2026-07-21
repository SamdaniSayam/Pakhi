"""Portfolio construction and position sizing.

Provides Kelly criterion, equal-weight, and risk-parity allocation methods
with configurable maximum position limits to prevent overexposure.
"""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np

__all__ = [
    "Portfolio",
    "SizingMethod",
]

logger = logging.getLogger(__name__)


class SizingMethod(str, Enum):
    """Supported position sizing methods."""

    KELLY = "kelly"
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"


class Portfolio:
    """Portfolio construction and position sizing engine.

    Parameters
    ----------
    max_position : float
        Maximum allowable position size as a fraction of capital.
        Default ``0.10`` (10%).
    kelly_fraction : float
        Fraction of full Kelly to use.  ``0.5`` = half-Kelly (default).
        Values in ``(0, 1]``; smaller values are more conservative.

    Examples
    --------
    >>> portfolio = Portfolio(max_position=0.1)
    >>> portfolio.position_size(0.7, method="kelly", odds=2.0)
    0.075
    """

    def __init__(
        self,
        max_position: float = 0.10,
        kelly_fraction: float = 0.5,
    ) -> None:
        if not 0.0 < max_position <= 1.0:
            raise ValueError(f"max_position must be in (0, 1], got {max_position}")
        if not 0.0 < kelly_fraction <= 1.0:
            raise ValueError(f"kelly_fraction must be in (0, 1], got {kelly_fraction}")
        self.max_position = max_position
        self.kelly_fraction = kelly_fraction

    def position_size(
        self,
        confidence: float,
        method: SizingMethod | str = "kelly",
        max_position: float | None = None,
        **kwargs: float,
    ) -> float:
        """Compute the position size for a single instrument.

        Parameters
        ----------
        confidence : float
            Model confidence (probability of the trade being profitable)
            in ``(0, 1)``.
        method : SizingMethod or str
            Position sizing method.  One of ``"kelly"``, ``"equal_weight"``,
            ``"risk_parity"``.
        max_position : float, optional
            Override the instance-level max position limit for this call.
        **kwargs
            Additional keyword arguments forwarded to the sizing method
            (e.g. ``odds`` for Kelly, ``n_instruments`` for equal weight,
            ``returns_matrix`` for risk parity).

        Returns
        -------
        float
            Position size in ``[0, max_position]``.
        """
        confidence = float(np.clip(confidence, 0.0, 1.0))
        cap = max_position if max_position is not None else self.max_position

        method_str = method.value if isinstance(method, SizingMethod) else method

        if method_str == "kelly":
            odds = float(kwargs.get("odds", 2.0))
            size = self.kelly_criterion(confidence, odds=odds)
        elif method_str == "equal_weight":
            n = int(kwargs.get("n_instruments", 1))
            size = self.equal_weight(n)
        elif method_str == "risk_parity":
            returns_matrix = kwargs.get("returns_matrix")
            if returns_matrix is None:
                raise ValueError("returns_matrix is required for risk_parity sizing.")
            weights = self.risk_parity(returns_matrix)
            # Use the first weight as the position size (single-instrument context).
            size = float(weights[0]) if len(weights) > 0 else 0.0
        else:
            raise ValueError(f"Unknown sizing method: {method_str!r}")

        return float(np.clip(size, 0.0, cap))

    def kelly_criterion(
        self,
        win_rate: float,
        odds: float = 2.0,
    ) -> float:
        """Full Kelly fraction: f* = (b*p - q) / b.

        Parameters
        ----------
        win_rate : float
            Estimated probability of a winning trade, in ``(0, 1)``.
        odds : float
            Payoff ratio *b* (average win / average loss).  Must be > 0.

        Returns
        -------
        float
            Kelly-optimal fraction, scaled by ``self.kelly_fraction`` and
            capped at ``self.max_position``.  Returns 0 if edge is negative.
        """
        p = float(np.clip(win_rate, 0.0, 1.0))
        b = max(odds, 1e-6)
        q = 1.0 - p

        kelly_f = (b * p - q) / b

        if kelly_f <= 0:
            return 0.0

        kelly_f *= self.kelly_fraction
        return float(np.clip(kelly_f, 0.0, self.max_position))

    def equal_weight(self, n_instruments: int) -> float:
        """Equal-weight allocation: 1 / n.

        Parameters
        ----------
        n_instruments : int
            Number of instruments in the portfolio.

        Returns
        -------
        float
            Weight per instrument, capped at ``self.max_position``.
        """
        if n_instruments <= 0:
            raise ValueError(f"n_instruments must be >= 1, got {n_instruments}")
        weight = 1.0 / n_instruments
        return float(np.clip(weight, 0.0, self.max_position))

    def risk_parity(self, returns_matrix: np.ndarray) -> np.ndarray:
        """Risk-parity weights that equalise risk contribution.

        Uses an iterative inverse-volatility approach:  w_i ∝ 1 / σ_i.

        Parameters
        ----------
        returns_matrix : array of shape ``(n_periods, n_instruments)``
            Historical return series for each instrument.

        Returns
        -------
        np.ndarray of shape ``(n_instruments,)``
            Normalised weights that sum to 1 (before max_position clamping).
        """
        R = np.asarray(returns_matrix, dtype=np.float64)
        if R.ndim == 1:
            R = R.reshape(-1, 1)

        vols = np.nanstd(R, axis=0, ddof=1)
        # Replace zero or NaN volatility with a floor to avoid division by zero.
        vols = np.where((~np.isfinite(vols)) | (vols < 1e-10), 1e-10, vols)

        inv_vol = 1.0 / vols
        weights = inv_vol / inv_vol.sum()

        logger.debug("Risk-parity weights: %s", weights.tolist())
        return weights

    def __repr__(self) -> str:
        return f"Portfolio(max_position={self.max_position}, kelly_fraction={self.kelly_fraction})"
