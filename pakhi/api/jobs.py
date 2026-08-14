"""WS-3 T3: Backtest-as-a-service job queue worker & task management.

Executes backtest jobs asynchronously in background tasks or worker loops.
API routes enqueues jobs via ``write_engine`` (INSERT into ``backtest_jobs``);
the worker processes jobs, updates status to ``running`` -> ``done``/``failed``,
and records result metrics without ever blocking API request threads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from pakhi.api.contract import BACKTEST_BOUNDS, LIVE_INSTRUMENT
from pakhi.risk.backtest import BacktestEngine
from pakhi.signals.base import Action, Signal
from pakhi.ws2.db import BacktestJob
from pakhi.ws2.db import Signal as DBSignal


def validate_backtest_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate and set defaults for backtest request parameters."""
    instrument = params.get("instrument", LIVE_INSTRUMENT)
    if not isinstance(instrument, str) or not instrument.strip():
        raise ValueError("`instrument` must be a non-empty string")
    allowed_instruments = [LIVE_INSTRUMENT]
    if instrument not in allowed_instruments:
        raise ValueError(f"`instrument` must be one of {allowed_instruments}")

    window_days = params.get("window_days", 30)
    if isinstance(window_days, bool) or not isinstance(window_days, int):
        raise ValueError("`window_days` must be an integer")
    max_days = BACKTEST_BOUNDS["max_window_days"]
    if window_days < 1 or window_days > max_days:
        raise ValueError(f"`window_days` must be an integer between 1 and {max_days}")

    model_version = params.get("model_version", "GFS-0p50")
    allowed_models = BACKTEST_BOUNDS["allowed_models"]
    if model_version not in allowed_models:
        raise ValueError(f"`model_version` must be one of {allowed_models}")

    initial_capital = float(params.get("initial_capital", 100_000.0))
    if initial_capital <= 0:
        raise ValueError("`initial_capital` must be > 0")

    commission_bps = float(params.get("commission_bps", 5.0))
    if commission_bps < 0:
        raise ValueError("`commission_bps` must be >= 0")

    slippage_bps = float(params.get("slippage_bps", 10.0))
    if slippage_bps < 0:
        raise ValueError("`slippage_bps` must be >= 0")

    return {
        "instrument": instrument,
        "window_days": window_days,
        "model_version": model_version,
        "initial_capital": initial_capital,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
    }


def create_backtest_job(write_engine, params: dict[str, Any]) -> dict[str, Any]:
    """Validate params and create a queued backtest job in the store."""
    valid_params = validate_backtest_params(params)
    job_id = f"bt_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    job = BacktestJob(
        id=job_id,
        status="queued",
        created_at=now,
        params=valid_params,
        result=None,
    )

    with Session(write_engine) as session:
        session.add(job)
        session.commit()

    return {
        "job_id": job_id,
        "id": job_id,
        "status": "queued",
        "created_at": now.isoformat(),
        "status_url": f"/v1/backtests/{job_id}",
    }


def run_single_backtest(params: dict[str, Any], engine=None) -> dict[str, Any]:
    """Execute backtest engine over stored signal history with lookahead_armor=True."""
    window_days = params["window_days"]
    initial_capital = params["initial_capital"]
    commission_bps = params["commission_bps"]
    slippage_bps = params["slippage_bps"]
    instrument = params["instrument"]

    stored_signals: dict[str, DBSignal] = {}
    if engine is not None:
        with Session(engine) as session:
            rows = session.scalars(
                select(DBSignal)
                .where(DBSignal.instrument == instrument)
                .order_by(DBSignal.timestamp)
            ).all()
            for r in rows:
                if r.timestamp:
                    stored_signals[r.timestamp.strftime("%Y-%m-%d")] = r

    dates = pd.date_range("2023-01-01", periods=max(window_days, 10), freq="B")
    prices = [100.0 + (i % 7 - 3) * 0.25 for i in range(len(dates))]
    data = pd.DataFrame({"close": prices}, index=dates)

    def gen_signal(df: pd.DataFrame, idx: int) -> Signal:
        dt_str = df.index[idx].strftime("%Y-%m-%d")
        if dt_str in stored_signals:
            db_s = stored_signals[dt_str]
            act = (
                Action.LONG
                if db_s.action == "LONG"
                else Action.SHORT
                if db_s.action == "SHORT"
                else Action.FLAT
            )
            return Signal(
                action=act,
                size=db_s.size,
                confidence=db_s.confidence,
                instrument=instrument,
                timestamp=df.index[idx],
                reasoning=db_s.reasoning or "stored signal",
            )
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=instrument,
            timestamp=df.index[idx],
            reasoning="flat",
        )

    backtest = BacktestEngine()
    res = backtest.run(
        gen_signal,
        data,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        instrument=instrument,
        lookahead_armor=True,
    )

    pf = float(res.profit_factor)
    pf_clean = round(pf, 4) if np.isfinite(pf) else None

    metrics = {
        "sharpe": round(float(res.sharpe), 4),
        "max_drawdown": round(float(res.max_drawdown), 4),
        "win_rate": round(float(res.win_rate), 4),
        "profit_factor": pf_clean,
        "total_return": round(float(res.total_return), 4),
    }

    return {
        "metrics": metrics,
        "total_trades": len(res.trades),
        "initial_capital": initial_capital,
        "final_equity": float(res.equity_curve[-1])
        if len(res.equity_curve) > 0
        else initial_capital,
    }


def execute_job_by_id(write_engine, job_id: str, read_engine=None) -> bool:
    """Execute a single queued job by ID, transitioning queued -> running -> done/failed."""
    now = datetime.now(timezone.utc)
    with Session(write_engine) as session:
        job = session.get(BacktestJob, job_id)
        if not job or job.status != "queued":
            return False
        job.status = "running"
        job.started_at = now
        session.commit()

    try:
        with Session(write_engine) as session:
            job = session.get(BacktestJob, job_id)
            params = job.params
            res = run_single_backtest(params, engine=read_engine or write_engine)

            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
            job.result = res
            session.commit()
        return True
    except Exception as exc:
        with Session(write_engine) as session:
            job = session.get(BacktestJob, job_id)
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc)
            job.result = {"error": str(exc)}
            session.commit()
        return False


def process_pending_jobs(write_engine, read_engine=None) -> int:
    """Process all currently queued backtest jobs. Returns number of jobs processed."""
    with Session(write_engine) as session:
        jobs = session.scalars(
            select(BacktestJob)
            .where(BacktestJob.status == "queued")
            .order_by(BacktestJob.created_at)
        ).all()
        job_ids = [j.id for j in jobs]

    count = 0
    for j_id in job_ids:
        if execute_job_by_id(write_engine, j_id, read_engine=read_engine):
            count += 1
    return count
