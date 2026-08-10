import pandas as pd
import pytest

from pakhi.src.cmes import CMEWeatherConnector


def test_cme_fetch_json_success(monkeypatch):
    cme = CMEWeatherConnector()

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": "test"}

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(cme._session, "get", mock_get)
    res = cme._fetch_json("http://test.com")
    assert res == {"data": "test"}


def test_cme_parse_invalid_price():
    cme = CMEWeatherConnector()
    # to hit ValueError/TypeError in parse
    raw = [{"month": "2023-01", "settlementPrice": "invalid_string"}]
    df = cme._parse_cme_settlements(raw, "HDD_CME")
    assert df.iloc[0]["settlement_price"] is None


def test_cme_latest_settlements_empty(monkeypatch):
    cme = CMEWeatherConnector()
    # mock _fetch_settlements_from_api to return empty df
    monkeypatch.setattr(cme, "_fetch_settlements_from_api", lambda x: pd.DataFrame())
    with pytest.raises(RuntimeError, match="No settlement data could be fetched"):
        cme.latest_settlements()


def test_cme_history_exception(monkeypatch):
    cme = CMEWeatherConnector()

    # mock _fetch_settlements_from_api to raise exception
    def mock_fetch(*args, **kwargs):
        raise ValueError("Simulated error")

    monkeypatch.setattr(cme, "_fetch_settlements_from_api", mock_fetch)
    # It should catch Exception and continue, then return synthetic
    df = cme.history(start="2020-01-01", end="2020-12-31")
    assert df["settlement_price"].isnull().all()
