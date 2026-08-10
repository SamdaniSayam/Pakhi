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

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Wedge decision | **DONE** | OJ primary / ERCOT backup |
| T1 Weather layer | **running** | full backfill in background (~11h); byte-range proven |
| T2 Market layer | **DONE** | Yahoo parquets + ICE-verified roll calendar |
| T3 Continuous contracts | pending | after T1 lands |
| T4 PIT dataset | pending | |
| T5 Reproducibility + DQ | pending | |
| T6 G0 handoff | pending | |

## Open items / risks

- ERCOT DAM data access needs registration/key (if ERCOT chosen).
- GFS 0p25 archive starts ~2021 → ~5y horizon for backtest.
- Yahoo auto_adjust vs raw prices: cross-check against CME settlement for a sample.
