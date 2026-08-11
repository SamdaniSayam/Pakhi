# WS-1 Progress Tracker — As-Published Backtest Platform

Per working agreement: every execution step is logged here with terminal evidence,
and the user is shown the running terminal live.

- Blueprint: `docs/WS1_EXECUTION_BLUEPRINT.md` (**REVIEWED & APPROVED** 2026-08-11)
- Evaluation contract: `docs/WS1_EVALUATION_CONTRACT.md` + `data/ws1/evaluation_contract.json`
- Gate: G1 (end of Phase 1 / week 12) — **pivot decision**
- Started: 2026-08-11

---

## Log

### 2026-08-11 — T0 Evaluation Contract LOCKED
- Blueprint rewritten per audit (0-trade dead end, event-based Sharpe,
  net-of-benchmark, tuning embargo, ≥2-session horizon, engine known-value test,
  corrected vintage armor, deferred NG/HDD/ensemble/paper-trading). Approved.
- **Pre-registered the evaluation contract before any backtest/tuning** to kill
  researcher degrees of freedom. Locked in two twin artifacts (human doc +
  machine JSON, hash-pinned):
  - `docs/WS1_EVALUATION_CONTRACT.md`
  - `data/ws1/evaluation_contract.json` → payload sha256
    `204ccf5cc46ab5c4cde43ee6d14f93e12feb4dc89f26d0d0f921c2e0d47d697f` (self-verifying)
- **Critical data fact discovered and encoded (shrunk edge claim):** the freeze
  signal can structurally never reach N≥30 OOS event-trades. Measured on the
  real PIT frame: **16 freeze episodes total (2021-11→2026-03); 13 inside the
  OOS test window**. N_min locked at **8**; N<8 ⇒ **UNDER-POWERED** outcome.
- **Fold structure locked:** season-block expanding-window walk-forward, 4 OOS
  folds (2022/23→2025/26), 1247 OOS rows, span 3.4114 y, embargo 5 sessions.
- **2-session hold verified feasible:** all 1612 PIT rows have a computable
  `close[D+2]` outcome (0 missing) — T1 dependency confirmed.
- **Benchmark locked:** always-long OJ; OOS 2-session mean `r̄ = +0.1722 %`.
  Headline = net-of-benchmark event-trade Sharpe
  (`(gross − 30 bps) − r̄`), annualized `mean/std × √(N/span)`, bootstrap 95% CI
  (10 000 resamples, seed 42).
- **Decision rules pre-committed:** PASS (N≥8 ∧ Sharpe>1.0 ∧ CI LB>0) /
  FAIL→PIVOT / UNDER-POWERED (N<8) / 0-trades = **architecture success** (fast
  rigorous disproof), not an engineering failure.
- Hard gates pre-committed (timestamp armor, vintage `noaa-gfs-bdp-pds` armor,
  roll-jump armor >5σ) — violation ⇒ invalid run.
- Full suite green: **1480 passed / 5 skipped**; ruff clean.

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Evaluation Contract | **DONE** | Locked v1.0; N_min=8 (ceiling 13 events); event-based net-of-benchmark Sharpe |
| T1 Engine Validation & Integration | pending | known-value test + PIT wiring + 2-session outcomes |
| T2 Provenance Logging | pending | cycle id / publication_ts / model_version / costs / roll state |
| T3 Lookahead Armor | pending | timestamp + vintage (bdp-pds) assertions |
| T4 Signal Redefinition & Safety | pending | in-fold re-estimation; roll-jump halt |
| T5 Statistical Significance Engine | pending | bootstrap CI, N gate, purged SEs |
| T6 G1 Hand-off | pending | OJ backtest + decision report |

## Open items / risks

- N≥30 structurally unreachable for freeze events → contract locks the shrunk
  claim (N_min=8) and an UNDER-POWERED path; live paper-trading (Phase 2) is
  the only way to grow event count.
- `BacktestEngine` unvalidated (no known-value test) → T1 must fix before any
  result is trusted.
- PIT holds only 1-session outcomes; 2-session outcomes must be built in T1
  (verified computable: 0 missing).
