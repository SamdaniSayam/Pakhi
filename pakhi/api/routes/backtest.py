"""WS-3 T3: Backtest-as-a-service route handlers.

POST /v1/backtests — validates parameters, enqueues a job in ``backtest_jobs``
via ``write_engine``, and returns 201 Created with status URL. Never executes
the backtest inside the HTTP request thread.

GET /v1/backtests/{job_id} — retrieves job status & parameters.
GET /v1/backtests/{job_id}/result — retrieves stored job result artifact when done.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pakhi.api.auth import hash_key
from pakhi.api.jobs import create_backtest_job, execute_job_by_id
from pakhi.api.serialize import utc
from pakhi.ws2.db import BacktestJob

router = APIRouter(prefix="/v1", tags=["backtests"])

# Locked per_key_cap (contract §backtest_bounds): max 1 queued job per client
# in any 300s window.
_MAX_QUEUED_PER_CLIENT = 1
_CAP_WINDOW_SECONDS = 300


def _client_id(request: Request) -> str:
    key_header = request.headers.get("X-Pakhi-Key") or request.query_params.get("key")
    if key_header:
        return f"key_{hash_key(key_header)[:12]}"
    return request.client.host if request.client else "127.0.0.1"


@router.post("/backtests", status_code=201)
def submit_backtest(request: Request, body: dict[str, Any], background_tasks: BackgroundTasks):
    """Enqueue a backtest-as-a-service job. Returns 201 Created."""
    write_engine = request.app.state.write_engine
    read_engine = request.app.state.read_engine
    client_id = _client_id(request)
    cap_since = datetime.now(timezone.utc) - timedelta(seconds=_CAP_WINDOW_SECONDS)

    # Enforce contract per_key_cap: max 1 queued job per client per 300s window.
    with Session(write_engine) as session:
        queued_count = (
            session.execute(
                select(func.count())
                .select_from(BacktestJob)
                .where(BacktestJob.status == "queued")
                .where(BacktestJob.client_id == client_id)
                .where(BacktestJob.created_at >= cap_since)
            ).scalar()
            or 0
        )
        if queued_count >= _MAX_QUEUED_PER_CLIENT:
            raise HTTPException(status_code=429, detail="a backtest job is already queued for this client")

    try:
        job_info = create_backtest_job(write_engine, body, client_id=client_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    job_id = job_info["job_id"]
    background_tasks.add_task(execute_job_by_id, write_engine, job_id, read_engine=read_engine)

    return JSONResponse(status_code=201, content=job_info)


@router.get("/backtests/{job_id}")
def get_backtest_status(request: Request, job_id: str):
    """Retrieve status and details for a backtest job."""
    job = None
    with Session(request.app.state.read_engine) as session:
        job = session.get(BacktestJob, job_id)

    if not job:
        with Session(request.app.state.write_engine) as write_session:
            job = write_session.get(BacktestJob, job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"backtest job {job_id!r} not found")

    created = utc(job.created_at)
    started = utc(job.started_at)
    finished = utc(job.finished_at)

    out = {
        "id": job.id,
        "job_id": job.id,
        "status": job.status,
        "created_at": created.isoformat() if created else None,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "params": job.params,
        "result": job.result if job.status == "done" else None,
    }
    return out


@router.get("/backtests/{job_id}/result")
def get_backtest_result(request: Request, job_id: str):
    """Stream or return stored backtest result artifact when done."""
    job = None
    with Session(request.app.state.read_engine) as session:
        job = session.get(BacktestJob, job_id)

    if not job:
        with Session(request.app.state.write_engine) as write_session:
            job = write_session.get(BacktestJob, job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"backtest job {job_id!r} not found")

    if job.status != "done" or job.result is None:
        raise HTTPException(status_code=404, detail=f"backtest job {job_id!r} is not done yet")

    return job.result
