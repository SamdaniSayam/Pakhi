"""
Pakhi — Weather Intelligence & Quantitative Trading Platform

Birds are living barometers and acoustic sensors. They detect approaching
storms, pressure changes, and atmospheric disturbances long before human
instruments register them. Pakhi does the same — but for markets.

    from pakhi.src.noaa import GFSConnector
    from pakhi.models.ensemble import EnsembleForecaster
    from pakhi.signals.freeze import FreezeSignal

    gfs = GFSConnector(variable=["temperature_2m", "wind_10m"])
    forecast = gfs.latest()
    ...
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = [
    "__version__",
]
