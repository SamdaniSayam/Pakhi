"""WS-3 T5 tests: pakhi.client SDK round-trips and API key verification."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from pakhi.api.auth import hash_key
from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.client import PakhiClient
from tests.ws3_fixtures import seed_store


@pytest.fixture
def api_client(tmp_path):
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    now = datetime.now()
    cycle = {
        "id": "20260812_12z",
        "publication_ts": now,
        "archive_source": "noaa_gfs",
        "model_version": "GFS-0p50",
    }
    signal = {
        "timestamp": now,
        "instrument": "OJ_FUTURES",
        "action": "LONG",
        "size": 0.5,
        "confidence": 0.8,
        "forecast_cycle_id": "20260812_12z",
        "publication_ts": now,
        "archive_source": "noaa_gfs",
        "model_version": "GFS-0p50",
    }
    seed_store(f"sqlite:///{read_db}", cycles=[cycle], signals=[signal])
    seed_store(f"sqlite:///{write_db}", cycles=[cycle], signals=[signal])

    settings = Settings(
        read_db_url=f"sqlite:///{read_db}",
        write_db_url=f"sqlite:///{write_db}",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client, app.state.write_engine


def test_sdk_health_and_status(api_client):
    test_client, _ = api_client
    # Custom httpx transport targeting TestClient WSGI/ASGI app
    transport = test_client._transport
    client = PakhiClient(base_url="http://test", transport=transport)

    health = client.health()
    assert health == {"status": "ok"}

    status = client.status()
    assert status["db_ok"] is True
    assert status["latest_cycle_id"] == "20260812_12z"
    client.close()


def test_sdk_signals_and_ledger(api_client):
    test_client, _ = api_client
    transport = test_client._transport
    with PakhiClient(base_url="http://test", transport=transport) as client:
        instruments = client.instruments()
        assert "instruments" in instruments

        signals = client.signals("OJ_FUTURES", limit=5)
        assert signals["instrument"] == "OJ_FUTURES"
        assert len(signals["signals"]) > 0

        ledger = client.ledger()
        assert "ledger" in ledger
        assert ledger["ledger"]["label"] == "paper / not live capital"


def test_sdk_backtests(api_client):
    test_client, write_engine = api_client
    transport = test_client._transport
    with PakhiClient(base_url="http://test", transport=transport) as client:
        created = client.backtests.create(instrument="OJ_FUTURES", window_days=15)
        assert created["job_id"].startswith("bt_")
        assert created["status"] in ("queued", "running", "done")

        job_id = created["job_id"]
        status = client.backtests.get(job_id)
        assert status["job_id"] == job_id

        # Execute explicitly and verify client.backtests.result(job_id)
        from pakhi.api.jobs import execute_job_by_id

        execute_job_by_id(write_engine, job_id)
        result = client.backtests.result(job_id)
        assert "metrics" in result


def test_api_key_hashing():
    raw_key = "pakhi_live_secret_123"
    hashed = hash_key(raw_key)
    assert len(hashed) == 64
    assert hash_key(raw_key) == hashed
