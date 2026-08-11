# WS-1 — As-Published Backtest Platform: Execution Blueprint

Status: **REVIEWED & APPROVED** (2026-08-11)
Progress: tracked in `docs/WS1_PROGRESS.md`
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-1
Gate: G1 (end of Phase 1 / week 12) — The Alpha Validation & Proof Gate. *This is a pivot decision.*

---

## 1. Purpose

Transform the data pipelines constructed in WS-0 into a hardened, **point-in-time, mathematically rigorous backtesting engine**. WS-1 is designed to aggressively try to disprove our models by introducing real-world trading frictions, enforcing strict no-lookahead assertions, and holding performance metrics to predefined statistical significance standards. 

Success = An automated backtest harness that logs trade-by-trade provenance and proves whether a signal on the wedge instrument yields a **statistically significant, benchmark-beating out-of-sample edge**, or definitively dictates a product pivot.

## 2. Readiness Audit (verified live, 2026-08-11)

| Layer | Status | Evidence |
|---|---|---|
| WS-0 PIT Frame | ✅ Complete | 16 core issues fixed; `build_pit.py` cleanly outputs continuous features aligned to *actual trading sessions*. |
| Risk Engine | ⚠️ Unvalidated | `BacktestEngine` exists and handles walk-forward/costs, but lacks a hand-computed known-value exactness test. |
| Rolling / Sorting | ✅ Fixed | Future rolling index joins corrected (`ws0/roll.py`). |
| Signal Edge | ❌ Refuted | G0 reported freeze_prob never hits the 0.6 threshold (max 0.218), and Spearman is negative (-0.062). *0 trades generated.* |
| CI / Hardware | ✅ Robust | CUDA hardware fallbacks; test mocks successfully simulate network failures. |

*Note: 100% line coverage means the engine doesn't crash; it does not establish correctness or market-usefulness.*

## 3. Task 0 — The Evaluation Contract (Pre-requisites)

Before running a single backtest or adjusting a single threshold, the evaluation rules must be locked to prevent p-hacking:
1. **OOS Split:** A strict, locked out-of-sample (OOS) timeline constraint.
2. **Sharpe Definition:** Use a **trade-level (event-based)** Sharpe ratio pooled across walk-forward folds, not a daily equity-return Sharpe (which is diluted to near-zero by flat days on sparse signals).
3. **Benchmark:** Absolute Sharpe is meaningless in a trending commodity. Returns must be measured **net-of-benchmark** (e.g., buy-and-hold OJ) or explicitly via a matched long-short hedge.
4. **Tuning Embargo:** Any threshold or feature re-estimation must be strictly confined to walk-forward train folds. Because consecutive-day freeze forecasts are highly autocorrelated, trade returns must be evaluated using event-based aggregation or purged/Newey-West standard errors to prevent overstated t-stats.
5. **Holding Horizon:** The freeze feature is a 48h forecast. The PIT outcome must be matched by holding the position for **≥ 2 trading sessions**, or dynamically sized from the `event_peak_time`.

## 4. Tasks, sequencing, exit criteria

### T1 — Engine Validation & Integration (week 1)
- Write an exact, hand-computed known-value walk-forward test for the `BacktestEngine` to mathematically prove the PnL and Sharpe calculations are correct, raising the bar from "crash-free" to validated.
- Wire the completed WS-0 PIT frames into the engine.
- Define cost semantics: 5 bps commission + 10 bps slippage **per position change** (round-trip = 30 bps total). 
- Document Engine fill timing convention: *signal at day i → fill at close of day i*.
- **Exit:** Engine reproduces hand-computed PnL/Sharpe exactly.

### T2 — Provenance Logging (week 1–2)
- Inject metadata tracking into the execution layer.
- Every simulated trade must record: `forecast_cycle_id`, `publication_ts`, `model_version`, `costs_incurred`, and the exact **contract roll state**.
- **Exit:** Trade ledgers export fully annotated transaction histories.

### T3 — The Lookahead Armor (week 2)
- Implement two layers of assertions in the CI and engine:
  - **Timestamp Layer:** Assert that no feature vector at time *t* references data published after the trading decision cutoff.
  - **Vintage Layer:** Assert that the forecast run was fetched strictly from the as-published archive (`noaa-gfs-bdp-pds`), not merely AWS. Actively **fail** the backtest if a feature's data was published *after* the decision cutoff.
- **Exit:** A backtest fed leaked future data immediately errors out.

### T4 — Signal Redefinition & Safety (week 3)
- G0 proved the current `FreezeSignal` is dead (0 trades). We must redefine the feature and thresholds from the PIT frame.
- Re-estimation must be done *inside* walk-forward folds without leaking future data.
- Implement Roll-Jump Assertions (reusing WS-0 machinery) to halt if continuous-price moves at roll dates exceed `X * daily_σ`.
- **Exit:** A new signal generator capable of firing trades under OOS constraints without exploiting roll gaps.

### T5 — Statistical Significance Engine (week 3–4)
- Build the evaluator module that computes event-based trade-level t-statistics and bootstrap confidence intervals.
- Implement the `N ≥ 30` minimum trade gate, or explicitly shrink edge claims for rare events.
- **Exit:** Performance reports output probability distributions and p-values, exposing whether sparse-trade variance is too high.

### T6 — G1 Hand-off & Decision Gate (week 4)
- Run the full end-to-end backtest strictly on the **OJ** wedge instrument. 
- *Note: NG, CME HDD/CDD, ensemble disagreement index, and 60-day live paper-trading are explicitly deferred to post-G1 or Phase 2 to maintain focus.*
- **Exit:** Final `WS1_G1_REPORT.md`. If the strategy achieves **Trade-level Sharpe > 1.0 net-of-benchmark (with CI + N≥30)**, we proceed. If the honest outcome is 0 trades or negative edge, we document the pivot.

## 5. Timeline

| Week | Focus | Deliverable |
|---|---|---|
| 1 | T0 + T1 + T2 | Evaluation Contract + Engine Validation + Provenance |
| 2 | T3 | No-lookahead assertions (Timestamp + Vintage) |
| 3 | T4 | Signal redefinition + Roll-jump checks |
| 4 | T5 + T6 | Stats engine + Full OJ backtest + G1 Decision |

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Zero trades (provably dead signal) | Acknowledged as a valid primary outcome leading to a documented pivot. |
| Diluted daily-Sharpe hides edge | T0 pre-commits to event-based, trade-level Sharpe pooled across folds. |
| Threshold tuning leaks future data | T0 tuning embargo; strict walk-forward embedded in T4. |
| Overstated significance from autocorrelation | Event-based trade returns; purged/Newey-West t-stats. |
