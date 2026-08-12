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

### 2026-08-11 — T1 Engine Validation & Integration DONE
- **Known-value engine test** (`tests/test_backtest_known_value.py`, 5 tests):
  exact hand-computed `Fraction`-rational oracle proves equity path, per-trade
  PnL, costs (5+10 bps per change = 30 bps round trip), total return, max_dd,
  Sharpe, walk-forward slicing, and retrain-slice isolation. Engine fills at
  close of the signal day (locked convention).
- **PIT rebuilt with 2-session outcomes**: `scripts/build_pit.py` now emits
  `ojd_next2_close` + `fwd2_return` (0/1612 missing); `freeze_pit` sha256 →
  `95eabae0…` (manifest refreshed). WS-1 DQ gate `gate_pit` now shared with
  `pakhi/ws1/pit.py` (single source of truth).
- **New `pakhi/ws1/` integration module** + `scripts/run_ws1_harness.py`:
  PIT frame wired into `BacktestEngine` over the real OJ path. Locked numbers
  reproduced from the archive: **16 episodes total / 13 OOS**, **1247 OOS rows**,
  span **3.4114 y**, benchmark **+0.1722 %**, embargo purges 1 (2025-11-09
  weekend entry at fold-4 head) → **12 scored events**.
  Cross-validation: all **13** OOS engine trades matched to PIT events,
  **max |Δ return| = 1.9e-16**, **0 price mismatches** — the engine reproduces
  the PIT forward returns exactly. Demo generator = parameter-free (fires at
  every episode start, 2-session hold); explicitly NOT a registered T4
  candidate and no G1 inference drawn. Report: `data/ws1/t1_harness_report.json`
  + `t1_event_ledger.csv`.
- **Open decision surfaced (T3 scope):** 7 of 13 OOS entries are
  **prior-close fills** (6 weekend + 1 holiday MLK 2024) under the locked
  "weekend cycles map to prior Friday close" rule — these fill at a session
  *before* the cycle's publish time, so the timestamp-armor gate must define
  how it treats them (contract §5 vs §9.1 tension).
- Full suite green: **1557 passed / 5 skipped**; ruff clean.

### 2026-08-11 — Contract v1.1: fill-timing & episode-segmentation amendment (T1 re-lock)
- **Vulnerability found in the locked v1.0 fill rule:** "weekend cycles map to
  prior Friday close" filled Saturday 15:35Z cycles at Friday's close — trading
  on information not yet published (lookahead, §5 vs §9.1 tension raised at T1).
  Also, calendar-day episode segmentation could fragment one weather event
  across a weekend into two episodes.
- **v1.1 amendment (re-locked 2026-08-11):**
  1. **Next-close fills:** fill session = **first trading session on/after** the
     cycle date; weekend/holiday cycles fill at the **next** trading close
     (never prior Friday). No lookahead: publish precedes every fill close.
  2. **Session-based episodes:** split only when fills are **≥ 2 trading
     sessions apart** — a weekend-interrupted event forms one episode.
  3. **Contract + PIT rebuilt** (`scripts/build_pit.py`, `episodes.py`,
     `signal.py`, `harness.py`); hash re-pinned (v1.1 payload sha256
     `31d093c1…`).
- **Numbers after re-lock (verified against the raw OJ path):**
  - Episodes unchanged: **16 total / 13 OOS**, same start dates (session rule
    reproduces the v1.0 segmentation on the current archive).
  - Benchmark on executable fills: **+0.2405 %** (was +0.1722 %).
  - Embargo now purges **0** events (the 2025-11-09 Sunday entry fills
    2025-11-10 = fold-4 session 6) → **13 scored events** (was 12).
  - Engine cross-val: 13/13 matched, **max |Δ return| = 2.6e-16**, 0 price
    mismatches; **holds_merged = false** (session rule makes overlapping holds
    structurally impossible; guard added).
  - Fold4 head: the 2025-11-09 (Sun) → 2025-11-10 (Mon) fill verified to land
    outside the 5-session embargo; no OOS event lands in any fold's embargo.
- **T3 §5-vs-§9.1 tension RESOLVED:** prior-close fills eliminated entirely;
  `n_prior_close_entries_oos` → `n_next_close_entries_oos` = **7** (6 weekend +
  1 holiday MLK 2024), all filling after publish.
- Full suite green: **1561 passed / 5 skipped**; ruff clean.

### 2026-08-11 — T2 Provenance Logging DONE
- **`Signal.provenance`** (`pakhi/signals/base.py`): new dataclass field, a dict
  defaulting to `{}`, preserved through `__post_init__` / Action coercion.
- **Engine injection** (`pakhi/risk/backtest.py`): entry signal's provenance and
  cumulative cost fractions are captured and copied into every trade record —
  `provenance` (dict), `costs_incurred` (fraction), `costs_bps` — for normal
  closes, walk-forward folds, and end-of-window flushes. Equity math unchanged
  (known-value tests still exact).
- **`pakhi/ws1/provenance.py`** (new):
  - `forecast_cycle_id(date, cycle)` → `20251109_12z` (matches the GFS archive
    `gfs_YYYYMMDD_HHz_*` naming; `cycle=12` is the locked operational cycle).
  - `roll_state_table(sessions)` → per-session ICE contract month (FND roll rule)
    + cumulative back-adjustment factor (`close_adj / close_raw`).
  - `build_provenance_map(pit, sessions)` → per-held-session provenance
    (forecast cycle id, publication_ts, model version, archive, roll state).
  - Locked constants: `MODEL_VERSION = "GFS-0p50"` (model + resolution; the
    as-published bucket carries no numeric GFS version), `ARCHIVE =
    noaa-gfs-bdp-pds` (the PIT source bucket), `ROLL_RULE = "FND"`,
    `ADJUSTMENT_TYPE = "back"`.
- **Harness** (`pakhi/ws1/harness.py`): `run_harness(..., trades_path=)` exports
  the provenance-injected engine trade log to `data/ws1/t1_engine_trades.csv`
  (entry/exit, return, `costs_incurred`, `costs_bps`, full `provenance` dict);
  report gains a `provenance` section; event ledger gains
  `forecast_cycle_id / publication_ts / model_version / contract_month /
  adjustment_factor` columns; runner prints the T2 summary.
- **Verified on real data:** 13/13 OOS engine trades carry provenance; e.g. the
  2025-11-09 (Sun) → 2025-11-10 (Mon) v1.1 fill maps to `20251109_12z`,
  publication `2025-11-09 15:30:00+00:00`, `Mar26` contract; every trade's
  round-trip costs exactly 30.000 bps (`costs_match_locked_round_trip=true`).
- **Tests** `tests/test_ws1_provenance.py` (20): Signal field defaults +
  preservation; engine injection across run / walk_forward / flush; costs
  30 bps RT; `forecast_cycle_id` naming; roll-state table matches the raw
  `close_adj/close_raw` ratio on a known date; provenance map covers every held
  session and matches PIT publish times; harness report + CSV + ledger export.
- Full suite green: **1581 passed / 5 skipped**; ruff clean.

### 2026-08-11 — T3 Lookahead Armor DONE
- **New module `pakhi/ws1/armor.py`** — two locked gates (Evaluation Contract §9):
  - **Timestamp layer** (`check_timestamp_armor`): for every PIT feature row,
    `publish_time` must precede its **decision cutoff** — the ICE OJ 14:00
    America/New_York close of the v1.1 executable fill session (the tightest
    real margin is **2.5 h**, on the 2021-11-01 EDT cycle). Also asserts the
    freeze feature window is confined to `[publish, publish + 48 h]`
    (`event_peak_time` inside it) and the feature vector is complete +
    separated from the `ojd_*`/`fwd*` outcome columns.
  - **Vintage layer** (`check_vintage_armor`): every PIT row now carries a
    `source` column = `noaa-gfs-bdp-pds` (as-published archive); a per-cycle
    **vintage manifest** (`data/ws0/gfs_vintage_manifest.json`) pins a sha256
    of each cycle's raw archive bytes so a rewritten/re-fetched archive is
    detected as drift (immutable S3 bucket ⇒ pinned bytes == as-published).
  - **Exit semantics:** any violation raises `LookaheadError` — the run is
    **INVALID**, not flagged (§9). `run_armor` bundles both layers.
- **Engine armor** (`pakhi/risk/backtest.py`): `BacktestEngine.run(...,
  lookahead_armor=True)` fails immediately if a signal's attached provenance
  references a **future cycle**, a **publication after the current session's
  decision cutoff**, or a **future signal timestamp**. Propagated through
  `walk_forward`. The WS-1 harness arms it on every engine run.
- **Harness**: `run_harness(..., armor=True)` runs `run_armor` (manifest from
  disk) and reports the pass summary under `report["armor"]`; a leaked PIT
  **errors out** (T3 exit criterion verified by test).
- **Dataset/CI**: `build_pit.py` writes `source`; `rebuild_dataset.py` traces
  `cycle_inventory.csv` to the explicit bucket, writes the vintage manifest,
  and runs a new **`armor` gate** (timestamp + vintage, incl. full disk-hash
  scan). New standalone `scripts/run_t3_armor.py` (CI entry, exit 0/1).
- **Tests** `tests/test_ws1_armor.py` (23): decision-cutoff EST/EDT; timestamp
  passes on real PIT; raises on post-cutoff publish, beyond-horizon peak, and
  missing feature columns; vintage passes (manifest + disk scan) and raises on
  wrong source / missing cycle / hash drift; engine guard raises on future
  cycle, future publication, future signal timestamp (run + walk_forward),
  lenient with armor off; harness report armor section; **leaked PIT errors
  out**; standalone runner exits 0 on real data.
- Full suite green: **1604 passed / 5 skipped**; ruff clean. Rebuild gates
  green (incl. armor).

### 2026-08-12 — T4 Signal Redefinition & Safety DONE
- **Pre-registered the candidate in writing BEFORE any OOS fold was scored**
  (contract §4, §10, one-shot; no re-tuning): `docs/T4_CANDIDATE_REGISTRATION.md`
  + machine twin `data/ws1/t4_candidate.json` (sha256
  `3e2f88b6…`). G0 refuted the baseline `FreezeSignal(entry=0.6)` (max
  `freeze_prob` 0.2182, 0 trades) — the redefinition lowers the bar to a level
  re-estimated from train data only.
- **Registered candidate "ColdGrip"** (`pakhi/ws1/candidate.py`):
  - Rule: fire on a PIT row iff `freeze_prob ≥ θ_p` **and** `temperature_min ≤ θ_t`.
  - `θ_p` = **median of `freeze_prob` over the fold's train-window freeze rows**
    (rows with `date ≤` previous fold's train end and `freeze_prob > 0`) — the
    *only* free parameter, re-estimated at each fold boundary (expanding
    window). `θ_t` = **0.0 °C**, fixed (physical freeze gate). ⇒ **1 free
    parameter ≤ 3** ✓.
  - **≤ 1 trade per episode** (first firing row = entry), hold 2 sessions
    (locked §5). The gates read only `freeze_prob`/`temperature_min` — never
    `ojd_*`/`fwd*` outcomes (tested on a feature-only frame).
- **In-fold re-estimation verified:** fold-1 θ_p is estimated from the seed
  window (≤ 2022-10-31) alone; θ_p drifts across folds (0.0404 / 0.0404 /
  0.0424 / 0.0343) as the window expands.
- **OOS firing (T4 exit criterion MET):** the candidate fires **7 OOS trades**
  (episodes 4, 6, 8, 13, 14, 15, 16 — one per episode, ≤ 13 ceiling). Engine
  cross-validation: 7/7 matched, **max |Δ return| = 1.4e-16**, 0 price
  mismatches. (Metric context only, decision is T6; N=7 < N_min=8 ⇒ the honest
  T6 path is UNDER-POWERED unless Phase 2 paper-trading grows N.)
- **Roll-jump armor (contract §9.3, X = 5) added to `pakhi/ws1/armor.py`:**
  - Reuses WS-0 machinery: `back_adjust(..., n_sigma=5.0)` measures the
    continuous-price gap **at each roll date**; an unadjusted gap ≥ 1+5σ that is
    **not co-located (±3 sessions) with a modeled freeze episode** raises
    `RollJumpError` ⇒ run **INVALID** (§9). `roll_jump_assertion` ±3-day net is
    reported for transparency.
  - On the real archive: **0 of 34 roll gaps flagged**; the 2023-11-02 OJ crash
    (−7.5 %, 5.73σ, one session after the 2023-11-01 FND roll) is a **real**
    move in the back-adjusted series, not a roll artifact, and sits outside the
    traded path — reported as context, not a halt.
- **Harness**: `run_harness(..., candidate=True)` runs the registered signal
  (report `signal` section: name, registration, params, per-fold θ_p/θ_t,
  n_trades); armor bundles timestamp + vintage + roll_jump layers and uses the
  run's own OJ frame. Demo default unchanged.
- **Runner**: new standalone `scripts/run_t4_candidate.py` (CI entry, exit 0/1)
  — prints signal, per-fold thresholds, OOS fires, metrics (context), roll-jump
  armor, cross-validation; writes `data/ws1/t4_candidate_report.json`,
  `t4_candidate_ledger.csv`, `t4_candidate_trades.csv`.
- **Tests** `tests/test_ws1_candidate.py` (16): pre-registration artifacts match
  implementation; θ_p = median of train freeze rows; fold-1 seed-only; empty
  train never fires; no outcome columns read; both gates respected; entries
  within test folds; ≤1 trade/episode; entry = first firing row; OOS firing;
  2-session schedule; fold-threshold summary; candidate harness mode + stable
  N. Plus 6 roll-jump tests in `test_ws1_armor.py` (28 total): real data passes
  (0 flagged rolls, 2023-11-02 context), unmodeled roll gap **raises**, weather
  co-located roll gap allowed, harness exposes roll_jump.
- Full suite green: **1625 passed / 5 skipped**; ruff clean. `run_ws1_harness.py`
  (demo) unchanged and green; `run_t4_candidate.py` exits 0.

### 2026-08-12 — T5 Statistical Significance Engine DONE
- **New `pakhi/ws1/significance.py`** — locked §8 evaluator over the scored
  OOS event ledger (`net_of_benchmark`):
  - **Newey-West HAC** (`newey_west_se` / `newey_west_tstat`): autocorrelation-
    robust SE of the mean, NW-1994 lag `floor(4(N/100)^(2/9))` clamped to
    `[1, N//2]`, Bartlett weights. Hand-verified: `[1,2,3,4]` lag 1 ⇒ SE 0.625,
    t 4.0 exactly.
  - **Bootstrap engine** (10 000 resamples, seed 42, deterministic): p-value of
    edge > 0 and 95 % CI of the annualized net-of-benchmark event Sharpe, plus
    the full resample percentiles (p1/p5/p25/p50/p75/p95/p99) — T5 exit: *reports
    output probability distributions and p-values, exposing whether sparse-trade
    variance is too high* ✓.
  - **Locked §8 decision gate** (`decision_gate`): ZERO_TRADES /
    UNDER-POWERED (N < N_min) / PASS (N ≥ 8 ∧ Sharpe > 1.0 ∧ CI LB > 0) /
    FAIL→PIVOT; the pass wording carries the exact §8 inequality, locked
    N_min=8, N_FULL=30, SHARPE_GATE=1.0.
  - **Overlap check**: no overlapping events on the session-based v1.1 holds.
- **Harness**: every report now carries a `significance` section (metrics +
  decision + distribution + overlap + NW t/lag).
- **Live verdict (candidate):** N=7, NW t −0.59, bootstrap CI (−1.02, +2.11)
  straddles zero, p(edge>0)=0.63 → **UNDER-POWERED**, exactly the a-priori
  expectation from T4.
- **Tests** `tests/test_ws1_significance.py` (18): NW vs hand-computed SE/t
  (exact), lag rule, IID NW≈classic, short-series zero; bootstrap determinism +
  sign (positive edge p < 0.1, negative p > 0.9); all 5 gate branches incl.
  locked constants; empty-ledger report; harness `significance` section on
  candidate (N=7, CI straddles zero, p > 0.05) and demo (N=13).
- Full suite green: **1643 passed / 5 skipped**; ruff clean.

### 2026-08-12 — T6 G1 Hand-off DONE
- **New `pakhi/ws1/g1.py`**: the G1 decision record is **derived**, never
  hand-typed — it copies the significance report's locked §8 decision and
  cross-checks headline metrics against the metrics section; the record is
  self-hash-pinned (`payload_sha256`, canonical JSON) exactly like the contract
  and candidate artifacts, so the outcome cannot drift after the fact
  (`g1_decision_consistent` verifies hash + cross-checks).
- **Runner `scripts/run_t6_g1_report.py`** (CI entry, exit 0/1): full end-to-end
  OJ backtest of the pre-registered candidate with all armor layers (timestamp +
  vintage + roll-jump PASS), prints the G1 headline (Sharpe, CI, NW t, p, N,
  overlap, benchmark, span), writes `data/ws1/g1_decision.json`, exits 0 only on
  a consistent record.
- **Final report `docs/WS1_G1_REPORT.md`** (T6 exit): decision recorded
  **UNDER-POWERED** — N=7 < N_min=8, net-of-bench event Sharpe −0.193 (95% CI
  −1.019, +2.110), NW t −0.590 (lag 2), p(edge>0)=0.630, 0 overlapping events.
  Not a disproof and not a proof: the thesis **defers to Phase 2 live
  paper-trading** (60-day harness) to accumulate events past N_min=8; NG/HDD/
  ensemble/paper-trading remain deferred per blueprint §4 T6.
- **Tests** `tests/test_ws1_g1_report.py` (10): outcome derived from
  significance verbatim; real candidate ⇒ UNDER_POWERED (N=7); self-hash pins
  (tamper breaks), metric cross-check rejects mismatches; outcome labels cover
  all 4 gate branches; sha256 deterministic; runner exits 0 and the on-disk
  record matches a fresh live derivation; report + evidence artifacts exist.
- Full suite green: **1653 passed / 5 skipped**; ruff clean; `run_t4_candidate.py`
  and `run_t6_g1_report.py` both exit 0.

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Evaluation Contract | **DONE** | Locked v1.1 (re-lock); N_min=8 (ceiling 13 events); event-based net-of-benchmark Sharpe |
| T1 Engine Validation & Integration | **DONE** | exact known-value tests; PIT wired into engine; 2-session outcomes built (0 missing); v1.1 next-close fills, session-based episodes, cross-val Δ 2.6e-16; T3 tension resolved |
| T2 Provenance Logging | **DONE** | Signal.provenance (forecast_cycle_id / publication_ts / model_version / archive / roll_state); engine injects costs_incurred + provenance into every trade; exports t1_engine_trades.csv; 13/13 trades annotated; costs exactly 30 bps RT |
| T3 Lookahead Armor | **DONE** | timestamp layer (features precede 14:00 NY decision cutoff, min margin 2.5h; 48h feature window; feature/outcome separation) + vintage layer (source=noaa-gfs-bdp-pds, per-cycle pinned hashes, drift detection); engine `lookahead_armor=True` aborts on leaked/future provenance; leaked backtest errors out |
| T4 Signal Redefinition & Safety | **DONE** | pre-registered "ColdGrip" (θ_p = train-window median freeze_prob, θ_t = 0°C fixed, 1 free param, ≤1 trade/episode, 2-session hold); in-fold re-estimation (fold-1 seed-only); fires **7 OOS trades** (exit criterion MET); roll-jump armor (§9.3, X=5, WS-0 machinery) added — unmodeled roll-date gap ⇒ `RollJumpError`; 0/34 real roll gaps flagged |
| T5 Statistical Significance Engine | **DONE** | Newey-West HAC (hand-verified SE 0.625/t 4.0); bootstrap p + 95% CI on annualized net-of-bench event Sharpe (10k resamples, seed 42, deterministic); §8 gate (ZERO/UNDER-POWERED/PASS/FAIL→PIVOT); overlap check; harness `significance` section. Live: N=7 ⇒ CI (−1.02, +2.11) straddles zero, p 0.63 |
| T6 G1 Hand-off | **DONE** | `docs/WS1_G1_REPORT.md` + self-hash-pinned `data/ws1/g1_decision.json`: outcome **UNDER-POWERED** (N=7 < N_min=8); Sharpe −0.193 (CI −1.019, +2.110); NW t −0.590; p 0.630; defers to Phase 2 paper-trading to grow N past 8; NG/HDD/ensemble/paper-trading deferred per blueprint |

## Open items / risks

- N≥30 structurally unreachable for freeze events → contract locks the shrunk
  claim (N_min=8) and an UNDER-POWERED path; live paper-trading (Phase 2) is
  the only way to grow event count.
- **T6 honest outcome recorded:** the pre-registered ColdGrip candidate fires
  **7 OOS trades** — above 0 (T4 exit MET) but below N_min=8, so G1 is
  **UNDER-POWERED** (no conclusion) and the thesis defers to Phase 2
  paper-trading to accumulate events. This is a data fact, not a defect: the
  rule was registered before scoring, is one-shot (no re-tuning), and every
  armor layer PASSED on the real run.
- `BacktestEngine` now exact (known-value tests) and PIT-integrated (T1 done).
- **v1.1 T3 note:** next-close fills resolve the prior-close lookahead. The
  timestamp/vintage assertion engine (bdp-pds) over the as-published archive is
  implemented and armed (T3 DONE); §9.1/§9.2 gates now abort any leaked run.
