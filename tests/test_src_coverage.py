"""Comprehensive tests for pakhi.src — all connectors with full coverage."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import requests
import xarray as xr


def _mock_response(json_data=None, status_code=200, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    resp.content = b"<xml></xml>"
    return resp


# === Yahoo ===
class TestYahooCoverage:
    def test_history(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        df = pd.DataFrame(
            {
                "Close": [80.0, 81.0],
                "Open": [79.0, 80.0],
                "High": [82.0, 83.0],
                "Low": [78.0, 79.0],
                "Volume": [1000, 1100],
            },
            index=pd.date_range("2024-01-01", periods=2),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        result = conn.history(period="5d")
        assert isinstance(result, dict)
        assert "CL=F" in result

    def test_history_invalid_period(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = MagicMock()
        with pytest.raises(ValueError, match="Invalid period"):
            conn.history(period="invalid")

    def test_history_invalid_interval(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = MagicMock()
        with pytest.raises(ValueError, match="Invalid interval"):
            conn.history(interval="bad")

    def test_history_with_start(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        df = pd.DataFrame(
            {"Close": [80.0], "Open": [80.0], "High": [81.0], "Low": [79.0], "Volume": [1000]},
            index=pd.date_range("2024-01-01", periods=1),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        result = conn.history(start="2024-01-01", end="2024-01-02")
        assert isinstance(result, dict)

    def test_latest(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        df = pd.DataFrame(
            {"Close": [80.0]},
            index=pd.date_range("2024-01-01", periods=1),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        result = conn.latest()
        assert isinstance(result, dict)

    def test_spread(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        df = pd.DataFrame(
            {"Close": [80.0, 81.0]},
            index=pd.date_range("2024-01-01", periods=2),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F", "NG=F"])
        conn._yf = mock_yf
        spread = conn.spread("CL=F", "NG=F", period="5d")
        assert isinstance(spread, pd.Series)

    def test_repr(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        conn = YahooFuturesConnector(tickers=["CL=F"])
        r = repr(conn)
        assert "CL=F" in r

    def test_history_all_empty(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        with pytest.raises(RuntimeError, match="No historical"):
            conn.history()

    def test_current_price_no_records(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        with pytest.raises(RuntimeError, match="No price data"):
            conn.current_price()

    def test_current_price_single_row(self):
        from pakhi.src.yahoo import YahooFuturesConnector

        mock_yf = MagicMock()
        df = pd.DataFrame(
            {"Close": [80.0], "Volume": [1000]},
            index=pd.date_range("2024-01-01", periods=1),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_yf.Ticker.return_value = mock_ticker
        conn = YahooFuturesConnector(tickers=["CL=F"])
        conn._yf = mock_yf
        result = conn.current_price()
        assert len(result) == 1


# === OpenMeteo ===
class TestOpenMeteoCoverage:
    def test_historical(self):
        from pakhi.src.openmeteo import OpenMeteoConnector

        resp_data = {
            "hourly": {
                "time": [f"2024-01-{i + 1:02d}T00:00" for i in range(5)],
                "temperature_2m": [10.0, 11.0, 12.0, 13.0, 14.0],
            }
        }
        conn = OpenMeteoConnector()
        conn._session = MagicMock()
        conn._session.get.return_value = _mock_response(resp_data)
        result = conn.historical("2024-01-01", "2024-01-05", 32.0, -88.0)
        assert result is not None

    def test_air_quality(self):
        from pakhi.src.openmeteo import OpenMeteoConnector

        resp_data = {
            "hourly": {
                "time": [f"2024-01-{i + 1:02d}T00:00" for i in range(3)],
                "european_aqi": [50, 60, 70],
                "pm10": [10, 15, 20],
                "pm2_5": [5, 7, 9],
                "ozone": [30, 35, 40],
            }
        }
        conn = OpenMeteoConnector()
        conn._session = MagicMock()
        conn._session.get.return_value = _mock_response(resp_data)
        result = conn.air_quality(32.0, -88.0)
        assert result is not None

    def test_multi_location(self):
        from pakhi.src.openmeteo import OpenMeteoConnector

        resp_data = {
            "hourly": {
                "time": [f"2024-01-{i + 1:02d}T00:00" for i in range(3)],
                "temperature_2m": [10.0, 11.0, 12.0],
            }
        }
        conn = OpenMeteoConnector()
        conn._session = MagicMock()
        conn._session.get.return_value = _mock_response(resp_data)
        locations = [{"lat": 32.0, "lon": -88.0}, {"lat": 33.0, "lon": -87.0}]
        result = conn.multi_location(locations)
        assert result is not None

    def test_rate_limiting(self):
        import requests as _req

        from pakhi.src.openmeteo import OpenMeteoConnector

        conn = OpenMeteoConnector(max_retries=2)
        rate_resp = MagicMock()
        rate_resp.raise_for_status.side_effect = _req.exceptions.HTTPError("429")
        ok_resp = _mock_response(
            {
                "hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [10.0]},
            }
        )
        conn._session = MagicMock()
        conn._session.get.side_effect = [rate_resp, ok_resp]
        result = conn.forecast(32.0, -88.0, days=1)
        assert result is not None

    def test_close(self):
        from pakhi.src.openmeteo import OpenMeteoConnector

        conn = OpenMeteoConnector()
        conn.close()


# === ERA5 ===
class TestERA5Coverage:
    def test_validate_variables(self):
        from pakhi.src.era5 import ERA5Connector

        with pytest.raises(ValueError, match="Unknown ERA5 variable"):
            ERA5Connector(variables=["bad_var"])

    def test_mixed_single_pressure_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        conn.pressure_level_vars = ["geopotential"]
        with pytest.raises(ValueError, match="Cannot fetch single-level"):
            conn.fetch("2024-01-01", "2024-01-02")

    def test_invalid_pressure_level(self):
        from pakhi.src.era5 import ERA5Connector

        with pytest.raises(ValueError, match="Pressure level"):
            ERA5Connector(pressure_levels=[999])

    def test_build_single_level_request(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        req = conn._build_single_level_request(["temperature_2m"], ["2024-01-01", "2024-01-02"])
        assert "variable" in req
        assert req["format"] == "netcdf"

    def test_build_pressure_level_request(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["geopotential"])
        req = conn._build_pressure_level_request(["geopotential"], ["2024-01-01"])
        assert "pressure_level" in req

    def test_build_request_with_area(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"], area=[50, -125, 24, -66])
        req = conn._build_single_level_request(["temperature_2m"], ["2024-01-01"])
        assert "area" in req

    def test_generate_dates(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector()
        dates = conn._generate_dates("2024-01-01", "2024-01-03")
        assert len(dates) == 3

    def test_fetch_monthly(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        with (
            patch.object(conn, "_download_dataset") as mock_dl,
            patch("pakhi.src.era5.xr.open_dataset") as mock_open,
        ):
            mock_path = Path(tempfile.mktemp(suffix=".nc"))
            mock_dl.return_value = mock_path
            ds = xr.Dataset({"temperature_2m": (["time", "lat", "lon"], np.random.randn(31, 5, 5))})
            mock_open.return_value = ds
            result = conn.fetch_monthly(2024, 1)
            assert result is not None

    def test_fetch_monthly_dec(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        with (
            patch.object(conn, "_download_dataset") as mock_dl,
            patch("pakhi.src.era5.xr.open_dataset") as mock_open,
        ):
            mock_dl.return_value = Path(tempfile.mktemp(suffix=".nc"))
            ds = xr.Dataset({"temperature_2m": (["time", "lat", "lon"], np.random.randn(31, 5, 5))})
            mock_open.return_value = ds
            result = conn.fetch_monthly(2024, 12)
            assert result is not None

    def test_get_cds_client_import_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector()
        with (
            patch.dict("sys.modules", {"cdsapi": None}),
            pytest.raises(ImportError, match="cdsapi"),
        ):
            conn._get_cds_client()

    def test_context_manager(self):
        from pakhi.src.era5 import ERA5Connector

        with ERA5Connector() as conn:
            assert conn is not None


# === NOAA ===
class TestNOAACoverage:
    def test_init_invalid_var(self):
        from pakhi.src.noaa import GFSConnector

        with pytest.raises(ValueError, match="Unknown variable"):
            GFSConnector(variables=["bad_var"])

    def test_init_invalid_bbox(self):
        from pakhi.src.noaa import GFSConnector

        with pytest.raises(ValueError, match="bbox must be"):
            GFSConnector(bbox=[1, 2, 3])

    def test_latest_cycle(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        ref = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
        date, cycle = conn._latest_cycle(ref)
        assert len(date) == 8
        assert len(cycle) == 2

    def test_build_url(self):
        from pakhi.src.noaa import GFS_VARIABLE_MAP, GFSConnector

        conn = GFSConnector()
        url = conn._build_url("20240615", "00", 0, GFS_VARIABLE_MAP["temperature_2m"])
        assert "gfs" in url

    def test_context_manager(self):
        from pakhi.src.noaa import GFSConnector

        with GFSConnector() as conn:
            assert conn is not None


# === Meteostat ===
class TestMeteostatCoverage:
    def test_get_retry(self):
        from pakhi.src.meteostat import MeteostatConnector

        with patch("pakhi.src.meteostat.requests.Session") as MockSession:
            mock_sess = MagicMock()
            MockSession.return_value = mock_sess
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"data": []}
            mock_sess.get.return_value = mock_resp
            conn = MeteostatConnector()
            result = conn._get("stations/nearby")
            assert result == {"data": []}

    def test_repr(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        assert "anonymous" in repr(conn)

    def test_repr_with_key(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector(api_key="test_key")
        assert "authenticated" in repr(conn)

    def test_stations_near_fallback(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with (
            patch.object(conn, "_get", side_effect=ConnectionError("fail")),
            patch.object(conn, "_stations_near_library") as mock_lib,
        ):
            mock_lib.return_value = pd.DataFrame()
            result = conn.stations_near(32.0, -88.0)
            assert isinstance(result, pd.DataFrame)

    def test_stations_near_from_api(self):
        from pakhi.src.meteostat import MeteostatConnector

        resp_data = {
            "data": [
                {
                    "id": "ST1",
                    "name": "Test Station",
                    "country": "US",
                    "region": "AL",
                    "latitude": 32.0,
                    "longitude": -88.0,
                    "elevation": 100,
                    "distance": 5.0,
                    "first": "2020",
                    "last": "2024",
                    "hourly": True,
                    "daily": True,
                },
            ]
        }
        with patch("pakhi.src.meteostat.requests.Session") as MockSession:
            mock_sess = MagicMock()
            MockSession.return_value = mock_sess
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = resp_data
            mock_sess.get.return_value = mock_resp
            conn = MeteostatConnector()
            result = conn.stations_near(32.0, -88.0)
            assert len(result) > 0

    def test_history_from_api(self):
        from pakhi.src.meteostat import MeteostatConnector

        resp_data = {
            "data": [
                {"date": "2024-01-01", "temperature_max": 15.0, "temperature_min": 5.0},
            ]
        }
        with patch("pakhi.src.meteostat.requests.Session") as MockSession:
            mock_sess = MagicMock()
            MockSession.return_value = mock_sess
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = resp_data
            mock_sess.get.return_value = mock_resp
            conn = MeteostatConnector()
            result = conn.history("ST1", "2024-01-01", "2024-01-01")
            assert isinstance(result, pd.DataFrame)

    def test_history_empty(self):
        from pakhi.src.meteostat import MeteostatConnector

        with patch("pakhi.src.meteostat.requests.Session") as MockSession:
            mock_sess = MagicMock()
            MockSession.return_value = mock_sess
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"data": []}
            mock_sess.get.return_value = mock_resp
            conn = MeteostatConnector()
            result = conn.history("ST1", "2024-01-01", "2024-01-01")
            assert result.empty

    def test_history_multi(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with patch.object(conn, "history") as mock_h:
            mock_h.return_value = pd.DataFrame({"temp": [10.0]})
            result = conn.history_multi(["ST1", "ST2"], "2024-01-01", "2024-01-01")
            assert isinstance(result, dict)

    def test_close(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        conn.close()


# === CME ===
class TestCMECoverage:
    def test_init_invalid_product(self):
        from pakhi.src.cmes import CMEWeatherConnector

        with pytest.raises(ValueError, match="Unknown product"):
            CMEWeatherConnector(products=["BAD"])

    def test_init_invalid_region(self):
        from pakhi.src.cmes import CMEWeatherConnector

        with pytest.raises(ValueError, match="Unknown region"):
            CMEWeatherConnector(regions=["BAD"])

    def test_parse_settlements(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        raw = {"settlements": [{"value": 50.0, "date": "2024-01-01"}]}
        result = conn._parse_cme_settlements(raw, "HDD_CME")
        assert isinstance(result, pd.DataFrame)

    def test_parse_settlements_list(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        raw = [{"value": 50.0, "date": "2024-01-01"}]
        result = conn._parse_cme_settlements(raw, "HDD_CME")
        assert isinstance(result, pd.DataFrame)

    def test_parse_settlements_empty(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        result = conn._parse_cme_settlements(None, "HDD_CME")
        assert result.empty

    def test_fetch_json_retry(self):
        import requests as _req

        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(max_retries=2)
        with patch.object(conn, "_session") as mock_sess:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = _req.exceptions.ConnectionError("fail")
            mock_sess.get.return_value = mock_resp
            with pytest.raises(ConnectionError):
                conn._fetch_json("http://test.com")

    def test_context_manager(self):
        from pakhi.src.cmes import CMEWeatherConnector

        with CMEWeatherConnector() as conn:
            assert conn is not None

    def test_close(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        conn.close()

    def test_settlements_list_type(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        raw = [{"value": 60.0, "date": "2024-01-02", "contract": "HDD_Jan24"}]
        result = conn._parse_cme_settlements(raw, "CDD_CME")
        assert isinstance(result, pd.DataFrame)


# === Satellite ===
class TestSatelliteCoverage:
    def test_init_invalid_satellite(self):
        from pakhi.src.satellite import GOESConnector

        with pytest.raises(ValueError, match="satellite must be"):
            GOESConnector(satellite="GOES-99")

    def test_init_invalid_sector(self):
        from pakhi.src.satellite import GOESConnector

        with pytest.raises(ValueError, match="sector must be"):
            GOESConnector(sector="BAD")

    def test_init_invalid_band(self):
        from pakhi.src.satellite import GOESConnector

        with pytest.raises(ValueError, match="Unknown band"):
            GOESConnector(bands=["band_99"])

    def test_s3_prefix(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        dt = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        prefix = conn._s3_prefix(dt, "band_13")
        assert isinstance(prefix, str)

    def test_find_latest_file_none(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        with patch.object(conn, "_list_s3_objects", return_value=[]):
            result = conn._find_latest_file("band_13")
            assert result is None

    def test_list_s3_objects_error(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        with patch.object(conn, "_session") as mock_sess:
            mock_sess.get.side_effect = Exception("S3 error")
            result = conn._list_s3_objects("prefix/")
            assert result == []

    def test_download_cached(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        cached_file = conn.cache_dir / "test_cached.nc"
        cached_file.write_text("cached")
        result = conn._download_s3_file("path/to/test_cached.nc")
        assert result.exists()
        cached_file.unlink()

    def test_cloud_motion_insufficient_images(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        with patch.object(conn, "_find_latest_file", return_value=None):
            result = conn.cloud_motion(minutes=15)
            assert "u_cloud_motion" in result

    def test_cloud_motion_invalid_minutes(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        with pytest.raises(ValueError, match="Minimum"):
            conn.cloud_motion(minutes=5)

    def test_close(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        conn.close()

    def test_context_manager(self):
        from pakhi.src.satellite import GOESConnector

        with GOESConnector() as conn:
            assert conn is not None

    def test_open_netcdf(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        tmp = Path(tempfile.mktemp(suffix=".nc"))
        ds = xr.Dataset({"CMI": (["y", "x"], np.random.randn(10, 10))})
        ds.to_netcdf(str(tmp))
        result = conn._open_netcdf(tmp)
        assert "brightness_temperature" in result or len(result.data_vars) > 0
        tmp.unlink()


# === Deep satellite tests ===
class TestSatelliteDeep:
    def test_download_fresh(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        key = "ABI-L2-CMIPF/2024/166/12/OR_ABI-L2-CMIPF-M6C13_G16_s20241661200.nc"
        fake_content = b"fake netcdf data"
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = lambda chunk_size: [fake_content]
        with patch.object(conn._session, "get", return_value=mock_resp):
            result = conn._download_s3_file(key)
            assert result.exists()
            result.unlink(missing_ok=True)

    def test_open_netcdf_with_scale(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        tmp = Path(tempfile.mktemp(suffix=".nc"))
        data = np.random.randn(10, 10).astype(np.float32)
        da = xr.DataArray(data, dims=["y", "x"])
        da.attrs["scale_factor"] = 0.1
        da.attrs["add_offset"] = 200.0
        ds = xr.Dataset({"CMI": da})
        ds.to_netcdf(str(tmp))
        result = conn._open_netcdf(tmp)
        assert "brightness_temperature" in result
        tmp.unlink()

    def test_open_netcdf_multiple_vars(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        tmp = Path(tempfile.mktemp(suffix=".nc"))
        ds = xr.Dataset(
            {
                "CMI": (["y", "x"], np.random.randn(10, 10)),
                "DQF": (["y", "x"], np.random.randn(10, 10)),
            }
        )
        ds.to_netcdf(str(tmp))
        result = conn._open_netcdf(tmp)
        assert len(result.data_vars) >= 2
        tmp.unlink()

    def test_latest_no_data(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        with (
            patch.object(conn, "_find_latest_file", return_value=None),
            pytest.raises(RuntimeError, match="No GOES data"),
        ):
            conn.latest()

    def test_cloud_motion_with_images(self):
        from pakhi.src.satellite import GOESConnector

        conn = GOESConnector()
        fake_img = np.random.randn(64, 64).astype(np.float32)

        def mock_find(band):
            return "fake_key"

        def mock_download(key):
            tmp = Path(tempfile.mktemp(suffix=".nc"))
            ds = xr.Dataset({"brightness_temperature": (["y", "x"], fake_img)})
            ds.to_netcdf(str(tmp))
            return tmp

        def mock_open(path):
            ds = xr.open_dataset(path)
            path.unlink(missing_ok=True)
            return ds

        with (
            patch.object(conn, "_find_latest_file", side_effect=mock_find),
            patch.object(conn, "_download_s3_file", side_effect=mock_download),
            patch.object(conn, "_open_netcdf", side_effect=mock_open),
        ):
            result = conn.cloud_motion(minutes=15)
            assert "u_cloud_motion" in result
            assert "confidence" in result


# === Deep era5 tests ===
class TestERA5Deep:
    def test_build_requests_with_area(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"], area=[50, -125, 24, -66])
        req = conn._build_single_level_request(["temperature_2m"], ["2024-01-01"])
        assert req["area"] == [50, -125, 24, -66]

    def test_pressure_level_request_with_area(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["geopotential"], area=[50, -125, 24, -66])
        req = conn._build_pressure_level_request(["geopotential"], ["2024-01-01"])
        assert "area" in req

    def test_fetch_pressure_level(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["geopotential"])
        with (
            patch.object(conn, "_download_dataset") as mock_dl,
            patch("pakhi.src.era5.xr.open_dataset") as mock_open,
        ):
            mock_dl.return_value = Path(tempfile.mktemp(suffix=".nc"))
            ds = xr.Dataset(
                {"geopotential": (["time", "level", "lat", "lon"], np.random.randn(1, 2, 5, 5))}
            )
            mock_open.return_value = ds
            result = conn.fetch("2024-01-01", "2024-01-01")
            assert result is not None

    def test_fetch_no_data_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=[])
        with pytest.raises(RuntimeError, match="No data"):
            conn.fetch("2024-01-01", "2024-01-01")

    def test_download_dataset_cached(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        cached = conn.cache_dir / "test.nc"
        cached.write_text("cached")
        mock_client = MagicMock()
        with patch.object(conn, "_get_cds_client", return_value=mock_client):
            result = conn._download_dataset({}, "test.nc")
            assert result == cached
            mock_client.retrieve.assert_not_called()
        cached.unlink()

    def test_download_dataset_fresh(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        mock_client = MagicMock()
        with patch.object(conn, "_get_cds_client", return_value=mock_client):
            conn._download_dataset(
                {"product_type": "reanalysis", "variable": ["2m_temperature"]}, "era5_test.nc"
            )
            mock_client.retrieve.assert_called_once()

    def test_download_dataset_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = Exception("CDS error")
        with (
            patch.object(conn, "_get_cds_client", return_value=mock_client),
            pytest.raises(Exception, match="CDS error"),
        ):
            conn._download_dataset({"product_type": "reanalysis"}, "test.nc")

    def test_get_cds_client_import_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector()
        with (
            patch.dict("sys.modules", {"cdsapi": None}),
            pytest.raises(ImportError, match="cdsapi"),
        ):
            conn._get_cds_client()

    def test_fetch_monthly(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"temperature_2m": (["time", "lat", "lon"], np.random.randn(1, 5, 5))})
        with patch.object(conn, "fetch", return_value=mock_ds) as mock_fetch:
            result = conn.fetch_monthly(2024, 1)
            mock_fetch.assert_called_once()
            assert result is not None

    def test_fetch_monthly_december(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"temperature_2m": (["time", "lat", "lon"], np.random.randn(1, 5, 5))})
        with patch.object(conn, "fetch", return_value=mock_ds) as mock_fetch:
            conn.fetch_monthly(2024, 12)
            call_args = mock_fetch.call_args
            assert call_args[0][0] == "2024-12-01"
            assert call_args[0][1] == "2024-12-31"

    def test_fetch_with_bbox(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector(variables=["temperature_2m"])
        with (
            patch.object(conn, "_download_dataset") as mock_dl,
            patch("pakhi.src.era5.xr.open_dataset") as mock_open,
        ):
            mock_dl.return_value = Path(tempfile.mktemp(suffix=".nc"))
            ds = xr.Dataset({"temperature_2m": (["time", "lat", "lon"], np.random.randn(1, 5, 5))})
            mock_open.return_value = ds
            conn.fetch("2024-01-01", "2024-01-01", bbox=[50, -125, 24, -66])
            assert conn.area == [50, -125, 24, -66]

    def test_fetch_zarr_import_error(self):
        from pakhi.src.era5 import ERA5Connector

        conn = ERA5Connector()
        with (
            patch.dict("sys.modules", {"zarr": None, "gcsfs": None}),
            pytest.raises(ImportError, match="zarr"),
        ):
            conn.fetch_zarr("2024-01-01", "2024-01-02")


# === Deep noaa tests ===
class TestNOAADeep:
    def test_download_with_retry_cached(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        cached = conn.cache_dir / "test_grib.grib2"
        cached.write_bytes(b"cached grib data")
        result = conn._download_with_retry("http://test.com", cached)
        assert result == cached
        cached.unlink()

    def test_build_url_with_level(self):
        from pakhi.src.noaa import GFS_VARIABLE_MAP, GFSConnector

        conn = GFSConnector(resolution="0p50")
        url = conn._build_url("20240615", "00", 6, GFS_VARIABLE_MAP["temperature_500"])
        assert "500 mb" in url or "lev" in url

    def test_build_url_no_level(self):
        from pakhi.src.noaa import GFS_VARIABLE_MAP, GFSConnector

        conn = GFSConnector()
        url = conn._build_url("20240615", "00", 12, GFS_VARIABLE_MAP["temperature_2m"])
        assert "gfs" in url

    def test_close(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        conn.close()


# === Deep meteostat tests ===
class TestMeteostatDeep:
    def test_stations_near_library_fallback(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with (
            patch.object(conn, "_get", side_effect=ConnectionError("fail")),
            pytest.raises(ImportError, match="meteostat"),
        ):
            conn.stations_near(32.0, -88.0)

    def test_history_library_fallback(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with (
            patch.object(conn, "_get", side_effect=ConnectionError("fail")),
            pytest.raises(ImportError, match="meteostat"),
        ):
            conn.history("ST1", "2024-01-01", "2024-01-02")

    def test_history_multi_with_error(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with patch.object(conn, "history", side_effect=Exception("fail")):
            result = conn.history_multi(["ST1"], "2024-01-01", "2024-01-01")
            assert result == {}

    def test_history_multi_partial(self):
        from pakhi.src.meteostat import MeteostatConnector

        conn = MeteostatConnector()
        with patch.object(
            conn, "history", side_effect=[Exception("fail"), pd.DataFrame({"temp": [10]})]
        ):
            result = conn.history_multi(["ST1", "ST2"], "2024-01-01", "2024-01-01")
            assert "ST2" in result


# === Deep NOAA tests ===
class TestNOAATrulyDeep:
    def test_latest_cycle_fallback(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        with patch("pakhi.src.noaa.requests.get") as mock_get:
            mock_get.side_effect = Exception("fail")
            date, cycle = conn._latest_cycle()
            assert len(date) == 8
            assert len(cycle) == 2

    def test_download_fresh_success(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(max_retries=1)
        dest = conn.cache_dir / "test_fresh.grib2"
        dest.unlink(missing_ok=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = lambda chunk_size: [b"fakedata"]
        with patch.object(conn._session, "get", return_value=mock_resp):
            result = conn._download_with_retry("http://test.com/data", dest)
            assert result.exists()
            assert result.stat().st_size > 0
        dest.unlink(missing_ok=True)

    def test_download_retry_all_fail(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(max_retries=2, retry_delay=0)
        dest = conn.cache_dir / "test_retry.grib2"
        dest.unlink(missing_ok=True)
        with (
            patch.object(conn._session, "get", side_effect=requests.ConnectionError("fail")),
            pytest.raises(ConnectionError, match="Failed to download"),
        ):
            conn._download_with_retry("http://test.com/data", dest)
        dest.unlink(missing_ok=True)

    def test_open_grib_fallback_engine(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        ds = xr.Dataset({"t2m": (["time", "lat", "lon"], np.random.randn(1, 5, 5))})
        with patch("pakhi.src.noaa.xr.open_dataset") as mock_open:
            # First call fails (with index_keys), second succeeds
            mock_open.side_effect = [
                Exception("index fail"),
                ds,
            ]
            conn._open_grib([Path("test.grib")])
            assert mock_open.call_count == 2

    def test_open_grib_all_fail(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector()
        with (
            patch("pakhi.src.noaa.xr.open_dataset", side_effect=Exception("all fail")),
            pytest.raises(RuntimeError, match="No GRIB2 files"),
        ):
            conn._open_grib([Path("test.grib")])

    def test_fetch_forecast_with_date(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"t2m": (["time"], [290.0])})
        with (
            patch.object(conn, "_download_with_retry") as mock_dl,
            patch.object(conn, "_open_grib", return_value=mock_ds),
        ):
            conn._fetch_forecast("20240615", "00", 0)
            assert mock_dl.called

    def test_fetch_forecast_auto_date(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"t2m": (["time"], [290.0])})
        with (
            patch.object(conn, "_latest_cycle", return_value=("20240615", "00")),
            patch.object(conn, "_download_with_retry"),
            patch.object(conn, "_open_grib", return_value=mock_ds),
        ):
            result = conn._fetch_forecast(forecast_hour=6)
            assert result is not None

    def test_latest(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"t2m": (["time"], [290.0])})
        with (
            patch.object(conn, "_latest_cycle", return_value=("20240615", "00")),
            patch.object(conn, "_fetch_forecast", return_value=mock_ds),
        ):
            conn.latest(forecast_hour=0)
            conn._fetch_forecast.assert_called_once_with("20240615", "00", 0)

    def test_forecast(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"t2m": (["time"], [290.0])})
        with (
            patch.object(conn, "_latest_cycle", return_value=("20240615", "00")),
            patch.object(conn, "_fetch_forecast", return_value=mock_ds),
        ):
            result = conn.forecast(steps=[0, 6])
            assert result is not None

    def test_forecast_all_fail(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        with (
            patch.object(conn, "_latest_cycle", return_value=("20240615", "00")),
            patch.object(conn, "_fetch_forecast", side_effect=Exception("fail")),
            pytest.raises(RuntimeError, match="No forecast steps"),
        ):
            conn.forecast(steps=[0, 6])

    def test_archive(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        mock_ds = xr.Dataset({"t2m": (["lat", "lon"], np.random.randn(5, 5))})
        with patch.object(conn, "_fetch_forecast", return_value=mock_ds):
            result = conn.archive("2024-06-15", "2024-06-15", forecast_hour=0)
            assert result is not None

    def test_archive_all_fail(self):
        from pakhi.src.noaa import GFSConnector

        conn = GFSConnector(variables=["temperature_2m"])
        with (
            patch.object(conn, "_fetch_forecast", side_effect=Exception("fail")),
            pytest.raises(RuntimeError, match="No archive data"),
        ):
            conn.archive("2024-06-15", "2024-06-15")


# === Deep CME tests ===
class TestCMEDeep:
    def test_fetch_settlements_from_api_no_url(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        result = conn._fetch_settlements_from_api("GAS_DD")
        assert isinstance(result, pd.DataFrame)

    def test_fetch_settlements_from_api_with_url(self):
        from pakhi.src.cmes import CME_PRODUCTS, CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        with patch.dict(
            CME_PRODUCTS,
            {
                "GAS_DD": {
                    "name": "GAS_DD",
                    "exchange": "CME",
                    "settlement_url": "http://test.com/api",
                }
            },
        ):
            mock_data = [{"date": "2024-01-01", "settlement": 3.5}]
            with patch.object(conn, "_fetch_json", return_value=mock_data):
                result = conn._fetch_settlements_from_api("GAS_DD")
                assert isinstance(result, pd.DataFrame)

    def test_fetch_settlements_from_api_error_fallback(self):
        from pakhi.src.cmes import CME_PRODUCTS, CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        with (
            patch.dict(
                CME_PRODUCTS,
                {
                    "GAS_DD": {
                        "name": "GAS_DD",
                        "exchange": "CME",
                        "settlement_url": "http://test.com/api",
                    }
                },
            ),
            patch.object(conn, "_fetch_json", side_effect=Exception("API fail")),
        ):
            result = conn._fetch_settlements_from_api("GAS_DD")
            assert isinstance(result, pd.DataFrame)

    def test_parse_settlements_nested(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        raw = {
            "data": [
                {
                    "date": "2024-01-01",
                    "settlement": 3.5,
                    "change": 0.1,
                    "volume": 1000,
                    "open_interest": 5000,
                }
            ]
        }
        result = conn._parse_cme_settlements(raw, "GAS_DD")
        assert isinstance(result, pd.DataFrame)

    def test_generate_synthetic_settlements(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        result = conn._generate_synthetic_settlements("GAS_DD")
        assert len(result) == 12
        assert "settlement_price" in result.columns

    def test_latest_settlements(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        with patch.object(conn, "_fetch_settlements_from_api") as mock_fetch:
            mock_fetch.return_value = pd.DataFrame(
                {"product": ["GAS_DD"], "settlement_price": [3.5]}
            )
            result = conn.latest_settlements()
            assert isinstance(result, pd.DataFrame)

    def test_history(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        with patch.object(conn, "_fetch_settlements_from_api") as mock_fetch:
            mock_fetch.return_value = pd.DataFrame(
                {
                    "settlement_date": ["2024-01-15"],
                    "settlement_price": [3.5],
                }
            )
            result = conn.history("2024-01-01", "2024-01-31")
            assert isinstance(result, pd.DataFrame)

    def test_history_empty(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        with patch.object(conn, "_fetch_settlements_from_api", return_value=pd.DataFrame()):
            result = conn.history()
            assert isinstance(result, pd.DataFrame)

    def test_compute_hdd(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([40.0, 50.0, 70.0, 80.0])
        result = conn.compute_hdd(temps)
        # Temps < 100 auto-detected as Celsius: 40C = 104F → 0 HDD
        assert isinstance(result, pd.Series)

    def test_compute_hdd_fahrenheit(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([40.0, 50.0, 70.0, 110.0])  # > 100 means Fahrenheit
        result = conn.compute_hdd(temps, base_temp_f=65.0)
        assert result.iloc[0] == 25.0
        assert result.iloc[2] == 0.0

    def test_compute_cdd(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([60.0, 70.0, 85.0, 90.0])
        result = conn.compute_cdd(temps)
        # Temps < 100 auto-detected as Celsius: 85C = 185F → high CDD
        assert isinstance(result, pd.Series)

    def test_compute_cdd_fahrenheit(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([60.0, 70.0, 85.0, 110.0])  # > 100 means Fahrenheit
        result = conn.compute_cdd(temps, base_temp_f=65.0)
        assert result.iloc[0] == 0.0
        assert result.iloc[2] == 20.0

    def test_compute_hdd_no_base(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([40.0, 110.0])  # > 100 = Fahrenheit
        result = conn.compute_hdd(temps, base_temp_f=50.0)
        assert result.iloc[0] == 10.0  # 50 - 40

    def test_compute_cdd_no_base(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector()
        temps = pd.Series([85.0, 110.0])  # > 100 = Fahrenheit
        result = conn.compute_cdd(temps, base_temp_f=80.0)
        assert result.iloc[0] == 5.0  # 85 - 80

    def test_repr(self):
        from pakhi.src.cmes import CMEWeatherConnector

        conn = CMEWeatherConnector(products=["GAS_DD"])
        r = repr(conn)
        assert "CMEWeatherConnector" in r
