"""WS-3 v1 meta routes — health (liveness) and status (readiness+freshness)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select

from pakhi.api.errors import error_body
from pakhi.ws2.db import ForecastCycle, Metric

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
    """Liveness only — the process is up and serving (Docker/K8s probes)."""
    return {"status": "ok"}


@router.get("/status")
def status(request: Request):
    """Readiness + data freshness.

    The never-empty / never-silent-drop rule means a missing recent cycle is a
    visible *stale* state (``X-Pakhi-Staleness`` header) — never a fabricated
    fresh value.  DB unreachable -> 503 ``db_unavailable`` (not ready).
    """
    engine = request.app.state.read_engine
    try:
        with engine.connect() as conn:
            latest = conn.execute(
                select(ForecastCycle.id, ForecastCycle.publication_ts)
                .order_by(desc(ForecastCycle.publication_ts))
                .limit(1)
            ).first()
            worker = conn.execute(
                select(func.max(Metric.timestamp)).where(Metric.name == "worker.last_run")
            ).scalar()
    except Exception as exc:
        logger.exception("status db check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content=error_body("db_unavailable", "database unreachable"),
        )

    pub = _utc(latest.publication_ts) if latest else None
    staleness = (datetime.now(timezone.utc) - pub).total_seconds() if pub else None
    # worker_last_run: prefer the orchestrator's heartbeat metric when the store
    # has one; until WS-2/T4 writes it, fall back to the latest cycle
    # publication timestamp (documented proxy — a fresh cycle implies a run).
    worker_run = _utc(worker) if worker else pub
    body = {
        "db_ok": True,
        "latest_cycle_id": latest.id if latest else None,
        "publication_ts": pub.isoformat() if pub else None,
        "staleness_seconds": round(staleness, 1) if staleness is not None else None,
        "worker_last_run": worker_run.isoformat() if worker_run else None,
    }
    response = JSONResponse(content=body)
    if staleness is not None and staleness > STALE_AFTER_SECONDS:
        response.headers["X-Pakhi-Staleness"] = f"{int(staleness)}s"
    return response
