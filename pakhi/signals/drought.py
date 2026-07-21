"""Drought event signal for grain and water futures.

Detects sustained low SPI (Standardized Precipitation Index) and
generates LONG signals on agricultural commodities.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from pakhi.signals.base import Action, BaseSignal, Signal, position_size

__all__ = ["DroughtSignal"]

logger = logging.getLogger(__name__)


class DroughtSignal(BaseSignal):
    """Generate trading signals from drought index forecasts.

    Parameters
    ----------
    spi_threshold : float
        SPI value below which drought conditions are flagged.
        Default -1.5.
    min_days : int
        Minimum number of consecutive days below threshold. Default 30.
    grains : list of str
        Grain futures to trade. Default corn, wheat, soybeans.
    water_futures : bool
        Whether to also signal water futures. Default ``True``.
    max_size : float
        Maximum position size per instrument. Default 0.15.

    Examples
    --------
    >>> sig = DroughtSignal(spi_threshold=-1.5)
    >>> signal = sig.generate(drought_index_forecast)
    """

    __all__ = ["generate"]

    def __init__(
        self,
        spi_threshold: float = -1.5,
        min_days: int = 30,
        grains: list[str] | None = None,
        water_futures: bool = True,
        max_size: float = 0.15,
    ) -> None:
        self.spi_threshold = spi_threshold
        self.min_days = min_days
        self.grains = grains or ["CORN_FUTURES", "WHEAT_FUTURES", "SOY_FUTURES"]
        self.water_futures = water_futures
        self.max_size = max_size

    def generate(self, drought_index_forecast: dict) -> Signal:
        """Generate a drought signal from SPI forecast data.

        Parameters
        ----------
        drought_index_forecast : dict
            Must contain:

            - ``"spi_values"``: array-like of daily SPI values.
            - ``"region"``: str, drought region name.
            - ``"current_time"``: datetime (optional).

        Returns
        -------
        Signal
            LONG grains if drought persists, FLAT otherwise.
        """
        current_time = drought_index_forecast.get("current_time", datetime.now(timezone.utc))
        spi_values = np.asarray(drought_index_forecast.get("spi_values", []), dtype=np.float64)
        region = drought_index_forecast.get("region", "Unknown")

        if len(spi_values) == 0:
            return self._flat_signal(current_time, "Empty SPI forecast.")

        below_threshold = spi_values < self.spi_threshold
        consecutive_drought = self._max_consecutive(below_threshold)

        if consecutive_drought < self.min_days:
            return self._flat_signal(
                current_time,
                f"SPI below {self.spi_threshold} for only {consecutive_drought} days "
                f"(need {self.min_days}).",
            )

        severity = float(np.clip(abs(np.mean(spi_values[below_threshold])) / 3.0, 0.0, 1.0))
        duration_factor = float(np.clip(consecutive_drought / 90.0, 0.0, 1.0))
        effective_prob = severity * (0.5 + 0.5 * duration_factor)
        conf = float(np.clip(effective_prob, 0.0, 1.0))

        size = position_size(
            conf, method="kelly", odds=2.0, half_kelly=True, max_size=self.max_size
        )

        instrument_list = list(self.grains)
        if self.water_futures:
            instrument_list.append("WATER_FUTURES")

        reasoning = (
            f"SPI below {self.spi_threshold} for {consecutive_drought} consecutive days in {region}. "
            f"Mean SPI={np.mean(spi_values):.2f}, min={np.min(spi_values):.2f}. "
            f"Expect yield losses → LONG grains."
        )

        logger.info("Drought signal: LONG %s, size=%.3f, conf=%.3f", instrument_list, size, conf)

        return Signal(
            action=Action.LONG,
            size=size,
            confidence=conf,
            instrument=",".join(instrument_list),
            timestamp=current_time,
            reasoning=reasoning,
            metadata={
                "region": region,
                "spi_mean": float(np.mean(spi_values)),
                "spi_min": float(np.min(spi_values)),
                "consecutive_drought_days": consecutive_drought,
                "severity": severity,
            },
        )

    @staticmethod
    def _max_consecutive(mask: np.ndarray) -> int:
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
        instrument_list = list(self.grains)
        if self.water_futures:
            instrument_list.append("WATER_FUTURES")
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=",".join(instrument_list),
            timestamp=ts,
            reasoning=reason,
        )
