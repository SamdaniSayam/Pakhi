"""WS-3 T3 tests: Backtest job submission, validation, status, and background execution."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
