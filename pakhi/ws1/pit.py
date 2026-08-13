"""WS-1 point-in-time frame: loading, validation, and locked evaluation windows.

Centralises the locked Evaluation Contract v1.1 parameters (data/ws1/) so the
harness, gates, and tests all read from one source of truth:

- signal universe: ``data/ws0/freeze_pit.parquet``
- OOS window / season-block expanding-window folds (see ``FOLD_BOUNDARIES``)
- 5-session fold embargo, OOS span (3.4114 y) and always-long benchmark mean
  (``+0.2405 %`` per 2 sessions on the current archive, v1.1 executable fills).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent.parent
WS0 = HERE / "data" / "ws0"
MARKET = HERE / "data" / "market"

DEFAULT_PIT = WS0 / "freeze_pit.parquet"
DEFAULT_OJ = MARKET / "oj_continuous.parquet"

COST_BPS = 30.0  # 5 bps commission + 10 bps slippage per position change, round trip
COST = COST_BPS / 10_000  # 0.0030 additive, per locked contract

FOLDS: list[tuple[str, str, str]] = [
    ("seed", "2021-11-01", "2022-10-31"),
    ("fold1", "2022-11-01", "2023-10-31"),
    ("fold2", "2023-11-01", "2024-10-31"),
    ("fold3", "2024-11-01", "2025-10-31"),
    ("fold4", "2025-11-01", "2026-03-31"),
]
TEST_FOLDS: list[tuple[str, str, str]] = FOLDS[1:]

EMBARGO_SESSIONS = 5  # first sessions of each test fold purged from scoring

OOS_START = pd.Timestamp("2022-11-01")
OOS_END = pd.Timestamp("2026-03-31")

__all__ = [
    "COST",
    "DEFAULT_OJ",
    "DEFAULT_PIT",
    "EMBARGO_SESSIONS",
    "FOLDS",
    "OOS_END",
    "OOS_START",
    "TEST_FOLDS",
    "load_oj",
    "load_pit",
    "validate_pit_frame",
]


def load_pit(path: Path | str | None = None) -> pd.DataFrame:
    """Load the freeze PIT frame with a normalised datetime ``date`` column.

    Returns a date-sorted copy (does not mutate the caller's frame).
    """
    if path is None:
        path = DEFAULT_PIT
    pit = pd.read_parquet(path)
    pit = pit.copy()
    pit["date"] = pd.to_datetime(pit["date"])
    return pit.sort_values("date").reset_index(drop=True)


def load_oj(path: Path | str | None = None) -> pd.DataFrame:
    """Load the back-adjusted OJ continuous close series.

    Returns a frame indexed by trading ``Date`` with a ``close_adj`` column.
    """
    if path is None:
        path = DEFAULT_OJ
    df = pd.read_parquet(path).reset_index()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df[["close_adj"]].dropna()


def validate_pit_frame(pit: pd.DataFrame) -> tuple[bool, str]:
    """Data-quality gate for the PIT frame (shared with ``rebuild_dataset.py``).

    Checks emptiness, plausibility of the 1- and 2-session forward returns, and
    completeness of the 2-session outcomes required by the Evaluation Contract.
    """
    if pit.empty:
        return False, "PIT frame empty"
    if "fwd_return" not in pit.columns or pit["fwd_return"].abs().max() > 0.5:
        return False, "PIT forward returns implausible (>50%)"
    if "fwd2_return" not in pit.columns or pit["fwd2_return"].isna().any():
        return False, "PIT missing 2-session outcomes"
    if pit["fwd2_return"].abs().max() > 0.5:
        return False, "PIT 2-session returns implausible (>50%)"
    detail = "PIT {} rows, fwd_return range [{:.2f}, {:.2f}], fwd2 range [{:.2f}, {:.2f}]".format(
        len(pit),
        pit["fwd_return"].min(),
        pit["fwd_return"].max(),
        pit["fwd2_return"].min(),
        pit["fwd2_return"].max(),
    )
    return True, detail


def oos_mask(pit: pd.DataFrame) -> np.ndarray:
    """Boolean mask of PIT rows inside the locked OOS window (folds 1-4)."""
    return ((pit["date"] >= OOS_START) & (pit["date"] <= OOS_END)).to_numpy()


def fold_label(pit: pd.DataFrame) -> pd.Series:
    """Per-row test-fold label (``fold1``..``fold4``; outside OOS → ``seed``)."""
    labels = np.full(len(pit), "seed", dtype=object)
    for name, start, end in TEST_FOLDS:
        in_fold = (pit["date"] >= pd.Timestamp(start)) & (pit["date"] <= pd.Timestamp(end))
        labels[in_fold] = name
    return pd.Series(labels, index=pit.index)


def embargo_sessions(sessions: pd.DatetimeIndex) -> set[pd.Timestamp]:
    """The locked 5-session embargo: first ``EMBARGO_SESSIONS`` sessions of each test fold.

    Purging the fold head drains autocorrelation bleed from adjacent train data.
    """
    embargoed: set[pd.Timestamp] = set()
    for _, start, end in TEST_FOLDS:
        in_fold = sessions[(sessions >= pd.Timestamp(start)) & (sessions <= pd.Timestamp(end))]
        embargoed.update(in_fold[:EMBARGO_SESSIONS])
    return embargoed


def oos_span_years() -> float:
    """OOS span in years (locked 3.4114): calendar days / 365.25."""
    return (OOS_END - OOS_START).days / 365.25


def benchmark_2sess(pit: pd.DataFrame) -> float:
    """Always-long benchmark: mean 2-session OJ return over the OOS window.

    Locked at ``+0.2405 %`` on the current archive (v1.1 executable fills;
    recomputed, never hard-coded).
    """
    oos = pit[oos_mask(pit)]
    return float(oos["fwd2_return"].mean())
