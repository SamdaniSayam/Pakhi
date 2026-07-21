"""Wind power generation signal for electricity markets.

Compares wind forecasts to normal conditions and generates signals
based on expected power price deviations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["WindPowerSignal"]

logger = logging.getLogger(__name__)


class WindPowerSignal(BaseSignal):
    """Generate trading signals from wind generation forecasts.

    High wind → low prices (short power). Low wind → high prices (long power).

    Parameters
    ----------
    low_wind_threshold : float
        Percentile below which wind is considered low. Default 25.
    high_wind_threshold : float
        Percentile above which wind is considered high. Default 75.
    normal_wind_percentile : float
        Reference percentile for "normal" wind. Default 50.
    default_market : str
        Default power market. Default ``"PJM"``.
    max_size : float
        Maximum position size. Default 0.15.

    Examples
    --------
    >>> sig = WindPowerSignal()
    >>> signal = sig.generate(wind_forecast, market="PJM")
    """

    __all__ = ["generate"]

    def __init__(
        self,
        low_wind_threshold: float = 25.0,
        high_wind_threshold: float = 75.0,
        normal_wind_percentile: float = 50.0,
        default_market: str = "PJM",
        max_size: float = 0.15,
    ) -> None:
        self.low_wind_threshold = low_wind_threshold
        self.high_wind_threshold = high_wind_threshold
        self.normal_wind_percentile = normal_wind_percentile
        self.default_market = default_market
        self.max_size = max_size

    def generate(self, forecast: dict) -> Signal:
        """Generate a wind power signal from wind speed/capacity forecasts.

        Parameters
        ----------
        forecast : dict
            Must contain:

            - ``"wind_forecast"``: array-like of forecast wind capacity
              factors (0–1) or wind speeds (m/s).
            - ``"wind_climatology"``: array-like of historical wind values
              for normal reference (optional).
            - ``"market"``: str, power market (optional).
            - ``"current_time"``: datetime (optional).

        Returns
        -------
        Signal
            LONG power if low wind, SHORT power if high wind, FLAT
            if near normal.
        """
        current_time = forecast.get("current_time", datetime.now(timezone.utc))
        market = forecast.get("market", self.default_market)
        wind_fc = np.asarray(forecast.get("wind_forecast", []), dtype=np.float64)
        wind_clim = forecast.get("wind_climatology")

        if len(wind_fc) == 0:
            return self._flat_signal(current_time, market, "Empty wind forecast.")

        mean_wind = float(np.mean(wind_fc))

        if wind_clim is not None:
            wind_clim_arr = np.asarray(wind_clim, dtype=np.float64)
            if len(wind_clim_arr) > 0:
                normal_wind = float(np.percentile(wind_clim_arr, self.normal_wind_percentile))
                low_bound = float(np.percentile(wind_clim_arr, self.low_wind_threshold))
                high_bound = float(np.percentile(wind_clim_arr, self.high_wind_threshold))
            else:
                normal_wind = mean_wind
                low_bound = mean_wind * 0.7
                high_bound = mean_wind * 1.3
        else:
            normal_wind = mean_wind
            low_bound = (
                np.percentile(wind_fc, self.low_wind_threshold)
                if len(wind_fc) > 1
                else mean_wind * 0.7
            )
            high_bound = (
                np.percentile(wind_fc, self.high_wind_threshold)
                if len(wind_fc) > 1
                else mean_wind * 1.3
            )

        if normal_wind < 1e-10:
            deviation = 0.0
        else:
            deviation = (mean_wind - normal_wind) / max(abs(normal_wind), 1e-10)

        instrument = f"{market}_POWER_FUTURES"

        if mean_wind < low_bound:
            severity = float(np.clip(abs(deviation), 0.0, 1.0))
            conf = float(np.clip(severity * 1.5, 0.0, 1.0))
            size = position_size(
                conf, method="kelly", odds=1.5, half_kelly=True, max_size=self.max_size
            )

            reasoning = (
                f"Wind capacity factor {mean_wind:.2f} below low threshold "
                f"{low_bound:.2f} (normal={normal_wind:.2f}). "
                f"Low wind → reduced generation → higher power prices. LONG {market}."
            )

            logger.info("Wind power signal: LONG %s, size=%.3f", market, size)

            return Signal(
                action=Action.LONG,
                size=size,
                confidence=conf,
                instrument=instrument,
                timestamp=current_time,
                reasoning=reasoning,
                metadata={
                    "market": market,
                    "wind_forecast": mean_wind,
                    "normal_wind": normal_wind,
                    "direction": "long",
                },
            )

        elif mean_wind > high_bound:
            severity = float(np.clip(abs(deviation), 0.0, 1.0))
            conf = float(np.clip(severity * 1.5, 0.0, 1.0))
            size = position_size(
                conf, method="kelly", odds=1.5, half_kelly=True, max_size=self.max_size
            )

            reasoning = (
                f"Wind capacity factor {mean_wind:.2f} above high threshold "
                f"{high_bound:.2f} (normal={normal_wind:.2f}). "
                f"High wind → excess generation → lower power prices. SHORT {market}."
            )

            logger.info("Wind power signal: SHORT %s, size=%.3f", market, size)

            return Signal(
                action=Action.SHORT,
                size=size,
                confidence=conf,
                instrument=instrument,
                timestamp=current_time,
                reasoning=reasoning,
                metadata={
                    "market": market,
                    "wind_forecast": mean_wind,
                    "normal_wind": normal_wind,
                    "direction": "short",
                },
            )

        return self._flat_signal(
            current_time,
            market,
            f"Wind capacity factor {mean_wind:.2f} near normal ({normal_wind:.2f}). No signal.",
        )

    def _flat_signal(self, ts: datetime, market: str, reason: str) -> Signal:
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=f"{market}_POWER_FUTURES",
            timestamp=ts,
            reasoning=reason,
        )
