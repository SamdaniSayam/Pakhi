# WS-0 Progress Tracker — Real-Data Foundation

Per working agreement: every execution step is logged here with terminal evidence,
and the user is shown the running terminal live.

- Blueprint: `docs/WS0_EXECUTION_BLUEPRINT.md`
- Gate: G0 (end week 4) — infra readiness, not a pivot decision
- Started: 2026-08-10 (blueprint approved by user)

---

## Log

### 2026-08-10 — Readiness + start
- **Found & fixed hard blocker (commit `770dd01`):** GFS connector used NOMADS v1.1
  `var=` format; v1.2 rejects it with HTTP 500 "invalid parameter: var". Fixed to
  `var_<ABBREV>=on&lev_<level>=on&subregion=` (checkbox format).
- **Verified live against NOMADS 0p25:** bbox [-85,-10,-60,50], 5 vars
  (`t2m, u10, v10, mslet, gh, t`), 241×101 grid, t2m ≈ 294.4 K. cfgrib parses cleanly.
- **Verified NOAA AWS as-published archive** (`noaa-gfs-bdp-pds`): HTTP 206 —
  multi-year backfill source (NOMADS retains only ~10 days; older cycles → 403).
- **Verified Yahoo futures:** `OJ=F` 139.55, `NG=F` 2.795 (1mo daily).
- **Precipitation fact:** GFS analysis files carry `PRATE` (not APCP); APCP exists f006+.
  Map updated accordingly.
- Full suite green: 1462 passed / 5 skipped; ruff clean.
- Blueprint reviewed and **approved** by user → execution started.

### 2026-08-10 — T0 decided + T1 (weather layer) technique proven
- **T0 WEDGE DECISION:** **OJ primary** (FreezeSignal built, 11.5y Yahoo history, 2022
  FL freeze spike 91→555 evidence), **ERCOT DAM backup** (network-access thesis; free
  API after registration, `NP4-180-ER` historical DAM hub prices; Feb 2021 Uri spike
  evidence). Recorded with rationale.
- **T1 blocker solved:** NOMADS only retains ~10 days (older cycles → 403). Verified
  **byte-range extraction** from the NOAA AWS as-published archive
  (`noaa-gfs-bdp-pds`): GRIB `.idx` offsets → Range-GET only the needed messages
  (~1MB/level vs ~120MB full file). 7 variables (`t2m,u10,v10,mslet,gh,t,prate`)
  parsed from a single cycle.
- **Implemented in connector** (`pakhi/src/noaa.py`): `AWS_GFS_URL`, `_object_url`,
  `_idx_offsets`, `_fetch_archive_cycle`, `_subset_bbox` (descending-lat fix);
  `archive(..., source="auto"|"nomads"|"aws")` with NOMADS→AWS fallback.
- **Pilot backfill:** 2026-01-15→16, Florida bbox [-84,25,-80,30], 8 cycles × 7 vars.
  Physically sane: t2m 271.9–296.8 K, mslet ~1010–1023 hPa, gh500 ~5.44–5.79 km.
  Cached rerun 6.8s. Descending-latitude subset bug found & fixed.
- Full suite: **1466 passed / 5 skipped**; ruff clean.

### 2026-08-11 — T1 scaling + T2 (market layer) done
- **Fixed cache-naming bug** (tuple unpacking order in `_fetch_archive_cycle` — produced
  var-named 0-byte files → "No valid message found"). Added `_range_get_with_retry`
  (transient `RemoteDisconnected` hit) and instant-over-average record selection
  (PRATE has `N hour fcst` + `N-M hour ave fcst` at f024+; we take the instantaneous one).
- **Parallelized backfill** (`scripts/backfill_gfs.py`, 8 workers, resumable via
  parquet-existence). Launched detached (setsid) for the full window:
  **2021-11-01 → 2026-03-31, 12Z, leads f000/f012/f024/f048, 0p50, Florida bbox
  [-84,25,-80,30] = 6448 cycles** (~11h background). 0 misses so far.
- **T2 DONE:** OJ=F + NG=F daily 2015→2026 (2918 rows each) saved to parquet.
- **Roll calendar:** ICE FCOJ specs verified (odd months, 15,000 lbs, tick 0.05¢,
  FND = 1st biz day of contract month, LTD = 15th-last biz day). Calendar generated
  with US-federal holidays minus Veterans Day (ICE does not observe it) — **matches
  ICE's published expiry table exactly** (Jul26=7/13, Sep26=9/10, Nov26=11/9, …).
  36 contracts, 2021–2026, saved to `data/market/oj_contract_calendar.csv`.
- **Spot-check finding (honest):** the signal docstring claims "15–40% OJ spikes
  within 48h" from freezes — real data shows the Jan-2022 freeze was small (~143→161);
  the big 5-day moves are 2025-04-14 (+43.6%), 2025-07-11 (+42.9%), max close 555.5 on
  2024-09-06 (hurricane). G0 will judge the real relationship — it may refute the
  synthetic backtest.

### 2026-08-11 — T3 (continuous contracts) DONE
- **Provenance check first:** Yahoo's raw `OJ=F` chain shows no systematic roll
  artifacts at FND — only 1/20 largest daily moves lands within ±2d of a First
  Notice Day → the big moves (Jul/Oct 2025 freezes, 2026-06-30) are real events.
  Individual ICE contract-month tickers (OJH26, …) are NOT on Yahoo → the chain is
  built from the continuous series with documented assumptions.
- **`pakhi/ws0/roll.py`** (new, tested): `front_month_map` (FND: roll *on* FND;
  LTD: roll *after* LTD), `back_adjust` (removes roll-date gaps below 5σ-of-prior-
  vol; flags larger ones as real events and never deletes them), `roll_jump_assertion`
  (flags any >5σ move within ±3d of a roll). Vol uses the **signed-return** rolling σ
  at the day *before* the move (avoids self-contamination); degenerate flat regime
  uses a nominal 1.5× threshold. (Two consistency bugs found+fixed during build:
  log-space threshold with threshold<1; abs-return vs signed-return σ mismatch.)
- **Outputs:** `data/market/oj_continuous.parquet` (back-adjusted + raw), 
  `oj_roll_provenance.csv` (22 rolls 2022-12→2026-08, each with factor + flag),
  `oj_roll_assertions.csv` (1 real event flagged: 2023-11-02 −7.5% @5.4σ).
  Build script: `scripts/build_continuous.py`.
- Full suite: **1474 passed / 5 skipped**; ruff clean.

### 2026-08-11 — T4 partial + T1 exit-criterion pre-check
- **`pakhi/ws0/features.py`** (tested): GFS grid → FreezeSignal `forecast` dict —
  `temperature_min` (min t2m °C), `freeze_prob` (fraction of (cell × lead) with
  t2m<0°C within 48h of publish), `event_peak_time`, point-in-time `current_time`
  (= 12Z run start + 3.5h publish latency).
- **`scripts/build_pit.py`**: aligns each 12Z cycle with the **next-trading-day**
  OJ outcome (decision cutoff = publish time). `data/ws0/freeze_pit.parquet`.
- **`scripts/eval_freeze_signal.py`** (T1 exit criterion): runs the real
  `FreezeSignal` over the PIT frame.
- **Honest findings (G0 pre-check), all from real as-published GFS + OJ data:**
  - Jan-2022: coldest FL-bbox 12Z f024 forecast was **+0.7°C (Jan 22)**; the
    Jan 29–30 freeze week saw OJ **fall 8.6%** (161.6→147.6). No freeze→spike.
  - Jul-2025 (+12.9%/+11.6% days): FL t2m **+23.9°C**, zero freeze cells. Not
    freeze-driven (Brazil crop).
  - Apr-2025 (+43.6% in 5d): FL t2m +10–14°C, zero freeze cells. Not freeze-driven.
- **VERDICT so far: REFUTED-dormant** — across 117 PIT days (2021-11→2022-02)
  `freeze_prob` maxes at 0.131 (< 0.6 entry), so FreezeSignal fires **0 LONGs**;
  all large OJ moves had zero freeze forecast. The "15–40% OJ spike within 48h
  of freeze" docstring claim is **not** a tradable rule on this real PIT data.
  (Caveat: bbox [-84,25,-80,30] may miss north-FL hard freezes; full 5-season
  verdict after backfill completes.)
- Raw OJ=F re-pulled from 2015 (was 2022-12) → continuous + PIT now cover the
  2021-22 season. Suite: **1480 passed / 5 skipped**.

### 2026-08-11 — FULL DATASET COMPLETE + T5/T6 DONE
- **Wide-bbox correction:** narrow bbox [-84,25,-80,30] **missed the Jan-2022
  hard freeze entirely** (coldest +0.7°C). Wide bbox [-85,24,-80,31] detects it
  (min −2.2…−2.8°C, 70–99 freeze cells on Jan 29–30). All backfill rerun with the
  wide bbox; filenames now bbox-tagged (deterministic rebuild).
- **Backfill complete: 6448/6448 parquets, 0 MISS** (2021-11-01→2026-03-31, 12Z,
  f000/f012/f024/f048, 0p50, wide FL bbox). DNS flakiness caused a 4864-MISS first
  run → fixed with whole-job retry+backoff and per-worker long-lived connectors
  (reuses connections/DNS). Rerun: 4864 OK, 0 MISS in 127.6 min.
- **T5 DONE:** `scripts/rebuild_dataset.py` — deterministic rebuild (backfill →
  continuous → PIT) + DQ gates. All 4 gates pass on full data (completeness 6448
  units, schema/range on every parquet, staleness, PIT plausibility). Manifest
  with per-step rc + sha256 hashes: `data/ws0/manifest.json`.
- **T6 DONE:** `docs/WS0_G0_REPORT.md` — **verdict: REFUTED.** Full 5-season
  evidence:
  - FreezeSignal fires **0/1612** LONGs; max freeze_prob 18.0% << 0.6 threshold.
  - Forward OJ return by bucket: no-freeze +0.08%, trace −0.22%, low −1.27% →
    relationship is **negative**; Spearman −0.040 (p=0.106).
  - Jan-2022 hard freeze (detected in wide bbox): OJ **fell** 8.6% that week.
  - Jul-2025 +12.9%/+11.6% and Apr-2025 +43.6% rallies: freeze_prob 0 (+22…24°C,
    +10…14°C). Biggest moves are NOT freeze-driven.
  - Recommendation: do not cite the 15–40% claim without qualification; redefine
    feature/thresholds if the freeze thesis is pursued.

### 2026-08-11 — PIT audit corrections + G0 report restated (commit `531485e`)
- **PIT outcome alignment fixed (`scripts/build_pit.py`):** the old builder
  resampled prices to calendar days with `.ffill()`, fabricating 529/1612 (33%)
  zero forward returns (weekend "prices" = Friday's close → 0.0 %). Now the
  outcome is the **next actual trading-day close** over the last close on-or-before
  the cycle date, read directly from the OJ index — no forward-filling. Rebuilt
  PIT: 1612 rows, **54/1612 (3.3 %)** flat returns, each verified as genuine
  consecutive-equal closes at holidays/month/year boundaries.
- **Point-in-time feature fix (`pakhi/ws0/features.py`):** freeze features now
  exclude forecast-valid times *before* the publish cutoff (`valid >= current_time`);
  f000 analysis cells (valid 12Z, pre-publish) are no longer usable. Max
  `freeze_prob` rises 18.0 % → **21.8 %** (2025/26); 74 PIT rows change.
- **G0 report restated (`docs/WS0_G0_REPORT.md`)** on the corrected frame.
  Verdict unchanged and **strengthened**: signal still fires **0/1612** LONGs;
  Spearman(`freeze_prob`, `fwd_return`) is now **−0.062 (p=0.013)** — significant
  and negative. Buckets: no-freeze +0.11 % (n=1557), trace −0.44 % (n=39), low
  −2.40 % (n=15), mid −10.8 % (n=1). All top forward moves (+9.5 %…+12.9 %) carry
  freeze_prob 0.
- **Dataset regenerated end-to-end** via `scripts/rebuild_dataset.py`: 6448/6448
  GFS units, all 4 DQ gates pass, manifest hashes refreshed
  (`freeze_pit` → `73d72260…`). **1480 passed / 5 skipped; ruff clean.**

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Wedge decision | **DONE** | OJ primary / ERCOT backup |
| T1 Weather layer | **DONE** | 6448/6448 parquets, 0 MISS (as-published AWS archive, byte-range) |
| T2 Market layer | **DONE** | Yahoo parquets + ICE-verified roll calendar |
| T3 Continuous contracts | **DONE** | roll.py + provenance; 34 rolls back-adjusted 2021→2026, 1 real event flagged |
| T4 PIT dataset | **DONE** | 1612-row PIT, next actual trading-session outcomes; signal never fires |
| T5 Reproducibility + DQ | **DONE** | rebuild_dataset.py; 4 DQ gates pass; manifest with sha256 hashes |
| T6 G0 handoff | **DONE** | G0 report: REFUTED (Spearman −0.062, p=0.013) |

## Open items / risks

- ERCOT DAM data access needs registration/key (if ERCOT chosen).
- GFS 0p25 archive starts ~2021 → ~5y horizon for backtest.
- Yahoo auto_adjust vs raw prices: cross-check against CME settlement for a sample.
