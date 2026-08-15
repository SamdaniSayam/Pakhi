"""WS-5 T2 — Prometheus /metrics + mandatory multiprocess mode.

Proves the T2 exit criteria:

- ``GET /metrics`` returns the exposition with the locked families and labels
  (request latency histogram, cycle freshness gauge, ratelimit rejections by
  tier) — route **templates** only, never raw paths, no PII/keys/tokens.
- A two-process aggregation test proves counters **sum** across workers in
  multiprocess mode (a scrape never shows a single worker's partial count).
- ``workers > 1`` without a valid ``PROMETHEUS_MULTIPROC_DIR`` is a boot error
  (both ``metrics.initialize`` and ``create_app``), never a silent per-worker
  registry.
- WS-3/WS-4 suites stay green (run separately; the endpoint here proves the
  additive behavior).
"""

from __future__ import annotations

import multiprocessing
import os

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws5 import metrics as ws5_metrics

ADMIN_KEY = "test-admin-key-123"
JWT_SECRET = "test-jwt-secret-0123456789abcdef"


# ---------------------------------------------------------------------------
# Multiprocess aggregation — two real child processes share one mmap dir
# ---------------------------------------------------------------------------


def _mp_writer(mp_dir: str, count: int) -> None:
    """Child worker: records ``count`` requests into the shared mmap dir."""
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = mp_dir
    from pakhi.ws5 import metrics

    metrics.initialize(workers_count=2)
    for _ in range(count):
        metrics.record_http_request("GET", "/v1/x", 200, 0.01)


def test_multiprocess_counters_sum_across_workers(tmp_path) -> None:
    mp_dir = str(tmp_path / "mp")
    os.makedirs(mp_dir, exist_ok=True)
    try:
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = mp_dir
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_mp_writer, args=(mp_dir, n)) for n in (5, 3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(30)
        assert all(p.exitcode == 0 for p in procs)

        ws5_metrics.initialize(workers_count=2)
        body, _ = ws5_metrics.render_metrics()
        # Both workers' counts summed: 5 + 3 == 8, never a partial worker count.
        assert 'pakhi_http_requests_total{method="GET",path="/v1/x",status="200"} 8.0' in body
    finally:
        os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


# ---------------------------------------------------------------------------
# Multiprocess boot error (never a silent per-worker registry)
# ---------------------------------------------------------------------------


def test_workers_gt_1_without_mp_dir_is_boot_error() -> None:
    os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
    with pytest.raises(ValueError, match="PROMETHEUS_MULTIPROC_DIR"):
        ws5_metrics.initialize(workers_count=2)


def test_workers_gt_1_with_bogus_mp_dir_is_boot_error(tmp_path) -> None:
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(tmp_path / "does-not-exist")
    try:
        with pytest.raises(ValueError, match="existing directory"):
            ws5_metrics.initialize(workers_count=2)
    finally:
        os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)


def test_create_app_workers_gt_1_without_mp_dir_boot_error() -> None:
    os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
    settings = Settings(
        read_db_url="sqlite:////tmp/x.db",
        write_db_url="sqlite:////tmp/x.db",
        workers=2,
        redis_url="redis://localhost:6379/0",
    )
    with pytest.raises(ValueError, match="PROMETHEUS_MULTIPROC_DIR"):
        create_app(settings)


# ---------------------------------------------------------------------------
# /metrics endpoint: locked families, template labels, no PII
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> TestClient:
    db = f"sqlite:///{tmp_path / 'store.db'}"
    settings = Settings(read_db_url=db, write_db_url=db, api_keys=(ADMIN_KEY,))
    return create_app(settings)


def test_metrics_endpoint_has_locked_families(app) -> None:
    with TestClient(app) as client:
        client.get("/v1/instruments", headers={"X-Pakhi-Key": ADMIN_KEY})
        client.get("/v1/signals/AAPL", headers={"X-Pakhi-Key": ADMIN_KEY})
        client.get("/v1/signals/IBM", headers={"X-Pakhi-Key": ADMIN_KEY})

        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text

        for name in (
            "pakhi_http_requests_total",
            "pakhi_http_request_duration_seconds_bucket",
            "pakhi_http_5xx_total",
            "pakhi_ratelimit_rejections_total",
            "pakhi_ws_active",
            "pakhi_cycle_freshness_seconds",
            "pakhi_cycle_ingestion_lag_seconds",
            "pakhi_cycle_compute_duration_seconds",
            "pakhi_cycle_status",
            "pakhi_cycle_last_ok_timestamp_seconds",
            "pakhi_live_bss_vs_baseline",
            "pakhi_db_pool_in_use",
            "pakhi_db_pool_max",
            "pakhi_audit_rows_appended_total",
            "pakhi_audit_chain_ok",
            "pakhi_db_key_validator_fail_closed_total",
        ):
            assert name in body, f"metric {name} missing from /metrics"

        # Label is the route TEMPLATE, not the raw path with user values.
        assert 'path="/v1/signals/{instrument}"' in body
        # No PII / keys / raw values anywhere (contract no-PII rule).
        assert "AAPL" not in body
        assert "IBM" not in body
        assert "test-admin-key-123" not in body
        assert "X-Pakhi-Key" not in body
        assert "?" not in body  # no query strings
        assert "/v1/signals/AAPL" not in body


def test_metrics_records_edge_status_including_404(app) -> None:
    with TestClient(app) as client:
        client.get("/v1/instruments", headers={"X-Pakhi-Key": ADMIN_KEY})
        body = client.get("/metrics").text
        assert 'status="404"' in body
        assert 'method="GET"' in body


def test_ratelimit_rejection_labeled_by_tier(tmp_path) -> None:
    db = f"sqlite:///{tmp_path / 'store.db'}"
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        for _ in range(60):
            assert client.get("/v1/instruments").status_code in (200, 404)
        rejected = client.get("/v1/instruments")
        assert rejected.status_code == 429
        body = client.get("/metrics").text
        assert 'pakhi_ratelimit_rejections_total{tier="anonymous"} 1.0' in body


def test_5xx_family_counts_error_status(tmp_path) -> None:
    # A bogus DB URL makes status/deep paths fail closed -> 503 (5xx).
    app = create_app(
        Settings(
            read_db_url="sqlite:////nonexistent_dir_xyz/store.db",
            write_db_url="sqlite:////nonexistent_dir_xyz/store.db",
        )
    )
    with TestClient(app) as client:
        assert client.get("/v1/status").status_code == 503
        body = client.get("/metrics").text
        assert 'pakhi_http_5xx_total{method="GET",path="/v1/status"} 1.0' in body


def test_cycle_and_audit_helpers_publish_gauges() -> None:
    ws5_metrics.initialize(workers_count=1)
    ws5_metrics.record_cycle_ok(12.0, 3.0, 1.5)
    ws5_metrics.set_audit_chain_ok(True)
    ws5_metrics.set_skill_drift(0.012)
    body, _ = ws5_metrics.render_metrics()
    assert "pakhi_cycle_freshness_seconds 12.0" in body
    assert "pakhi_cycle_status 1.0" in body
    assert "pakhi_audit_chain_ok 1.0" in body
    assert "pakhi_live_bss_vs_baseline 0.012" in body
