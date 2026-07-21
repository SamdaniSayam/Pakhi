"""Hurricane event signal for natural gas futures.

Detects landfall probability and generates LONG signals on nat gas
futures when Gulf production shut-in risk is elevated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["HurricaneSignal"]

logger = logging.getLogger(__name__)

CATEGORY_DISRUPTION: dict[int, float] = {
    1: 0.05,
    2: 0.15,
    3: 0.35,
    4: 0.60,
    5: 0.90,
}


class HurricaneSignal(BaseSignal):
    """Generate trading signals from hurricane track forecasts.

    Parameters
    ----------
    entry_threshold : float
        Minimum landfall probability to enter. Default 0.4.
    gulf_proximity_miles : float
        Maximum distance from Gulf production area to consider
        shut-in risk. Default 200.
    max_size : float
        Maximum position size. Default 0.20.

    Examples
    --------
    >>> sig = HurricaneSignal(entry_threshold=0.5)
    >>> signal = sig.generate(track_forecast, landfall_probability=0.65)
    """

    __all__ = ["generate"]

    def __init__(
        self,
        entry_threshold: float = 0.4,
        gulf_proximity_miles: float = 200.0,
        max_size: float = 0.20,
    ) -> None:
        self.entry_threshold = entry_threshold
        self.gulf_proximity_miles = gulf_proximity_miles
        self.max_size = max_size

    def generate(
        self,
        track_forecast: dict,
        landfall_probability: float | None = None,
    ) -> Signal:
        """Generate a hurricane signal from track forecast data.

        Parameters
        ----------
        track_forecast : dict
            Must contain:

            - ``"landfall_prob"``: float in ``[0, 1]`` (or use
              *landfall_probability* arg).
            - ``"category"``: int, Saffir-Simpson category 1–5.
            - ``"closest_approach_miles"``: float, distance to Gulf
              production zone.
            - ``"hours_to_landfall"``: float, time until expected landfall.
            - ``"current_time"``: datetime (optional).
        landfall_probability : float, optional
            Override for ``track_forecast["landfall_prob"]``.

        Returns
        -------
        Signal
            LONG nat gas if landfall risk is high, FLAT otherwise.
        """
        current_time = track_forecast.get("current_time", datetime.now(timezone.utc))
        prob = (
            landfall_probability
            if landfall_probability is not None
            else track_forecast.get("landfall_prob", 0.0)
        )
        prob = float(np.clip(prob, 0.0, 1.0))

        category = int(track_forecast.get("category", 1))
        category = max(1, min(category, 5))

        distance = float(track_forecast.get("closest_approach_miles", 500.0))
        hours_to_landfall = float(track_forecast.get("hours_to_landfall", 120.0))

        disruption_factor = CATEGORY_DISRUPTION.get(category, 0.35)

        proximity_factor = float(
            np.clip(1.0 - distance / (self.gulf_proximity_miles * 3), 0.0, 1.0)
        )

        urgency_factor = float(np.clip(1.0 - hours_to_landfall / 168.0, 0.0, 1.0))

        effective_prob = (
            prob * disruption_factor * (0.5 + 0.5 * proximity_factor) * (0.7 + 0.3 * urgency_factor)
        )

        if effective_prob > self.entry_threshold:
            conf = float(np.clip(effective_prob, 0.0, 1.0))
            size = position_size(
                conf, method="kelly", odds=2.5, half_kelly=True, max_size=self.max_size
            )

            reasoning = (
                f"Hurricane Cat-{category}: landfall prob {prob:.1%}, "
                f"{distance:.0f} miles from Gulf production, "
                f"{hours_to_landfall:.0f}h to landfall. "
                f"Expected disruption: {disruption_factor:.0%}. "
                f"LONG nat gas on Gulf shut-in risk."
            )

            logger.info("Hurricane signal: LONG nat gas, size=%.3f, conf=%.3f", size, conf)

            return Signal(
                action=Action.LONG,
                size=size,
                confidence=conf,
                instrument="NG_FUTURES",
                timestamp=current_time,
                reasoning=reasoning,
                metadata={
                    "landfall_prob": prob,
                    "category": category,
                    "distance_miles": distance,
                    "hours_to_landfall": hours_to_landfall,
                    "disruption_factor": disruption_factor,
                    "effective_prob": effective_prob,
                },
            )

        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="NG_FUTURES",
            timestamp=current_time,
            reasoning=(
                f"Hurricane Cat-{category}: effective risk {effective_prob:.1%} "
                f"below entry threshold {self.entry_threshold:.1%}."
            ),
        )
