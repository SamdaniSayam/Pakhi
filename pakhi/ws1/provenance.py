"""WS-1 T2: per-trade provenance — forecast cycle, publication, model, roll state.

Every simulated trade must record (Evaluation Contract / blueprint T2):

- ``forecast_cycle_id`` — the as-published GFS run that fired the signal,
  e.g. ``20251109_12z`` (matches the ``gfs_YYYYMMDD_HHz_*`` archive naming);
- ``publication_ts`` — the cycle's publication timestamp (PIT ``publish_time``);
- ``model_version`` — GFS model + resolution (the archive subset does not carry
  the numeric GFS version, so the honest label is the model+resolution);
- ``archive`` — the as-published source bucket (``noaa-gfs-bdp-pds``);
- ``roll_state`` — the exact contract month and cumulative back-adjustment
  factor in force at the entry session (ICE FND roll calendar).

The signal generator attaches this as ``Signal.provenance`` per held session;
``BacktestEngine`` injects it (with ``costs_incurred``) into the trade log.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pakhi.ws0.roll import front_month_map
from pakhi.ws1.episodes import freeze_episodes
from pakhi.ws1.signal import HOLD_SESSIONS, fill_session_of

__all__ = [
    "ADJUSTMENT_TYPE",
    "ARCHIVE",
    "MODEL_VERSION",
    "ROLL_RULE",
    "build_provenance_map",
    "forecast_cycle_id",
    "roll_state_table",
]

HERE = Path(__file__).resolve().parent.parent.parent
MARKET = HERE / "data" / "market"

MODEL_VERSION = "GFS-0p50"  # GFS forecast at 0.50 deg resolution (12Z cycle)
ARCHIVE = "noaa-gfs-bdp-pds"  # as-published NOAA S3 archive (never reanalysis)
ROLL_RULE = "FND"  # ICE first-notice-day roll rule (matches WS-0 continuous build)
ADJUSTMENT_TYPE = "back"  # back-adjustment applied at each roll


def forecast_cycle_id(cycle_date: pd.Timestamp, cycle_hour: int) -> str:
    """As-published GFS cycle id, e.g. ``20251109_12z``."""
    return f"{pd.Timestamp(cycle_date):%Y%m%d}_{int(cycle_hour):02d}z"


def roll_state_table(
    sessions: pd.DatetimeIndex,
    calendar: pd.DataFrame | None = None,
    continuous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Contract roll state at every trading session.

    Returns a frame indexed by session with columns ``contract_month`` (ICE FND
    calendar), ``adjustment_factor`` (cumulative back-adjust = adj/raw ratio),
    ``adjustment_type`` and ``roll_rule``.
    """
    if calendar is None:
        calendar = pd.read_csv(MARKET / "oj_contract_calendar.csv")
    if continuous is None:
        continuous = pd.read_parquet(MARKET / "oj_continuous.parquet")
    contract = front_month_map(sessions, calendar, roll_rule=ROLL_RULE)
    factor = (continuous["close_adj"] / continuous["close_raw"]).reindex(sessions)
    return pd.DataFrame(
        {
            "contract_month": contract.to_numpy(),
            "adjustment_factor": factor.to_numpy(dtype=float),
            "adjustment_type": ADJUSTMENT_TYPE,
            "roll_rule": ROLL_RULE,
        },
        index=sessions,
    )


def build_provenance_map(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    hold_sessions: int = HOLD_SESSIONS,
    calendar: pd.DataFrame | None = None,
    continuous: pd.DataFrame | None = None,
) -> dict[pd.Timestamp, dict]:
    """Provenance dict for every held session, keyed by session.

    One entry per freeze-episode start: ``forecast_cycle_id``, ``publication_ts``,
    ``model_version``, ``archive`` and the entry-session ``roll_state``.  The
    same provenance is attached to all ``hold_sessions`` of the episode's hold.
    """
    ep = freeze_episodes(pit, sessions)
    starts = ep[ep["episode_start"]]
    roll = roll_state_table(sessions, calendar, continuous)

    prov_map: dict[pd.Timestamp, dict] = {}
    for _, row in starts.iterrows():
        base = fill_session_of(pd.Timestamp(row["date"]), sessions)
        if base is None:
            continue
        pos = sessions.get_loc(base)
        rs = roll.loc[base]
        provenance = {
            "forecast_cycle_id": forecast_cycle_id(row["date"], row["cycle"]),
            "publication_ts": str(row["publish_time"]),
            "model_version": MODEL_VERSION,
            "archive": ARCHIVE,
            "roll_state": {
                "contract_month": str(rs["contract_month"]),
                "adjustment_factor": float(rs["adjustment_factor"]),
                "adjustment_type": str(rs["adjustment_type"]),
                "roll_rule": str(rs["roll_rule"]),
            },
        }
        for k in range(hold_sessions):
            if pos + k < len(sessions):
                prov_map[sessions[pos + k]] = provenance
    return prov_map
