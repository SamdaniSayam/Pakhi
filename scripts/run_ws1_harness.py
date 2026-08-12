#!/usr/bin/env python3
"""WS-1 T1: run the PIT->engine harness and emit the locked-number report.

Usage:
    python scripts/run_ws1_harness.py

Writes:
    data/ws1/t1_event_ledger.csv   every episode event (scoring flags + provenance)
    data/ws1/t1_harness_report.json full report (locked numbers + metrics + provenance)
    data/ws1/t1_engine_trades.csv  engine trade log (provenance-injected, T2)

The demo generator fires at every episode start (parameter-free, max-load
exercise).  This is plumbing evidence for T1/T2 — NOT a G1 decision (T6) and
NOT a registered T4 candidate.
"""

from __future__ import annotations

from pathlib import Path

from pakhi.ws1.harness import run_harness

HERE = Path(__file__).resolve().parent.parent
WS1 = HERE / "data" / "ws1"


def main() -> None:
    WS1.mkdir(parents=True, exist_ok=True)
    ledger_path = WS1 / "t1_event_ledger.csv"
    report_path = WS1 / "t1_harness_report.json"
    trades_path = WS1 / "t1_engine_trades.csv"

    report = run_harness(
        ledger_path=ledger_path,
        report_path=report_path,
        trades_path=trades_path,
    )

    if not report["valid"]:
        print("INVALID PIT:", report["validation"])
        raise SystemExit(1)

    locked = report["locked"]
    print("== WS-1 T1 harness ==")
    print(f"validation : {report['validation']}")
    print(
        "locked     : episodes {n_episodes_total} total / {n_episodes_oos} OOS | "
        "oos_rows {oos_rows} | span {span_years:.4f} y | benchmark {benchmark_2sess_pct:.4f}%".format(
            **locked
        )
    )
    ev = report["events"]
    print(
        "events     : {n_oos_events} OOS | {n_scored} scored "
        "(embargoed {n_embargoed}, weekend-entries {n_weekend_entries_oos}, "
        "next-close fills {n_next_close_entries_oos}, holds_merged {holds_merged_in_engine})".format(
            **ev
        )
    )

    m = report["metrics"]
    print("\n-- event metrics (scored, net-of-benchmark is the locked G1 metric) --")
    print(f"N                    : {m['n_events']}")
    print(f"mean gross           : {m['mean_gross'] * 100:+.4f}%")
    print(f"mean net (gross-30bp): {m['mean_net'] * 100:+.4f}%")
    print(f"mean net-of-benchmark: {m['mean_net_of_benchmark'] * 100:+.4f}%")
    print(f"gross Sharpe         : {m['gross_sharpe']:.3f}")
    print(f"net Sharpe           : {m['net_sharpe']:.3f}")
    print(
        f"net-of-bench Sharpe  : {m['net_of_benchmark_sharpe']:.3f}  "
        f"(95% CI {m['ci_95_net_of_benchmark_sharpe'][0]:.3f}, "
        f"{m['ci_95_net_of_benchmark_sharpe'][1]:.3f})"
    )
    print(f"t-stat               : {m['t_stat']:.3f}   win rate {m['win_rate']:.2f}")

    ec = report["engine_context"]
    xv = ec["cross_validation"]
    print("\n-- engine (BacktestEngine over OJ path) --")
    print(
        f"full OOS : return {ec['full_oos_total_return'] * 100:+.2f}% | "
        f"daily-equity Sharpe {ec['full_oos_daily_equity_sharpe']:.3f} | {ec['full_oos_trades']} trades"
    )
    print(
        f"cross-val: {xv['matched_trades']} engine trades matched to events | "
        f"max |Δ return| {xv['max_return_abs_error']:.2e} | price mismatches {xv['price_mismatches']}"
    )
    for fr in ec["per_fold"]:
        print(
            "  {fold}: ret {total_return:+.2%} | eq-Sharpe {daily_equity_sharpe:.3f} | "
            "{n_trades} trades".format(**fr)
        )

    pr = report["provenance"]
    print("\n-- provenance (T2) --")
    print(
        f"{pr['n_trades_with_provenance']}/{pr['n_trades']} trades carry provenance "
        f"({pr['model_version']} / {pr['archive']})"
    )
    print(f"forecast cycles: {', '.join(pr['forecast_cycle_ids'])}")
    print(
        f"costs_bps range [{pr['costs_bps_range'][0]:.2f}, {pr['costs_bps_range'][1]:.2f}] | "
        f"round-trip == 30 bps: {pr['costs_match_locked_round_trip']}"
    )

    ar = report["armor"]
    ts, vg = ar["timestamp"], ar["vintage"]
    print("\n-- lookahead armor (T3) --")
    print(
        f"timestamp: {ts['n_rows']} rows | publish-after-cutoff {ts['publish_after_cutoff']} | "
        f"min margin {ts['min_publish_margin_hours']:.2f}h | horizon {ts['event_peak_outside_horizon']} violations"
    )
    print(
        f"vintage  : {vg['archive']} | {vg['n_cycles_in_manifest']}/{vg['n_pit_cycles']} cycles | "
        f"source match {vg['source_match']} | hash drift {vg['n_hash_drift']} | PASS {ar['pass']}"
    )

    print("\nnote     :", report["note"])
    print(f"\nwrote    : {ledger_path}  {report_path}  {trades_path}")

    ok = m["n_events"] >= 8  # locked N_min, reported for context only
    print("\nN_min gate (8, context only, decision is T6):", "MET" if ok else "NOT MET")
    raise SystemExit(0)

if __name__ == "__main__":
    main()
