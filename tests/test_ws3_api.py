"""WS-3 T1: FastAPI app — health/status, error envelope, CORS, JSON logging,
request ids, and the sync-``def`` (no async DB) guard.

Tests run against a seeded sqlite store (both engines point at the same file —
Postgres role separation is covered by the T1 CI permission test, not here).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from pakhi.api.errors import request_validation_handler
from pakhi.api.logcfg import JsonFormatter, request_id_var
from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws2.db import ForecastCycle, Metric, init_db


def _seed(db_url: str, cycles: list[tuple[str, datetime]]) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    init_db(engine)
    with engine.begin() as conn:
        for cycle_id, pub in cycles:
            conn.execute(
                ForecastCycle.__table__.insert().values(
                    id=cycle_id,
                    publication_ts=pub,
                    archive_source="noaa-gfs-bdp-pds",
                    model_version="GFS-0p50",
                )
            )
    engine.dispose()


def _seed_metrics(db_url: str, name: str, ts: datetime) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(
            Metric.__table__.insert().values(
                timestamp=ts,
                name=name,
                value=1.0,
                details=None,
            )
        )
    engine.dispose()


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


@pytest.fixture
def settings_factory(tmp_db):
    def make(*, cors: tuple[str, ...] = (), db_url: str | None = None) -> Settings:
        url = db_url or tmp_db
        return Settings(read_db_url=url, write_db_url=url, cors_origins=cors)

    return make


def test_health_ok(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["X-Pakhi-Version"] == "1.1"


def test_status_latest_cycle(settings_factory, tmp_db):
    # Fixed timestamps: a "now-relative" cycle id/date pair is a time-bomb that
    # breaks the day after the nominal date (2026-08-13).
    pub = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    stale = pub - timedelta(days=3)
    _seed(tmp_db, [("20260810_12z", stale), ("20260813_12z", pub)])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_ok"] is True
    assert body["latest_cycle_id"] == "20260813_12z"
    assert body["publication_ts"] == "2026-08-13T12:00:00+00:00"
    expected = (datetime.now(timezone.utc) - pub).total_seconds()
    assert body["staleness_seconds"] == pytest.approx(expected, abs=2.0)
    # No worker.last_run metric yet -> documented proxy: latest cycle publication.
    assert body["worker_last_run"] == body["publication_ts"]
    assert "X-Pakhi-Staleness" not in resp.headers


def test_status_worker_last_run_prefers_metrics(settings_factory, tmp_db):
    pub = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    _seed(tmp_db, [("20260813_12z", pub)])
    worker_ts = pub + timedelta(minutes=5)
    _seed_metrics(tmp_db, "worker.last_run", worker_ts)
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["worker_last_run"] == "2026-08-13T12:05:00+00:00"
    assert body["latest_cycle_id"] == "20260813_12z"


def test_status_honest_stale_header(settings_factory, tmp_db):
    old = datetime.now(timezone.utc) - timedelta(days=3)
    _seed(tmp_db, [("20260810_12z", old)])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    assert "X-Pakhi-Staleness" in resp.headers
    assert body_is_stale(resp.json())


def test_status_empty_store_not_fresh(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_ok"] is True
    assert body["latest_cycle_id"] is None
    assert body["publication_ts"] is None
    assert body["staleness_seconds"] is None
    assert "X-Pakhi-Staleness" not in resp.headers


def test_status_db_unreachable_503(settings_factory):
    app = create_app(settings_factory(db_url="sqlite:////nonexistent_dir_xyz/store.db"))
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "db_unavailable"


def test_404_uses_locked_envelope(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Not Found"
    assert resp.headers["X-Pakhi-Version"] == "1.1"


def test_422_uses_locked_envelope_in_stack(settings_factory, tmp_db):
    """Real FastAPI validation through the stack — a query param is validated by
    the framework, and the 422 must still come back in the locked envelope."""
    _seed(tmp_db, [])

    val = APIRouter()

    @val.get("/val")
    def val_endpoint(limit: int):
        return {"limit": limit}

    app = create_app(settings_factory())
    app.include_router(val)
    with TestClient(app) as client:
        resp = client.get("/val", params={"limit": "not-an-int"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert resp.headers["X-Pakhi-Version"] == "1.1"


def test_422_validation_handler_direct():
    exc = RequestValidationError(
        [{"loc": ["query", "limit"], "msg": "field required", "type": "missing"}]
    )
    resp = asyncio.run(request_validation_handler(None, exc))
    assert resp.status_code == 422
    body = json.loads(resp.body)
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["query", "limit"]


def test_unhandled_exception_500_envelope(settings_factory, tmp_db):
    _seed(tmp_db, [])

    boom = APIRouter()

    @boom.get("/boom")
    def boom_endpoint():
        raise ValueError("boom")

    app = create_app(settings_factory())
    app.include_router(boom)
    # raise_server_exceptions=False: ServerErrorMiddleware always re-raises after
    # sending the 500 handler's response (so servers can log it); the client
    # still receives the envelope. This is the standard way to test 500 handlers.
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom", headers={"X-Request-ID": "rid-500"})
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"error": {"code": "internal_error", "message": "internal server error"}}
    assert "boom" not in resp.text, "internal exception detail must never leak"
    # The 500 handler runs inside ServerErrorMiddleware (outside all user
    # middleware), so it must stamp the contract headers itself.
    assert resp.headers["X-Pakhi-Version"] == "1.1"
    assert resp.headers["X-Request-ID"] == "rid-500"


def test_cors_preflight(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory(cors=("https://example.com",)))
    with TestClient(app) as client:
        resp = client.options(
            "/v1/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "https://example.com"
    # RequestContextMiddleware sits outside CORS, so even the preflight
    # short-circuit carries the version header (contract: every response).
    assert resp.headers["X-Pakhi-Version"] == "1.1"


def test_cors_not_configured_no_header(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/health", headers={"Origin": "https://evil.example.com"})
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_request_id_echo_and_generated(settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with TestClient(app) as client:
        resp = client.get("/v1/health", headers={"X-Request-ID": "abc123"})
        assert resp.headers["X-Request-ID"] == "abc123"
        resp2 = client.get("/v1/health")
        assert resp2.headers["X-Request-ID"]
        assert resp2.headers["X-Request-ID"] != "abc123"


def test_json_formatter_emits_request_id_and_fields():
    record = logging.LogRecord(
        name="pakhi.api.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET /v1/health -> 200 12ms",
        args=(),
        exc_info=None,
    )
    record.json_fields = {"method": "GET", "path": "/v1/health", "status": 200}
    token = request_id_var.set("rid-1")
    try:
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)
    parsed = json.loads(line)
    assert parsed["request_id"] == "rid-1"
    assert parsed["method"] == "GET"
    assert parsed["status"] == 200
    assert parsed["message"].startswith("GET /v1/health")


def test_json_formatter_prefers_record_request_id_over_contextvar():
    """Regression guard (P1): the access line must carry the request id even
    when the contextvar is already reset (dispatch resets it before logging)."""
    record = logging.LogRecord(
        name="pakhi.api.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET /v1/health -> 200 12ms",
        args=(),
        exc_info=None,
    )
    record.request_id = "rid-record"
    record.json_fields = {"method": "GET", "path": "/v1/health", "status": 200}
    token = request_id_var.set("rid-contextvar")
    try:
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)
    parsed = json.loads(line)
    assert parsed["request_id"] == "rid-record"


def test_access_log_end_to_end_carries_request_id(caplog, settings_factory, tmp_db):
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    with caplog.at_level(logging.INFO, logger="pakhi.api.access"), TestClient(app) as client:
        client.get("/v1/health", headers={"X-Request-ID": "rid-e2e"})
    records = [r for r in caplog.records if r.name == "pakhi.api.access"]
    assert records, "an access line must be emitted"
    assert records[-1].request_id == "rid-e2e"
    assert records[-1].json_fields["status"] == 200


def test_no_async_data_handlers(settings_factory, tmp_db):
    """Guard test (T1 exit): only WebSocket endpoints may be async def.  Blocking
    DB work must run in the anyio threadpool, never on the event loop.  Only
    ``APIRoute`` (has ``methods``) endpoints are data handlers — framework
    plumbing (openapi.json, /docs, /redoc) is excluded by construction."""
    _seed(tmp_db, [])
    app = create_app(settings_factory())
    async_routes = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        path = getattr(route, "path", None)
        # API data routes are locked under /v1 (contract versioning policy);
        # framework plumbing (/docs, /openapi.json, /redoc) is excluded.
        if endpoint is None or not hasattr(route, "methods") or not str(path).startswith("/v1"):
            continue
        if getattr(route, "protocol", None) == "websocket":
            continue
        if asyncio.iscoroutinefunction(endpoint):
            async_routes.append(getattr(route, "path", repr(route)))
    assert async_routes == [], f"data handlers must be sync def, found async: {async_routes}"


def body_is_stale(body: dict) -> bool:
    return body["staleness_seconds"] is not None and body["staleness_seconds"] > 36 * 3600
