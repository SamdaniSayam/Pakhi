"""Ensemble signal combiner for correlated weather signals.

Aggregates multiple weather signals into a single trade decision with
correlation-adjusted position sizing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["EnsembleSignal"]

logger = logging.getLogger(__name__)


class EnsembleSignal(BaseSignal):
    """Combine multiple weather signals into a unified trade signal.

    Parameters
    ----------
    min_agreement : float
        Minimum fraction of signals that must agree on direction to
        generate a non-FLAT signal. Default 0.5.
    correlation_penalty : float
        Penalty factor for correlated signals.  0.0 means full
        correlation (full penalty), 1.0 means uncorrelated. Default 0.3.
    max_size : float
        Maximum ensemble position size. Default 0.25.

    Examples
    --------
    >>> ensemble = EnsembleSignal()
    >>> combined = ensemble.combine([freeze_signal, drought_signal])
    """

    __all__ = ["combine"]

    def __init__(
        self,
        min_agreement: float = 0.5,
        correlation_penalty: float = 0.3,
        max_size: float = 0.25,
    ) -> None:
        self.min_agreement = min_agreement
        self.correlation_penalty = correlation_penalty
        self.max_size = max_size

    def generate(self, forecast: Any) -> Signal:
        """Not used directly — call ``combine()`` instead."""
        raise NotImplementedError("Use combine(signals) for ensemble signals.")

    def combine(self, signals: Sequence[Signal]) -> Signal:
        """Combine multiple signals into a single ensemble signal.

        Parameters
        ----------
        signals : list of Signal
            Individual weather signals to combine.

        Returns
        -------
        Signal
            Aggregated signal with correlation-adjusted sizing.

        Raises
        ------
        ValueError
            If *signals* is empty.
        """
        if not signals:
            raise ValueError("At least one signal is required.")

        valid = [s for s in signals if s.confidence > 0]
        if not valid:
            return self._flat_signal(
                signals[0].timestamp if signals else datetime.utcnow(),
                "No signals with confidence > 0.",
            )

        directions = np.array([self._direction_value(s.action) for s in valid], dtype=np.float64)
        confidences = np.array([s.confidence for s in valid], dtype=np.float64)
        n_long = int(np.sum(directions > 0))
        n_short = int(np.sum(directions < 0))
        n_total = len(valid)

        agreement = max(n_long, n_short) / n_total

        if agreement < self.min_agreement:
            ts = valid[0].timestamp
            instruments = sorted(set(s.instrument for s in valid))
            return Signal(
                action=Action.FLAT,
                size=0.0,
                confidence=0.0,
                instrument=",".join(instruments),
                timestamp=ts,
                reasoning=(
                    f"Insufficient agreement: {max(n_long, n_short)}/{n_total} signals "
                    f"agree (need {self.min_agreement:.0%}). "
                    f"LONG={n_long}, SHORT={n_short}."
                ),
            )

        if n_long > n_short:
            consensus = Action.LONG
        else:
            consensus = Action.SHORT

        corr_adjustment = 1.0 - self.correlation_penalty * (1.0 - agreement)
        weighted_conf = float(np.average(confidences, weights=confidences))
        weighted_conf *= corr_adjustment

        avg_conf = float(np.mean(confidences))
        size = position_size(
            float(np.clip(weighted_conf, 0.0, 1.0)),
            method="kelly",
            odds=2.0,
            half_kelly=True,
            max_size=self.max_size,
        )

        instruments = sorted(set(s.instrument for s in valid))
        ts = valid[0].timestamp

        reasoning_parts = [
            f"Ensemble of {n_total} signals: {n_long} LONG, {n_short} SHORT.",
            f"Agreement: {agreement:.0%}, direction: {consensus.value}.",
            f"Mean confidence: {avg_conf:.3f}, adjusted: {weighted_conf:.3f}.",
            f"Correlation penalty: {self.correlation_penalty:.1%}, adjustment: {corr_adjustment:.3f}.",
        ]

        # Include individual signal reasoning
        for s in valid:
            reasoning_parts.append(
                f"  [{s.instrument}] {s.action.value} conf={s.confidence:.3f}: {s.reasoning[:80]}"
            )

        logger.info(
            "Ensemble signal: %s %s, size=%.3f, conf=%.3f, agreement=%.0f%%",
            consensus.value,
            instruments,
            size,
            weighted_conf,
            agreement * 100,
        )

        return Signal(
            action=consensus,
            size=size,
            confidence=float(np.clip(weighted_conf, 0.0, 1.0)),
            instrument=",".join(instruments),
            timestamp=ts,
            reasoning="\n".join(reasoning_parts),
            metadata={
                "n_signals": n_total,
                "n_long": n_long,
                "n_short": n_short,
                "agreement": agreement,
                "correlation_adjustment": corr_adjustment,
                "individual_confidences": confidences.tolist(),
            },
        )

    @staticmethod
    def _direction_value(action: Action) -> float:
        if action == Action.LONG:
            return 1.0
        elif action == Action.SHORT:
            return -1.0
        return 0.0

    def _flat_signal(self, ts: datetime, reason: str) -> Signal:
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="ENSEMBLE",
            timestamp=ts,
            reasoning=reason,
        )
