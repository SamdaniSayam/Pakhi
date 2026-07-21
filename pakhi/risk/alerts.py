"""Alert manager for extreme weather risk events.

Monitors forecasts and triggers alerts for freeze, heatwave,
hurricane, and drought conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import numpy as np

__all__ = ["Alert", "AlertManager", "AlertSeverity", "send_alert"]

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """A weather risk alert.

    Attributes
    ----------
    severity : AlertSeverity
        Severity level.
    message : str
        Human-readable alert description.
    timestamp : datetime
        Time the alert was generated.
    trigger_value : float
        The value that triggered the alert.
    alert_type : str
        Type of alert (``"freeze"``, ``"heatwave"``, etc.).
    metadata : dict
        Additional context.
    """

    severity: AlertSeverity
    message: str
    timestamp: datetime
    trigger_value: float
    alert_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AlertManager:
    """Monitor forecasts and generate risk alerts.

    Examples
    --------
    >>> mgr = AlertManager()
    >>> alert = mgr.check_freeze({"temperature_min": -5.0})
    """

    __all__ = [
        "check_freeze",
        "check_heatwave",
        "check_hurricane",
        "check_drought",
    ]

    def check_freeze(
        self,
        temperature_forecast: dict,
        threshold: float = 0.0,
    ) -> Alert | None:
        """Check for freeze conditions.

        Parameters
        ----------
        temperature_forecast : dict
            Must contain ``"temperature_min"`` (°C) and optionally
            ``"current_time"`` and ``"location"``.
        threshold : float
            Temperature threshold in °C. Default 0.0.

        Returns
        -------
        Alert or None
        """
        ts = temperature_forecast.get("current_time", datetime.now(timezone.utc))
        temp_min = float(temperature_forecast.get("temperature_min", 10.0))
        location = temperature_forecast.get("location", "Unknown")

        if temp_min >= threshold:
            return None

        severity_delta = abs(temp_min - threshold)
        if severity_delta > 10:
            severity = AlertSeverity.CRITICAL
        elif severity_delta > 5:
            severity = AlertSeverity.HIGH
        elif severity_delta > 2:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        alert = Alert(
            severity=severity,
            message=f"FREEZE ALERT ({severity.value}): {location} min temp {temp_min:.1f}°C (threshold {threshold:.1f}°C).",
            timestamp=ts,
            trigger_value=temp_min,
            alert_type="freeze",
            metadata={"location": location, "threshold": threshold},
        )

        logger.warning("FREEZE ALERT: %s", alert.message)
        return alert

    def check_heatwave(
        self,
        temperature_forecast: dict,
        threshold: float = 38.0,
        days: int = 3,
    ) -> Alert | None:
        """Check for heatwave conditions.

        Parameters
        ----------
        temperature_forecast : dict
            Must contain ``"temperature_forecast"`` (array of daily max
            temps in °C) and optionally ``"current_time"`` and
            ``"location"``.
        threshold : float
            Temperature threshold in °C. Default 38.0.
        days : int
            Minimum consecutive days. Default 3.

        Returns
        -------
        Alert or None
        """
        ts = temperature_forecast.get("current_time", datetime.now(timezone.utc))
        location = temperature_forecast.get("location", "Unknown")
        temps = np.asarray(temperature_forecast.get("temperature_forecast", []), dtype=np.float64)

        if len(temps) == 0:
            return None

        hot_days = temps > threshold
        consecutive = 0
        max_consecutive = 0
        for val in hot_days:
            if val:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive < days:
            return None

        max_temp = float(np.max(temps))
        severity_factor = max_consecutive / 7.0
        if severity_factor > 0.8:
            severity = AlertSeverity.CRITICAL
        elif severity_factor > 0.5:
            severity = AlertSeverity.HIGH
        elif severity_factor > 0.3:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        alert = Alert(
            severity=severity,
            message=(
                f"HEATWAVE ALERT ({severity.value}): {location} — "
                f"{max_consecutive} consecutive days >{threshold}°C. "
                f"Peak: {max_temp:.1f}°C."
            ),
            timestamp=ts,
            trigger_value=float(max_consecutive),
            alert_type="heatwave",
            metadata={
                "location": location,
                "threshold": threshold,
                "consecutive_days": max_consecutive,
                "max_temp": max_temp,
            },
        )

        logger.warning("HEATWAVE ALERT: %s", alert.message)
        return alert

    def check_hurricane(
        self,
        track_forecast: dict,
    ) -> Alert | None:
        """Check for hurricane threat.

        Parameters
        ----------
        track_forecast : dict
            Must contain ``"landfall_prob"`` (0–1), ``"category"`` (1–5),
            ``"closest_approach_miles"``, and optionally ``"current_time"``
            and ``"location"``.

        Returns
        -------
        Alert or None
        """
        ts = track_forecast.get("current_time", datetime.now(timezone.utc))
        location = track_forecast.get("location", "Gulf Coast")
        prob = float(track_forecast.get("landfall_prob", 0.0))
        category = int(track_forecast.get("category", 1))
        distance = float(track_forecast.get("closest_approach_miles", 500))

        if prob < 0.1:
            return None

        if category >= 4 and prob > 0.5:
            severity = AlertSeverity.CRITICAL
        elif category >= 3 and prob > 0.4:
            severity = AlertSeverity.HIGH
        elif category >= 2 and prob > 0.3:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        alert = Alert(
            severity=severity,
            message=(
                f"HURRICANE ALERT ({severity.value}): Category {category} "
                f"threatening {location}. Landfall prob: {prob:.1%}, "
                f"closest approach: {distance:.0f} miles."
            ),
            timestamp=ts,
            trigger_value=prob,
            alert_type="hurricane",
            metadata={
                "location": location,
                "category": category,
                "distance_miles": distance,
            },
        )

        logger.warning("HURRICANE ALERT: %s", alert.message)
        return alert

    def check_drought(
        self,
        spi_index: dict,
        threshold: float = -1.5,
        days: int = 30,
    ) -> Alert | None:
        """Check for drought conditions.

        Parameters
        ----------
        spi_index : dict
            Must contain ``"spi_values"`` (array of daily SPI values),
            ``"region"``, and optionally ``"current_time"``.
        threshold : float
            SPI threshold below which drought is flagged. Default -1.5.
        days : int
            Minimum consecutive days. Default 30.

        Returns
        -------
        Alert or None
        """
        ts = spi_index.get("current_time", datetime.now(timezone.utc))
        region = spi_index.get("region", "Unknown")
        spi_values = np.asarray(spi_index.get("spi_values", []), dtype=np.float64)

        if len(spi_values) == 0:
            return None

        below = spi_values < threshold
        consecutive = 0
        max_consecutive = 0
        for val in below:
            if val:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive < days:
            return None

        mean_spi = float(np.mean(spi_values))
        if mean_spi < -3.0:
            severity = AlertSeverity.CRITICAL
        elif mean_spi < -2.0:
            severity = AlertSeverity.HIGH
        elif mean_spi < -1.5:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        alert = Alert(
            severity=severity,
            message=(
                f"DROUGHT ALERT ({severity.value}): {region} — "
                f"SPI below {threshold} for {max_consecutive} consecutive days. "
                f"Mean SPI: {mean_spi:.2f}."
            ),
            timestamp=ts,
            trigger_value=mean_spi,
            alert_type="drought",
            metadata={
                "region": region,
                "threshold": threshold,
                "consecutive_days": max_consecutive,
                "mean_spi": mean_spi,
            },
        )

        logger.warning("DROUGHT ALERT: %s", alert.message)
        return alert


def send_alert(alert: Alert, channels: list[str] | None = None) -> None:
    """Dispatch an alert to configured channels.

    Parameters
    ----------
    alert : Alert
        The alert to send.
    channels : list of str, optional
        Delivery channels. Default ``["log"]``.

    Supported channels
    ------------------
    - ``"log"``: Python logging (always active).
    - ``"email"``: Placeholder for email integration.
    - ``"slack"``: Placeholder for Slack webhook.
    - ``"telegram"``: Placeholder for Telegram bot.
    """
    if channels is None:
        channels = ["log"]

    for channel in channels:
        if channel == "log":
            logger.info(
                "[%s] %s @ %s (trigger=%.3f)",
                alert.severity.value,
                alert.message,
                alert.timestamp.isoformat(),
                alert.trigger_value,
            )
        elif channel == "email":
            logger.info("[EMAIL PLACEHOLDER] Would send: %s", alert.message)
        elif channel == "slack":
            logger.info("[SLACK PLACEHOLDER] Would send: %s", alert.message)
        elif channel == "telegram":
            logger.info("[TELEGRAM PLACEHOLDER] Would send: %s", alert.message)
        else:
            logger.warning("Unknown alert channel: %s", channel)
