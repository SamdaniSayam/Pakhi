# WS-1 G1 Report — Alpha Validation & Proof Gate (end of Phase 1)

Status: **DECISION RECORDED — UNDER-POWERED**
Gate: G1 (Execution Blueprint §4 T6) — *this is a pivot decision.*
Date: 2026-08-12
Machine twin: `data/ws1/g1_decision.json` (self-hash pinned)
Evaluation contract: `docs/WS1_EVALUATION_CONTRACT.md` + `data/ws1/evaluation_contract.json`
Candidate registration: `docs/T4_CANDIDATE_REGISTRATION.md` + `data/ws1/t4_candidate.json`

---

## 1. Decision (the short answer)

| | |
|---|---|
| **G1 outcome** | **UNDER-POWERED** |
| **Reason** | N = **7** OOS event-trades < N_min = **8** (locked, §8) ⇒ no statistical conclusion |
| **Implication** | Freeze thesis **defers to Phase 2** live paper-trading (60-day harness) to accumulate events; G1 recorded as UNDER-POWERED, *not* PASS, *not* FAIL. |
| **What this is not** | Not a disproof of edge, and not a proof of edge. The pre-registered ColdGrip candidate **did fire** OOS (7 trades, T4 exit MET), but 7 events cannot clear a power gate — the honest verdict is *no conclusion yet*. |

## 2. Headline metric (net-of-benchmark event-trade Sharpe, OOS)

All numbers reproduced live by `scripts/run_t6_g1_report.py` on the real PIT frame
(terminal evidence, 2026-08-12):

```
signal            : ColdGrip (pre-registered, one-shot)
armor             : PASS (timestamp + vintage + roll-jump layers)
engine cross-val  : matched 7 trades | max |d return| 1.39e-16 | price mismatches 0

N                  : 7  (N_min = 8)
power class        : under-powered (N < N_min)
mean net-of-bench  : -1.2372%
event Sharpe       : -0.193  (95% CI -1.019, 2.110)
classic t / NW t   : -0.356 / -0.590 (lag 2)
bootstrap p (edge) : 0.630
overlap check      : {'n_overlapping_events': 0, 'purging_needed': False}
benchmark (2-sess) : +0.2405% | span 3.4113620807665983 y | OOS rows 1247

G1 outcome         : UNDER_POWERED
```

- Pooled OOS window: **1247 rows**, 4 season-block expanding-window folds,
  span **3.41 y**, embargo 5 sessions, benchmark = always-long OJ 2-session
  mean **+0.2405 %**.
- N = 7 scored event-trades (all 7 OOS, one per episode, ≤ 13 ceiling).
- Net-of-benchmark event Sharpe **−0.193** with bootstrap 95 % CI
  **(−1.019, +2.110)** — the CI straddles zero, i.e. the sparse-variance
  interval is so wide that neither an edge nor its absence can be concluded.
- Newey-West HAC t = **−0.590** (lag 2) vs classic t = −0.356; bootstrap
  p(edge > 0) = **0.630**. Overlap check: 0 overlapping events, no purging needed.

## 3. Why this is the honest reading (one-shot, no re-tuning)

1. **Pre-registration before scoring.** ColdGrip (rule family, θ_p estimator,
   θ_t = 0 °C fixed, ≤ 1 trade/episode, 2-session hold, 1 free parameter) was
   registered in writing **before any OOS fold was scored** and scored **once**.
   No threshold was adjusted in response to the 7-trade result — any such move
   would void G1 per contract §4/§10.
2. **Power ceiling is structural.** Freeze episodes are rare (16 total,
   2021-11 → 2026-03; 13 OOS). The contract therefore locked the *shrunk claim*:
   N_min = 8 and a mandatory UNDER-POWERED outcome below it. Growing N past 8
   requires live events, which only Phase 2 paper-trading can produce.
3. **The gates all fired for the right reason.** Timestamp armor (features
   precede the 14:00 NY decision cutoff), vintage armor (as-published
   `noaa-gfs-bdp-pds`, pinned cycle hashes), and roll-jump armor (X = 5σ,
   0/34 real roll gaps flagged) all PASS — the run is **valid**, and the
   UNDER-POWERED outcome is the data speaking, not a plumbing failure.
4. **Engine trust.** Every candidate trade's return reproduces the PIT forward
   return to `1.39e-16` with 0 price mismatches (known-value-exact engine).

## 4. Phase 2 plan (the forward path)

| Step | Action |
|---|---|
| **P1** | Launch the 60-day live **paper-trading harness** on OJ (strictly one-shot ColdGrip, locked params) to accumulate real-time OOS event-trades. |
| **P2** | Re-run G1 when the paper ledger reaches **N ≥ N_min = 8**; the verdict updates on data (PASS / FAIL→PIVOT / still UNDER-POWERED). |
| **P3** | Deferred to post-G1 / Phase 2 (unchanged): NG, CME HDD/CDD, ensemble disagreement index. |

Any amendment to the contract or the candidate requires a new version, a
re-lock, and voids prior results (contract change control).

## 5. Evidence chain (all artifacts on disk)

| Artifact | Path |
|---|---|
| Evaluation contract (v1.1, hash-pinned) | `docs/WS1_EVALUATION_CONTRACT.md`, `data/ws1/evaluation_contract.json` |
| Candidate registration (one-shot) | `docs/T4_CANDIDATE_REGISTRATION.md`, `data/ws1/t4_candidate.json` |
| Candidate harness report + ledger + trades | `data/ws1/t4_candidate_report.json`, `t4_candidate_ledger.csv`, `t4_candidate_trades.csv` |
| G1 decision record (self-hash-pinned) | `data/ws1/g1_decision.json` |
| Execution blueprint / progress tracker | `docs/WS1_EXECUTION_BLUEPRINT.md`, `docs/WS1_PROGRESS.md` |

**Signed by evidence:** every figure above is reproduced by
`scripts/run_t6_g1_report.py` (exit 0) and asserted by
`tests/test_ws1_g1_report.py`; the G1 record's payload sha256 is checked on
every run so the recorded outcome cannot silently drift from the data.
