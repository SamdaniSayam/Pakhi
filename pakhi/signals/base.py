"""Signal base classes and Kelly criterion position sizing.

Every weather signal generator inherits from ``BaseSignal`` and
produces a ``Signal`` dataclass that the execution layer can act on.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np

__all__ = ["Action", "BaseSignal", "Signal", "position_size"]

logger = logging.getLogger(__name__)


class Action(str, Enum):
    """Trading action."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class Signal:
    """Container for a trading signal.

    Attributes
    ----------
    action : Action
        Direction of the trade.
    size : float
        Position size as a fraction of capital, in ``[0, 1]``.
    confidence : float
        Model confidence in ``[0, 1]``.
    instrument : str
        Target instrument ticker or identifier.
    timestamp : datetime
        Time the signal was generated.
    reasoning : str
        Human-readable explanation of the signal.
    metadata : dict
        Arbitrary extra data (model name, thresholds, etc.).
    """

    action: Action
    size: float
    confidence: float
    instrument: str
    timestamp: datetime
    reasoning: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.action, str):
            self.action = Action(self.action)
        self.size = float(np.clip(self.size, 0.0, 1.0))
        self.confidence = float(np.clip(self.confidence, 0.0, 1.0))


class BaseSignal(ABC):
    """Abstract base class for all weather signal generators.

    Subclasses must implement ``generate(forecast)``.
    """

    @abstractmethod
    def generate(self, forecast: Any) -> Signal:
        """Generate a trading signal from a forecast.

        Parameters
        ----------
        forecast : any
            Forecast data specific to the signal type.

        Returns
        -------
        Signal
            The trading signal.
        """
        ...


def position_size(
    confidence: float,
    method: str = "kelly",
    odds: float = 2.0,
    half_kelly: bool = True,
    max_size: float = 0.25,
) -> float:
    """Compute optimal position size from confidence.

    Parameters
    ----------
    confidence : float
        Model's estimated probability of the trade being profitable,
        in ``(0, 1)``.
    method : {"kelly", "uniform", "confidence"}
        Sizing method.

        - ``"kelly"``: Kelly criterion f* = (bp - q) / b.
        - ``"uniform"``: equal sizing regardless of confidence.
        - ``"confidence"``: position = confidence (linear scaling).
    odds : float
        Payoff ratio (b) for Kelly.  Default 2.0 means a winning trade
        returns 2× the risk.
    half_kelly : bool
        If ``True`` (default), return f*/2 for reduced variance.
    max_size : float
        Maximum allowed position size.

    Returns
    -------
    float
        Position size in ``[0, max_size]``.
    """
    confidence = float(np.clip(confidence, 0.0, 1.0))

    if method == "uniform":
        return min(0.1, max_size)

    if method == "confidence":
        return float(np.clip(confidence * max_size, 0.0, max_size))

    if method == "kelly":
        b = max(odds, 0.01)
        p = confidence
        q = 1.0 - p
        kelly_f = (b * p - q) / b
        if kelly_f <= 0:
            return 0.0
        if half_kelly:
            kelly_f /= 2.0
        return float(np.clip(kelly_f, 0.0, max_size))

    raise ValueError(f"Unknown method: {method!r}. Use 'kelly', 'uniform', or 'confidence'.")
