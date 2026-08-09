import pytest
from pakhi.src.openmeteo import OpenMeteoConnector

def test_openmeteo_forecast_models(monkeypatch):
    om = OpenMeteoConnector()
    # mock _get to return dummy
    def mock_get(url, params):
        assert params.get("models") == "gfs_seamless,ecmwf_ifs025"
        return {"hourly": {"time": ["2023-01-01T00:00"], "t": [1]}}
    monkeypatch.setattr(om, "_get", mock_get)
    ds = om.forecast(lat=0, lon=0, models=["gfs_seamless", "ecmwf_ifs025"])
    assert "t" in ds

def test_openmeteo_multi_location_list(monkeypatch):
    om = OpenMeteoConnector()
    # mock _get to return list
    def mock_get(url, params):
        return [
            {"hourly": {"time": ["2023-01-01T00:00"], "t": [1]}},
            {"hourly": {"time": ["2023-01-01T00:00"], "t": [2]}}
        ]
    monkeypatch.setattr(om, "_get", mock_get)
    ds = om.multi_location([{"lat": 0, "lon": 0}, {"lat": 1, "lon": 1}])
    assert "location" in ds.dims

def test_openmeteo_parse_model_attr():
    om = OpenMeteoConnector()
    # mock parse
    res = om._parse_response({
        "hourly": {"time": ["2023-01-01T00:00"], "t": [1]},
        "model": "gfs"
    })
    assert res.attrs["model"] == "gfs"

def test_openmeteo_parse_empty():
    om = OpenMeteoConnector()
    with pytest.raises(RuntimeError, match="No data in Open-Meteo response"):
        om._parse_response({"latitude": 0})
