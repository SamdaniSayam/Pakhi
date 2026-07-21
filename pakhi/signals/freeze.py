"""Freeze event signal for orange juice futures.

Detects freezing temperature forecasts and generates LONG signals on
OJ futures.  Historical freezes have driven 15–40% OJ price spikes
within 48 hours.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["FreezeSignal"]

logger = logging.getLogger(__name__)


class FreezeSignal(BaseSignal):
    """Generate trading signals from freeze probability forecasts.

    Parameters
    ----------
    entry_threshold : float
        Minimum freeze probability to enter a LONG position. Default 0.6.
    exit_threshold : float
        Probability below which to go FLAT. Default 0.2.
    time_decay_hours : float
        Half-life in hours for signal strength decay after the freeze
        event peak. Default 48.
    instrument : str
        Instrument to trade. Default ``"OJ_FUTURES"``.
    max_size : float
        Maximum position size. Default 0.20.

    Examples
    --------
    >>> sig_gen = FreezeSignal(entry_threshold=0.7)
    >>> signal = sig_gen.generate(freeze_forecast)
    """

    __all__ = ["generate"]

    def __init__(
        self,
        entry_threshold: float = 0.6,
        exit_threshold: float = 0.2,
        time_decay_hours: float = 48.0,
        instrument: str = "OJ_FUTURES",
        max_size: float = 0.20,
    ) -> None:
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.time_decay_hours = time_decay_hours
        self.instrument = instrument
        self.max_size = max_size

    def generate(self, forecast: dict) -> Signal:
        """Generate a freeze signal from a probability forecast.

        Parameters
        ----------
        forecast : dict
            Must contain:

            - ``"freeze_prob"``: float, probability of freeze event in
              ``[0, 1]``.
            - ``"event_peak_time"``: datetime of expected peak freeze risk.
            - ``"temperature_min"``: float, minimum forecast temperature (°C).
            - ``"current_time"``: datetime, current timestamp.

        Returns
        -------
        Signal
            LONG if freeze risk exceeds threshold, FLAT otherwise.
        """
        freeze_prob = float(forecast.get("freeze_prob", 0.0))
        event_peak = forecast.get("event_peak_time")
        temp_min = float(forecast.get("temperature_min", 10.0))
        current_time = forecast.get("current_time", datetime.now(timezone.utc))

        if event_peak is None:
            event_peak = current_time

        time_since_peak = max(0.0, (current_time - event_peak).total_seconds() / 3600.0)
        decay_factor = float(np.exp(-0.693 * time_since_peak / self.time_decay_hours))

        effective_prob = freeze_prob * decay_factor

        if effective_prob > self.entry_threshold and temp_min < 0.0:
            conf = float(np.clip(effective_prob, 0.0, 1.0))
            size = position_size(
                conf, method="kelly", odds=3.0, half_kelly=True, max_size=self.max_size
            )

            temp_severity = float(np.clip(abs(temp_min) / 10.0, 0.0, 1.0))
            adjusted_size = min(size * (1.0 + 0.5 * temp_severity), self.max_size)

            reasoning = (
                f"Freeze probability {freeze_prob:.1%} (effective {effective_prob:.1%} "
                f"after time decay). Min temperature: {temp_min:.1f}°C. "
                f"Historical OJ spike 15–40% within 48h of freeze."
            )

            logger.info(
                "Freeze signal: LONG %s, size=%.3f, conf=%.3f", self.instrument, adjusted_size, conf
            )

            return Signal(
                action=Action.LONG,
                size=adjusted_size,
                confidence=conf,
                instrument=self.instrument,
                timestamp=current_time,
                reasoning=reasoning,
                metadata={
                    "freeze_prob": freeze_prob,
                    "effective_prob": effective_prob,
                    "temp_min": temp_min,
                    "decay_factor": decay_factor,
                },
            )

        if effective_prob < self.exit_threshold:
            return Signal(
                action=Action.FLAT,
                size=0.0,
                confidence=0.0,
                instrument=self.instrument,
                timestamp=current_time,
                reasoning=f"Freeze probability {effective_prob:.1%} below exit threshold.",
            )

        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=self.instrument,
            timestamp=current_time,
            reasoning=f"Freeze probability {effective_prob:.1%} below entry threshold {self.entry_threshold:.1%}.",
        )
