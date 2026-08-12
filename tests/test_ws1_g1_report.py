"""WS-1 T6: G1 hand-off — decision record consistency + runner exit.

T6 exit (Execution Blueprint §4): *Final ``WS1_G1_REPORT.md``; if the honest
outcome is 0 trades or negative edge, document the pivot.*  These tests prove
the G1 outcome is *derived* from the locked significance decision (never
hand-typed), the record is self-hash-pinned and metric-cross-checked, and the
runner exits 0 with a consistent record on the real OJ backtest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pakhi.ws1.g1 import (
    DECISION_JSON,
    G1_REPORT,
    OUTCOME_LABEL,
    build_g1_decision,
    g1_decision_consistent,
    record_sha256,
)
from pakhi.ws1.harness import run_harness

HERE = Path(__file__).resolve().parent.parent


def _candidate_report() -> dict:
    return run_harness(candidate=True)


class TestG1Record:
    def test_outcome_derived_from_significance(self):
        rep = _candidate_report()
        record = build_g1_decision(rep)
        # The G1 outcome must equal the locked significance decision verbatim.
        assert record["outcome"] == rep["significance"]["decision"]["outcome"]

    def test_outcome_is_under_powered_on_real_candidate(self):
        rep = _candidate_report()
        assert rep["significance"]["decision"]["outcome"] == "UNDER_POWERED"
        record = build_g1_decision(rep)
        assert record["headline_metric"]["n_events"] == 7

    def test_self_hash_pinned(self):
        record = build_g1_decision(_candidate_report())
        assert g1_decision_consistent(record)
        # Tampering with the outcome breaks the hash.
        tampered = dict(record)
        tampered["outcome"] = "PASS"
        assert not g1_decision_consistent(tampered)

    def test_crosscheck_rejects_metric_mismatch(self):
        record = build_g1_decision(_candidate_report())
        broken = json.loads(json.dumps(record, default=str))
        broken["metrics_crosscheck"]["n_events"] = broken["headline_metric"]["n_events"] + 1
        assert not g1_decision_consistent(broken)

    def test_outcome_labels_cover_all_gate_branches(self):
        assert set(OUTCOME_LABEL) == {"ZERO_TRADES", "UNDER_POWERED", "PASS", "FAIL_PIVOT"}

    def test_record_sha256_deterministic(self):
        a = {"x": [1, 2.5], "y": "z"}
        assert record_sha256(a) == record_sha256(a)
        assert record_sha256(a) != record_sha256({**a, "y": "w"})


class TestRunner:
    def test_runner_exits_zero_and_writes_record(self):
        result = subprocess.run(
            [sys.executable, "scripts/run_t6_g1_report.py"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        path = HERE / DECISION_JSON
        assert path.exists()
        record = json.loads(path.read_text())
        assert record["outcome"] == "UNDER_POWERED"
        assert g1_decision_consistent(record)
        assert "G1" in result.stdout
        assert "UNDER_POWERED" in result.stdout

    def test_decision_json_matches_live_harness(self):
        path = HERE / DECISION_JSON
        if not path.exists():
            pytest.skip("g1_decision.json not generated yet")
        on_disk = json.loads(path.read_text())
        fresh = build_g1_decision(_candidate_report())
        assert on_disk["outcome"] == fresh["outcome"]
        assert on_disk["headline_metric"]["n_events"] == fresh["headline_metric"]["n_events"]


class TestArtifacts:
    def test_report_doc_exists(self):
        assert (HERE / G1_REPORT).exists()

    def test_contract_and_registration_referenced(self):
        record = build_g1_decision(_candidate_report())
        for ref in record["evidence_chain"].values():
            assert (HERE / ref).exists()
