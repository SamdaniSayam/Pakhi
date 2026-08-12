"""WS-1 T6: G1 hand-off — decision record built from the live significance report.

T6 exit (Execution Blueprint §4): *Final ``WS1_G1_REPORT.md``; if the honest
outcome is 0 trades or negative edge, document the pivot.*  The whole run is
strictly on the OJ wedge instrument — NG, HDD/CDD, ensemble disagreement and
60-day paper-trading are explicitly deferred to post-G1 / Phase 2.

This module turns the candidate harness report's :func:`significance_report`
decision into the machine-readable G1 record (twin of the human
``docs/WS1_G1_REPORT.md``), self-hash-pinned exactly like the locked contract
and candidate-registration artifacts, so the outcome is falsifiable and
non-gamable after the fact.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json

__all__ = [
    "DECISION_JSON",
    "G1_REPORT",
    "OUTCOME_LABEL",
    "build_g1_decision",
    "g1_decision_consistent",
    "record_sha256",
]

# machine twin of the human report (same convention as evaluation_contract.json)
G1_REPORT = "docs/WS1_G1_REPORT.md"
DECISION_JSON = "data/ws1/g1_decision.json"

OUTCOME_LABEL = {
    "ZERO_TRADES": "architecture success (fast rigorous disproof; not a failure)",
    "UNDER_POWERED": "no conclusion; defers to Phase 2 live paper-trading to accumulate events",
    "PASS": "G1 cleared; proceed to WS-2",
    "FAIL_PIVOT": "edge refuted; documented pivot",
}


def record_sha256(payload: dict) -> str:
    """Self-verifying hash over the canonical JSON payload (excluding itself)."""
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()


def build_g1_decision(report: dict) -> dict:
    """Compute the G1 decision record from a candidate harness report.

    The outcome is *derived*, never hand-typed: it copies the locked
    :func:`~pakhi.ws1.significance.significance_report` decision
    (N gate + Sharpe>1.0 + CI lower bound, Evaluation Contract §8) and
    cross-checks the headline numbers against the metrics section.
    """
    sig = report["significance"]
    metrics = report["metrics"]
    decision = sig["decision"]
    outcome = decision["outcome"]

    record = {
        "gate": "G1",
        "instrument": report.get("signal", {}).get("name", "ColdGrip"),
        "decision_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "outcome": outcome,
        "outcome_statement": OUTCOME_LABEL[outcome],
        "decision_reason": decision["reason"],
        "headline_metric": {
            "net_of_benchmark_event_sharpe": sig["net_of_benchmark_sharpe"],
            "ci_95_lower": sig["ci_95_net_of_benchmark_sharpe"][0],
            "ci_95_upper": sig["ci_95_net_of_benchmark_sharpe"][1],
            "bootstrap_pvalue_edge_gt_zero": sig["bootstrap_pvalue_edge_gt_zero"],
            "n_events": sig["n_events"],
            "power_class": sig["power_class"],
            "mean_net_of_benchmark": sig["mean_net_of_benchmark"],
            "classic_t": sig["classic_t"],
            "newey_west_t": sig["newey_west_t"],
            "newey_west_lag": sig["newey_west_lag"],
        },
        "metrics_crosscheck": {
            "n_events": metrics["n_events"],
            "net_of_benchmark_sharpe": metrics["net_of_benchmark_sharpe"],
        },
        "evidence_chain": {
            "evaluation_contract": "docs/WS1_EVALUATION_CONTRACT.md",
            "contract_json": "data/ws1/evaluation_contract.json",
            "candidate_registration": "docs/T4_CANDIDATE_REGISTRATION.md",
            "candidate_json": "data/ws1/t4_candidate.json",
            "harness_report": "data/ws1/t4_candidate_report.json",
            "decision_report": G1_REPORT,
        },
        "phase_2": {
            "scope": "60-day live paper-trading harness to accumulate OOS event-trades",
            "entry_criterion": "grow N >= N_min (8) so G1 can reach a statistical verdict",
            "re_evaluation": "G1 re-run on the paper-trading event ledger; verdict updates on data",
        },
        "note": (
            "Strictly OJ (NG, CME HDD/CDD, ensemble disagreement index deferred per "
            "Execution Blueprint §4 T6). One-shot: the pre-registered ColdGrip "
            "candidate is scored exactly once against the locked contract; no "
            "re-tuning after any fold is scored."
        ),
    }
    record["payload_sha256"] = record_sha256(record)
    return record


def g1_decision_consistent(record: dict) -> bool:
    """True iff the record's self-hash and metric cross-checks still hold."""
    if record.get("payload_sha256") != record_sha256({k: v for k, v in record.items() if k != "payload_sha256"}):
        return False
    hm = record["headline_metric"]
    mc = record["metrics_crosscheck"]
    return (
        hm["n_events"] == mc["n_events"]
        and abs(hm["net_of_benchmark_event_sharpe"] - mc["net_of_benchmark_sharpe"]) < 1e-9
    )
