"""WS-1 engine integration: point-in-time hold schedule + signal generator.

Bridges the locked Evaluation Contract trade construction (§5) to
``BacktestEngine``:

- Entry fills at the **first trading session on/after** the entry cycle date
  (the session whose close is ``ojd_close``).  Weekend/holiday cycles fill at
  the next trading session close (contract v1.1 fill amendment) — never the
  prior Friday close, so there is no lookahead.
- Hold is a fixed **2 trading sessions**; the position exits (FLAT) at the
  2nd next trading session close, matching ``fwd2_return``.
- The generator is a pure lookup into a precomputed schedule whose entries are
  functions of freeze features and the trading-session grid only (never of
  prices), so it is safe to precompute — and it still honours the engine's
  ``(data.iloc[:i+1], i)`` call convention with an explicit lookahead guard.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from pakhi.signals.base import Action, Signal
from pakhi.ws1.episodes import freeze_episodes

__all__ = ["build_hold_schedule", "fill_session_of", "make_episode_hold_generator"]

HOLD_SESSIONS = 2  # locked: entry session close -> 2nd next trading close


def fill_session_of(cycle_date: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    """First trading session ON/AFTER ``cycle_date`` (the executable fill).

    Same-day close for trading-day cycles; the next trading close for
    weekend/holiday cycles (v1.1 fill amendment — no prior-close lookahead).
    """
    idx = sessions.searchsorted(cycle_date, side="left")
    if idx >= len(sessions):
        return None
    return sessions[idx]


def build_hold_schedule(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    hold_sessions: int = HOLD_SESSIONS,
) -> pd.Series:
    """Position to hold at each trading session (0.0 / 1.0), per locked hold.

    One LONG interval ``[base, base + hold_sessions - 1]`` per episode start,
    where ``base`` is the episode's executable fill session; overlapping
    intervals (two episodes whose holds collide) are merged into the union, so
    the resulting position path never double-trades.  Exits happen naturally
    when the union drops back to 0.
    """
    schedule = pd.Series(0.0, index=sessions, dtype=np.float64)
    ep = freeze_episodes(pit, sessions)
    starts = ep[ep["episode_start"]]

    for _, row in starts.iterrows():
        base = fill_session_of(pd.Timestamp(row["date"]), sessions)
        if base is None:
            continue
        pos = sessions.get_loc(base)
        for k in range(hold_sessions):
            if pos + k < len(sessions):
                schedule.iloc[pos + k] = 1.0
    return schedule


def make_episode_hold_generator(
    schedule: pd.Series,
    instrument: str = "OJ_FUTURES",
    provenance_map: dict[pd.Timestamp, dict] | None = None,
) -> Callable[[pd.DataFrame, int], Signal]:
    """Engine-compatible ``(data, step_index) -> Signal`` from a hold schedule.

    ``data`` is the engine's point-in-time slice ``data.iloc[:i+1]``; the
    current session is ``data.index[i]``.  Raises if the engine ever hands the
    generator a frame that is not exactly the prefix ending at step ``i``.

    When a LONG fires on a held session, the matching T2 provenance
    (``forecast_cycle_id``, ``publication_ts``, ``model_version``,
    ``roll_state``) is attached as ``Signal.provenance`` so the engine can
    inject it into the trade log.
    """
    prov_map = provenance_map or {}

    def gen(data: pd.DataFrame, i: int) -> Signal:
        assert len(data) == i + 1, "engine leaked future rows to the signal"
        session = data.index[i]
        pos = float(schedule.get(session, 0.0))
        if pos > 0:
            return Signal(
                action=Action.LONG,
                size=pos,
                confidence=0.8,
                instrument=instrument,
                timestamp=session,
                reasoning="WS-1 hold schedule: freeze episode, 2-session hold",
                provenance=prov_map.get(session, {}),
            )
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument=instrument,
            timestamp=session,
            reasoning="WS-1 hold schedule: flat",
        )

    return gen
