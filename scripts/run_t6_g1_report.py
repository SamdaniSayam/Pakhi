#!/usr/bin/env python3
"""WS-1 T6: G1 hand-off — full OJ backtest + decision record.

Usage:
    python scripts/run_t6_g1_report.py

Runs the pre-registered ColdGrip candidate end-to-end on the OJ wedge
instrument with all armor layers (timestamp + vintage + roll-jump), derives the
locked G1 decision from the significance report, and writes the machine twin of
the decision report:

    data/ws1/g1_decision.json      G1 decision record (self-hash-pinned)

Exit code 0 when the run is valid, armored, and the G1 record is consistent
with its own payload hash; 1 otherwise (INVALID run / inconsistent record).
"""

from __future__ import annotations

import json
from pathlib import Path

from pakhi.ws1.g1 import build_g1_decision, g1_decision_consistent
from pakhi.ws1.harness import run_harness

HERE = Path(__file__).resolve().parent.parent
WS1 = HERE / "data" / "ws1"


def main() -> None:
    WS1.mkdir(parents=True, exist_ok=True)
    decision_path = WS1 / "g1_decision.json"

    report = run_harness(candidate=True)
    if not report["valid"]:
        print("INVALID PIT:", report["validation"])
        raise SystemExit(1)

    sig = report["significance"]
    xv = report["engine_context"]["cross_validation"]

    record = build_g1_decision(report)
    decision_path.write_text(json.dumps(record, indent=2, default=str))

    print("== WS-1 T6: G1 hand-off (OJ backtest + decision) ==")
    print(f"signal            : {report['signal']['name']} (pre-registered, one-shot)")
    print("armor             : PASS (timestamp + vintage + roll-jump layers)")
    print(
        f"engine cross-val  : matched {xv['matched_trades']} trades | "
        f"max |d return| {xv['max_return_abs_error']:.2e} | price mismatches {xv['price_mismatches']}"
    )

    print("\n-- G1 headline (net-of-benchmark event-trade Sharpe, OOS) --")
    print(f"N                  : {sig['n_events']}  (N_min = 8)")
    print(f"power class        : {sig['power_class']}")
    print(f"mean net-of-bench  : {sig['mean_net_of_benchmark'] * 100:+.4f}%")
    print(
        f"event Sharpe       : {sig['net_of_benchmark_sharpe']:.3f}  "
        f"(95% CI {sig['ci_95_net_of_benchmark_sharpe'][0]:.3f}, "
        f"{sig['ci_95_net_of_benchmark_sharpe'][1]:.3f})"
    )
    print(
        f"classic t / NW t   : {sig['classic_t']:.3f} / {sig['newey_west_t']:.3f} (lag {sig['newey_west_lag']})"
    )
    print(f"bootstrap p (edge) : {sig['bootstrap_pvalue_edge_gt_zero']:.3f}")
    print(f"overlap check      : {sig['overlap_check']}")
    print(
        f"benchmark (2-sess) : {report['locked']['benchmark_2sess_pct']:+.4f}% | "
        f"span {report['locked']['span_years']} y | OOS rows {report['locked']['oos_rows']}"
    )

    print(f"\nG1 outcome         : {record['outcome']}")
    print(f"  {record['outcome_statement']}")
    print(f"  {record['decision_reason']}")

    assert g1_decision_consistent(record), "G1 record self-hash/cross-check broken"
    print("\nG1 decision record: self-verifying (sha256 pinned) and metric-consistent")
    print(f"wrote    : {decision_path}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
