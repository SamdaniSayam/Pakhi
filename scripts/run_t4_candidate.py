#!/usr/bin/env python3
"""WS-1 T4: run the pre-registered "ColdGrip" candidate + roll-jump armor.

Usage:
    python scripts/run_t4_candidate.py

Writes:
    data/ws1/t4_candidate_report.json  full report (signal + thresholds + armor + metrics)
    data/ws1/t4_candidate_ledger.csv   candidate event-trade ledger
    data/ws1/t4_candidate_trades.csv   engine trade log (provenance-injected)

The candidate is the one-shot, pre-registered redefined freeze signal
(docs/T4_CANDIDATE_REGISTRATION.md, data/ws1/t4_candidate.json): thresholds
re-estimated inside walk-forward folds from train freeze rows only, <= 1 trade
per episode, 2-session hold (locked).  T4 exit = the candidate fires trades
under OOS constraints without exploiting roll gaps; the roll-jump gate (§9.3)
aborts (RollJumpError) if an unadjusted roll-date gap is not a modeled weather
event.  Exit code 0 on a clean run (fires OOS, armor passes), 1 otherwise.
"""

from __future__ import annotations

from pathlib import Path

from pakhi.ws1.harness import run_harness

HERE = Path(__file__).resolve().parent.parent
WS1 = HERE / "data" / "ws1"


def main() -> None:
    WS1.mkdir(parents=True, exist_ok=True)
    ledger_path = WS1 / "t4_candidate_ledger.csv"
    report_path = WS1 / "t4_candidate_report.json"
    trades_path = WS1 / "t4_candidate_trades.csv"

    report = run_harness(
        ledger_path=ledger_path,
        report_path=report_path,
        trades_path=trades_path,
        candidate=True,
    )

    if not report["valid"]:
        print("INVALID PIT:", report["validation"])
        raise SystemExit(1)

    sig = report["signal"]
    m = report["metrics"]
    ar = report["armor"]
    rj = ar["roll_jump"]
    xv = report["engine_context"]["cross_validation"]

    print("== WS-1 T4: registered candidate 'ColdGrip' ==")
    print(f"signal    : {sig['name']} ({sig['kind']})")
    print(f"registration: {sig['registration']}")
    params = sig["params"]
    print(
        f"params    : theta_p = {params['theta_p_estimator']} | theta_t = {params['theta_t_c']}C | "
        f"{params['free_parameters']} free (max 3) | hold {params['hold_sessions']} sessions"
    )
    print("\n-- per-fold in-sample re-estimation (train-only, expanding window) --")
    for t in sig["fold_thresholds"]:
        print(
            "  {fold}: train <= {train_end} | theta_p {theta_p:.4f} | theta_t {theta_t}C | "
            "{n_entries} trade(s)".format(**t)
        )

    print(f"\nOOS trades: {sig['n_trades']}  (<= 1 per episode)")
    if sig["n_trades"] == 0:
        print("T4 exit criterion NOT met: the candidate fires nothing OOS.")
        raise SystemExit(1)

    print("\n-- event metrics (candidate trades, context only; G1 is T6) --")
    print(f"N                    : {m['n_events']}")
    print(f"mean gross           : {m['mean_gross'] * 100:+.4f}%")
    print(f"mean net (gross-30bp): {m['mean_net'] * 100:+.4f}%")
    print(f"mean net-of-benchmark: {m['mean_net_of_benchmark'] * 100:+.4f}%")
    print(f"net-of-bench Sharpe  : {m['net_of_benchmark_sharpe']:.3f}  "
          f"(95% CI {m['ci_95_net_of_benchmark_sharpe'][0]:.3f}, "
          f"{m['ci_95_net_of_benchmark_sharpe'][1]:.3f})")

    print("\n-- roll-jump armor (T4, contract 9.3, X = 5) --")
    print(
        f"roll-date gaps     : {rj['n_flagged_rolls']} flagged of {rj['n_rolls']} rolls | "
        f"unmodeled {rj['unmodeled_roll_gaps']}"
    )
    print(
        f"near-roll extreme  : {rj['n_near_roll_extreme_moves']} move(s) within +-{3}d of a roll "
        f"(reported context)"
    )
    for mv in rj["near_roll_extreme_moves"]:
        print(
            "    {date}: return {return:+.2%} | {ratio:.2f}x sigma | weather_co_located "
            "{weather_co_located}".format(**mv)
        )

    print("\n-- engine cross-validation (candidate schedule) --")
    print(
        f"matched {xv['matched_trades']} engine trades to events | "
        f"max |Δ return| {xv['max_return_abs_error']:.2e} | price mismatches {xv['price_mismatches']}"
    )

    print("\nT4 Lookahead+RollJump Armor: PASS")
    print("T4 candidate exit: PASS (fires OOS, <= 1 trade/episode, no roll-gap exploitation)")
    print(f"wrote    : {ledger_path}  {report_path}  {trades_path}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
