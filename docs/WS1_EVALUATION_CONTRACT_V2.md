# WS-1 Evaluation Contract v2.0 (DRAFT — NOT YET LOCKED)

**Status:** DRAFT 2026-08-19. This contract is **not locked**. It extends v1.1
(ColdGrip on OJ) to a multi-instrument evaluation. It MUST be hash-locked by the
CEO (with CTO co-sign) **before any OOS scoring of new instruments begins**.
v1.1 remains the authority for the existing single-instrument G1 result.

Machine-readable twin: `data/ws1/evaluation_contract_v2.json` (hash-pinned at lock).
Companion log: `docs/WS1_PROGRESS.md`.

**Companion code (Phase 1A):** the machine-readable instrument & signal-class
registry lives at `pakhi/ws1/instruments.py` (kept in sync with
`data/ws1/evaluation_contract_v2.json`). The market-data downloader is
`scripts/refresh_market.py` (fetches `OJ=F`, `ZC=F`, `NG=F`, `ZW=F` from Yahoo;
ERCOT is skipped — its price feed is a Phase 1B deliverable).

---

## 0. Purpose & relationship to v1.1

- **v1.1** covers OJ=F / ColdGrip only — locked, authoritative for the existing G1.
- **v2.0** adds Corn (ZC), Nat Gas (NG), Wheat (ZW), and ERCOT power as additional
  instruments, each with its own candidate signal and fold window.
- The single bottleneck is **N (event count)**. v2.0 is designed to **pool events
  across instruments** to reach a defensible sample size.
- **Pooled statistics are equal-weight per event**, not per-instrument, so no
  single instrument dominates the Sharpe estimate.

---

## 1. Instruments & data (locked at lock time)

| Instrument | Ticker | Signal class | Weather var | Region (bounding box) | Price source | Weather source |
|---|---|---|---|---|---|---|
| OJ (baseline) | `OJ=F` | ColdGrip | `freeze_prob` | Florida citrus belt | `yahoo` | `noaa-gfs-bdp-pds` |
| Corn | `ZC=F` | DroughtGrip | `spi_30d` | US Corn Belt `[-104,36,-80,48]` | `yahoo` | `noaa-gfs-bdp-pds` |
| Nat Gas | `NG=F` | StormGrip | `hurricane_prob` | Gulf of Mexico | `yahoo` | `noaa-gfs-bdp-pds` |
| Wheat | `ZW=F` | DroughtGrip | `spi_30d` | Great Plains wheat `[-104,32,-96,48]` | `yahoo` | `noaa-gfs-bdp-pds` |
| ERCOT Power | `ERCOT_POWER` | HeatGrip | `cdd_3day` | Texas (ERCOT) | `ercot_settlement` (pending, Phase 1B) | `noaa-gfs-bdp-pds` |

- **All features from the `noaa-gfs-bdp-pds` archive** (asserted in T3); **no ERA5
  in test features**. This is the same honesty discipline as v1.1 §1 — using
  archived *forecast* data, not reanalysis, preserves the no-lookahead property.
- **ERA5 reanalysis MAY be used ONLY for target validation** (did the drought /
  freeze actually occur?). It is **never** an input feature. Using ERA5 as a
  feature is hindsight bias and invalidates the run.
- **Price data:** OJ / Corn / Nat Gas / Wheat come from Yahoo Finance via
  `scripts/refresh_market.py`; ERCOT power has no Yahoo ticker and requires a
  settlement feed (Phase 1B). All price data is regenerable and git-ignored.
- 2-session outcome computable for all PIT rows (0 missing).

---

## 2. Windows & folds (per instrument, locked at lock)

Season-block **expanding-window** walk-forward, analogous to v1.1 §2. Each
instrument gets its own folds over its own historical window. The OOS evaluation
window per instrument is the union of its test folds.

| Instrument | Train seed | Test folds (OOS) | Approx. span |
|---|---|---|---|
| OJ | ≤ 2021-10-31 | 2022-11-01 → 2026-03-31 (4 folds) | 3.41 yr |
| Corn | ≤ 2015-12-31 | 2016-01-01 → 2026-03-31 | ~10 yr |
| Nat Gas | ≤ 2015-12-31 | 2016-01-01 → 2026-03-31 | ~10 yr |
| Wheat | ≤ 2015-12-31 | 2016-01-01 → 2026-03-31 | ~10 yr |
| ERCOT | ≤ 2015-12-31 | 2016-01-01 → 2026-03-31 | ~10 yr |

- **Embargo:** first 5 sessions of each test fold purged from scoring.
- Fold boundaries locked at hash time; no redefinition after OOS scoring.

---

## 3. Candidate definitions (pre-committed, locked at lock)

Each candidate is a **pure function of train-window data only** (per fold), has
**≤ 3 free parameters**, produces **≤ 1 trade per episode** (first firing row =
entry), and **never reads future prices** during definition.

### ColdGrip (OJ) — per v1.1 (unchanged)
Freeze-episode signal; see v1.1 §4. Pre-committed baseline.

### DroughtGrip (ZC, ZW)
```
fire(row) = (spi_30d <= theta_spi) AND (precip_anomaly <= theta_precip)
```
- `theta_spi`: **median SPI over train-window drought rows** (deterministic,
  per-fold — a fixed rule, not a tuned constant).
- `theta_precip`: **0.0** (physical: below-normal precipitation).

### StormGrip (NG)
```
fire(row) = (hurricane_prob >= theta_h) AND (gulf_proximity_km <= 320)
```
- `theta_h`: **median of the train-fold `hurricane_prob` distribution**
  (deterministic, per-fold) — the same empirical-median principle as ColdGrip's
  `theta_p`. No hardcoded float; the value is *derived*, never guessed.
- `gulf_proximity_km`: distance from Gulf landfall to NG infrastructure corridor
  (a fixed geographic constant, not a tuned parameter).

### HeatGrip (ERCOT)
```
fire(row) = (cdd_3day >= theta_cdd) AND (temperature_max_C >= 38)
```
- `theta_cdd`: **median of the train-fold `cdd_3day` distribution**
  (deterministic, per-fold) — empirical-median principle, same as above.
- `temperature_max_C >= 38`: fixed physical threshold (heatwave definition), not
  a tuned parameter.

> **Lock the mechanism, not the float.** Every non-physical threshold
> (`theta_spi`, `theta_h`, `theta_cdd`) is defined as the **median of the
> train-fold distribution of its weather variable**, computed per-fold and frozen
> before OOS scoring. This is exactly the intellectual-honesty discipline that
> made ColdGrip's `theta_p` defensible: the value is *derived from training data*,
> never hand-picked. Only physical/geographic anchors (precip ≤ 0, temp ≥ 38 °C,
> gulf proximity ≤ 320 km) are fixed constants. No `[PROPOSED]` floats remain.

---

## 4. Sample-size rule (locked)

- **Per-instrument N_min:** the highest defensible bar the data supports (mirrors
  v1.1's shrunk-edge logic). For OJ, N_min = 8 (ceiling 13). For others, set at
  lock from achievable episode ceilings.
- **Pooled N_min = 30 OOS event-trades** (full proof) / **≥ 8 pooled** (interim;
  UNDER-POWERED otherwise).
- `N_pooled < 30` ⇒ **UNDER-POWERED** (not a pass, not a forced pivot) — continue
  live paper-trading accumulation.

---

## 5. Trade construction & costs (locked — same as v1.1 §5)

- **Entry:** signal fires on PIT row with cycle date `c` → fill at the close of
  the **first trading session on/after** `c`.
- **Hold:** fixed **2 trading sessions**.
- **Gross event return:** `gross = close[fill+2]/close[fill] − 1`.
- **Costs:** 5 bps commission + 10 bps slippage per position change; **30 bps
  round trip**. `net = gross − 0.0030`.

---

## 6. Metric (locked — pooled, equal-weight per event)

- Pool all OOS event trades across **all instruments and folds** ⇒ `N_pooled`.
- **Headline = net-of-benchmark event-trade Sharpe**, annualized by the pooled
  span across instruments.
- Each instrument's own benchmark (always-long that instrument) is subtracted
  **per event** before pooling, so the pooled Sharpe is a clean cross-instrument
  net-of-benchmark estimate.
- Also reported (context only): gross event Sharpe, net event Sharpe, mean
  net-of-benchmark per event, t-stat, bootstrap 95 % CI (10 000 resamples,
  `np.random.default_rng(42)`).

---

## 7. Decision rules (locked, a-priori)

| Outcome | Condition | Action |
|---|---|---|
| **PASS** | `N_pooled ≥ 30` **and** net-of-benchmark Sharpe > 1.0 **and** bootstrap CI lower > 0 | Proceed to WS-2 multi-instrument |
| **FAIL → PIVOT** | `N_pooled ≥ 30` **and** (CI includes 0 **or** mean net ≤ 0) | Documented pivot (cat-bonds / reinsurance analytics) |
| **UNDER-POWERED** | `N_pooled < 30` | No conclusion; continue live paper-trading to accumulate events; G1 recorded UNDER-POWERED |
| **0 trades** | No signal fires OOS | **Architecture SUCCESS** → documented pivot |

**Kill / pivot criterion (added in v2.0):** if `N_pooled ≥ 30` **and**
net-of-benchmark Sharpe **< 0**, the multi-instrument edge is a **confirmed
null** → pivot to cat-bond / reinsurance analytics per blueprint §4 T6. This is
**not** an engineering failure; it is the harness fulfilling its falsification
mandate. A negative pooled Sharpe at sufficient N is a result, not a retry.

---

## 8. Hard gates (violation ⇒ run INVALID)

1. **Timestamp armor:** any feature vector referencing data published after its
   decision cutoff ⇒ invalid run.
2. **Vintage armor:** any feature not traced to `noaa-gfs-bdp-pds` (or whose
   vintage hash predates the feature's timestamp) ⇒ invalid run.
3. **Roll-jump armor:** any continuous-price move > `5 × daily_σ` at a roll date
   not driven by a modeled weather event ⇒ halt.
4. **[NEW] Cross-instrument leakage gate:** no instrument's features may use
   another instrument's market returns.

---

## 9. Anti-gaming (locked)

- One-shot evaluation; no metric feedback into tuning.
- No parameter search over the full window.
- No re-running the backtest with different thresholds to "find" a pass.
- All pre-registration artifacts committed to git before execution.

---

## 10. Change control

v2.0 draft → **lock** (CEO + CTO hash-sign). Amendments require `v2.(n+1)` with
rationale and re-locking before any result is final. v1.1 results are unaffected.

---

## 11. Implementation phase plan (1A–1D)

Status: **Phase 1A in progress.** Hash-lock only after 1A–1D are complete and
the empirical-median mechanism is verified clean of lookahead on historical
folds (reviewed by both the AI Co-Architect and CEO/CTO).

| Phase | Status | Deliverables |
|---|---|---|
| **1A** | IN PROGRESS | Contract V2 structure; `pakhi/ws1/instruments.py` registry (empirical-median mechanisms, no hardcoded thresholds); `scripts/refresh_market.py` downloader (Yahoo OJ/Corn/NG/Wheat; ERCOT pending) |
| **1B** | PENDING | DroughtGrip candidate + `theta_spi` (Corn/Wheat); continuous-series rebuild across all Yahoo instruments; ERCOT price-feed connector |
| **1C** | PENDING | StormGrip (NatGas) candidate + `theta_h`; HeatGrip (ERCOT) candidate + `theta_cdd` |
| **1D** | PENDING | Pooled event-level harness across instruments AND folds; lookahead-armor verification of every feature; `N_pooled ≥ 30` check |
| **LOCK** | PENDING | CEO + CTO hash after 1A–1D verified; flip `status: DRAFT → LOCKED`, set `payload_sha256` |

---

*Drafted by AI Co-Architect 2026-08-19. Pending CEO/CTO hash-lock. Companion files:
`data/ws1/evaluation_contract_v2.json` (to be hash-pinned), `docs/WS1_PROGRESS.md`.*
