"""WS-1 T3: Lookahead Armor — timestamp layer, vintage layer, engine guard.

Exit criterion (blueprint T3): *a backtest fed leaked future data immediately
errors out.*  These tests prove both armor layers fire on leaked PIT frames and
that ``BacktestEngine(lookahead_armor=True)`` aborts on future provenance.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd
import pytest

from pakhi.risk.backtest import BacktestEngine, BacktestResult
from pakhi.signals.base import Action, Signal
from pakhi.ws1.armor import (
    FEATURE_HORIZON_HOURS,
    GFS,
    MANIFEST_PATH,
    ROLL_JUMP_SIGMA,
    LookaheadError,
    RollJumpError,
    build_vintage_manifest,
    check_roll_jump_armor,
    check_timestamp_armor,
    check_vintage_armor,
    decision_cutoff,
    run_armor,
)
from pakhi.ws1.harness import run_harness
from pakhi.ws1.pit import load_oj, load_pit

IDX = pd.date_range("2023-01-02", periods=6, freq="B")
PRICES = [100.0, 100.0, 110.0, 121.0, 121.0, 133.1]


@pytest.fixture(scope="module")
def pit():
    return load_pit()


@pytest.fixture(scope="module")
def sessions():
    return load_oj().index


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(build_vintage_manifest(GFS), indent=1))
    return json.loads(MANIFEST_PATH.read_text())


class TestDecisionCutoff:
    def test_est_close_1900_utc(self):
        # January: New York is EST (UTC-5) -> 14:00 = 19:00 UTC.
        assert decision_cutoff(pd.Timestamp("2023-01-10")) == pd.Timestamp("2023-01-10 19:00:00+00:00")

    def test_edt_close_1800_utc(self):
        # July: New York is EDT (UTC-4) -> 14:00 = 18:00 UTC.
        assert decision_cutoff(pd.Timestamp("2023-07-10")) == pd.Timestamp("2023-07-10 18:00:00+00:00")


class TestTimestampArmor:
    def test_passes_on_real_pit(self, pit, sessions):
        detail = check_timestamp_armor(pit, sessions)
        assert detail["publish_after_cutoff"] == 0
        assert detail["event_peak_outside_horizon"] == 0
        assert detail["feature_outcome_separation"] is True
        assert detail["n_rows"] == len(pit)
        assert detail["min_publish_margin_hours"] >= 2.0  # tightest is 2.5h

    def test_raises_on_publish_after_cutoff(self, pit, sessions):
        leaked = pit.copy()
        row = leaked.iloc[0]
        base = sessions[sessions >= pd.Timestamp(row["date"])][0]
        leaked.loc[leaked.index[0], "publish_time"] = decision_cutoff(base) + pd.Timedelta(hours=1)
        with pytest.raises(LookaheadError, match="publish .* after decision cutoff"):
            check_timestamp_armor(leaked, sessions)

    def test_raises_on_event_peak_beyond_horizon(self, pit, sessions):
        leaked = pit.copy()
        leaked.loc[leaked.index[0], "event_peak_time"] = (
            leaked.loc[leaked.index[0], "publish_time"]
            + pd.Timedelta(hours=FEATURE_HORIZON_HOURS + 1)
        )
        with pytest.raises(LookaheadError, match="outside"):
            check_timestamp_armor(leaked, sessions)

    def test_raises_on_missing_feature_column(self, pit, sessions):
        leaked = pit.drop(columns=["temperature_min"])
        with pytest.raises(LookaheadError, match="feature vector incomplete"):
            check_timestamp_armor(leaked, sessions)


class TestVintageArmor:
    def test_passes_on_real_data(self, pit, sessions, manifest):
        detail = check_vintage_armor(pit, manifest=manifest, gfs_dir=None)
        assert detail["archive"] == "noaa-gfs-bdp-pds"
        assert detail["n_cycles_in_manifest"] == detail["n_pit_cycles"]
        assert detail["source_match"] is True
        assert detail["n_hash_drift"] == 0

    def test_no_archive_drift_with_disk_scan(self, pit, sessions, manifest):
        detail = check_vintage_armor(pit, manifest=manifest, gfs_dir=GFS)
        assert detail["n_hash_drift"] == 0

    def test_raises_on_wrong_source(self, pit, sessions, manifest):
        bad = dict(manifest)
        bad["source"] = "aws-other-bucket"
        with pytest.raises(LookaheadError, match="source"):
            check_vintage_armor(pit, manifest=bad, gfs_dir=None)

    def test_raises_on_missing_cycle(self, pit, sessions, manifest):
        bad = dict(manifest)
        bad["cycles"] = dict(manifest["cycles"])
        bad["cycles"].pop(next(iter(bad["cycles"])))
        with pytest.raises(LookaheadError, match="missing from vintage manifest"):
            check_vintage_armor(pit, manifest=bad, gfs_dir=None)

    def test_raises_on_hash_drift(self, pit, sessions, manifest):
        bad = dict(manifest)
        bad["cycles"] = dict(manifest["cycles"])
        first = next(iter(bad["cycles"]))
        bad["cycles"][first] = dict(bad["cycles"][first])
        bad["cycles"][first]["sha256"] = "0" * 64
        with pytest.raises(LookaheadError, match="drifted"):
            check_vintage_armor(pit, manifest=bad, gfs_dir=GFS)

    def test_manifest_structure(self, manifest):
        assert manifest["source"] == "noaa-gfs-bdp-pds"
        assert manifest["n_cycles"] == len(manifest["cycles"])
        first = next(iter(manifest["cycles"].values()))
        assert {"n_files", "nbytes", "sha256"} <= set(first)
        assert first["sha256"] == build_vintage_manifest(GFS)["cycles"][next(iter(manifest["cycles"]))]["sha256"]


class TestRunArmor:
    def test_pass_summary(self, pit, sessions, manifest):
        summary = run_armor(pit, sessions, manifest=manifest, gfs_dir=None)
        assert summary["pass"] is True
        assert "timestamp" in summary and "vintage" in summary


class TestEngineLookaheadArmor:
    def _engine(self, provenance, armor: bool = True) -> BacktestResult:
        data = pd.DataFrame({"close": PRICES}, index=IDX)

        def gen(d, i):
            if i == 2:
                return Signal(
                    action=Action.LONG,
                    size=1.0,
                    confidence=0.8,
                    instrument="X",
                    timestamp=d.index[i],
                    reasoning="t",
                    provenance=provenance,
                )
            return Signal(
                action=Action.FLAT,
                size=0.0,
                confidence=0.0,
                instrument="X",
                timestamp=d.index[i],
                reasoning="flat",
            )

        return BacktestEngine().run(
            gen, data, initial_capital=100_000, commission_bps=5, slippage_bps=10, instrument="X",
            lookahead_armor=armor,
        )

    def test_future_cycle_raises(self):
        with pytest.raises(LookaheadError, match="future cycle"):
            self._engine({"forecast_cycle_id": "20231231_12z"})

    def test_future_publication_raises(self):
        # Session 2023-01-04 (EDT?) is EST; cutoff 19:00 UTC; publish next-day -> leak.
        with pytest.raises(LookaheadError, match="after decision cutoff"):
            self._engine({"publication_ts": "2023-01-05 15:30:00+00:00"})

    def test_future_signal_timestamp_raises(self):
        data = pd.DataFrame({"close": PRICES}, index=IDX)

        def gen(d, i):
            if i == 2:
                return Signal(
                    action=Action.LONG,
                    size=1.0,
                    confidence=0.8,
                    instrument="X",
                    timestamp=IDX[4],  # two days in the future
                    reasoning="t",
                )
            return Signal(
                action=Action.FLAT, size=0.0, confidence=0.0, instrument="X",
                timestamp=d.index[i], reasoning="flat",
            )

        with pytest.raises(LookaheadError, match="signal timestamp"):
            BacktestEngine().run(
                gen, data, initial_capital=100_000, commission_bps=5, slippage_bps=10, instrument="X",
                lookahead_armor=True,
            )

    def test_armor_off_is_lenient(self):
        res = self._engine({"forecast_cycle_id": "20231231_12z"}, armor=False)
        assert len(res.trades) == 1

    def test_walk_forward_propagates_armor(self):
        data = pd.DataFrame({"close": PRICES}, index=IDX)

        def gen(d, i):
            if i == 1:  # fires inside every 2-bar test fold
                return Signal(
                    action=Action.LONG,
                    size=1.0,
                    confidence=0.8,
                    instrument="X",
                    timestamp=d.index[i],
                    reasoning="t",
                    provenance={"forecast_cycle_id": "20231231_12z"},
                )
            return Signal(
                action=Action.FLAT, size=0.0, confidence=0.0, instrument="X",
                timestamp=d.index[i], reasoning="flat",
            )

        with pytest.raises(LookaheadError, match="future cycle"):
            BacktestEngine().walk_forward(
                gen, data, train_window=2, test_window=2,
                initial_capital=100_000, commission_bps=5, slippage_bps=10, instrument="X",
                lookahead_armor=True,
            )

    def test_clean_provenance_passes(self):
        prov = {
            "forecast_cycle_id": "20230104_12z",
            "publication_ts": "2023-01-04 15:30:00+00:00",
        }
        res = self._engine(prov, armor=True)
        assert len(res.trades) == 1
        assert res.trades[0]["provenance"]["forecast_cycle_id"] == "20230104_12z"


class TestHarnessArmor:
    def test_report_has_armor_section(self):
        rep = run_harness(pit=load_pit(), oj=load_oj())
        assert rep["armor"]["pass"] is True
        assert rep["armor"]["timestamp"]["publish_after_cutoff"] == 0
        assert rep["armor"]["vintage"]["n_cycles_in_manifest"] == 1612

    def test_leaked_pit_errors_out(self):
        # T3 exit: a backtest fed leaked future data immediately errors out.
        leaked = load_pit()
        row = leaked.iloc[0]
        base = load_oj().index[load_oj().index >= pd.Timestamp(row["date"])][0]
        leaked.loc[leaked.index[0], "publish_time"] = decision_cutoff(base) + pd.Timedelta(hours=1)
        with pytest.raises(LookaheadError):
            run_harness(pit=leaked, oj=load_oj())

    def test_armor_can_be_disabled(self):
        leaked = load_pit()
        row = leaked.iloc[0]
        base = load_oj().index[load_oj().index >= pd.Timestamp(row["date"])][0]
        leaked.loc[leaked.index[0], "publish_time"] = decision_cutoff(base) + pd.Timedelta(hours=1)
        rep = run_harness(pit=leaked, oj=load_oj(), armor=False)
        assert rep["valid"] is True


class TestRollJumpArmor:
    """T4 §9.3: halt on unmodeled roll-date gaps > X × daily_σ (X = 5, WS-0)."""

    def _prices_with_jump(self, jump_date: str, multiple: float) -> pd.DataFrame:
        oj = load_oj().copy()
        idx = oj.index[oj.index >= pd.Timestamp(jump_date)]
        assert not idx.empty
        d = idx[0]
        pos = oj.index.get_loc(d)
        oj.iloc[pos, oj.columns.get_loc("close_adj")] = (
            float(oj.iloc[pos - 1]["close_adj"]) * multiple
        )
        return oj

    def test_passes_on_real_data(self, pit, sessions):
        detail = check_roll_jump_armor(pit, sessions)
        assert detail["n_rolls"] == 34
        assert detail["n_flagged_rolls"] == 0
        assert detail["unmodeled_roll_gaps"] == []
        # The stricter ±3-day net reports the real 2023-11-02 crash as context.
        assert detail["n_near_roll_extreme_moves"] == 1
        mv = detail["near_roll_extreme_moves"][0]
        assert mv["date"] == "2023-11-02"
        assert mv["weather_co_located"] is False
        assert detail["x_sigma"] == ROLL_JUMP_SIGMA

    def test_run_armor_includes_roll_jump_layer(self, pit, sessions, manifest):
        summary = run_armor(pit, sessions, manifest=manifest, gfs_dir=None)
        assert summary["pass"] is True
        assert summary["roll_jump"]["n_flagged_rolls"] == 0

    def test_raises_on_unmodeled_roll_gap(self, pit, sessions):
        # Inject a 2x close gap AT a roll date (2023-11-01) with no freeze
        # episode co-located -> the run must be INVALID (RollJumpError).
        oj = self._prices_with_jump("2023-11-01", 2.0)
        with pytest.raises(RollJumpError, match="unmodeled roll-date gaps"):
            check_roll_jump_armor(pit, sessions, oj=oj)

    def test_weather_co_located_roll_gap_is_allowed(self, sessions):
        # Same 2x roll gap, but with a modeled freeze episode filling exactly on
        # the roll date -> weather-driven, so the run proceeds.
        pit = pd.DataFrame(
            {
                "date": [pd.Timestamp("2023-11-01")],
                "freeze_prob": [0.1],
                "temperature_min": [-5.0],
            }
        )
        oj = self._prices_with_jump("2023-11-01", 2.0)
        detail = check_roll_jump_armor(pit, sessions, oj=oj)
        assert detail["n_flagged_rolls"] == 1
        assert detail["unmodeled_roll_gaps"] == []

    def test_harness_report_exposes_roll_jump(self):
        rep = run_harness(pit=load_pit(), oj=load_oj())
        rj = rep["armor"]["roll_jump"]
        assert rj["n_flagged_rolls"] == 0
        assert rj["x_sigma"] == 5.0


class TestStandaloneRunner:
    def test_t3_armor_script_exits_zero_on_real_data(self):
        r = subprocess.run(
            [sys.executable, "scripts/run_t3_armor.py"], capture_output=True, text=True
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "T3 Lookahead Armor: PASS" in r.stdout
