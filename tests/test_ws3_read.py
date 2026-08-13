"""WS-3 T2: read endpoints — instruments, signals, forecasts, ensemble, ledger.

Verifies: provenance passthrough, 404-vs-empty, honest 501s for not-yet-stored
data, ledger summary math, and the X-Pakhi-Edge-Status header computed live from
the seeded ledger.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from tests.ws3_fixtures import seed_store


def _now() -> datetime:
    return datetime.now()  # naive UTC matches sqlite storage


@pytest.fixture
def store_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


@pytest.fixture
def app(store_url):
    app = create_app(Settings(read_db_url=store_url, write_db_url=store_url))
    return app


@pytest.fixture
def seeded_store(store_url):
    now = _now()
    seed_store(
        store_url,
        cycles=[
            {
                "id": "20260813_12z",
                "publication_ts": now - timedelta(hours=2),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            },
            {
                "id": "20260812_12z",
                "publication_ts": now - timedelta(hours=26),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            },
        ],
        signals=[
            {
                "timestamp": now - timedelta(hours=1),
                "instrument": "OJ_FUTURES",
                "action": "LONG",
                "size": 1.0,
                "confidence": 0.81,
                "reasoning": "freeze_prob above theta_p in key OJ region",
                "forecast_cycle_id": "20260813_12z",
                "publication_ts": now - timedelta(hours=2),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            },
            {
                "timestamp": now - timedelta(hours=25),
                "instrument": "OJ_FUTURES",
                "action": "LONG",
                "size": 1.0,
                "confidence": 0.77,
                "reasoning": "cold snap window tightening",
                "forecast_cycle_id": "20260812_12z",
                "publication_ts": now - timedelta(hours=26),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            },
        ],
        ledger=[
            {
                "episode_id": 1,
                "forecast_cycle_id": "20260810_12z",
                "publication_ts": now - timedelta(days=2),
                "model_version": "GFS-0p50",
                "scored": True,
                "archive_source": "noaa-gfs-bdp-pds",
                "vintage_hash": "a" * 64,
                "net_of_benchmark": 0.02,
                "net": 0.03,
                "gross": 0.05,
            },
            {
                "episode_id": 2,
                "forecast_cycle_id": "20260811_12z",
                "publication_ts": now - timedelta(days=1),
                "model_version": "GFS-0p50",
                "scored": True,
                "archive_source": "noaa-gfs-bdp-pds",
                "vintage_hash": "b" * 64,
                "net_of_benchmark": -0.01,
                "net": 0.0,
                "gross": 0.02,
            },
            {
                "episode_id": 3,
                "forecast_cycle_id": "20260812_12z",
                "publication_ts": now - timedelta(hours=20),
                "model_version": "GFS-0p50",
                "scored": False,  # embargoed / not in OOS — excluded from edge status
                "archive_source": "noaa-gfs-bdp-pds",
                "vintage_hash": "c" * 64,
                "net_of_benchmark": 0.5,
                "net": 0.4,
                "gross": 0.42,
            },
        ],
    )
    return store_url


def test_instruments_list(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/instruments")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["instruments"]) == 1
    entry = body["instruments"][0]
    assert entry["instrument"] == "OJ_FUTURES"
    assert entry["signal_count"] == 2
    assert entry["latest_signal_at"] is not None
    assert entry["staleness_seconds"] < 7200


def test_instruments_empty_404(store_url, app):
    seed_store(store_url)  # schema only — zero rows is a 404, not a 200
    with TestClient(app) as client:
        resp = client.get("/v1/instruments")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_signals_latest_first_with_provenance(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES")
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument"] == "OJ_FUTURES"
    assert body["count"] == 2
    first = body["signals"][0]
    assert first["forecast_cycle_id"] == "20260813_12z"  # newest first
    assert first["archive_source"] == "noaa-gfs-bdp-pds"
    assert first["model_version"] == "GFS-0p50"
    assert first["action"] == "LONG"
    assert first["size"] == 1.0
    assert first["confidence"] == 0.81
    assert set(first) == {
        "instrument",
        "action",
        "size",
        "confidence",
        "reasoning",
        "timestamp",
        "forecast_cycle_id",
        "publication_ts",
        "archive_source",
        "model_version",
    }
    assert resp.headers["X-Pakhi-Edge-Status"] == "underpowered_n2"


def test_signals_limit(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES", params={"limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["signals"][0]["forecast_cycle_id"] == "20260813_12z"


def test_signals_since_filter(seeded_store, app):
    since = (_now() - timedelta(hours=12)).isoformat()
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES", params={"since": since})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["signals"][0]["forecast_cycle_id"] == "20260813_12z"


def test_signals_cycle_filter(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES", params={"cycle_id": "20260812_12z"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["signals"][0]["forecast_cycle_id"] == "20260812_12z"


def test_signals_unknown_instrument_404(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/NG_FUTURES")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_signals_invalid_since_422_envelope(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES", params={"since": "not-a-date"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"


def test_signals_invalid_limit_422(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/signals/OJ_FUTURES", params={"limit": 0})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_forecasts_501_not_implemented(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/forecasts/OJ_FUTURES", params={"lead": "7d"})
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "not_implemented"
    assert "not" in body["error"]["message"]


def test_ensemble_disagreement_501(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/ensemble/disagreement")
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "not_implemented"


def test_ledger_summary_and_edge_status(seeded_store, app):
    with TestClient(app) as client:
        resp = client.get("/v1/ledger")
    assert resp.status_code == 200
    body = resp.json()["ledger"]
    assert body["label"] == "paper / not live capital"
    assert body["total_count"] == 3
    assert body["scored_count"] == 2
    assert body["net_of_benchmark"] == pytest.approx(0.01)  # 0.02 + (-0.01)
    assert body["mean_net_of_benchmark"] == pytest.approx(0.005)
    assert resp.headers["X-Pakhi-Edge-Status"] == "underpowered_n2"


def test_ledger_empty_store(store_url, app):
    seed_store(store_url)  # schema only — empty ledger is honest zeros, not 404
    with TestClient(app) as client:
        resp = client.get("/v1/ledger")
    assert resp.status_code == 200
    body = resp.json()["ledger"]
    assert body["total_count"] == 0
    assert body["scored_count"] == 0
    assert body["net_of_benchmark"] is None
    assert resp.headers["X-Pakhi-Edge-Status"] == "underpowered_n0"
