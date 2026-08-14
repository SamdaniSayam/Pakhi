"""WS-3 T3 tests: Backtest job submission, validation, status, and background execution."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pakhi.api.auth import hash_key
from pakhi.api.jobs import create_backtest_job, execute_job_by_id, process_pending_jobs
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
        yield client, app.state.write_engine


def test_submit_backtest_job_valid(api_client):
    client, _ = api_client
    payload = {
        "instrument": "OJ_FUTURES",
        "window_days": 30,
        "model_version": "GFS-0p50",
        "initial_capital": 100000.0,
    }
    resp = client.post("/v1/backtests", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_id"].startswith("bt_")
    assert data["status"] in ("queued", "running", "done")
    assert "status_url" in data


def test_submit_backtest_job_invalid_window_422(api_client):
    client, _ = api_client
    payload = {"window_days": 500}  # max is 365
    resp = client.post("/v1/backtests", json=payload)
    assert resp.status_code == 422
    err = resp.json()
    assert "error" in err
    assert err["error"]["code"] == "validation_error"


def test_submit_backtest_job_invalid_model_422(api_client):
    client, _ = api_client
    payload = {"model_version": "UNSUPPORTED_MODEL"}
    resp = client.post("/v1/backtests", json=payload)
    assert resp.status_code == 422
    err = resp.json()
    assert err["error"]["code"] == "validation_error"


def test_get_backtest_status_not_found_404(api_client):
    client, _ = api_client
    resp = client.get("/v1/backtests/bt_nonexistent_999")
    assert resp.status_code == 404
    err = resp.json()
    assert err["error"]["code"] == "not_found"


def test_get_backtest_status_and_result_execution(api_client):
    client, write_engine = api_client
    job_info = create_backtest_job(write_engine, {"instrument": "OJ_FUTURES", "window_days": 10})
    job_id = job_info["job_id"]

    # Result before done should be 404
    resp_result_before = client.get(f"/v1/backtests/{job_id}/result")
    assert resp_result_before.status_code == 404

    # Execute job explicitly
    success = execute_job_by_id(write_engine, job_id)
    assert success is True

    # Retrieve status via GET
    resp = client.get(f"/v1/backtests/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "done"
    assert data["result"] is not None
    assert "metrics" in data["result"]

    # Retrieve result artifact via GET /v1/backtests/{id}/result
    resp_result = client.get(f"/v1/backtests/{job_id}/result")
    assert resp_result.status_code == 200
    res_data = resp_result.json()
    assert "metrics" in res_data
    assert "total_trades" in res_data


def test_process_pending_jobs(api_client):
    _, write_engine = api_client
    create_backtest_job(write_engine, {"instrument": "OJ_FUTURES", "window_days": 5})
    create_backtest_job(write_engine, {"instrument": "OJ_FUTURES", "window_days": 5})

    count = process_pending_jobs(write_engine)
    assert count == 2


def _signal_row(offset_days: int) -> dict:
    ts = datetime.now() + timedelta(days=offset_days)
    return {
        "timestamp": ts,
        "instrument": "OJ_FUTURES",
        "action": "LONG",
        "size": 0.5,
        "confidence": 0.8,
        "forecast_cycle_id": ts.strftime("%Y%m%d") + "_12z",
        "publication_ts": ts,
        "archive_source": "noaa-gfs-bdp-pds",
        "model_version": "GFS-0p50",
    }


def test_backtest_replays_stored_signals(tmp_path):
    """The backtest must run on the store's real signal history, not synthetic."""
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    signals = [_signal_row(d) for d in (0, 3, 6, 9)]
    seed_store(f"sqlite:///{read_db}", signals=signals)
    seed_store(f"sqlite:///{write_db}")

    app = create_app(
        Settings(read_db_url=f"sqlite:///{read_db}", write_db_url=f"sqlite:///{write_db}")
    )
    with TestClient(app) as client:
        created = client.post("/v1/backtests", json={"window_days": 60}).json()
        job_id = created["job_id"]

        body = client.get(f"/v1/backtests/{job_id}").json()
        assert body["status"] == "done"
        result = body["result"]
        assert result["signal_source"] == "stored"
        assert result["price_source"] == "synthetic_proxy"
        assert result["total_trades"] > 0, "stored LONG signals must produce trades"


def test_backtest_honest_when_no_signals(tmp_path):
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    app = create_app(
        Settings(read_db_url=f"sqlite:///{read_db}", write_db_url=f"sqlite:///{write_db}")
    )
    with TestClient(app) as client:
        created = client.post("/v1/backtests", json={"window_days": 30}).json()
        execute_job_by_id(app.state.write_engine, created["job_id"])
        result = client.get(f"/v1/backtests/{created['job_id']}/result").json()
        assert result["total_trades"] == 0
        assert "no stored signals" in result["note"]
        assert result["metrics"]["profit_factor"] is None


def test_per_key_queue_cap(tmp_path):
    """Contract per_key_cap: max 1 queued job per key in 300s — not a global cap."""
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    app = create_app(
        Settings(
            read_db_url=f"sqlite:///{read_db}",
            write_db_url=f"sqlite:///{write_db}",
            api_keys=("key_a", "key_b"),
        )
    )
    k1 = f"key_{hash_key('key_a')[:12]}"

    with TestClient(app) as client:
        # key_a already has 1 queued job; key_b has none.
        create_backtest_job(app.state.write_engine, {"window_days": 5}, client_id=k1)

        h_a = {"X-Pakhi-Key": "key_a"}
        h_b = {"X-Pakhi-Key": "key_b"}

        resp_a = client.post("/v1/backtests", json={"window_days": 5}, headers=h_a)
        assert resp_a.status_code == 429
        assert resp_a.json()["error"]["code"] == "rate_limited"

        # A different key is NOT blocked by key_a's queue — proves it is per-key.
        resp_b = client.post("/v1/backtests", json={"window_days": 5}, headers=h_b)
        assert resp_b.status_code == 201
