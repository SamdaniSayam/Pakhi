"""WS-2 T0: live paper-trading protocol pre-registration.

T0 exit (WS-2 blueprint §4): *protocol + machine JSON approved and hash-pinned;
artifacts exist.*  These tests prove the protocol is pre-registered (before any
live event), the frozen θ_p is *derived* from the historical PIT frame (never
hand-typed), the payload is self-hash-pinned, and the machine artifact exists
and is consistent with a fresh live derivation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pakhi.ws1.pit import benchmark_2sess, load_pit
from pakhi.ws1.significance import N_MIN
from pakhi.ws2.protocol import (
    G1_DATE,
    PROTOCOL_DOC,
    PROTOCOL_JSON,
    build_paper_trading_protocol,
    frozen_theta_p,
    payload_sha256,
    protocol_consistent,
)

HERE = Path(__file__).resolve().parent.parent
JSON_PATH = HERE / PROTOCOL_JSON


class TestFrozenThetaP:
    def test_median_of_historical_freeze_rows(self):
        pit = load_pit()
        theta = frozen_theta_p(pit, G1_DATE)
        freeze = pit.loc[
            (pit["freeze_prob"] > 0) & (pit["date"] <= G1_DATE), "freeze_prob"
        ]
        assert theta["theta_p"] == pytest.approx(freeze.median(), abs=1e-15)
        assert theta["theta_t"] == 0.0

    def test_known_frozen_value(self):
        # Locked in the human protocol doc (2026-08-12).
        assert frozen_theta_p(load_pit(), G1_DATE)["theta_p"] == pytest.approx(0.03636363636363636, abs=1e-15)

    def test_freeze_rows_count(self):
        pit = load_pit()
        freeze = pit.loc[(pit["freeze_prob"] > 0) & (pit["date"] <= G1_DATE)]
        assert len(freeze) == 55

    def test_payload_freeze_rows_count_consistent(self):
        rec = build_paper_trading_protocol()
        assert rec["signal"]["theta_p_n_historical_freeze_rows"] == 55

    def test_candidate_estimator_used(self):
        # Single source of truth: same median estimator as the WS-1 backtest.
        pit = load_pit()
        from pakhi.ws1.candidate import estimate_thresholds
        assert frozen_theta_p(pit, G1_DATE) == estimate_thresholds(pit[pit["date"] <= G1_DATE])


class TestProtocolPayload:
    def test_self_hash_pinned(self):
        rec = build_paper_trading_protocol()
        assert protocol_consistent(rec)
        tampered = dict(rec)
        tampered["signal"]["theta_p"] = 0.5
        assert not protocol_consistent(tampered)

    def test_payload_sha256_deterministic(self):
        a = {"theta_p": 0.0364, "rules": ["next-close fill"]}
        assert payload_sha256(a) == payload_sha256(a)
        assert payload_sha256(a) != payload_sha256({**a, "rules": ["prior-close fill"]})

    def test_theta_p_derived_not_typed(self):
        rec = build_paper_trading_protocol()
        assert rec["signal"]["theta_p"] == frozen_theta_p(load_pit(), G1_DATE)["theta_p"]

    def test_locked_rules_present(self):
        rec = build_paper_trading_protocol()
        tr = rec["trade"]
        assert tr["entry"] == (
            "fill at the first trading-session close ON/AFTER the firing row's "
            "cycle date; same-day for trading days, next trading close for "
            "weekend/holiday cycles; NEVER prior close"
        )
        assert tr["costs_bps_round_trip"] == 30
        assert rec["benchmark"]["rbar_2sess_oos_backtest"] == pytest.approx(benchmark_2sess(load_pit()), abs=1e-12)
        assert rec["event_counting"]["n_min"] == N_MIN
        assert rec["cycle"]["signal_cycle"] == "12Z"

    def test_anti_gaming_and_change_control(self):
        rec = build_paper_trading_protocol()
        joined = "\n".join(rec["anti_gaming"])
        assert "BEFORE any live event" in joined
        assert "no live re-estimation" in joined
        assert "new version + re-lock" in rec["change_control"]

    def test_g1_predecessor_consistent(self):
        rec = build_paper_trading_protocol()
        assert rec["predecessor"]["g1_outcome"] == "UNDER_POWERED"
        assert rec["predecessor"]["g1_n_events"] == 7


class TestArtifacts:
    def test_machine_json_exists_and_consistent(self):
        assert JSON_PATH.exists()
        rec = json.loads(JSON_PATH.read_text())
        assert protocol_consistent(rec)

    def test_machine_json_matches_fresh_build(self):
        on_disk = json.loads(JSON_PATH.read_text())
        fresh = build_paper_trading_protocol()
        assert on_disk["signal"]["theta_p"] == fresh["signal"]["theta_p"]
        assert on_disk["version"] == fresh["version"]
        assert on_disk["event_counting"]["n_min"] == fresh["event_counting"]["n_min"]

    def test_human_doc_exists(self):
        assert (HERE / PROTOCOL_DOC).exists()

    def test_doc_embeds_payload_hash(self):
        rec = json.loads(JSON_PATH.read_text())
        doc = (HERE / PROTOCOL_DOC).read_text()
        assert rec["payload_sha256"][:8] in doc


class TestRunner:
    def test_runner_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "scripts/run_ws2_t0_protocol.py"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        assert "FROZEN" in result.stdout
        assert "pre-registration" in result.stdout.lower()
        assert json.loads(JSON_PATH.read_text())["payload_sha256"] in result.stdout
