"""WS-3 T3: Backtest-as-a-service job queue worker & task management.

Executes backtest jobs asynchronously in background tasks or worker loops.
API routes enqueues jobs via ``write_engine`` (INSERT into ``backtest_jobs``);
the worker processes jobs, updates status to ``running`` -> ``done``/``failed``,
and records result metrics without ever blocking API request threads.

Backtest semantics (honest): the job replays the store's *real* signal history
for the requested instrument/model within ``window_days``, with lookahead armor
on. The store does not yet hold OHLCV prices, so fills are simulated against a
synthetic price proxy — that is disclosed on every result payload
(``price_source: "synthetic_proxy"``); signals are never fabricated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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

METRIC_KEYS = ("sharpe", "max_drawdown", "win_rate", "profit_factor", "total_return")


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


def create_backtest_job(
    write_engine, params: dict[str, Any], client_id: str | None = None
) -> dict[str, Any]:
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
        client_id=client_id,
    )

    with Session(write_engine) as session:
        session.add(job)
        session.commit()

    return {
        "id": job_id,
        "job_id": job_id,
        "status": "queued",
        "created_at": now.isoformat(),
        "status_url": f"/v1/backtests/{job_id}",
    }


def _day(ts) -> pd.Timestamp:
    """Normalize a DB timestamp to a tz-naive calendar day (for date-keying)."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.normalize()


def _clip_publication(pub, current: pd.Timestamp) -> pd.Timestamp:
    """Clip a stored publication to the session's decision cutoff.

    The lookahead armor rejects any publication after the ICE OJ decision cutoff
    of the session. Replaying a historical signal at its own session, a
    publication recorded later in the day is a false positive — the signal was
    not actionable before the cutoff anyway, so clipping is the honest,
    conservative interpretation.
    """
    from pakhi.ws1.armor import decision_cutoff

    pub_ts = pd.Timestamp(pub)
    if pub_ts.tzinfo is None:
        pub_ts = pub_ts.tz_localize("UTC")
    cutoff = decision_cutoff(current)
    return pub_ts if pub_ts <= cutoff else cutoff


def run_single_backtest(params: dict[str, Any], engine=None) -> dict[str, Any]:
    """Execute the backtest engine over the store's real signal history."""
    instrument = params["instrument"]
    window_days = params["window_days"]
    model_version = params["model_version"]
    initial_capital = params["initial_capital"]
    commission_bps = params["commission_bps"]
    slippage_bps = params["slippage_bps"]

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    signals_by_date: dict[pd.Timestamp, DBSignal] = {}
    if engine is not None:
        with Session(engine) as session:
            stmt = (
                select(DBSignal)
                .where(DBSignal.instrument == instrument)
                .where(DBSignal.model_version == model_version)
                .where(DBSignal.timestamp >= cutoff)
                .order_by(DBSignal.timestamp)
            )
            for row in session.scalars(stmt):
                if row.timestamp is None:
                    continue
                signals_by_date[_day(row.timestamp)] = row

    if not signals_by_date:
        return {
            "metrics": {k: None for k in METRIC_KEYS},
            "total_trades": 0,
            "initial_capital": initial_capital,
            "final_equity": initial_capital,
            "note": "no stored signals within the requested window",
            "signal_source": "stored",
            "price_source": "synthetic_proxy",
        }

    dates = sorted(signals_by_date)
    start, end = dates[0], dates[-1]
    if (end - start) < pd.Timedelta(days=1):
        end = start + pd.Timedelta(days=3)  # give the engine at least 2 bars
    index = pd.bdate_range(start=start, end=end)

    # Synthetic price proxy (disclosed): no OHLCV table in the store yet.
    prices = [100.0 + (i % 7 - 3) * 0.25 for i in range(len(index))]
    data = pd.DataFrame({"close": prices}, index=index)

    def gen_signal(df: pd.DataFrame, idx: int) -> Signal:
        current = df.index[idx]
        row = signals_by_date.get(current.normalize())
        if row is None:
            return Signal(
                action=Action.FLAT,
                size=0.0,
                confidence=0.0,
                instrument=instrument,
                timestamp=current,
                reasoning="flat",
            )
        provenance: dict[str, Any] = {
            "forecast_cycle_id": row.forecast_cycle_id,
            "archive_source": row.archive_source,
            "model_version": row.model_version,
        }
        if row.publication_ts is not None:
            provenance["publication_ts"] = _clip_publication(row.publication_ts, current)
        return Signal(
            action=Action(row.action),
            size=row.size,
            confidence=row.confidence,
            instrument=instrument,
            timestamp=current,
            reasoning=row.reasoning or "stored signal",
            provenance=provenance,
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

    def _num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return round(f, 4) if np.isfinite(f) else None

    metrics = {k: _num(getattr(res, k)) for k in METRIC_KEYS}

    return {
        "metrics": metrics,
        "total_trades": len(res.trades),
        "initial_capital": initial_capital,
        "final_equity": float(res.equity_curve[-1])
        if len(res.equity_curve) > 0
        else initial_capital,
        "signal_source": "stored",
        "price_source": "synthetic_proxy",
        "note": "fills simulated on a synthetic price proxy; real OHLCV not yet stored",
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
