"""WS-5 T4 — /v1/health liveness split + /v1/status deep page + SLO accounting.

Exit criteria (blueprint §4 / contract §6):
- ``/v1/health`` is DB-free probe liveness: no auth, no rate limit, stays 200
  through downstream outages.
- ``/v1/status`` is the deep page: rate-limited, 10 s TTL cache, JSON + HTML
  views, reports db, redis, pipeline freshness (DEGRADED past one cycle),
  error-budget remaining, audit chain, worker count — the same numbers the WS-5
  alert rules use.
- SLO-1 accounting feeds ``pakhi_error_budget_remaining_fraction``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws5.budget import budget
from pakhi.ws5.contract import cycle_period_seconds
from tests.test_ws3_api import _seed

ADMIN_KEY = "test-admin-key-123"


def _recent_pub() -> datetime:
    # 30 min ago -> staleness far below one cycle period (no time-bomb dates).
    return datetime.now(timezone.utc) - timedelta(minutes=30)


def _app(tmp_path, **settings_kwargs) -> Settings:
    db = f"sqlite:///{tmp_path / 'store.db'}"
    return Settings(read_db_url=db, write_db_url=db, **settings_kwargs)


def test_health_is_db_free_liveness(tmp_path):
    # Bogus DB: liveness must stay 200 (probes never see downstream state).
    app = create_app(
        Settings(
            read_db_url="sqlite:////nonexistent_dir_xyz/x.db",
            write_db_url="sqlite:////nonexistent_dir_xyz/x.db",
        )
    )
    with TestClient(app) as client:
        resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "X-RateLimit-Limit" not in resp.headers


def test_health_never_rate_limited_or_authed(tmp_path):
    settings = _app(tmp_path, api_keys=(ADMIN_KEY,))
    _seed(f"sqlite:///{tmp_path / 'store.db'}", [])
    app = create_app(settings)
    with TestClient(app) as client:
        # No key, and hammered past any bucket: still 200 liveness.
        for _ in range(70):
            resp = client.get("/v1/health")
            assert resp.status_code == 200
        assert "X-RateLimit-Limit" not in resp.headers


def test_status_deep_page_components(tmp_path):
    pub = _recent_pub()
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260813_12z", pub)])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    # WS-3 locked keys preserved.
    assert body["db_ok"] is True
    assert body["latest_cycle_id"] == "20260813_12z"
    assert body["publication_ts"] == pub.isoformat()
    # WS-5 deep-page components (contract §6).
    assert body["pipeline"]["state"] == "OK"
    assert body["pipeline"]["cycle_period_seconds"] == cycle_period_seconds()
    assert body["redis"] is None  # single-worker posture, no shared store
    assert body["audit_chain"]["ok"] is True
    assert body["workers"] == 1
    assert body["error_budget"]["api_availability_target"] == 0.999
    assert body["error_budget"]["budget_minutes"] == 43.2
    assert 0.0 <= body["error_budget"]["remaining_fraction"] <= 1.0
    assert body["cache"]["ttl_seconds"] == 10
    assert body["status"] == "OK"


def test_status_degraded_past_one_cycle(tmp_path):
    # A cycle older than the SLO-3 limit (cycle_period_seconds) flips the
    # pipeline to DEGRADED (contract §2); 3 days old also trips the 36h
    # X-Pakhi-Staleness header (WS-3 locked behavior).
    old = datetime.now(timezone.utc) - timedelta(days=3)
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260810_12z", old)])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline"]["state"] == "DEGRADED"
    assert body["status"] == "DEGRADED"
    assert "X-Pakhi-Staleness" in resp.headers


def test_status_html_view(tmp_path):
    pub = _recent_pub()
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260813_12z", pub)])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        resp = client.get("/v1/status", params={"format": "html"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Pakhi" in resp.text
        assert "20260813_12z" in resp.text
        # Accept: text/html also selects the HTML view.
        resp2 = client.get("/v1/status", headers={"Accept": "text/html"})
        assert resp2.headers["content-type"].startswith("text/html")


def test_status_cache_ttl_and_expiry(tmp_path):
    pub = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260813_12z", pub)])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        first = client.get("/v1/status").json()
        assert first["latest_cycle_id"] == "20260813_12z"
        # New cycle lands, but the 10 s TTL serves the cached body.
        _seed(db, [("20260814_12z", pub + timedelta(days=1))])
        cached = client.get("/v1/status").json()
        assert cached["latest_cycle_id"] == "20260813_12z"
        # Expire the cache -> fresh deep read sees the new cycle.
        app.state.status_cache["ts"] -= 11
        fresh = client.get("/v1/status").json()
        assert fresh["latest_cycle_id"] == "20260814_12z"


def test_status_cache_is_per_app(tmp_path):
    db_a = f"sqlite:///{tmp_path / 'a.db'}"
    db_b = f"sqlite:///{tmp_path / 'b.db'}"
    _seed(db_a, [("20260813_12z", datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc))])
    _seed(db_b, [("20260812_12z", datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc))])
    app_a = create_app(Settings(read_db_url=db_a, write_db_url=db_a))
    app_b = create_app(Settings(read_db_url=db_b, write_db_url=db_b))
    with TestClient(app_a) as ca, TestClient(app_b) as cb:
        assert ca.get("/v1/status").json()["latest_cycle_id"] == "20260813_12z"
        assert cb.get("/v1/status").json()["latest_cycle_id"] == "20260812_12z"


@pytest.fixture
def redis_tcp_server():
    import threading

    server = fakeredis.TcpFakeServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"redis://127.0.0.1:{server.server_address[1]}/0"
    server.shutdown()
    thread.join(timeout=2)


def test_status_redis_up_reported(tmp_path, redis_tcp_server):
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260813_12z", _recent_pub())])
    settings = Settings(
        read_db_url=db,
        write_db_url=db,
        redis_url=redis_tcp_server,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        body = client.get("/v1/status").json()
    assert body["redis"]["configured"] is True
    assert body["redis"]["ok"] is True
    assert body["redis"]["fail_closed_http"] == 503
    assert body["status"] == "OK"


def test_status_503_db_unavailable_not_cached(tmp_path):
    app = create_app(
        Settings(
            read_db_url="sqlite:////nonexistent_dir_xyz/x.db",
            write_db_url="sqlite:////nonexistent_dir_xyz/x.db",
        )
    )
    with TestClient(app) as client:
        r1 = client.get("/v1/status")
        assert r1.status_code == 503
        assert r1.json()["error"]["code"] == "db_unavailable"
        # Second request re-checks liveness (no cached 503 poisoning).
        r2 = client.get("/v1/status")
        assert r2.status_code == 503


def test_error_budget_ledger_counts_real_5xx(tmp_path):
    # Real (non-fail-closed) 5xx are ledgered and consume the budget.
    budget.reset()
    app = create_app(
        Settings(
            read_db_url="sqlite:////nonexistent_dir_xyz/x.db",
            write_db_url="sqlite:////nonexistent_dir_xyz/x.db",
        )
    )
    with TestClient(app) as client:
        assert client.get("/v1/status").status_code == 503
    snap = budget.snapshot()
    assert snap["real_5xx"] >= 1
    assert snap["fail_closed_503"] == 0
    assert snap["remaining_fraction"] < 1.0


def test_error_budget_gauge_published(tmp_path):
    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [("20260813_12z", datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc))])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        client.get("/v1/status")
        body = client.get("/metrics").text
    assert "pakhi_error_budget_remaining_fraction" in body


def test_fail_closed_503_tagged_not_real_downtime(tmp_path):
    # A fail-closed 503 (Redis down, multi-worker) is ledgered separately and
    # never consumes the error budget (contract §2 — recorded, not hidden).
    budget.reset()
    settings = Settings(
        read_db_url="sqlite:////nonexistent_dir_xyz/x.db",
        write_db_url="sqlite:////nonexistent_dir_xyz/x.db",
        redis_url="redis://127.0.0.1:1/0",
        jwt_secret="test-jwt-secret-0123456789abcdef",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # ws4 enabled -> per-tier Redis buckets -> down store fails closed 503.
        assert client.get("/v1/status").status_code == 503
    snap = budget.snapshot()
    assert snap["fail_closed_503"] >= 1
    assert snap["real_5xx"] == 0
    assert snap["remaining_fraction"] == 1.0
