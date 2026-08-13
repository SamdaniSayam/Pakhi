#!/usr/bin/env python3
"""WS-2 T4 CLI: G1 re-run & G2 handoff on the live paper ledger.

Usage:
    python scripts/run_ws2_t4_g2_report.py
    python scripts/run_ws2_t4_g2_report.py --db sqlite:///data/ws2/paper.db
    python scripts/run_ws2_t4_g2_report.py --out data/ws2/g2_decision.json

Runs the **exact** ``pakhi.ws1.significance.significance_report`` on the live
scored paper events, derives the G2 decision (same N / Sharpe / CI rules as G1),
and writes the self-hash-pinned machine twin + the human report:

    data/ws2/g2_decision.json      G2 decision record (self-hash-pinned)
    docs/WS2_G2_REPORT.md          human report

Exit 0 when the record is self-consistent with its payload hash; 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pakhi.ws2.db import get_engine
from pakhi.ws2.g2 import G2_DECISION_JSON, G2_REPORT, g2_decision_consistent, produce_g2_report

HERE = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="sqlite:///data/ws2/paper.db",
        help="Paper-ledger DB (default: sqlite:///data/ws2/paper.db)",
    )
    parser.add_argument(
        "--out",
        default=str(HERE / G2_DECISION_JSON),
        help="Machine-twin output path (default: data/ws2/g2_decision.json)",
    )
    parser.add_argument(
        "--md",
        default=str(HERE / G2_REPORT),
        help="Human report path (default: docs/WS2_G2_REPORT.md)",
    )
    args = parser.parse_args()

    engine = get_engine(args.db)
    record = produce_g2_report(engine, out_json=args.out, out_md=args.md)

    hm = record["headline_metric"]
    ll = record["live_ledger"]
    print("== WS-2 T4: G2 handoff (G1 re-run on the live paper ledger) ==")
    print(f"scored events      : {ll['n_scored_events']}  (N_min = {ll['n_min']})")
    print(f"ledger rows        : {ll['n_ledger_rows']}")
    print(
        f"event Sharpe       : {hm['net_of_benchmark_event_sharpe']:.3f}  "
        f"(95% CI {hm['ci_95_lower']:.3f}, {hm['ci_95_upper']:.3f})"
    )
    print(
        f"classic t / NW t   : {hm['classic_t']:.3f} / {hm['newey_west_t']:.3f} "
        f"(lag {hm['newey_west_lag']})"
    )
    print(f"bootstrap p (edge) : {hm['bootstrap_pvalue_edge_gt_zero']:.3f}")
    print(f"G1 predecessor     : {record['g1_predecessor']['outcome']}")
    print(f"\nG2 outcome         : {record['outcome']}")
    print(f"  {record['outcome_statement']}")
    print(f"  {record['decision_reason']}")

    assert g2_decision_consistent(record), "G2 record self-hash/cross-check broken"
    print("\nG2 decision record: self-verifying (sha256 pinned) and metric-consistent")
    print(f"wrote    : {args.out}")
    print(f"wrote    : {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
