"""WS-1: hold-2-session schedule and the engine-compatible generator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.signals.base import Action
from pakhi.ws1.pit import load_oj, load_pit
from pakhi.ws1.signal import (
    HOLD_SESSIONS,
    build_hold_schedule,
    fill_session_of,
    make_episode_hold_generator,
)


def _sessions() -> pd.DatetimeIndex:
    # Weekly Mon-Fri sessions starting 2024-01-01 (Monday).
    return pd.date_range("2024-01-01", periods=15, freq="B")


def _pit_with_episode(start: str) -> pd.DataFrame:
    dates = pd.date_range(start, periods=4, freq="D")
    return pd.DataFrame({"date": dates, "freeze_prob": [0.1, 0.1, 0.0, 0.0]})


class TestFillSession:
    def test_weekday_maps_to_itself(self):
        sessions = _sessions()
        assert fill_session_of(pd.Timestamp("2024-01-03"), sessions) == pd.Timestamp("2024-01-03")

    def test_saturday_maps_to_next_monday(self):
        sessions = _sessions()
        # v1.1: never the prior Friday — the Saturday cycle fills at Monday.
        assert fill_session_of(pd.Timestamp("2024-01-06"), sessions) == pd.Timestamp("2024-01-08")

    def test_sunday_maps_to_next_monday(self):
        sessions = _sessions()
        assert fill_session_of(pd.Timestamp("2024-01-07"), sessions) == pd.Timestamp("2024-01-08")

    def test_before_data_maps_to_first_session(self):
        sessions = _sessions()
        # A cycle before the grid fills at the first available session.
        assert fill_session_of(pd.Timestamp("2023-12-31"), sessions) == pd.Timestamp("2024-01-01")

    def test_after_data_is_none(self):
        sessions = _sessions()
        assert fill_session_of(pd.Timestamp("2024-03-31"), sessions) is None

    def test_exact_boundary_inclusive(self):
        sessions = _sessions()
        assert fill_session_of(pd.Timestamp("2024-01-05"), sessions) == pd.Timestamp("2024-01-05")


class TestHoldSchedule:
    def test_two_session_hold_then_flat(self):
        sessions = _sessions()
        pit = _pit_with_episode("2024-01-03")  # entry cycle Wednesday
        sched = build_hold_schedule(pit, sessions, hold_sessions=2)
        assert sched.loc["2024-01-03"] == 1.0  # entry fill at close
        assert sched.loc["2024-01-04"] == 1.0  # hold
        assert sched.loc["2024-01-05"] == 0.0  # exit at 2nd next close
        assert sched.sum() == 2.0

    def test_hold_matches_locked_constant(self):
        assert HOLD_SESSIONS == 2

    def test_weekend_entry_maps_to_next_monday(self):
        sessions = _sessions()
        pit = _pit_with_episode("2024-01-06")  # Saturday cycle
        sched = build_hold_schedule(pit, sessions, hold_sessions=2)
        # v1.1: Base = Monday 2024-01-08; hold Mon + Tue, exit Wed.
        assert sched.loc["2024-01-05"] == 0.0  # prior Friday is NOT filled
        assert sched.loc["2024-01-08"] == 1.0
        assert sched.loc["2024-01-09"] == 1.0
        assert sched.loc["2024-01-10"] == 0.0
        assert sched.sum() == 2.0

    def test_disjoint_episode_holds_do_not_merge(self):
        # Locked v1.1: episodes split only at >= 2 session gaps, so holds
        # (2 sessions each) are structurally disjoint and never merged.
        sessions = pd.date_range("2024-01-01", periods=12, freq="B")
        dates = pd.date_range("2024-01-01", periods=12, freq="D")
        pit = pd.DataFrame({"date": dates, "freeze_prob": 0.0})
        pit.loc[pit["date"] == "2024-01-03", "freeze_prob"] = 0.1  # ep A (Wed)
        pit.loc[pit["date"] == "2024-01-08", "freeze_prob"] = 0.1  # ep B (Mon)
        sched = build_hold_schedule(pit, sessions, hold_sessions=2)
        # A hold [Wed, Thu], exit Fri; B hold [Mon, Tue], exit Wed.
        assert sched.loc["2024-01-03"] == 1.0
        assert sched.loc["2024-01-04"] == 1.0
        assert sched.loc["2024-01-05"] == 0.0
        assert sched.loc["2024-01-08"] == 1.0
        assert sched.loc["2024-01-09"] == 1.0
        assert sched.loc["2024-01-10"] == 0.0
        assert sched.sum() == 4.0

    def test_long_hold_union_never_double_trades(self):
        # Defense-in-depth: even with an exaggerated hold length that forces
        # overlapping intervals, the union schedule never counts a session twice.
        sessions = pd.date_range("2024-01-01", periods=15, freq="B")
        dates = pd.date_range("2024-01-01", periods=20, freq="D")
        pit = pd.DataFrame({"date": dates, "freeze_prob": 0.0})
        pit.loc[pit["date"] == "2024-01-03", "freeze_prob"] = 0.1  # ep A (Wed)
        pit.loc[pit["date"] == "2024-01-08", "freeze_prob"] = 0.1  # ep B (Mon)
        sched = build_hold_schedule(pit, sessions, hold_sessions=6)
        # A [Wed..Wed+5] and B [Mon..Mon+5] overlap; union must stay binary 0/1.
        assert ((sched == 0.0) | (sched == 1.0)).all()
        assert 0 < sched.sum() <= 12  # overlap collapsed, no double-counting

    def test_real_schedule_never_leaves_window(self):
        pit = load_pit()
        sessions = load_oj().index
        sched = build_hold_schedule(pit, sessions)
        assert ((sched == 0.0) | (sched == 1.0)).all()
        # Position is 1.0 only inside the [start, start+2) sessions of OOS window.
        held = sessions[sched == 1.0]
        assert held.min() >= pd.Timestamp("2022-01-21")  # first episode base
        assert held.max() <= pd.Timestamp("2026-02-24")  # last episode exit

    def test_real_schedule_trade_count_matches_episode_ceiling(self):
        # The parameter-free demo fires once per episode (16 total, 13 in OOS);
        # holds must not overlap, so exactly 16 LONG intervals exist and 13 of
        # them start inside the OOS window.
        pit = load_pit()
        sessions = load_oj().index
        sched = build_hold_schedule(pit, sessions)
        transitions = int((np.diff(sched.to_numpy()) > 0).sum())
        assert transitions == 16
        pos = sched.to_numpy()
        oos_start = int(np.searchsorted(sessions, pd.Timestamp("2022-11-01"), side="left"))
        oos_transitions = int((np.diff(pos[oos_start:]) > 0).sum()) + int(pos[oos_start] > 0)
        assert oos_transitions == 13


class TestGenerator:
    def test_long_then_flat_signals(self):
        sessions = _sessions()
        pit = _pit_with_episode("2024-01-03")
        sched = build_hold_schedule(pit, sessions)
        gen = make_episode_hold_generator(sched)
        data = pd.DataFrame({"close": [1.0] * 5}, index=sessions[:5])

        s0 = gen(data.iloc[:2], 1)  # step 1 = 2024-01-02 (before episode)
        assert s0.action == Action.FLAT
        s1 = gen(data.iloc[:3], 2)  # step 2 = 2024-01-03 (entry)
        assert s1.action == Action.LONG
        assert s1.size == 1.0
        assert s1.timestamp == pd.Timestamp("2024-01-03")
        s2 = gen(data.iloc[:4], 3)  # hold
        assert s2.action == Action.LONG
        s3 = gen(data.iloc[:5], 4)  # exit
        assert s3.action == Action.FLAT

    def test_flat_by_default(self):
        sessions = _sessions()
        pit = pd.DataFrame({"date": sessions, "freeze_prob": 0.0})
        sched = build_hold_schedule(pit, sessions)
        gen = make_episode_hold_generator(sched)
        data = pd.DataFrame({"close": [1.0] * 2}, index=sessions[:2])
        assert gen(data, 1).action == Action.FLAT

    def test_lookahead_guard(self):
        sessions = _sessions()
        sched = build_hold_schedule(_pit_with_episode("2024-01-03"), sessions)
        gen = make_episode_hold_generator(sched)
        # Pass the whole frame at step 1 -> len(data) != i+1 -> must raise.
        data = pd.DataFrame({"close": [1.0] * 3}, index=sessions[:3])
        with pytest.raises(AssertionError):
            gen(data, 1)
