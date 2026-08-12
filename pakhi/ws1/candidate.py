"""WS-1 T4: "ColdGrip" redefined freeze signal — in-fold re-estimation.

Pre-registered (docs/T4_CANDIDATE_REGISTRATION.md, data/ws1/t4_candidate.json)
*before* any OOS fold is scored (contract §4, §10 — one-shot, no re-tuning).
It replaces the dead pre-committed baseline ``FreezeSignal(entry=0.6)`` (G0:
max ``freeze_prob`` 0.2182, 0 trades) with a rule that fires when the model's
freeze call reaches the **train-typical** level under a physically sub-zero
temperature:

    fire(row) = freeze_prob >= theta_p   AND   temperature_min <= theta_t

- ``theta_p`` = median ``freeze_prob`` over the fold's TRAIN-window freeze
  rows (the only free parameter; re-estimated per fold, expanding window);
- ``theta_t`` = 0.0 °C, fixed (physical freeze definition);
- ``<= 1`` trade per episode: the **first** firing row is the entry;
- hold = 2 trading sessions (locked by contract §5).

The gates read only ``freeze_prob`` / ``temperature_min`` — never ``ojd_*`` /
``fwd*`` outcomes — so the schedule is a pure function of train features and
can never leak future prices into the signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pakhi.ws1.episodes import freeze_episodes
from pakhi.ws1.pit import FOLDS, TEST_FOLDS, fold_label
from pakhi.ws1.signal import fill_session_of

__all__ = [
    "CANDIDATE_NAME",
    "TEMP_GATE_C",
    "build_candidate_schedule",
    "candidate_entries",
    "estimate_thresholds",
    "fires",
]

CANDIDATE_NAME = "ColdGrip"
TEMP_GATE_C = 0.0  # fixed physical freeze gate (theta_t), not estimated
FREEZE_PROB_ESTIMATOR_RANK = 0.5  # median over train freeze rows (pre-registered)


def estimate_thresholds(train: pd.DataFrame) -> dict[str, float]:
    """θ_p (median train freeze_prob) and θ_t (fixed 0 °C) from train rows only.

    Train freeze rows are rows with ``freeze_prob > 0``.  With no train freeze
    evidence θ_p is +inf so the fold fires nothing — never a fabricated bar.
    """
    freeze_rows = train.loc[train["freeze_prob"] > 0, "freeze_prob"]
    theta_p = (
        float(freeze_rows.quantile(FREEZE_PROB_ESTIMATOR_RANK))
        if not freeze_rows.empty
        else float("inf")
    )
    return {"theta_p": theta_p, "theta_t": TEMP_GATE_C}


def fires(row: pd.Series, thresholds: dict[str, float]) -> bool:
    """True iff a freeze row clears both pre-registered gates."""
    return bool(
        row["freeze_prob"] >= thresholds["theta_p"]
        and row["temperature_min"] <= thresholds["theta_t"]
    )


def _per_fold_fire_mask(pit: pd.DataFrame) -> pd.DataFrame:
    """Boolean column per test fold: which test rows clear the fold's gates."""
    pit = pit.copy()
    pit["candidate_fire"] = False
    for k, (_, start, end) in enumerate(TEST_FOLDS):
        train_end = pd.Timestamp(FOLDS[k][2])
        train = pit[pit["date"] <= train_end]
        theta = estimate_thresholds(train)
        in_fold = (pit["date"] >= pd.Timestamp(start)) & (pit["date"] <= pd.Timestamp(end))
        test = pit[in_fold]
        if test.empty:
            continue

        def _clears(r: pd.Series, _theta: dict[str, float] = theta) -> bool:
            return fires(r, _theta)

        cleared = test.apply(_clears, axis=1)
        pit.loc[test.index, "candidate_fire"] = cleared.to_numpy()
    return pit


def candidate_entries(pit: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Entry rows of the redefined signal: first firing row per episode.

    Returns one row per traded episode with the entry cycle / fill session,
    the entry features, fold label and the PIT outcome (``fwd2_return``,
    carried for the harness ledger only — the signal itself never reads it).
    """
    pit = freeze_episodes(pit, sessions)
    pit = _per_fold_fire_mask(pit)
    folds = fold_label(pit)

    rows: list[dict] = []
    seen: set[int] = set()
    for idx, row in pit.iterrows():
        eid = int(row["episode_id"])
        if eid == 0 or not row["candidate_fire"] or eid in seen:
            continue
        seen.add(eid)
        base = fill_session_of(pd.Timestamp(row["date"]), sessions)
        rows.append(
            {
                "episode_id": eid,
                "entry_cycle": pd.Timestamp(row["date"]),
                "entry_session": base,
                "freeze_prob": float(row["freeze_prob"]),
                "temperature_min": float(row["temperature_min"]),
                "fold": folds.loc[idx],
                "fwd2_return": float(row["fwd2_return"]),
            }
        )
    return pd.DataFrame(rows)


def build_candidate_schedule(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    hold_sessions: int = 2,
) -> tuple[pd.Series, list[dict]]:
    """Position path (0.0/1.0) for the redefined signal over ``sessions``.

    Holds the locked ``hold_sessions`` sessions from each entry session.  Also
    returns the per-fold thresholds / firing summary for the report.
    """
    schedule = pd.Series(0.0, index=sessions, dtype=np.float64)
    entries = candidate_entries(pit, sessions)

    thresholds: list[dict] = []
    for k, (name, _, _) in enumerate(TEST_FOLDS):
        train_end = pd.Timestamp(FOLDS[k][2])
        theta = estimate_thresholds(pit[pit["date"] <= train_end])
        ep_entries = entries[entries["fold"] == name] if not entries.empty else entries
        thresholds.append(
            {
                "fold": name,
                "train_end": str(train_end.date()),
                "theta_p": theta["theta_p"],
                "theta_t": theta["theta_t"],
                "n_entries": len(ep_entries),
            }
        )

    for _, ent in entries.iterrows():
        base = pd.Timestamp(ent["entry_session"])
        if base not in sessions:
            continue
        pos = sessions.get_loc(base)
        for k in range(hold_sessions):
            if pos + k < len(sessions):
                schedule.iloc[pos + k] = 1.0
    return schedule, thresholds
