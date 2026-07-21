"""Power market signal for heatwave-driven demand spikes.

Generates LONG signals on power futures when extreme heat is forecast,
using CDD-driven demand modelling with wind supply adjustment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["PowerSignal"]

logger = logging.getLogger(__name__)


class PowerSignal(BaseSignal):
    """Generate trading signals from temperature forecasts for power markets.

    Parameters
    ----------
    heatwave_threshold : float
        Temperature in °C above which a day counts as a heatwave day.
        Default 38.0.
    min_consecutive_days : int
        Minimum consecutive hot days to trigger a signal. Default 3.
    cdd_base : float
        Base temperature for CDD calculation (°C). Default 18.3.
    wind_capacity_factor_threshold : float
        Below this capacity factor, wind supply is considered low,
        amplifying the heatwave signal. Default 0.15.
    default_market : str
        Default power market. Default ``"ERCOT"``.
    max_size : float
        Maximum position size. Default 0.20.

    Examples
    --------
    >>> sig = PowerSignal(heatwave_threshold=40.0)
    >>> signal = sig.generate({"temperature_forecast": temps, "market": "ERCOT"})
    """

    __all__ = ["generate"]

    # Approximate wind share of total capacity by market
    WIND_SHARE: dict[str, float] = {
        "ERCOT": 0.30,
        "PJM": 0.08,
        "CAISO": 0.12,
        "MISO": 0.10,
        "NYISO": 0.05,
        "ISO_NE": 0.06,
    }

    def __init__(
        self,
        heatwave_threshold: float = 38.0,
        min_consecutive_days: int = 3,
        cdd_base: float = 18.3,
        wind_capacity_factor_threshold: float = 0.15,
        default_market: str = "ERCOT",
        max_size: float = 0.20,
    ) -> None:
        self.heatwave_threshold = heatwave_threshold
        self.min_consecutive_days = min_consecutive_days
        self.cdd_base = cdd_base
        self.wind_capacity_factor_threshold = wind_capacity_factor_threshold
        self.default_market = default_market
        self.max_size = max_size

    def generate(self, forecast: dict) -> Signal:
        """Generate a power signal from temperature and wind forecasts.

        Parameters
        ----------
        forecast : dict
            Must contain:

            - ``"temperature_forecast"``: array-like of daily max temps (°C).
            - ``"market"``: str, power market code.
            - ``"wind_capacity_factor"``: array-like of wind capacity factors
              (optional).
            - ``"current_time"``: datetime (optional).

        Returns
        -------
        Signal
            LONG for heatwave-driven demand spike, FLAT otherwise.
        """
        temps = np.asarray(forecast.get("temperature_forecast", []), dtype=np.float64)
        market = forecast.get("market", self.default_market)
        wind_cf = forecast.get("wind_capacity_factor")
        current_time = forecast.get("current_time", datetime.now(timezone.utc))

        if len(temps) == 0:
            return self._flat_signal(current_time, "Empty temperature forecast.")

        hot_days = temps > self.heatwave_threshold
        consecutive = self._max_consecutive(hot_days)

        if consecutive < self.min_consecutive_days:
            return self._flat_signal(
                current_time,
                f"Only {consecutive} consecutive hot days (need {self.min_consecutive_days}).",
            )

        cdd = float(np.sum(np.maximum(temps - self.cdd_base, 0.0)))

        wind_amplifier = 1.0
        if wind_cf is not None:
            wind_arr = np.asarray(wind_cf, dtype=np.float64)
            mean_wind = float(np.mean(wind_arr))
            if mean_wind < self.wind_capacity_factor_threshold:
                wind_share = self.WIND_SHARE.get(market, 0.10)
                wind_amplifier = 1.0 + wind_share * 2.0

        severity = float(np.clip(cdd / 500.0, 0.0, 1.0))
        effective_prob = min(severity * wind_amplifier, 0.95)
        conf = float(np.clip(effective_prob, 0.0, 1.0))
        size = position_size(
            conf, method="kelly", odds=2.0, half_kelly=True, max_size=self.max_size
        )

        reasoning = (
            f"{consecutive} consecutive days >{self.heatwave_threshold}°C in {market}. "
            f"CDD={cdd:.0f}. Wind amplification={wind_amplifier:.2f}x. "
            f"Expect elevated power demand and prices."
        )

        logger.info("Power signal: LONG %s, size=%.3f, conf=%.3f", market, size, conf)

        return Signal(
            action=Action.LONG,
            size=size,
            confidence=conf,
            instrument=f"{market}_POWER_FUTURES",
            timestamp=current_time,
            reasoning=reasoning,
            metadata={
                "market": market,
                "cdd": cdd,
                "consecutive_hot_days": consecutive,
                "wind_amplifier": wind_amplifier,
            },
        )

    @staticmethod
    def _max_consecutive(mask: np.ndarray) -> int:
        """Maximum run of True values in a boolean array."""
        best = 0
        current = 0
        for val in mask:
            if val:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    def _flat_signal(self, ts: datetime, reason: str) -> Signal:
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=f"{self.default_market}_POWER_FUTURES",
            timestamp=ts,
            reasoning=reason,
        )
