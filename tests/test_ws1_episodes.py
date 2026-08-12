"""WS-1: locked freeze-episode segmentation (§2, v1.1) — 16 total / 13 OOS.

v1.1: episode gaps are measured between **executable fill sessions** (first
trading session on/after the cycle date), not calendar days.  A weather event
interrupted by a weekend/holiday merges into one episode instead of fragmenting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.ws1.episodes import episode_summary, freeze_episodes
from pakhi.ws1.pit import load_oj, load_pit, oos_mask

EXPECTED_STARTS = [
    "2022-01-21",
    "2022-01-27",
    "2022-03-11",
    "2022-12-21",
    "2023-01-13",
    "2024-01-15",
    "2025-01-05",
    "2025-01-18",
    "2025-02-19",
    "2025-11-09",
    "2025-12-13",
    "2025-12-29",
    "2026-01-14",
    "2026-01-25",
    "2026-01-30",
    "2026-02-21",
]
EXPECTED_OOS_STARTS = EXPECTED_STARTS[3:]  # 13 starts inside the OOS window


@pytest.fixture(scope="module")
def sessions() -> pd.DatetimeIndex:
    return load_oj().index


@pytest.fixture(scope="module")
def ep(sessions) -> pd.DataFrame:
    return freeze_episodes(load_pit(), sessions)


class TestLockedEpisodeCounts:
    def test_sixteen_episodes_total(self, ep):
        assert ep.loc[ep["episode_start"], "episode_id"].nunique() == 16

    def test_thirteen_oos_episodes(self, ep):
        oos_starts = ep["episode_start"] & oos_mask(ep)
        assert ep.loc[oos_starts, "episode_id"].nunique() == 13

    def test_exact_start_dates(self, ep):
        got = ep.loc[ep["episode_start"], "date"].dt.strftime("%Y-%m-%d").tolist()
        assert got == EXPECTED_STARTS

    def test_exact_oos_start_dates(self, ep):
        got = ep.loc[ep["episode_start"] & oos_mask(ep), "date"].dt.strftime("%Y-%m-%d").tolist()
        assert got == EXPECTED_OOS_STARTS

    def test_episode_ids_are_sequential_from_1(self, ep):
        ids = sorted(ep.loc[ep["is_freeze"], "episode_id"].unique())
        assert ids == list(range(1, 17))

    def test_no_duplicate_starts_per_episode(self, ep):
        starts = ep.loc[ep["episode_start"]]
        assert len(starts) == starts["episode_id"].nunique()

    def test_summary_matches_segmentation(self, ep, sessions):
        summary = episode_summary(load_pit(), sessions)
        assert len(summary) == 16
        assert summary["start_date"].min() == pd.Timestamp("2022-01-21")
        assert summary["start_date"].max() == pd.Timestamp("2026-02-21")


class TestGapSemantics:
    """Locked v1.1 rule: splits when fill sessions are >= 2 sessions apart.

    Sessions are business days (2024-01-01 is a Monday), so a Fri/Sat/Sun
    freeze all fill at the next Monday -> one episode (weekend merge).
    """

    @pytest.fixture
    def sessions(self) -> pd.DatetimeIndex:
        return pd.bdate_range("2024-01-01", periods=22)  # 2024-01-01 Mon .. 01-30

    def _pit(self, freeze_dates, prob=0.1):
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        df = pd.DataFrame({"date": dates, "freeze_prob": 0.0})
        for d in freeze_dates:
            df.loc[df["date"] == pd.Timestamp(d), "freeze_prob"] = prob
        return df

    def test_two_session_boundary_keeps_episode(self, sessions):
        # Jan 05 (Fri) and Jan 09 (Tue): fills Fri, Tue (1 session between) -> same.
        pit = self._pit(["2024-01-05", "2024-01-09"])
        ep = freeze_episodes(pit, sessions)
        ids = ep.loc[ep["is_freeze"], "episode_id"].tolist()
        assert ids == [1, 1]
        assert ep.loc[ep["episode_start"], "date"].tolist() == [pd.Timestamp("2024-01-05")]

    def test_three_session_gap_starts_new_episode(self, sessions):
        # Jan 05 (Fri) and Jan 10 (Wed): fills Fri, Wed (2 sessions between) -> new.
        pit = self._pit(["2024-01-05", "2024-01-10"])
        ep = freeze_episodes(pit, sessions)
        ids = ep.loc[ep["is_freeze"], "episode_id"].tolist()
        assert ids == [1, 2]

    def test_weekend_freeze_merges_into_one_episode(self, sessions):
        # The v1.1 fix: Fri + Sat + Sun freezes all fill at Monday -> ONE episode.
        pit = self._pit(["2024-01-05", "2024-01-06", "2024-01-07"])
        ep = freeze_episodes(pit, sessions)
        ids = ep.loc[ep["is_freeze"], "episode_id"].tolist()
        assert ids == [1, 1, 1]
        assert ep.loc[ep["episode_start"], "date"].tolist() == [pd.Timestamp("2024-01-05")]

    def test_weekend_and_following_monday_merge(self, sessions):
        # Sat freeze fills Mon, and a Mon freeze fills Mon -> same episode.
        pit = self._pit(["2024-01-06", "2024-01-08"])
        ep = freeze_episodes(pit, sessions)
        assert ep.loc[ep["is_freeze"], "episode_id"].nunique() == 1

    def test_non_freeze_rows_do_not_split(self, sessions):
        pit = self._pit(["2024-01-05", "2024-01-07"])
        ep = freeze_episodes(pit, sessions)
        # Jan 06 (non-freeze) must not start an episode.
        assert not ep.loc[ep["date"] == pd.Timestamp("2024-01-06"), "episode_start"].any()

    def test_consecutive_freeze_rows_share_episode(self, sessions):
        pit = self._pit(["2024-01-05", "2024-01-06"])
        ep = freeze_episodes(pit, sessions)
        assert ep.loc[ep["is_freeze"], "episode_id"].tolist() == [1, 1]

    def test_zero_probability_never_fires(self, sessions):
        pit = self._pit([])
        ep = freeze_episodes(pit, sessions)
        assert not ep["episode_start"].any()
        assert (ep["episode_id"] == 0).all()
        assert not ep["is_freeze"].any()

    def test_exact_two_session_boundary_is_same_episode(self, sessions):
        # Locked: fill sessions >= 2 apart splits; exactly 1 session between
        # fills (boundary of the rule) stays the same episode.
        pit = self._pit(["2024-01-05", "2024-01-09"])
        ep = freeze_episodes(pit, sessions)
        assert ep.loc[ep["is_freeze"], "episode_id"].nunique() == 1


class TestRealDataInvariants:
    def test_oos_freeze_rows_consistent(self, ep):
        # Every OOS freeze row belongs to a real episode (id >= 1).
        oos_freezing = ep["is_freeze"] & oos_mask(ep)
        assert (ep.loc[oos_freezing, "episode_id"] >= 1).all()
        # Episode ids never repeat non-contiguously.
        ids = ep.loc[ep["is_freeze"], "episode_id"].to_numpy()
        assert np.all(np.diff(ids) >= 0)
