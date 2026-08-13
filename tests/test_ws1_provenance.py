"""WS-1 T2: provenance logging — Signal carries it, the engine injects it.

Covers the full chain: ``Signal.provenance`` (dataclass), engine extraction
into the trade log with ``costs_incurred``, the WS-1 provenance builder from
the real PIT + ICE roll calendar, and the harness report/CSV export.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pakhi.risk.backtest import BacktestEngine
from pakhi.signals.base import Action, Signal
from pakhi.ws1.harness import run_harness
from pakhi.ws1.pit import load_oj, load_pit
from pakhi.ws1.provenance import (
    ARCHIVE,
    MODEL_VERSION,
    build_provenance_map,
    forecast_cycle_id,
    roll_state_table,
)
from pakhi.ws1.signal import build_hold_schedule

IDX = pd.date_range("2023-01-02", periods=8, freq="B")
PRICES = [100, 100, 110, 121, 121, 121, 133.1, 133.1]

PROVENANCE = {
    "forecast_cycle_id": "20230104_12z",
    "publication_ts": "2023-01-04 15:30:00+00:00",
    "model_version": MODEL_VERSION,
    "archive": ARCHIVE,
    "roll_state": {
        "contract_month": "Mar23",
        "adjustment_factor": 1.05,
        "adjustment_type": "back",
        "roll_rule": "FND",
    },
}


def _gen_with_provenance(provenance: dict | None = None):
    prov = PROVENANCE if provenance is None else provenance

    def gen(data: pd.DataFrame, i: int) -> Signal:
        # LONG during sessions 1..2 and 5..6 (2-session holds), FLAT elsewhere.
        pos = 1.0 if i in (1, 2, 5, 6) else 0.0
        if pos > 0:
            return Signal(
                action=Action.LONG,
                size=pos,
                confidence=0.8,
                instrument="OJ_FUTURES",
                timestamp=data.index[i],
                reasoning="test",
                provenance=prov,
            )
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="OJ_FUTURES",
            timestamp=data.index[i],
            reasoning="flat",
        )

    return gen


def _engine_trades(provenance: dict | None = None) -> list[dict]:
    data = pd.DataFrame({"close": PRICES}, index=IDX)
    res = BacktestEngine().run(
        _gen_with_provenance(provenance),
        data,
        initial_capital=100_000,
        commission_bps=5,
        slippage_bps=10,
    )
    return res.trades


class TestSignalProvenance:
    def test_provenance_defaults_to_empty_dict(self):
        s = Signal(Action.LONG, 0.5, 0.8, "OJ_FUTURES", pd.Timestamp("2023-01-04"), "r")
        assert s.provenance == {}

    def test_provenance_preserved_through_post_init(self):
        s = Signal(
            Action.LONG,
            0.5,
            0.8,
            "OJ_FUTURES",
            pd.Timestamp("2023-01-04"),
            "r",
            provenance=PROVENANCE,
        )
        assert s.provenance["forecast_cycle_id"] == "20230104_12z"

    def test_string_action_coerced_with_provenance(self):
        s = Signal(
            "LONG", 0.5, 0.8, "OJ_FUTURES", pd.Timestamp("2023-01-04"), "r", provenance=PROVENANCE
        )
        assert s.action == Action.LONG
        assert s.provenance["roll_state"]["contract_month"] == "Mar23"


class TestEngineInjectProvenance:
    def test_every_trade_carries_provenance(self):
        trades = _engine_trades()
        assert len(trades) == 2
        for t in trades:
            assert t["provenance"] == PROVENANCE

    def test_costs_incurred_30bps_round_trip(self):
        trades = _engine_trades()
        for t in trades:
            assert t["costs_incurred"] == pytest.approx(0.0030, abs=1e-9)
            assert t["costs_bps"] == pytest.approx(30.0, abs=1e-6)

    def test_trade_pnl_fields_preserved(self):
        trades = _engine_trades()
        assert trades[0]["entry_time"] == IDX[1]
        assert trades[0]["exit_time"] == IDX[3]
        assert trades[0]["entry_price"] == 100.0 and trades[0]["exit_price"] == 121.0
        assert trades[0]["return"] == pytest.approx(0.21)

    def test_empty_provenance_gives_empty_dict_in_log(self):
        trades = _engine_trades(provenance={})
        assert trades[0]["provenance"] == {}

    def test_walk_forward_propagates_provenance(self):
        data = pd.DataFrame({"close": PRICES}, index=IDX)
        results = BacktestEngine().walk_forward(
            _gen_with_provenance(),
            data,
            train_window=4,
            test_window=2,
            initial_capital=100_000,
            commission_bps=5,
            slippage_bps=10,
        )
        all_trades = [t for res in results for t in res.trades]
        assert all_trades
        assert all(t["provenance"] == PROVENANCE for t in all_trades)


class TestForecastCycleId:
    def test_format_matches_archive_naming(self):
        assert forecast_cycle_id(pd.Timestamp("2025-11-09"), 12) == "20251109_12z"

    def test_pad_zero_cycle_hour(self):
        assert forecast_cycle_id(pd.Timestamp("2024-01-05"), 6) == "20240105_06z"


class TestRollState:
    def test_contract_mapping_known_date(self):
        cont = pd.read_parquet("data/market/oj_continuous.parquet")
        sess = cont.index
        rs = roll_state_table(sess)
        # 2022-02-15 sits between Jan22 and Mar22 first-notice days -> Mar22.
        assert rs.loc[pd.Timestamp("2022-02-15"), "contract_month"] == "Mar22"
        # Adjustment factor must equal the adj/raw ratio of the continuous series.
        expected = float(
            cont.loc[pd.Timestamp("2022-02-15"), "close_adj"]
            / cont.loc[pd.Timestamp("2022-02-15"), "close_raw"]
        )
        assert rs.loc[pd.Timestamp("2022-02-15"), "adjustment_factor"] == pytest.approx(
            expected, abs=1e-12
        )
        assert rs["roll_rule"].unique().tolist() == ["FND"]
        assert rs["adjustment_type"].unique().tolist() == ["back"]


class TestProvenanceMap:
    @pytest.fixture(scope="class")
    def map_(self):
        pit = load_pit()
        sessions = load_oj().index
        return build_provenance_map(pit, sessions)

    def test_covers_every_held_session(self, map_):
        pit = load_pit()
        sessions = load_oj().index
        sched = build_hold_schedule(pit, sessions)
        held = sessions[sched == 1.0]
        assert len(held) > 0
        assert all(s in map_ for s in held)

    def test_provenance_keys_present(self, map_):
        for prov in map_.values():
            for key in (
                "forecast_cycle_id",
                "publication_ts",
                "model_version",
                "archive",
                "roll_state",
            ):
                assert key in prov
            for rk in ("contract_month", "adjustment_factor", "adjustment_type", "roll_rule"):
                assert rk in prov["roll_state"]

    def test_publication_ts_matches_pit(self, map_):
        pit = load_pit()
        sessions = load_oj().index
        # The 2025-11-09 (Sun) episode fills 2025-11-10; its provenance must
        # carry the PIT publish_time of the 2025-11-09 cycle.
        entry = sessions[sessions >= pd.Timestamp("2025-11-09")][0]
        prov = map_[entry]
        pit_row = pit[pit["date"] == pd.Timestamp("2025-11-09")].iloc[0]
        assert prov["forecast_cycle_id"] == "20251109_12z"
        assert prov["publication_ts"] == str(pit_row["publish_time"])

    def test_roll_state_contract_nonempty(self, map_):
        for prov in map_.values():
            assert prov["roll_state"]["contract_month"]  # truthy month label
            assert prov["roll_state"]["adjustment_factor"] > 0


class TestHarnessProvenance:
    @pytest.fixture(scope="class")
    def report(self):
        return run_harness(pit=load_pit(), oj=load_oj())

    def test_all_trades_have_provenance(self, report):
        pr = report["provenance"]
        assert pr["n_trades"] == 13
        assert pr["n_trades_with_provenance"] == 13

    def test_costs_match_locked_30bps(self, report):
        pr = report["provenance"]
        assert pr["costs_match_locked_round_trip"]
        assert pr["costs_bps_range"][0] == pytest.approx(30.0, abs=1e-3)
        assert pr["costs_bps_range"][1] == pytest.approx(30.0, abs=1e-3)

    def test_forecast_cycle_ids_match_episode_starts(self, report):
        ids = report["provenance"]["forecast_cycle_ids"]
        assert len(ids) == 13
        assert "20251109_12z" in ids  # the v1.1 next-close weekend entry
        assert ids == sorted(ids)

    def test_engine_trades_csv_export(self, tmp_path):
        csv = tmp_path / "trades.csv"
        run_harness(pit=load_pit(), oj=load_oj(), trades_path=csv)
        df = pd.read_csv(csv)
        assert len(df) == 13
        assert "costs_bps" in df.columns
        assert "provenance" in df.columns
        assert df["costs_bps"].sub(30.0).abs().max() < 1e-6

    def test_ledger_carries_provenance_columns(self):
        # The event ledger written to disk carries provenance columns.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "ledger.csv"
            run_harness(pit=load_pit(), oj=load_oj(), ledger_path=csv)
            df = pd.read_csv(csv)
        for col in (
            "forecast_cycle_id",
            "publication_ts",
            "model_version",
            "contract_month",
            "adjustment_factor",
        ):
            assert col in df.columns
        assert (df["forecast_cycle_id"].str.endswith("_12z")).all()
