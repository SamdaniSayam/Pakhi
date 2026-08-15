"""WS-3 v1 meta routes — /v1/health (liveness) and /v1/status (deep page).

WS-5 T4 (contract §6): ``/v1/health`` is liveness only — DB-free, no auth, no
rate limiting — the Docker/K8s probe target. All deep readiness/freshness lives
on ``/v1/status``: rate-limited, cached (``status.cache_ttl_seconds`` = 10 s),
JSON + HTML views, and it reports the same components the WS-5 alert rules
consume (db, redis, pipeline freshness, error-budget remaining, audit chain,
worker count) from the contract twin as the single source of truth.
"""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import desc, func, select

from pakhi.api.errors import error_body
from pakhi.api.settings import VERSION
from pakhi.ws2.db import ForecastCycle, Metric
from pakhi.ws5 import metrics as ws5_metrics
from pakhi.ws5.budget import budget
from pakhi.ws5.contract import (
    api_availability_target,
    cycle_period_seconds,
    error_budget_minutes,
    redis_fail_closed_http,
    status_cache_ttl_seconds,
)

logger = logging.getLogger("pakhi.api.meta")

router = APIRouter(prefix="/v1", tags=["meta"])

# A cycle is "stale" once it is ~1.5x the daily cycle cadence old.
STALE_AFTER_SECONDS = 36 * 3600


def _utc(dt):
    """Coerce a DB datetime to aware UTC (sqlite returns naive datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/health")
def health():
    """Liveness only — the process is up and serving (Docker/K8s probes). DB-
    free, no auth, no rate limit, no Redis dependency: stays 200 through any
    downstream outage (deep state lives on /v1/status)."""
    return {"status": "ok"}


def _redis_component(request: Request) -> dict | None:
    """Multi-worker shared-store state (None when not configured)."""
    redis_url = getattr(request.app.state, "redis_url", None)
    if not redis_url:
        return None
    client = getattr(request.app.state, "redis_client", None)
    ok = False
    try:
        ok = bool(client and client.ping())
    except Exception:
        ok = False
    return {
        "configured": True,
        "ok": ok,
        "fail_closed_http": redis_fail_closed_http(),
    }


def _audit_component(request: Request) -> dict:
    """Chain integrity via store replay, throttled by the status cache. Tolerant
    of stores without the audit table (reports ``unverified`` — never a 503)."""
    ok = None
    error = None
    try:
        from pakhi.ws4.audit_events import verify_chain_in_store

        ok, _first_bad = verify_chain_in_store(request.app.state.write_engine)
    except Exception:
        error = "audit store not initialized"
        logger.info("audit component check: %s", error)
    if ok is not None:
        ws5_metrics.set_audit_chain_ok(ok)
    return {
        "ok": ok,
        "error": error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _pipeline_state(staleness_seconds: float | None) -> str:
    if staleness_seconds is None:
        return "UNKNOWN"  # no published cycle yet — honest, not "fresh"
    return "DEGRADED" if staleness_seconds >= cycle_period_seconds() else "OK"


def _deep_status(request: Request) -> dict:
    """Compute the deep status body (uncached). Caller handles DB failure -> 503."""
    engine = request.app.state.read_engine
    with engine.connect() as conn:
        latest = conn.execute(
            select(ForecastCycle.id, ForecastCycle.publication_ts)
            .order_by(desc(ForecastCycle.publication_ts))
            .limit(1)
        ).first()
        worker = conn.execute(
            select(func.max(Metric.timestamp)).where(Metric.name == "worker.last_run")
        ).scalar()

    pub = _utc(latest.publication_ts) if latest else None
    staleness = (datetime.now(timezone.utc) - pub).total_seconds() if pub else None
    # worker_last_run: prefer the orchestrator's heartbeat metric when the store
    # has one; until WS-2/T4 writes it, fall back to the latest cycle
    # publication timestamp (documented proxy — a fresh cycle implies a run).
    worker_run = _utc(worker) if worker else pub

    budget_snap = budget.snapshot()
    ws5_metrics.set_error_budget_remaining(budget_snap["remaining_fraction"])

    redis = _redis_component(request)
    audit = _audit_component(request)
    pipeline_state = _pipeline_state(staleness)
    degraded = bool(
        pipeline_state == "DEGRADED"
        or (redis is not None and not redis["ok"])
        or audit.get("ok") is False
    )

    # WS-6 T4: S1-class incidents surface on the status page — read straight
    # from the audit chain so the feed is the ledger of truth, not a config.
    from pakhi.ws6 import support as ws6_support

    incidents = []
    try:
        incidents = ws6_support.recent_incidents(engine)
    except Exception:
        incidents = []

    body = {
        "db_ok": True,
        "latest_cycle_id": latest.id if latest else None,
        "publication_ts": pub.isoformat() if pub else None,
        "staleness_seconds": round(staleness, 1) if staleness is not None else None,
        "worker_last_run": worker_run.isoformat() if worker_run else None,
        # WS-5 T4 deep-page additions (contract §6 components).
        "version": VERSION,
        "status": "DEGRADED" if degraded else "OK",
        "workers": getattr(request.app.state, "workers", 1),
        "pipeline": {
            "state": pipeline_state,
            "cycle_period_seconds": cycle_period_seconds(),
            "staleness_limit_seconds": cycle_period_seconds(),
        },
        "redis": redis,
        "audit_chain": audit,
        "error_budget": {
            "api_availability_target": api_availability_target(),
            "budget_minutes": error_budget_minutes(),
            "remaining_fraction": budget_snap["remaining_fraction"],
            "observed_requests": budget_snap["observed_requests"],
            "real_5xx": budget_snap["real_5xx"],
            "fail_closed_503": budget_snap["fail_closed_503"],
            "model": "rate-based proxy, in-process (honest per-worker view)",
        },
        "cache": {"ttl_seconds": status_cache_ttl_seconds()},
        "incidents": incidents,
    }
    return body


def _status_html(body: dict) -> str:
    budget = body["error_budget"]
    redis = body["redis"]
    audit = body["audit_chain"]
    rows = []

    def row(label: str, value: str) -> None:
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>")

    row("API status", body["status"])
    row("Version", body["version"])
    row("DB", "ok" if body["db_ok"] else "down")
    row("Workers", body["workers"])
    row("Latest cycle", body["latest_cycle_id"] or "none")
    row("Publication", body["publication_ts"] or "never")
    row("Staleness (s)", body["staleness_seconds"])
    row("Pipeline", body["pipeline"]["state"])
    row(
        "Redis",
        "down (fail-closed)"
        if redis and not redis["ok"]
        else ("up" if redis else "not configured"),
    )
    row("Audit chain", "ok" if audit["ok"] else (audit["error"] or "broken"))
    row("S1 incidents", str(len(body.get("incidents", []))))
    row("Error budget remaining", f"{budget['remaining_fraction'] * 100:.2f}%")
    row("Error budget (minutes)", budget["budget_minutes"])
    row("Observed requests", budget["observed_requests"])
    row("Real 5xx", budget["real_5xx"])
    row("Fail-closed 503", budget["fail_closed_503"])
    row("Cache TTL (s)", body["cache"]["ttl_seconds"])

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Pakhi status</title>
<style>body{{font-family:ui-monospace,Menlo,Consolas,monospace;margin:2rem;}}
table{{border-collapse:collapse}}td{{border:1px solid #ccc;padding:.35rem .6rem}}
td:first-child{{font-weight:600;color:#444}}</style></head>
<body><h1>Pakhi — {html.escape(body["status"])}</h1>
<table>{"".join(rows)}</table></body></html>"""


@router.get("/status")
def status(
    request: Request,
    response_format: str | None = Query(default=None, pattern="^(json|html)$", alias="format"),
):
    """Readiness + data freshness (deep page, contract §6).

    Rate-limited and cached for ``status.cache_ttl_seconds`` (10 s). JSON
    (default) or HTML via ``?format=html`` / ``Accept: text/html``. The
    never-empty / never-silent-drop rule means a missing recent cycle is a
    visible *stale* state (``X-Pakhi-Staleness`` header) — never a fabricated
    fresh value. DB unreachable -> 503 ``db_unavailable`` (not ready).
    """
    engine = request.app.state.read_engine
    try:
        with engine.connect() as conn:
            _ = conn.execute(select(1)).first()
    except Exception as exc:
        logger.exception("status db check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content=error_body("db_unavailable", "database unreachable"),
        )

    cache = request.app.state.status_cache
    ttl = status_cache_ttl_seconds()
    now = time.monotonic()
    if cache["data"] is None or now - cache["ts"] >= ttl:
        cache["data"] = _deep_status(request)
        cache["ts"] = now

    body = cache["data"]
    staleness = body["staleness_seconds"]
    if response_format == "html" or (
        response_format is None and request.headers.get("accept", "").startswith("text/html")
    ):
        response = HTMLResponse(_status_html(body))
    else:
        response = JSONResponse(content=body)
    if staleness is not None and staleness > STALE_AFTER_SECONDS:
        response.headers["X-Pakhi-Staleness"] = f"{int(staleness)}s"
    return response
