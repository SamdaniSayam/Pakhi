"""WS-3 v1 read endpoints — instruments, signals, forecasts, ensemble, ledger.

All data handlers are sync ``def`` (anyio threadpool) per the locked contract;
every query reads through ``read_engine``; missing data is a 404 — never an
empty success.  Forecast rows and ensemble disagreement are honest 501s: the
store does not contain that data yet, and the API never fabricates what the
store does not have.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from pakhi.api.edge import edge_status
from pakhi.api.serialize import bind_dt, signal_to_dict, utc
from pakhi.ws2.db import PaperLedger, Signal

router = APIRouter(prefix="/v1", tags=["read"])


@router.get("/instruments")
def instruments(request: Request):
    """Distinct instruments in the store with signal count + freshness."""
    engine = request.app.state.read_engine
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                Signal.instrument,
                func.count().label("signal_count"),
                func.max(Signal.timestamp).label("latest_at"),
            )
            .group_by(Signal.instrument)
            .order_by(Signal.instrument)
        ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="no instruments in the store")
    now = datetime.now(timezone.utc)
    out = []
    for instrument, count, latest_at in rows:
        latest = utc(latest_at)
        out.append(
            {
                "instrument": instrument,
                "signal_count": int(count),
                "latest_signal_at": latest.isoformat() if latest else None,
                "staleness_seconds": round((now - latest).total_seconds(), 1) if latest else None,
            }
        )
    return {"instruments": out}


@router.get("/signals/{instrument}")
def signals(
    request: Request,
    instrument: str,
    limit: int = Query(20, ge=1, le=100),
    since: str | None = None,
    cycle_id: str | None = None,
):
    """Latest + history for an instrument; empty -> 404, never an empty 200."""
    engine = request.app.state.read_engine
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, f"invalid `since` {since!r}: expected ISO8601")
        since_dt = bind_dt(engine, since_dt)

    stmt = select(Signal).where(Signal.instrument == instrument)
    if since_dt is not None:
        stmt = stmt.where(Signal.timestamp >= since_dt)
    if cycle_id is not None:
        stmt = stmt.where(Signal.forecast_cycle_id == cycle_id)
    stmt = stmt.order_by(desc(Signal.timestamp)).limit(limit)

    with Session(engine) as session:
        rows = session.scalars(stmt).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"no signals recorded for {instrument}")

    body = {
        "instrument": instrument,
        "count": len(rows),
        "signals": [signal_to_dict(r) for r in rows],
    }
    response = JSONResponse(content=body)
    response.headers["X-Pakhi-Edge-Status"] = edge_status(engine)["header"]
    return response


@router.get("/forecasts/{instrument}")
def forecasts(instrument: str):
    """Stored forecast rows — honest 501: WS-2 does not store forecast rows yet."""
    raise HTTPException(
        status_code=501,
        detail="stored forecast rows are not yet available (WS-2 does not store forecast rows)",
    )


@router.get("/ensemble/disagreement")
def ensemble_disagreement():
    """Stored disagreement series — honest 501: deferred from WS-2."""
    raise HTTPException(
        status_code=501,
        detail="ensemble disagreement is deferred from WS-2 and not yet computed",
    )


@router.get("/ledger")
def ledger(request: Request):
    """Paper-ledger summary, clearly labeled paper / not live capital."""
    engine = request.app.state.read_engine
    with engine.connect() as conn:
        total = int(conn.execute(select(func.count()).select_from(PaperLedger)).scalar() or 0)
        scored = int(
            conn.execute(
                select(func.count()).select_from(PaperLedger).where(PaperLedger.scored.is_(True))
            ).scalar()
            or 0
        )
        agg = conn.execute(
            select(
                func.sum(PaperLedger.net_of_benchmark), func.avg(PaperLedger.net_of_benchmark)
            ).where(PaperLedger.scored.is_(True))
        ).first()
    es = edge_status(engine)
    net = float(agg[0]) if agg and agg[0] is not None else None
    mean = float(agg[1]) if agg and agg[1] is not None else None
    body = {
        "ledger": {
            "label": "paper / not live capital",
            "total_count": total,
            "scored_count": scored,
            "net_of_benchmark": round(net, 6) if net is not None else None,
            "mean_net_of_benchmark": round(mean, 6) if mean is not None else None,
        }
    }
    response = JSONResponse(content=body)
    response.headers["X-Pakhi-Edge-Status"] = es["header"]
    return response
