"""WS-2 T2: live compute worker — frozen-θ ColdGrip → paper event ledger.

Contract (``docs/WS2_PAPER_TRADING_PROTOCOL.md`` §2, §4, §5, §7 and the
execution blueprint T2):

- Reads the **frozen** θ_p / θ_t from the hash-pinned T0 protocol payload —
  never re-estimated from the accumulating live dataset.
- **Equivalence gate:** on the same cycle the stored output must equal the
  offline ``pakhi.ws1.candidate.fires`` verdict; the worker **halts**
  (:class:`EquivalenceError`) on any mismatch.
- Builds a provenance-complete paper-ledger row in the locked
  ``data/ws1/t4_candidate_ledger.csv`` shape (gross = ``close[fill+2]/
  close[fill]-1``, net = gross − 30 bps, net_of_benchmark = gross − 0.0030 −
  rbar) and persists it via dialect-aware ON CONFLICT UPSERTs into
  ``forecast_cycles``, ``signals`` and ``paper_ledger``.
- A firing event whose fill or exit session has no realized OJ close is
  rejected (never a fabricated fill).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pakhi.ws1.candidate import estimate_thresholds
from pakhi.ws1.pit import COST, benchmark_2sess, load_oj, load_pit
from pakhi.ws1.provenance import MARKET, roll_state_table
from pakhi.ws1.signal import fill_session_of
from pakhi.ws2.db import ForecastCycle, PaperLedger, Signal, upsert
from pakhi.ws2.ingest import RejectCycleError
from pakhi.ws2.protocol import G1_DATE, PROTOCOL_JSON

__all__ = [
    "HOLD_SESSIONS",
    "ComputeError",
    "EquivalenceError",
    "build_ledger_row",
    "compute_cycle",
    "evaluate_cycle",
    "frozen_thresholds",
    "live_embargo_sessions",
    "offline_verdict",
]

HOLD_SESSIONS = 2
EMBARGO_SESSIONS = 5
LIVE_INSTRUMENT = "OJ_FUTURES"


class ComputeError(Exception):
    """Base class for live compute failures (never a silent drop)."""


class EquivalenceError(ComputeError):
    """Stored worker output diverged from the offline candidate on the same cycle."""


def frozen_thresholds(protocol_path: Path | str = PROTOCOL_JSON) -> dict:
    """Frozen θ_p / θ_t read from the hash-pinned T0 protocol payload."""
    payload = json.loads(Path(protocol_path).read_text())
    sig = payload["signal"]
    return {
        "theta_p": float(sig["theta_p"]),
        "theta_t": float(sig["theta_t_c"]),
        "source": payload["payload_sha256"],
    }


def offline_verdict(features: dict, thresholds: dict | None = None) -> bool:
    """Offline WS-1 candidate verdict on the same feature row (equivalence oracle).

    Recomputed *independently* from the raw PIT (re-deriving θ_p/θ_t with the WS-1
    estimator) rather than reusing the stored/frozen threshold dict, so a real
    divergence in the stored gate is actually caught by :class:`EquivalenceError`
    in :func:`evaluate_cycle`.  The ``thresholds`` argument is accepted for
    signature compatibility and intentionally ignored — independence is the point.
    """
    pit = load_pit()
    theta = estimate_thresholds(pit[pit["date"] <= pd.Timestamp(G1_DATE)])
    return bool(
        features["freeze_prob"] >= theta["theta_p"]
        and features["temperature_min"] <= theta["theta_t"]
    )


def evaluate_cycle(record: dict, thresholds: dict | None = None) -> dict:
    """Frozen-θ fire gate plus the stored-vs-offline equivalence gate.

    Raises :class:`EquivalenceError` (the worker halts) if the stored gate and
    the offline ``pakhi.ws1.candidate`` disagree on the same cycle.
    """
    thresholds = thresholds or frozen_thresholds()
    features = record["features"]
    stored = bool(
        features["freeze_prob"] >= thresholds["theta_p"]
        and features["temperature_min"] <= thresholds["theta_t"]
    )
    offline = offline_verdict(features, thresholds)
    if stored != offline:
        raise EquivalenceError(
            f"stored fires={stored} != offline candidate fires={offline} "
            f"on {record['forecast_cycle_id']}"
        )
    return {
        "fires": stored,
        "freeze_prob": float(features["freeze_prob"]),
        "temperature_min": float(features["temperature_min"]),
        "theta_p": float(thresholds["theta_p"]),
        "theta_t": float(thresholds["theta_t"]),
        "equivalence": {"stored": stored, "offline": offline, "pass": True},
        "forecast_cycle_id": record["forecast_cycle_id"],
    }


def live_embargo_sessions(
    sessions: pd.DatetimeIndex, start=G1_DATE, n: int = EMBARGO_SESSIONS
) -> set[pd.Timestamp]:
    """First ``n`` trading sessions of the live window (the §5 embargo)."""
    return set(sessions[sessions >= pd.Timestamp(start)][:n])


def build_ledger_row(
    record: dict,
    decision: dict,
    sessions: pd.DatetimeIndex,
    oj: pd.DataFrame,
    calendar: pd.DataFrame | None = None,
    continuous: pd.DataFrame | None = None,
    rbar: float | None = None,
    episode_id: int | None = None,
) -> dict:
    """Locked event-trade row in the WS-1 ledger shape + protocol §7 provenance.

    A firing event without a realized OJ close at its fill or exit session is
    rejected (never a fabricated fill).
    """
    entry_cycle = pd.Timestamp(record["cycle_date"])
    base = fill_session_of(entry_cycle, sessions)
    if base is None:
        raise RejectCycleError(
            f"no trading session on/after {entry_cycle.date()} for {record['forecast_cycle_id']}"
        )
    loc = sessions.get_loc(base)
    if loc + HOLD_SESSIONS >= len(sessions):
        raise RejectCycleError(f"no exit session {HOLD_SESSIONS} sessions after fill {base.date()}")
    exit_session = sessions[loc + HOLD_SESSIONS]

    close = oj["close_adj"]
    missing = [s for s in (base, exit_session) if s not in close.index]
    if missing:
        raise RejectCycleError(
            f"missing OJ close at {[str(s.date()) for s in missing]} — "
            f"cycle {record['forecast_cycle_id']} skipped, never a fabricated fill"
        )

    gross = float(close.loc[exit_session] / close.loc[base] - 1.0)
    if rbar is None:
        rbar = benchmark_2sess(load_pit())
    embargoed = base in live_embargo_sessions(sessions)

    if calendar is None:
        calendar = pd.read_csv(MARKET / "oj_contract_calendar.csv")
    if continuous is None:
        continuous = pd.read_parquet(MARKET / "oj_continuous.parquet")
    roll_table = roll_state_table(sessions, calendar, continuous)
    roll = roll_table.loc[base] if base in roll_table.index else None

    entry_weekend = entry_cycle.dayofweek >= 5
    next_close_fill = base > entry_cycle
    in_oos = entry_cycle >= pd.Timestamp(G1_DATE)

    return {
        "episode_id": int(episode_id) if episode_id is not None else None,
        "entry_cycle": entry_cycle.to_pydatetime(),
        "entry_session": base.to_pydatetime(),
        "exit_session": exit_session.to_pydatetime(),
        "gross": gross,
        "net": gross - COST,
        "net_of_benchmark": gross - COST - float(rbar),
        "fold": "live",
        "in_oos": bool(in_oos),
        "embargoed": bool(embargoed),
        "entry_weekend": bool(entry_weekend),
        "next_close_fill": bool(next_close_fill),
        "fill_days_after_cycle": int((base - entry_cycle).days),
        "entry_freeze_prob": float(decision["freeze_prob"]),
        "entry_temperature_min": float(decision["temperature_min"]),
        "forecast_cycle_id": record["forecast_cycle_id"],
        "publication_ts": pd.Timestamp(record["publication_ts"]).to_pydatetime(),
        "model_version": record["model_version"],
        "contract_month": str(roll["contract_month"]) if roll is not None else None,
        "adjustment_factor": float(roll["adjustment_factor"]) if roll is not None else None,
        "scored": bool(in_oos and not embargoed),
        "archive_source": record["archive_source"],
        "vintage_hash": record["vintage"]["sha256"],
        "fetch_date": pd.Timestamp(record["fetch_date"]).to_pydatetime(),
    }


def _upsert_forecast_cycle(engine, record: dict) -> None:
    upsert(
        engine,
        ForecastCycle,
        {
            "id": record["forecast_cycle_id"],
            "publication_ts": pd.Timestamp(record["publication_ts"]).to_pydatetime(),
            "archive_source": record["archive_source"],
            "model_version": record["model_version"],
        },
        ["id"],
    )


def _upsert_signal(engine, row: dict) -> None:
    upsert(
        engine,
        Signal,
        {
            "timestamp": row["entry_session"],
            "instrument": LIVE_INSTRUMENT,
            "action": "LONG",
            "size": 1.0,
            "confidence": 0.8,
            "reasoning": f"ColdGrip live paper event {row['forecast_cycle_id']}",
            "forecast_cycle_id": row["forecast_cycle_id"],
            "publication_ts": pd.Timestamp(row["publication_ts"]).to_pydatetime(),
            "archive_source": row["archive_source"],
            "model_version": row["model_version"],
        },
        ["forecast_cycle_id"],
    )


def _upsert_ledger_row(engine, row: dict) -> None:
    upsert(engine, PaperLedger, row, ["forecast_cycle_id"])


def compute_cycle(
    record: dict,
    engine=None,
    sessions: pd.DatetimeIndex | None = None,
    oj: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    continuous: pd.DataFrame | None = None,
    rbar: float | None = None,
    episode_id: int | None = None,
    persist: bool = True,
    protocol_path: Path | str = PROTOCOL_JSON,
) -> dict:
    """Gate one ingested cycle with the frozen θ, then persist the ledger row.

    The ``forecast_cycles`` provenance row is UPSERTed for every ingested
    cycle; the signal + paper-ledger rows only when the frozen-θ gate fires.
    """
    decision = evaluate_cycle(record, frozen_thresholds(protocol_path))
    result: dict = {"decision": decision, "ledger_row": None, "signal": None}

    if engine is not None and persist:
        _upsert_forecast_cycle(engine, record)

    if not decision["fires"]:
        return result

    if sessions is None:
        sessions = load_oj().index
    if oj is None:
        oj = load_oj()
    row = build_ledger_row(
        record,
        decision,
        sessions,
        oj,
        calendar=calendar,
        continuous=continuous,
        rbar=rbar,
        episode_id=episode_id,
    )
    result["ledger_row"] = row

    if engine is not None and persist:
        _upsert_signal(engine, row)
        _upsert_ledger_row(engine, row)
    return result
