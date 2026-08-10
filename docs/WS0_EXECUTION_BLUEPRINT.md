# WS-0 — Real-Data Foundation: Execution Blueprint

Status: **AWAITING USER REVIEW** (2026-08-10)
Progress: tracked in `docs/WS0_PROGRESS.md` (created after this blueprint is approved)
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-0
Gate: G0 (end of Phase 0 / week 4) — infra readiness, *not* a pivot decision.

---

## 1. Purpose

Replace synthetic / ERA5-derived assumptions with a **point-in-time, as-published,
provenance-tracked real dataset** that WS-1 can backtest honestly. WS-0 does not
produce a decision on alpha; it produces the pipeline that makes the decision possible
without fooling ourselves.

Success = a reproducible dataset rebuild script + data-quality checks + provenance
manifest, and a walk-forward backtest that **reproduces or refutes** the synthetic
numbers.

## 2. Readiness audit (verified live today, 2026-08-10)

| Layer | Status | Evidence |
|---|---|---|
| GFS connector (NOMADS) | **FIXED** — was broken | `var=TMP` → HTTP 500 "invalid parameter: var"; now `var_TMP=on&lev_2_m_above_ground=on&subregion=` → 200 |
| GFS live fetch | ✅ works | 0p25, bbox [-85,-10,-60,50], 5 vars (`t2m, u10, v10, mslet, gh, t`), 241×101 grid, real t2m ≈ 294.4 K |
| cfgrib parse | ✅ works | `t2m` coords: time, step, heightAboveGround, latitude, longitude, valid_time |
| NOAA AWS as-published archive | ✅ reachable | `noaa-gfs-bdp-pds` S3 bucket HTTP 206 — multi-year backfill source |
| NOMADS retention | ⚠️ ~10 days only | 2026-07-15 / 06-01 cycles → HTTP 403 |
| Yahoo futures market data | ✅ works | `OJ=F` (139.55), `NG=F` (2.795) 1mo daily history |
| FreezeSignal | ⚠️ built, untested on real data | entry 0.6 / exit 0.2, LONG iff prob>threshold & tmin<0 |
| Unit/CI gate | ✅ green | 1462 passed / 5 skipped; ruff clean |

**Hard blocker found and already fixed** (commit `770dd01`): the GFS connector used the
NOMADS v1.1 `var=` query format, which the v1.2 filter rejects. This would have silently
made WS-0 impossible. Fixed format (verified against NOMADS and the AWS archive):

```
filter_gfs_0p25.pl?file=gfs.t{cycle}z.pgrb2.0p25.f{hh}&dir=/gfs.{date}/{cycle}/atmos
  &subregion=&leftlon=..&rightlon=..&toplat=..&bottomlat=..
  &var_TMP=on&lev_2_m_above_ground=on
```

Note: `precipitation` maps to `PRATE` (GFS analysis files carry precipitation *rate*,
not accumulated APCP; `APCP` exists only from f006+). Committed as part of the fix.

## 3. Data sources & availability matrix

| Source | Use | Vintage | Horizon | Access |
|---|---|---|---|---|
| NOMADS filter (`filter_gfs_{res}.pl`) | live / recent cycles | as-published | ~10 days back | free HTTPS, no key |
| NOAA Open Data archive (`noaa-gfs-bdp-pds`, AWS S3) | as-published backfill | as-published, per-cycle | 2021–now (0p25) | free HTTPS, no key |
| ERA5 (CDS) | **training ground-truth only** | reanalysis (not as-published) | 1940–now | free API key (CDS) |
| Yahoo Finance futures (`OJ=F`, `NG=F`, …) | market close / OHLC | as-published-ish (revised) | ~10y | free, no key |
| CME settlement / ERCOT DAM archives | contract/roll + DA prices | as-published | varies | free downloads |

Decision rule: **any field that drives a backtest trade must be as-published**; ERA5 may
feed model training, never the test window's features.

## 4. Tasks, sequencing, exit criteria

### T0 — Wedge instrument decision (day 1)
- Criteria (network access, not edge): (a) local/regional data we can get that the market
  doesn't price instantly; (b) liquid futures to trade; (c) ≥ 5y of both forecast and price
  history; (d) existing Pakhi signal coverage.
- Candidates: **OJ** (Florida freeze — `FreezeSignal` exists, classic), **NG** (winter
  storms/heating), **ERCOT DAM** (local TX grid vs DA auction — strongest *network-access*
  story, hardest data).
- **Exit:** one primary + one backup instrument recorded with rationale.

### T1 — Weather data layer (week 1)
- Extend `GFSConnector.archive()` to source from the NOAA AWS archive for cycles older
  than NOMADS retention; NOMADS for recent.
- Backfill `[as-published]` GFS for the wedge bbox at 0p25: t2m, u10/v10, mslet,
  HGT500, TMP850, PRATE — 4 cycles/day.
- Storage: per-cycle Parquet (bounded rows, cheap, no indexpath headaches) with cycle +
  archive-version metadata.
- **Exit:** rebuild script reproduces N days of weather for the wedge region; spot-check
  a known event against NWS records; cycle inventory table (which cycles have data, from
  which archive).

### T2 — Market data layer (week 1–2)
- `YahooFuturesConnector` daily OHLC for wedge instruments (front-month = ticker).
- Acquire **contract roll schedule** (first notice / expiry per contract month) — from CME
  specs, not inferred.
- ERCOT DAM history if ERCOT is the wedge.
- **Exit:** contiguous daily price series with explicit missing-day log; roll schedule table
  committed to repo (with source URLs).

### T3 — Continuous contracts with roll adjustment (week 2)
- Build back- (ratio-) adjusted continuous series **before any feature** is computed.
- Record per-contract provenance: roll date, adjustment type (back/ratio), factor, source.
- Guard: no adjustment factor applied twice; splice verified by checking no phantom jump
  > X× daily σ at roll dates.
- **Exit:** continuous series + roll-provenance table; roll-jump assertion passes.

### T4 — Point-in-time aligned dataset (week 2–3)
- For each trading day: the **last forecast run published before the decision cutoff**
  (GFS ~3.5h after cycle) + the **realized outcome** (next day's close) joined to the
  roll-adjusted contract.
- Vintage layer: each feature carries `archive_version`/`publication_ts`; feature with a
  vintage predating its own timestamp → excluded, logged.
- **Exit:** PIT feature frame; zero lookahead leaks (timestamp + vintage assertion passes).

### T5 — Reproducibility + data quality (week 3–4)
- One script rebuilds the whole dataset from raw sources (`scripts/rebuild_dataset.py`),
  deterministic, with a hash of inputs → output manifest.
- Quality gates: schema check, completeness (cycles expected vs present), staleness,
  empty-frame ban (per commercial blueprint), outlier flags.
- **Exit:** clean rebuild on a fresh machine checkout; manifest hash reproducible.

### T6 — G0 handoff (end week 4)
- Run the current `BacktestEngine` (walk-forward, costs) on the PIT frame with the wedge
  signal — **reproduce or refute** the synthetic numbers. This is G0's purpose.
- Record result in `WS0_PROGRESS.md` + docs. It is explicitly *not* a pivot decision.
- **Exit:** G0 report written; WS-1 has a clean PIT frame to harden.

## 5. Provenance & vintage discipline (applies to all tasks)

1. **As-published only for backtest features.** Reanalysis (ERA5) never enters the test window.
2. **Vintage hash per cycle:** record source (NOMADS vs AWS), fetch date, and a content hash;
   a cycle fetched today for a past date is not bit-for-bit what was published in real time —
   this is the lookahead bug that survives timestamp-only checks.
3. **Explicit gaps:** missing cycles are listed, never silently interpolated.
4. **Roll state in provenance:** every price point knows its contract month + adjustment factor.

## 6. Timeline

| Week | Focus | Deliverable |
|---|---|---|
| 0 | Readiness (this doc) + T0 | wedge decision |
| 1 | T1 + T2 | weather + market raw layers |
| 2 | T3 + T4 | continuous contracts + PIT frame |
| 3 | T4 + T5 | PIT frame complete + quality gates |
| 4 | T5 + T6 | reproducible rebuild + G0 report |

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| NOAA AWS archive gaps (missing cycles) | cycle inventory; explicit gap log; fall back to NOMADS/DODS; exclude from test window |
| Yahoo price revisions / survivorship | only wedge tickers; cross-check against CME settlement for a sample |
| Roll adjustment errors inflate Sharpe | ratio-adjustment before features; roll-jump assertion; provenance table |
| GFS `archive()` slow (4 cycles/day × N days) | parallel downloader; cached Parquet; range-limited backfill windows |
| FreezeSignal untuned on real data | G0 evaluates honestly; no threshold tuning on test window |

## 8. Handoff to WS-1

WS-0 delivers to WS-1: the PIT frame (feature frame + provenance columns), the
roll-adjusted continuous series, the cycle inventory, and the rebuild script. WS-1 adds
no-lookahead guardrails, provenance logging on trades, and statistical-significance rules
(min trade count ≥ 30 + bootstrap CI) before G1.

## 9. Progress tracking

Per working agreement: after this blueprint is reviewed, all execution progress is tracked
in **`docs/WS0_PROGRESS.md`** (kept together with the other `.md` docs), updated at each
step with terminal evidence, and the user is shown the running terminal output live.
