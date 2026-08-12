"""WS-1 freeze-episode segmentation (Evaluation Contract v1.1, §2, locked).

Event definition (locked, v1.1):

  a *freeze episode* = maximal run of PIT rows with ``freeze_prob > 0`` grouped
  by **executable fill session**, not calendar days.  Two consecutive freeze
  rows belong to the same episode iff their fill sessions are at most one
  trading session apart (``fill_pos_cur - fill_pos_prev <= 2``); otherwise a
  new episode starts.

  The fill session is the first trading session on/after the cycle date
  (v1.1 fill amendment), so a weather event interrupted by a weekend/holiday
  maps to a *single* entry opportunity instead of fragmenting into two.

Measured on the real archive: **16 episodes total**, of which **13 fall inside
the OOS window** → the maximum achievable OOS event-trade count is **13**.
Those two numbers are asserted by ``test_ws1_episodes.py`` and reproduced by
the harness, so any segmentation drift is caught immediately.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pakhi.ws1.pit import oos_mask

__all__ = ["episode_summary", "freeze_episodes"]


def freeze_episodes(pit: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Annotate the PIT frame with locked episode membership.

    Adds columns:

    - ``is_freeze`` : ``freeze_prob > 0``
    - ``episode_id`` : ``0`` for non-freeze rows, ``1..K`` for episodes
      (numbered in chronological order of episode start)
    - ``episode_start`` : ``True`` only on the first freeze row of an episode

    A new episode starts when a freeze row's **fill session** is >= 2 trading
    sessions after the previous freeze row's fill session (i.e. more than one
    session strictly in between), or when it has no executable fill.
    """
    pit = pit.copy()
    n = len(pit)
    dates = pit["date"].to_numpy(dtype="datetime64[ns]")
    freeze = pit["freeze_prob"].to_numpy(dtype=float) > 0.0

    fill_pos = sessions.searchsorted(dates, side="left")
    fill_pos = np.clip(fill_pos, 0, len(sessions))
    valid_fill = fill_pos < len(sessions)

    episode_id = np.zeros(n, dtype=np.int64)
    episode_start = np.zeros(n, dtype=bool)
    current = 0
    last_fill_pos: int | None = None

    for i in range(n):
        if not freeze[i]:
            continue
        if not valid_fill[i]:
            current += 1
            episode_id[i] = current
            episode_start[i] = True
            last_fill_pos = None
            continue
        fp = int(fill_pos[i])
        if last_fill_pos is not None and fp - last_fill_pos <= 2:
            episode_id[i] = current
        else:
            current += 1
            episode_id[i] = current
            episode_start[i] = True
        last_fill_pos = fp

    pit["is_freeze"] = freeze
    pit["episode_id"] = episode_id
    pit["episode_start"] = episode_start
    return pit


def episode_summary(pit: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per episode: id, entry (start) date, row count, entry freeze_prob."""
    ep = freeze_episodes(pit, sessions)
    starts = ep[ep["episode_start"]]
    rows: list[dict] = []
    for eid in sorted(s for s in ep["episode_id"].unique() if s > 0):
        sub = ep[ep["episode_id"] == eid]
        start = starts.loc[starts["episode_id"] == eid, "date"].iloc[0]
        rows.append(
            {
                "episode_id": int(eid),
                "start_date": start,
                "n_rows": len(sub),
                "n_freezing": int(sub["is_freeze"].sum()),
                "entry_freeze_prob": float(sub.loc[sub["is_freeze"], "freeze_prob"].max()),
            }
        )
    return pd.DataFrame(rows)


def _count_episodes(ep: pd.DataFrame) -> int:
    return int(ep["episode_id"].nunique() - (1 if (ep["episode_id"] == 0).any() else 0))


def _count_oos_episodes(ep: pd.DataFrame) -> int:
    return int(ep.loc[ep["episode_start"] & oos_mask(ep), "episode_id"].nunique())
