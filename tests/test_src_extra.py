"""Tests for pakhi.src — yahoo, openmeteo, noaa, era5, satellite, meteostat, cmes."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pandas as pd


class TestYahooFutures:
    def test_init(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector()
        assert conn is not None
        assert len(conn.tickers) > 0

    def test_init_custom_tickers(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector(tickers=["CL=F", "NG=F"])
        assert len(conn.tickers) == 2

    def test_current_price(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 80.5
        mock_ticker.history.return_value = pd.DataFrame(
            {
                "Close": [80.0, 80.5],
                "High": [81.0, 81.5],
                "Low": [79.0, 79.5],
                "Open": [80.0, 80.5],
                "Volume": [1000, 1100],
            }
        )
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        result = conn.current_price()
        assert isinstance(result, pd.DataFrame)

    def test_get_yf_missing(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector()
        conn._yf = None
        with contextlib.suppress(ImportError):
            conn._get_yf()


class TestOpenMeteo:
    @patch("pakhi.src.openmeteo.requests.get")
    def test_forecast(self, mock_get):
        mock_resp = mock_get.return_value
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hourly": {
                "time": [f"2024-01-0{i}T00:00" for i in range(5)],
                "temperature_2m": [10.0, 11.0, 12.0, 13.0, 14.0],
                "precipitation": [0.0, 1.0, 0.0, 2.0, 0.0],
                "wind_speed_10m": [5.0, 6.0, 7.0, 8.0, 9.0],
            }
        }
        mock_resp.raise_for_status = lambda: None
        from pakhi.src.openmeteo import OpenMeteoConnector

        conn = OpenMeteoConnector()
        result = conn.forecast(32.0, -88.0, days=5)
        assert result is not None


class TestNOAA:
    def test_gfs_connector_init(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        assert conn is not None


class TestERA5:
    def test_era5_connector_init(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector()
        assert conn is not None


class TestSatelliteSrc:
    def test_goes_connector_init(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        assert conn is not None


class TestMeteostat:
    def test_meteostat_connector_init(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        assert conn is not None


class TestCMES:
    def test_cmes_connector_init(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        assert conn is not None
