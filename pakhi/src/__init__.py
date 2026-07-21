"""Data source connectors for the Pakhi weather quant platform.

Re-exports all connector classes for convenient imports:

    from pakhi.src import GFSConnector, ERA5Connector, GOESConnector
"""

from __future__ import annotations

from pakhi.src.cmes import CMEWeatherConnector
from pakhi.src.era5 import ERA5Connector
from pakhi.src.meteostat import MeteostatConnector
from pakhi.src.noaa import GFSConnector
from pakhi.src.openmeteo import OpenMeteoConnector
from pakhi.src.satellite import GOESConnector
from pakhi.src.yahoo import YahooFuturesConnector

__all__ = [
    "CMEWeatherConnector",
    "ERA5Connector",
    "GFSConnector",
    "GOESConnector",
    "MeteostatConnector",
    "OpenMeteoConnector",
    "YahooFuturesConnector",
]
