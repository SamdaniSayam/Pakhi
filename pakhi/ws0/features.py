"""WS-0 freeze features extracted from as-published GFS cycles.

Turns the gridded GFS frame for one cycle into the ``forecast`` dict that
:class:`pakhi.signals.freeze.FreezeSignal` consumes:

- ``temperature_min``  min t2m across the bbox and forecast leads (°C)
- ``freeze_prob``      fraction of (cell, lead-hour) pairs with t2m < 0 °C
                       inside the next ``horizon_hours``
- ``event_peak_time``  time of the coldest forecast temperature
- ``current_time``     cycle publish time (point-in-time decision cutoff)
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

T0C_K = 273.15


def publish_time(cycle_date, cycle_hour: int = 12, latency_hours: float = 3.5) -> datetime:
    """GFS 0.50°/0.25° cycle publish time = run start + publish latency."""
    run_start = datetime(
        cycle_date.year,
        cycle_date.month,
        cycle_date.day,
        cycle_hour,
        tzinfo=timezone.utc,
    )
    return run_start + pd.Timedelta(hours=latency_hours)


def freeze_features(
    frame: pd.DataFrame,
    horizon_hours: int = 48,
    freeze_kelvin: float = T0C_K,
    publish_latency_hours: float = 3.5,
) -> dict:
    """Compute freeze features from one cycle's gridded GFS frame.

    Args:
        frame: DataFrame with ``latitude``, ``longitude``, ``valid_time``,
            ``t2m`` (K) columns for a single cycle.
        horizon_hours: Only cells valid within ``[publish, publish+horizon]``
            count toward the freeze probability.
        freeze_kelvin: Temperature threshold for a "freeze" cell (K).
        publish_latency_hours: Latency between run start and publish used for
            the point-in-time ``current_time`` cutoff.

    Returns:
        Forecast dict matching :class:`FreezeSignal.generate`'s contract.
    """
    if frame.empty or "t2m" not in frame.columns:
        return {
            "temperature_min": np.nan,
            "freeze_prob": 0.0,
            "event_peak_time": None,
            "current_time": None,
        }

    run_start = pd.Timestamp(frame["time"].min()).to_pydatetime()
    current_time = run_start.replace(tzinfo=timezone.utc) + pd.Timedelta(
        hours=publish_latency_hours
    )

    valid = pd.to_datetime(frame["valid_time"], utc=True)
    t2m = frame["t2m"].astype(float)
    horizon_end = pd.Timestamp(current_time) + pd.Timedelta(hours=horizon_hours)
    in_horizon = valid <= horizon_end

    cold = t2m[in_horizon] < freeze_kelvin
    freeze_prob = float(cold.sum() / max(int(in_horizon.sum()), 1))

    cold_slice = frame.loc[in_horizon & (t2m == t2m[in_horizon].min())]
    temp_min_k = float(t2m[in_horizon].min()) if in_horizon.any() else float(t2m.min())
    event_peak = (
        pd.to_datetime(cold_slice["valid_time"].iloc[0], utc=True).to_pydatetime()
        if not cold_slice.empty
        else valid[in_horizon].max().to_pydatetime()
    )

    return {
        "temperature_min": temp_min_k - T0C_K,
        "freeze_prob": freeze_prob,
        "event_peak_time": event_peak,
        "current_time": current_time,
        "t2m_min_k": temp_min_k,
        "grid_cells": len(t2m),
        "horizon_cells": int(in_horizon.sum()),
    }


def load_cycle(parquet: str) -> pd.DataFrame:
    """Load a single backfilled GFS cycle parquet (multi-run safety)."""
    df = pd.read_parquet(parquet)
    if "date" in df.columns:
        df = df.loc[(df["date"].astype(str).str[:8].astype(int) == int(parquet.split("gfs_")[1][:8]))]
    return df
