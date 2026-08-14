"""WS-3 T4 tests: WebSocket live stream connection, broadcast fan-out, ping/pong, and disconnect handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pakhi.api.broadcast import broadcaster
from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from tests.ws3_fixtures import seed_store


@pytest.fixture
def api_client(tmp_path):
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    settings = Settings(
        read_db_url=f"sqlite:///{read_db}",
        write_db_url=f"sqlite:///{write_db}",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_websocket_stream_connect_and_broadcast(api_client):
    client = api_client
    payload = {
        "type": "signals.batch",
        "version": "1",
        "cycle_id": "20260813_12z",
        "publication_ts": "2026-08-13T12:00:00+00:00",
        "signals": [
            {
                "instrument": "OJ_FUTURES",
                "action": "LONG",
                "size": 0.5,
                "confidence": 0.8,
                "timestamp": "2026-08-13T12:00:00+00:00",
                "forecast_cycle_id": "20260813_12z",
                "publication_ts": "2026-08-13T12:00:00+00:00",
                "archive_source": "noaa_gfs",
                "model_version": "GFS-0p50",
            }
        ],
    }

    with client.websocket_connect("/v1/stream/signals") as websocket:
        assert broadcaster.active_count == 1
        # Broadcast batch to connected clients
        import anyio

        sent = anyio.run(broadcaster.broadcast, payload)
        assert sent == 1

        data = websocket.receive_json()
        assert data["type"] == "signals.batch"
        assert data["cycle_id"] == "20260813_12z"
        assert len(data["signals"]) == 1
        assert data["signals"][0]["instrument"] == "OJ_FUTURES"

    assert broadcaster.active_count == 0


def test_websocket_ping_pong(api_client):
    client = api_client
    with client.websocket_connect("/v1/stream/signals") as websocket:
        websocket.send_text("ping")
        resp = websocket.receive_text()
        assert resp == "pong"


def test_websocket_multiple_clients_fanout(api_client):
    client = api_client
    payload = {"type": "signals.batch", "version": "1", "cycle_id": "20260813_18z", "signals": []}

    with (
        client.websocket_connect("/v1/stream/signals") as ws1,
        client.websocket_connect("/v1/stream/signals") as ws2,
    ):
        assert broadcaster.active_count == 2
        import anyio

        sent = anyio.run(broadcaster.broadcast, payload)
        assert sent == 2

        msg1 = ws1.receive_json()
        msg2 = ws2.receive_json()
        assert msg1["cycle_id"] == "20260813_18z"
        assert msg2["cycle_id"] == "20260813_18z"

    assert broadcaster.active_count == 0


def test_websocket_rejects_invalid_or_missing_key(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    app = create_app(
        Settings(
            read_db_url=f"sqlite:///{read_db}",
            write_db_url=f"sqlite:///{write_db}",
            api_keys=("good_key",),
        )
    )
    with TestClient(app) as client:
        assert app.state.require_auth is True

        # Wrong key -> rejected before accept (close code 1008).
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/v1/stream/signals", headers={"X-Pakhi-Key": "bad_key"}),
        ):
            pass
        assert broadcaster.active_count == 0

        # Missing key -> rejected.
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/v1/stream/signals"):
            pass
        assert broadcaster.active_count == 0

        # Valid key -> connects.
        with client.websocket_connect("/v1/stream/signals", headers={"X-Pakhi-Key": "good_key"}):
            assert broadcaster.active_count == 1
    assert broadcaster.active_count == 0
