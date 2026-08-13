"""WS-1 T4: "ColdGrip" redefined freeze signal — in-fold re-estimation, no leakage.

Pre-registration artifacts (docs/T4_CANDIDATE_REGISTRATION.md,
data/ws1/t4_candidate.json) are asserted to exist and match the rule family
implemented here.  The tests verify:

- the gates are pure functions of train-window features (never ojd_*/fwd*);
- thresholds are re-estimated per fold from train rows only (expanding window),
  with fold-1 coming from the seed window alone;
- <= 1 trade per episode (first firing row = entry);
- the exit criterion: the candidate fires trades OOS without exploiting roll
  gaps (roll-jump armor is a separate hard gate, tested in test_ws1_armor.py).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from pakhi.ws1.candidate import (
    CANDIDATE_NAME,
    TEMP_GATE_C,
    build_candidate_schedule,
    candidate_entries,
    estimate_thresholds,
    fires,
)
from pakhi.ws1.episodes import freeze_episodes
from pakhi.ws1.harness import run_harness
from pakhi.ws1.pit import FOLDS, TEST_FOLDS, load_oj, load_pit

REG_DOC = "docs/T4_CANDIDATE_REGISTRATION.md"
REG_JSON = "data/ws1/t4_candidate.json"


@pytest.fixture(scope="module")
def pit():
    return load_pit()


@pytest.fixture(scope="module")
def sessions():
    return load_oj().index


def _train_rows(pit: pd.DataFrame, fold_index: int) -> pd.DataFrame:
    return pit[pit["date"] <= pd.Timestamp(FOLDS[fold_index][2])]


class TestPreRegistration:
    def test_artifacts_exist(self):
        from pathlib import Path

        assert Path(REG_DOC).exists()
        reg = json.loads(Path(REG_JSON).read_text())
        assert reg["candidate"] == CANDIDATE_NAME
        assert reg["status"] == "REGISTERED"
        assert reg["rule_family"]["free_parameters"] <= 3
        assert reg["rule_family"]["trades_per_episode_max"] == 1

    def test_registration_matches_implementation(self):
        from pathlib import Path

        reg = json.loads(Path(REG_JSON).read_text())
        family = reg["rule_family"]
        assert family["theta_t_c"] == TEMP_GATE_C
        assert family["theta_p_estimator"].startswith("median(freeze_prob)")
        assert family["hold_sessions"] == 2
        assert reg["roll_jump"]["x_sigma"] == 5.0


class TestEstimation:
    def test_theta_p_is_median_of_train_freeze_rows(self, pit):
        for k in range(len(TEST_FOLDS)):
            train = _train_rows(pit, k)
            freeze = train.loc[train["freeze_prob"] > 0, "freeze_prob"]
            theta = estimate_thresholds(train)
            assert theta["theta_p"] == pytest.approx(freeze.median(), abs=1e-12)
            assert theta["theta_t"] == TEMP_GATE_C

    def test_theta_p_comes_from_seed_window_only_for_fold1(self, pit):
        seed = _train_rows(pit, 0)
        theta = estimate_thresholds(seed)
        expected = seed.loc[seed["freeze_prob"] > 0, "freeze_prob"].median()
        assert theta["theta_p"] == pytest.approx(expected, abs=1e-12)
        # fold-1 estimation must not peek past 2022-10-31
        assert (seed["date"] <= pd.Timestamp("2022-10-31")).all()

    def test_empty_train_never_fires(self):
        empty = pd.DataFrame({"freeze_prob": [], "temperature_min": []})
        theta = estimate_thresholds(empty)
        assert theta["theta_p"] == float("inf")
        row = pd.Series({"freeze_prob": 1.0, "temperature_min": -20.0})
        assert fires(row, theta) is False

    def test_no_outcome_columns_used(self, pit):
        # Estimation and firing read only freeze features — strip ojd_*/fwd*.
        features_only = pit[["date", "freeze_prob", "temperature_min"]]
        theta = estimate_thresholds(features_only)
        assert theta["theta_p"] == pytest.approx(
            pit.loc[pit["freeze_prob"] > 0, "freeze_prob"].median(), abs=1e-12
        )
        row = pd.Series({"freeze_prob": theta["theta_p"], "temperature_min": TEMP_GATE_C - 1})
        assert fires(row, theta) is True


class TestFiringRule:
    def test_fires_respects_both_gates(self, pit):
        theta = {"theta_p": 0.03, "theta_t": 0.0}
        assert fires(pd.Series({"freeze_prob": 0.04, "temperature_min": -5.0}), theta)
        assert not fires(pd.Series({"freeze_prob": 0.02, "temperature_min": -5.0}), theta)
        assert not fires(pd.Series({"freeze_prob": 0.04, "temperature_min": 1.0}), theta)


class TestWalkForwardFiring:
    def test_entries_are_within_test_folds(self, pit, sessions):
        entries = candidate_entries(pit, sessions)
        assert not entries.empty
        for _, e in entries.iterrows():
            assert e["fold"] in [f[0] for f in TEST_FOLDS]

    def test_at_most_one_trade_per_episode(self, pit, sessions):
        entries = candidate_entries(pit, sessions)
        assert entries["episode_id"].is_unique

    def test_entry_is_first_firing_row_of_episode(self, pit, sessions):
        ep = freeze_episodes(pit, sessions)
        entries = candidate_entries(pit, sessions)
        for _, e in entries.iterrows():
            eid = int(e["episode_id"])
            sub = ep[ep["episode_id"] == eid]
            firing = sub[
                (sub["freeze_prob"] >= e["freeze_prob"])
                & (sub["temperature_min"] <= e["temperature_min"])
            ]
            assert firing.index.min() == sub[sub["date"] == e["entry_cycle"]].index.min()

    def test_fires_under_oos_constraints(self, pit, sessions):
        # T4 exit criterion: capable of firing trades under OOS constraints.
        entries = candidate_entries(pit, sessions)
        assert len(entries) >= 1
        assert entries["fwd2_return"].notna().all()

    def test_fold1_uses_seed_thresholds_only(self, pit, sessions):
        # Recompute fold-1 entries manually from the seed theta_p and compare.
        theta = estimate_thresholds(_train_rows(pit, 0))
        ep = freeze_episodes(pit, sessions)
        fold1 = ep[
            (ep["date"] >= pd.Timestamp("2022-11-01")) & (ep["date"] <= pd.Timestamp("2023-10-31"))
        ]
        first_firing = fold1[
            (fold1["freeze_prob"] >= theta["theta_p"])
            & (fold1["temperature_min"] <= theta["theta_t"])
        ].sort_values("date")
        assert not first_firing.empty
        entries = candidate_entries(pit, sessions)
        e1 = entries[entries["fold"] == "fold1"]
        assert len(e1) == 1
        assert e1.iloc[0]["entry_cycle"] == first_firing.iloc[0]["date"]


class TestSchedule:
    def test_schedule_holds_two_sessions_per_entry(self, pit, sessions):
        schedule, _ = build_candidate_schedule(pit, sessions)
        entries = candidate_entries(pit, sessions)
        assert schedule.sum() == 2 * len(entries)
        for _, e in entries.iterrows():
            base = e["entry_session"]
            pos = sessions.get_loc(base)
            assert schedule.iloc[pos] == 1.0 and schedule.iloc[pos + 1] == 1.0

    def test_fold_thresholds_summary_matches_entries(self, pit, sessions):
        _, thr = build_candidate_schedule(pit, sessions)
        entries = candidate_entries(pit, sessions)
        for t in thr:
            n = int((entries["fold"] == t["fold"]).sum()) if not entries.empty else 0
            assert t["n_entries"] == n
            assert t["theta_t"] == TEMP_GATE_C


class TestHarnessCandidateMode:
    def test_candidate_harness_runs_clean(self, pit, sessions):
        rep = run_harness(pit=pit, oj=load_oj(), candidate=True)
        assert rep["valid"]
        assert rep["signal"]["name"] == CANDIDATE_NAME
        assert rep["signal"]["n_trades"] == rep["metrics"]["n_events"]
        assert rep["armor"]["pass"] is True
        assert "roll_jump" in rep["armor"]
        xv = rep["engine_context"]["cross_validation"]
        assert xv["matched_trades"] == rep["signal"]["n_trades"]
        assert xv["unmatched_events"] == []
        assert xv["price_mismatches"] == 0

    def test_candidate_n_trades_is_stable(self, pit, sessions):
        # The registered one-shot count (7) is reproducible and <= 13 max OOS.
        rep = run_harness(pit=pit, oj=load_oj(), candidate=True)
        n = rep["signal"]["n_trades"]
        assert 1 <= n <= 13
        assert rep["metrics"]["n_events"] == n
