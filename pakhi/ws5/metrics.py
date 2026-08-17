"""WS-5 metrics — Prometheus registry, multiprocess aggregation (T2).

Multiprocess mode is mandatory above one worker (contract §3.2 / §5.8): every
worker records into a shared ``PROMETHEUS_MULTIPROC_DIR`` memory-mapped
registry, and ``/metrics`` aggregates the files across all workers. An empty or
unset dir with workers > 1 is a **boot error**, never a silent per-worker
registry.

``prometheus_client`` is imported lazily inside ``initialize()`` so
``import pakhi.ws5`` stays dependency- and side-effect-free (T0 contract).

No PII rule (contract): metric labels carry route templates, tier, method,
status — never raw keys, tokens, query strings, or request bodies.
"""

from __future__ import annotations

import os
from typing import Any

from pakhi.ws5.contract import reliability_contract

_registry = None
_metrics: dict[str, Any] = {}
_workers: int = 1
_initialized = False
_scrape_provider = None

DEFAULT_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def metric_families() -> dict:
    return reliability_contract()["metrics"]["families"]


def multiprocess_env() -> str:
    return reliability_contract()["metrics"]["multiprocess"]["env"]


def workers() -> int:
    return _workers


def get_registry() -> Any:
    """The initialized registry; raises if ``initialize()`` was not called."""
    if not _initialized or _registry is None:
        raise RuntimeError("metrics.initialize() has not been called")
    return _registry


def initialize(workers_count: int = 1) -> Any:
    """Build (and cache) the registry for the given worker count.

    ``workers_count > 1`` requires ``PROMETHEUS_MULTIPROC_DIR`` to be set and
    to point at an existing directory; otherwise the boot fails loudly — never
    a silent per-worker registry (contract §5.8).
    """
    global _registry, _metrics, _workers, _initialized, _scrape_provider

    # A fresh registry means a fresh app lifecycle: drop any stale scrape
    # provider from a previous process/test so direct initialize() callers
    # (and production boots before the lifespan wires the real provider) fall
    # back to the helper-set gauge values instead of a dead closure.
    _scrape_provider = None

    _workers = max(1, workers_count)
    env = multiprocess_env()
    mp_dir = os.environ.get(env) or ""

    if _workers > 1 and (not mp_dir or not os.path.isdir(mp_dir)):
        raise ValueError(
            f"{env} must be set and point at an existing directory when "
            f"workers={_workers} — multiprocess mode is mandatory, never a "
            f"silent per-worker registry (reliability contract §3.2)"
        )

    from prometheus_client import CollectorRegistry

    if _workers > 1:
        from prometheus_client import multiprocess

        os.environ[env] = mp_dir
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = CollectorRegistry()

    _registry = registry
    _metrics = _define(registry)
    _initialized = True
    return registry


def _define(registry: Any) -> dict[str, Any]:
    import prometheus_client as pc

    m: dict[str, Any] = {}

    # --- API (contract families["api"]) ---
    m["pakhi_http_requests_total"] = pc.Counter(
        "pakhi_http_requests_total",
        "Total HTTP requests served (route template, never raw paths).",
        ["method", "path", "status"],
        registry=registry,
    )
    m["pakhi_http_request_duration_seconds"] = pc.Histogram(
        "pakhi_http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path"],
        buckets=DEFAULT_HISTOGRAM_BUCKETS,
        registry=registry,
    )
    m["pakhi_http_5xx_total"] = pc.Counter(
        "pakhi_http_5xx_total",
        "HTTP 5xx responses (the only events that count toward downtime).",
        ["method", "path"],
        registry=registry,
    )
    m["pakhi_ratelimit_rejections_total"] = pc.Counter(
        "pakhi_ratelimit_rejections_total",
        "Rate-limit rejections by tier (429 is a client fault, never downtime).",
        ["tier"],
        registry=registry,
    )
    m["pakhi_ws_active"] = pc.Gauge(
        "pakhi_ws_active",
        "Active WebSocket connections.",
        registry=registry,
    )

    # --- Pipeline / cycle (contract families["pipeline"]) ---
    # These gauges are refreshed from the live store at scrape time (see
    # render_metrics -> _apply_scrape), so /metrics reflects reality instead of
    # only whatever /v1/status last wrote. The helper setters still update them
    # as a fallback when no provider is wired (scripts/CLI/tests).
    m["pakhi_cycle_freshness_seconds"] = pc.Gauge(
        "pakhi_cycle_freshness_seconds",
        "Age of the latest published cycle in seconds.",
        registry=registry,
    )
    m["pakhi_cycle_ingestion_lag_seconds"] = pc.Gauge(
        "pakhi_cycle_ingestion_lag_seconds",
        "Ingestion lag of the latest cycle in seconds.",
        registry=registry,
    )
    m["pakhi_cycle_compute_duration_seconds"] = pc.Gauge(
        "pakhi_cycle_compute_duration_seconds",
        "Compute duration of the latest cycle in seconds.",
        registry=registry,
    )
    m["pakhi_cycle_status"] = pc.Gauge(
        "pakhi_cycle_status",
        "Latest cycle status (1 = ok, 0 = failed/stale).",
        registry=registry,
    )
    m["pakhi_cycle_last_ok_timestamp_seconds"] = pc.Gauge(
        "pakhi_cycle_last_ok_timestamp_seconds",
        "Unix timestamp of the last OK cycle.",
        registry=registry,
    )

    # --- Model skill / drift (contract families["skill"]) ---
    m["pakhi_live_bss_vs_baseline"] = pc.Gauge(
        "pakhi_live_bss_vs_baseline",
        "Live BSS minus the locked WS-2 baseline; sustained regression alerts.",
        registry=registry,
    )

    # --- Store / security (contract families["store"]) ---
    m["pakhi_db_pool_in_use"] = pc.Gauge(
        "pakhi_db_pool_in_use",
        "DB pool connections currently in use.",
        registry=registry,
    )
    m["pakhi_db_pool_max"] = pc.Gauge(
        "pakhi_db_pool_max",
        "DB pool max connections.",
        registry=registry,
    )
    m["pakhi_audit_rows_appended_total"] = pc.Counter(
        "pakhi_audit_rows_appended_total",
        "Audit rows appended (multi-worker chain).",
        registry=registry,
    )
    m["pakhi_audit_chain_ok"] = pc.Gauge(
        "pakhi_audit_chain_ok",
        "Audit chain integrity, 1 = verify_chain_in_store passes, 0 = broken.",
        registry=registry,
    )
    m["pakhi_db_key_validator_fail_closed_total"] = pc.Counter(
        "pakhi_db_key_validator_fail_closed_total",
        "DB key validator fail-closed events (WS-4).",
        registry=registry,
    )

    # --- SLO / error budget (contract families["slo"], published by T4) ---
    m["pakhi_error_budget_remaining_fraction"] = pc.Gauge(
        "pakhi_error_budget_remaining_fraction",
        "Fraction of the rolling 30-day error budget still remaining.",
        registry=registry,
    )
    # Boot with a full budget so the PakhiErrorBudgetBurn alert is never a false
    # positive before any traffic has been observed (contract §3 / T4).
    m["pakhi_error_budget_remaining_fraction"].set(1.0)
    return m


# ---------------------------------------------------------------------------
# Scrape-time refresh (fix: gauges that /v1/status used to set but Prometheus
# never scrapes /v1/status — they must be computed live at scrape time).
# ---------------------------------------------------------------------------

# Maps the provider's returned key -> the gauge name it refreshes. Provider keys
# it does not return keep their helper-set (or default) value.
_SCRAPE_REFRESH: tuple[tuple[str, str], ...] = (
    ("audit_chain_ok", "pakhi_audit_chain_ok"),
    ("cycle_status", "pakhi_cycle_status"),
    ("cycle_freshness_seconds", "pakhi_cycle_freshness_seconds"),
    ("cycle_ingestion_lag_seconds", "pakhi_cycle_ingestion_lag_seconds"),
    ("cycle_compute_duration_seconds", "pakhi_cycle_compute_duration_seconds"),
    ("cycle_last_ok_timestamp_seconds", "pakhi_cycle_last_ok_timestamp_seconds"),
    ("live_bss_vs_baseline", "pakhi_live_bss_vs_baseline"),
    ("db_pool_in_use", "pakhi_db_pool_in_use"),
    ("db_pool_max", "pakhi_db_pool_max"),
)


def set_scrape_provider(provider: Any) -> None:
    """Wire a callable that returns live store/state values at scrape time.

    Invoked inside ``render_metrics`` (i.e. on every Prometheus scrape). It must
    return a mapping of provider-key -> value for any of the keys in
    ``_SCRAPE_REFRESH``; missing keys fall back to the helper-set gauge value.
    Pass ``None`` to clear (used by ``initialize`` so stale closures never leak
    across boots).
    """
    global _scrape_provider
    _scrape_provider = provider


def _apply_scrape() -> None:
    """Refresh the deep/security gauges from the wired provider (no-op if none)."""
    if not callable(_scrape_provider):
        return
    try:
        snap = _scrape_provider() or {}
    except Exception:
        return
    for key, name in _SCRAPE_REFRESH:
        if key in snap and name in _metrics:
            _metrics[name].set(float(snap[key]))


# ---------------------------------------------------------------------------
# Recording helpers — all no-ops until initialize() (safe for scripts/CLI).
# ---------------------------------------------------------------------------


def record_http_request(
    method: str, path: str, status: int, duration_seconds: float, fail_closed: bool = False
) -> None:
    counter = _metrics.get("pakhi_http_requests_total")
    if not counter:
        return
    status_s = str(status)
    counter.labels(method=method, path=path, status=status_s).inc()
    _metrics["pakhi_http_request_duration_seconds"].labels(method=method, path=path).observe(
        duration_seconds
    )
    # Only *real* 5xx count toward downtime/SLO. Planned fail-closed 503s
    # (Redis/DB down in multi-worker mode) are recorded separately in the budget
    # ledger and must NOT inflate the 5xx total that the SLO-1 alert keys on.
    if status >= 500 and not (fail_closed and status == 503):
        _metrics["pakhi_http_5xx_total"].labels(method=method, path=path).inc()


def record_ratelimit_rejection(tier: str) -> None:
    metric = _metrics.get("pakhi_ratelimit_rejections_total")
    if not metric:
        return
    metric.labels(tier=tier).inc()


def ws_connected() -> None:
    gauge = _metrics.get("pakhi_ws_active")
    if gauge:
        gauge.inc()


def ws_disconnected() -> None:
    gauge = _metrics.get("pakhi_ws_active")
    if gauge:
        gauge.dec()


def record_cycle_ok(
    freshness_seconds: float, ingestion_lag_seconds: float, compute_duration_seconds: float
) -> None:
    if not _metrics:
        return
    import time

    _metrics["pakhi_cycle_freshness_seconds"].set(freshness_seconds)
    _metrics["pakhi_cycle_ingestion_lag_seconds"].set(ingestion_lag_seconds)
    _metrics["pakhi_cycle_compute_duration_seconds"].set(compute_duration_seconds)
    _metrics["pakhi_cycle_status"].set(1)
    _metrics["pakhi_cycle_last_ok_timestamp_seconds"].set(time.time())


def record_cycle_failed(freshness_seconds: float) -> None:
    if not _metrics:
        return
    _metrics["pakhi_cycle_freshness_seconds"].set(freshness_seconds)
    _metrics["pakhi_cycle_status"].set(0)


def set_skill_drift(value: float) -> None:
    gauge = _metrics.get("pakhi_live_bss_vs_baseline")
    if gauge:
        gauge.set(value)


def record_audit_row_appended() -> None:
    counter = _metrics.get("pakhi_audit_rows_appended_total")
    if counter:
        counter.inc()


def set_audit_chain_ok(ok: bool) -> None:
    gauge = _metrics.get("pakhi_audit_chain_ok")
    if gauge:
        gauge.set(1 if ok else 0)


def record_db_key_validator_fail_closed() -> None:
    counter = _metrics.get("pakhi_db_key_validator_fail_closed_total")
    if counter:
        counter.inc()


def set_db_pool(in_use: int, max_conns: int) -> None:
    if _metrics:
        _metrics["pakhi_db_pool_in_use"].set(in_use)
        _metrics["pakhi_db_pool_max"].set(max_conns)


def set_error_budget_remaining(fraction: float) -> None:
    gauge = _metrics.get("pakhi_error_budget_remaining_fraction")
    if gauge:
        gauge.set(fraction)


def render_metrics() -> tuple[str, str]:
    """Body + content-type for GET /metrics (aggregates workers in mp mode)."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    # Refresh the deep/security gauges from the live store at scrape time so
    # /metrics reflects reality (audit chain, latest cycle, DB pool) rather than
    # only whatever /v1/status last wrote — Prometheus scrapes /metrics, not
    # /v1/status.
    _apply_scrape()
    return generate_latest(get_registry()).decode("utf-8"), CONTENT_TYPE_LATEST
