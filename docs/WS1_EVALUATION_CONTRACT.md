# WS-1 Evaluation Contract v1.1 (LOCKED)

**Status:** LOCKED 2026-08-11. Pre-registered before any backtest or signal
tuning. Amendments require a new version and re-lock (see §11).
Machine-readable twin: `data/ws1/evaluation_contract.json` (hash-pinned).

**v1.1 amendment (effective 2026-08-11):**
1. **Fill timing:** non-trading-day cycles now fill at the **next** trading-session
   close instead of the prior Friday close — eliminating lookahead on
   weekend/holiday cycles (a Saturday 15:35Z cycle previously filled at Friday's
   close, i.e. on information not yet published).
2. **Episode segmentation:** gaps are measured in **trading sessions between
   executable fill sessions**, not calendar days — a weather event interrupted by
   a weekend/holiday forms **one** episode.
3. Episode count on the archive is **unchanged (16 / 13)**; scored N rises **12 → 13**
   (the 2025-11-09 Sunday entry now fills 2025-11-10, outside the fold-4 head
   embargo). Benchmark recomputed on executable fills: **+0.2405 %** per 2 sessions
   (was +0.1722 %). Prior v1.0 results void (see §11).

The purpose of this contract is to make G1 **falsifiable and non-gamable**:
every rule that could otherwise become a researcher degree of freedom
(metric, benchmark, split, sample size, horizon, costs) is fixed here, in
advance, from the real data.

---

## 1. Instrument & data

| Item | Value |
|---|---|
| Instrument | OJ=F — back-adjusted continuous close (`data/market/oj_continuous.parquet` → PIT `ojd_close`/`ojd_next_close`) |
| Signal universe | `data/ws0/freeze_pit.parquet` (1612 PIT rows, 2021-11-01 → 2026-03-31) |
| As-published requirement | All features from `noaa-gfs-bdp-pds` archive (asserted in T3); no ERA5 in test |
| 2-session outcome | Computable for **all** 1612 rows (0 missing) — `close[fill+2]/close[fill] − 1` |
| Fill base (v1.1) | **First trading session on/after** the cycle date — same-day close for trading days, **next** trading close for weekend/holiday cycles |

## 2. Windows & folds (locked)

Season-block **expanding-window** walk-forward. Fold = freeze season
(Nov N → Mar N+1; off-season rows included in each fold).

| Fold | Train window | Test window | Test rows |
|---|---|---|---|
| — | 2021-11-01 → 2022-10-31 | *(seed train only, never scored)* | — |
| 1 | ≤ 2022-10-31 | 2022-11-01 → 2023-10-31 | 365 |
| 2 | ≤ 2023-10-31 | 2023-11-01 → 2024-10-31 | 366 |
| 3 | ≤ 2024-10-31 | 2024-11-01 → 2025-10-31 | 365 |
| 4 | ≤ 2025-10-31 | 2025-11-01 → 2026-03-31 | 151 |

- **OOS evaluation window** = test folds 1–4 = **1247 rows**,
  2022-11-01 → 2026-03-31 (**span = 3.4114 years**).
- **Embargo:** the first **5 sessions** of each test fold are purged from
  scoring (drains autocorrelation bleed from adjacent train data).
- **Event definition (locked, v1.1):** a *freeze episode* = maximal run of PIT
  rows with `freeze_prob > 0` grouped by **executable fill session**. Two
  freeze rows split into new episodes iff their fill sessions are **≥ 2
  trading sessions apart** (more than one session strictly in between).
  Measured on the real archive: **16 episodes total**, of which **13 fall
  inside the OOS window** → the maximum achievable OOS event-trade count is
  **13**. (Unchanged from v1.0; the session rule is the hardened, weekend-safe
  formulation.)

## 3. Sample-size rule (locked, shrunk edge claim — per blueprint T5)

N ≥ 30 OOS event-trades is **structurally unreachable** for a freeze-triggered
signal on this archive (hard ceiling 13). The gate is therefore set to the
highest defensible bar the data can support:

- **N_min = 8 OOS event-trades** (≥ 62 % of the 13 available episodes must be
  captured by the redefined signal).
- N < 8 ⇒ **UNDER-POWERED** outcome (see §9) — not a pass, not a forced pivot.
- This is an explicit, documented *shrunk edge claim*; significance is judged
  by bootstrap CI width, not point Sharpe alone.

## 4. Signal under test (T4 scope, locked)

- The current `FreezeSignal` (entry 0.6) is the **pre-committed baseline** and
  is expected to produce 0 trades (G0: max `freeze_prob` 0.218). It is *not*
  the candidate under test.
- The candidate is a **redefined** freeze/cold-event signal, constrained to:
  1. be a pure function of **train-window data only** (per fold);
  2. have **≤ 3 free parameters** (e.g., `freeze_prob` threshold, temperature
     gate, hold sessions);
  3. produce **≤ 1 trade per episode** (first firing row = entry);
  4. never read future prices (`ojd_*` outcomes) during definition.
- The candidate must be **registered in writing before any OOS fold is scored**
  (one-shot evaluation; no re-tuning after seeing OOS results).

## 5. Trade construction & costs (locked)

- **Entry:** signal fires on PIT row with cycle date `c` → fill at the close of
  the **first trading session on/after** `c` (the session whose close =
  `ojd_close`). Same-day close for trading days; weekend/holiday cycles fill at
  the **next** trading close (v1.1 — never the prior Friday close, no lookahead).
- **Hold:** fixed **2 trading sessions** (entry session close → 2nd next trading
  close), matching the ≥ 2-session rule for the 48 h feature window.
  (`ojd_close_2` = `close[fill+2]`.)
- **Gross event return:** `gross = close[fill+2]/close[fill] − 1`.
- **Costs:** 5 bps commission + 10 bps slippage **per position change**; entry +
  exit = **30 bps round trip**. `net = gross − 0.0030`.
- **Fill timing convention:** signal from the `D` 12Z cycle (published ~15:35Z)
  → fill at the first trading close on/after `D` (executable: the publish
  precedes any fill close).

## 6. Metric (locked — event-based, trade-level, pooled)

- Pool all OOS event trades across folds 1–4 ⇒ N pooled trades.
- **Headline G1 metric = net-of-benchmark event-trade Sharpe** (defined §7-§8),
  annualized as `mean/std × √(N / span_years)`.
- Also reported (context only, never the gate): gross event Sharpe, net event
  Sharpe, daily-equity Sharpe, mean net-of-benchmark per event, t-stat
  (`mean/(std/√N)`), and **bootstrap 95 % CI** (10 000 resamples, percentile
  method, `np.random.default_rng(42)`).

## 7. Benchmark (locked — net-of-benchmark)

Per-event comparison versus **always-long OJ**:

- `r̄_2sess` = mean 2-session OJ return over the OOS window
  (= **+0.2405 %** on the current data, v1.1 executable fills; recomputed by
  the harness).
- **net-of-benchmark event return** =
  `(gross_event − 0.0030) − r̄_2sess`.
- A matched long-short hedge variant (`2 × gross − 2 × costs`) is reported as
  context only.

## 8. Decision rules (locked, a-priori)

| Outcome | Condition | Action |
|---|---|---|
| **PASS** (G1 cleared) | N ≥ 8 **and** net-of-benchmark event Sharpe > 1.0 **and** bootstrap CI lower bound > 0 | Proceed to WS-2 |
| **FAIL → PIVOT** | N ≥ 8 **and** (CI includes 0 or mean net ≤ 0) | Documented pivot (cat-bonds / reinsurance analytics) |
| **UNDER-POWERED** | N < 8 OOS event-trades | No conclusion; freeze thesis defers to Phase 2 live paper-trading (60-day harness) to accumulate events; G1 recorded as UNDER-POWERED |
| **0 trades** | No signal fires OOS | **Architecture SUCCESS** (fast, rigorous disproof) → documented pivot |

Per `PRODUCTION_BLUEPRINT.md`: a negative G1 is a statement about the market
edge, **not** an engineering failure. The harness proving the signal is dead is
the architecture doing its job.

## 9. Hard gates (violation ⇒ run is INVALID, not just flagged)

1. **Timestamp armor:** any feature vector referencing data published after its
   decision cutoff ⇒ invalid run.
2. **Vintage armor:** any feature not traced to the `noaa-gfs-bdp-pds`
   as-published archive (or whose vintage hash predates the feature's own
   timestamp) ⇒ invalid run.
3. **Roll-jump armor:** any continuous-price move > `X × daily_σ` at a roll
   date not driven by a modeled weather event ⇒ halt (X = 5, from WS-0
   machinery).

## 10. Anti-gaming (locked)

- One-shot evaluation; no metric feedback into tuning.
- No parameter search over the full window.
- No re-running the backtest with different thresholds to "find" a pass.
- All pre-registration artifacts are committed to git before execution.

## 11. Change control

Any amendment to this contract (metric, split, threshold policy, costs,
sample-size rule) requires a new version `v1.(n+1)` with rationale, and
**re-locking before any result is final**. Results from a previous version are
void for G1. **v1.0 → v1.1** (2026-08-11): fill-timing amendment (next trading
close for weekend/holiday cycles, eliminating prior-close lookahead) and
session-based episode segmentation (see header).

---

*Locked by WS-1 Task 0. Companion files: `data/ws1/evaluation_contract.json`
(hash-pinned), `docs/WS1_PROGRESS.md` (log).*
