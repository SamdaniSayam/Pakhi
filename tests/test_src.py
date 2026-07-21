"""Tests for data source connectors in pakhi.src."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from pakhi.src.cmes import CMEWeatherConnector
from pakhi.src.era5 import ERA5Connector
from pakhi.src.meteostat import MeteostatConnector
from pakhi.src.noaa import GFS_VARIABLE_MAP, GFSConnector
from pakhi.src.openmeteo import OpenMeteoConnector
from pakhi.src.satellite import GOESConnector
from pakhi.src.yahoo import YahooFuturesConnector

# ---------------------------------------------------------------------------
# ERA5Connector
# ---------------------------------------------------------------------------


class TestERA5Connector:
    def test_instantiation_defaults(self):
        conn = ERA5Connector()
        assert "temperature_2m" in conn.single_level_vars
        assert conn.product_type == "reanalysis"
        assert conn.chunks == {"time": 365}

    def test_instantiation_pressure_level(self):
        conn = ERA5Connector(variables=["temperature"], pressure_levels=[500, 850])
        assert "temperature" in conn.pressure_level_vars
        assert 500 in conn.pressure_levels

    def test_invalid_variable_raises(self):
        with pytest.raises(ValueError, match="Unknown ERA5 variable"):
            ERA5Connector(variables=["nonexistent_var"])

    def test_invalid_pressure_level_raises(self):
        with pytest.raises(ValueError, match="not in standard ERA5 levels"):
            ERA5Connector(variables=["temperature"], pressure_levels=[123])

    def test_build_single_level_request(self):
        conn = ERA5Connector(variables=["temperature_2m"])
        req = conn._build_single_level_request(["temperature_2m"], ["2023-01-01", "2023-01-02"])
        assert "2m_temperature" in req["variable"]
        assert "2023" in req["year"]
        assert req["format"] == "netcdf"

    def test_build_pressure_level_request(self):
        conn = ERA5Connector(variables=["temperature"], pressure_levels=[500])
        req = conn._build_pressure_level_request(["temperature"], ["2023-06-01"])
        assert "temperature" in req["variable"]
        assert "500" in req["pressure_level"]

    def test_generate_dates(self):
        conn = ERA5Connector()
        dates = conn._generate_dates("2023-01-01", "2023-01-03")
        assert len(dates) == 3
        assert dates[0] == "2023-01-01"
        assert dates[-1] == "2023-01-03"

    def test_context_manager(self):
        with ERA5Connector() as conn:
            assert conn is not None


# ---------------------------------------------------------------------------
# GFSConnector
# ---------------------------------------------------------------------------


class TestGFSConnector:
    def test_instantiation_defaults(self):
        conn = GFSConnector()
        assert "temperature_2m" in conn.variables
        assert conn.resolution == "0p25"
        assert len(conn.bbox) == 4

    def test_custom_bbox(self):
        conn = GFSConnector(bbox=[-100, 25, -80, 45])
        assert conn.bbox == [-100, 25, -80, 45]

    def test_invalid_variable_raises(self):
        with pytest.raises(ValueError, match="Unknown variable"):
            GFSConnector(variables=["fake_var"])

    def test_invalid_bbox_length_raises(self):
        with pytest.raises(ValueError, match="bbox must be"):
            GFSConnector(bbox=[1, 2, 3])

    def test_latest_cycle(self):
        conn = GFSConnector()
        ref = datetime(2023, 6, 15, 10, 0, tzinfo=timezone.utc)
        date_str, cycle = conn._latest_cycle(ref)
        assert len(date_str) == 8
        assert cycle in ["00", "06", "12", "18"]

    def test_build_url(self):
        conn = GFSConnector(variables=["temperature_2m"])
        var_cfg = GFS_VARIABLE_MAP["temperature_2m"]
        url = conn._build_url("20230615", "00", 0, var_cfg)
        assert "gfs.t00z" in url
        assert "var=TMP" in url

    def test_context_manager(self):
        with GFSConnector() as conn:
            assert conn is not None


# ---------------------------------------------------------------------------
# GOESConnector
# ---------------------------------------------------------------------------


class TestGOESConnector:
    def test_instantiation_defaults(self):
        conn = GOESConnector()
        assert conn.satellite == "GOES-16"
        assert conn.sector == "CONUS"
        assert "band_13" in conn.bands

    def test_custom_satellite(self):
        conn = GOESConnector(satellite="GOES-18", bands=["band_08"])
        assert conn.satellite == "GOES-18"
        assert conn.s3_bucket == "noaa-goes18"

    def test_invalid_satellite_raises(self):
        with pytest.raises(ValueError, match="satellite must be one of"):
            GOESConnector(satellite="GOES-99")

    def test_invalid_sector_raises(self):
        with pytest.raises(ValueError, match="sector must be one of"):
            GOESConnector(sector="InvalidSector")

    def test_invalid_band_raises(self):
        with pytest.raises(ValueError, match="Unknown band"):
            GOESConnector(bands=["band_99"])

    def test_cloud_motion_minimum_minutes(self):
        conn = GOESConnector()
        with pytest.raises(ValueError, match="Minimum temporal baseline"):
            conn.cloud_motion(minutes=5)

    def test_context_manager(self):
        with GOESConnector() as conn:
            assert conn is not None


# ---------------------------------------------------------------------------
# YahooFuturesConnector
# ---------------------------------------------------------------------------


class TestYahooFuturesConnector:
    def test_instantiation_defaults(self):
        yf = YahooFuturesConnector()
        assert "CL=F" in yf.tickers
        assert "NG=F" in yf.tickers

    def test_custom_tickers_list(self):
        yf = YahooFuturesConnector(tickers=["CL=F", "NG=F"])
        assert set(yf.tickers.keys()) == {"CL=F", "NG=F"}

    def test_custom_tickers_dict(self):
        yf = YahooFuturesConnector(tickers={"CL=F": "Oil"})
        assert yf.tickers["CL=F"] == "Oil"

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError, match="Invalid period"):
            yf = YahooFuturesConnector(tickers=["CL=F"])
            yf.history(period="bad")

    def test_invalid_interval_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            yf = YahooFuturesConnector(tickers=["CL=F"])
            yf.history(interval="bad")

    def test_repr(self):
        yf = YahooFuturesConnector(tickers=["CL=F"])
        assert "CL=F" in repr(yf)


# ---------------------------------------------------------------------------
# CMEWeatherConnector
# ---------------------------------------------------------------------------


class TestCMEWeatherConnector:
    def test_instantiation_defaults(self):
        cmes = CMEWeatherConnector()
        assert "HDD_CME" in cmes.products
        assert "CDD_CME" in cmes.products
        assert cmes.regions == ["US_NATIONAL"]

    def test_custom_products(self):
        cmes = CMEWeatherConnector(products=["HDD_CME"])
        assert cmes.products == ["HDD_CME"]

    def test_invalid_product_raises(self):
        with pytest.raises(ValueError, match="Unknown product"):
            CMEWeatherConnector(products=["INVALID"])

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError, match="Unknown region"):
            CMEWeatherConnector(regions=["INVALID"])

    def test_compute_hdd_celsius_input(self):
        cmes = CMEWeatherConnector()
        temps = pd.Series([0.0, 10.0, 20.0, 30.0])
        hdd = cmes.compute_hdd(temps, base_temp_f=65.0)
        assert hdd.name == "HDD"
        assert hdd.iloc[0] > 0

    def test_compute_cdd(self):
        cmes = CMEWeatherConnector()
        temps = pd.Series([0.0, 20.0, 30.0, 40.0])
        cdd = cmes.compute_cdd(temps, base_temp_f=65.0)
        assert cdd.name == "CDD"
        assert cdd.iloc[0] == 0.0

    def test_context_manager(self):
        with CMEWeatherConnector() as cmes:
            assert cmes is not None


# ---------------------------------------------------------------------------
# OpenMeteoConnector
# ---------------------------------------------------------------------------


class TestOpenMeteoConnector:
    def test_instantiation_defaults(self):
        api = OpenMeteoConnector()
        assert api.temperature_unit == "celsius"
        assert api.max_retries == 3

    def test_custom_units(self):
        api = OpenMeteoConnector(
            temperature_unit="fahrenheit",
            wind_speed_unit="mph",
        )
        assert api.temperature_unit == "fahrenheit"
        assert api.wind_speed_unit == "mph"

    def test_context_manager(self):
        with OpenMeteoConnector() as api:
            assert api is not None


# ---------------------------------------------------------------------------
# MeteostatConnector
# ---------------------------------------------------------------------------


class TestMeteostatConnector:
    def test_instantiation_defaults(self):
        ms = MeteostatConnector()
        assert ms.timeout == 30

    def test_repr(self):
        ms = MeteostatConnector()
        assert "MeteostatConnector" in repr(ms)

    def test_context_manager(self):
        with MeteostatConnector() as ms:
            assert ms is not None


# ---------------------------------------------------------------------------
# Mock HTTP error handling
# ---------------------------------------------------------------------------


class TestHTTPErrorHandling:
    @patch("pakhi.src.cmes.requests.Session.get")
    def test_cmes_fetch_retries_on_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Network error")
        cmes = CMEWeatherConnector(max_retries=2)
        with pytest.raises(ConnectionError, match="Failed to fetch CME data"):
            cmes._fetch_json("http://fake.url")

    @patch("pakhi.src.openmeteo.requests.Session.get")
    def test_openmeteo_retries_on_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Timeout")
        api = OpenMeteoConnector(max_retries=2)
        with pytest.raises(ConnectionError, match="Open-Meteo API request failed"):
            api._get("http://fake.url", {})

    @patch("pakhi.src.meteostat.requests.Session.get")
    def test_meteostat_retries_on_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Timeout")
        ms = MeteostatConnector(max_retries=2)
        with pytest.raises(ConnectionError, match="Meteostat API request failed"):
            ms._get("stations/nearby")


# ---------------------------------------------------------------------------
# CME settlement parsing
# ---------------------------------------------------------------------------


class TestCMESettlementParsing:
    def test_parse_settlements_empty(self):
        cmes = CMEWeatherConnector()
        df = cmes._parse_cme_settlements([], "HDD_CME")
        assert df.empty

    def test_parse_settlements_dict(self):
        cmes = CMEWeatherConnector()
        raw = {
            "settlements": [
                {
                    "settlementDate": "2023-06-01",
                    "month": "2023-07",
                    "settlementPrice": 150.0,
                    "volume": 100,
                },
                {
                    "settlementDate": "2023-06-01",
                    "month": "2023-08",
                    "settlementPrice": 160.0,
                    "volume": 200,
                },
            ]
        }
        df = cmes._parse_cme_settlements(raw, "HDD_CME")
        assert len(df) == 2
        assert df["settlement_price"].iloc[0] == 150.0
        assert df["product"].iloc[0] == "HDD_CME"

    def test_generate_synthetic_settlements(self):
        cmes = CMEWeatherConnector()
        df = cmes._generate_synthetic_settlements("HDD_CME")
        assert len(df) == 12
        assert df["settlement_price"].isna().all()

    def test_cache_key_deterministic(self):
        from pakhi.pipeline.cache import WeatherCache

        key1 = WeatherCache.hash_key("https://api.example.com/data", {"lat": 40.0})
        key2 = WeatherCache.hash_key("https://api.example.com/data", {"lat": 40.0})
        assert key1 == key2

    def test_cache_key_differs(self):
        from pakhi.pipeline.cache import WeatherCache

        key1 = WeatherCache.hash_key("https://api.example.com/data", {"lat": 40.0})
        key2 = WeatherCache.hash_key("https://api.example.com/data", {"lat": 41.0})
        assert key1 != key2
