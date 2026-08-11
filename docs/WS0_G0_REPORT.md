# WS-0 G0 Report — Freeze → OJ Relationship on Real PIT Data

Generated: 2026-08-11 (restated after PIT alignment + point-in-time feature fix).
Everything in this report is computed from **as-published** GFS archive data and
a back-adjusted OJ=F continuous close, assembled into a point-in-time frame. The
pipeline is deterministic and rebuildable via `scripts/rebuild_dataset.py`
(manifest: `data/ws0/manifest.json`, all 4 DQ gates green).

## 1. Dataset

| Layer | Coverage | Content | Status |
|---|---|---|---|
| Weather (GFS) | 2021-11-01 → 2026-03-31, 12Z, leads f000/f012/f024/f048 | 0p50, bbox [-85,24,-80,31], t2m/prate/mslet/u10/v10/gh500/t850 | 6448 parquets, **0 MISS**, all DQ gates pass |
| Market | 2015-01-02 → 2026-08-10 | OJ=F continuous, back-adjusted at 34 ICE FND roll dates | provenance CSV, 1 real event flagged |
| PIT frame | 1612 rows | freeze features \| next actual trading-session OJ return | `data/ws0/freeze_pit.parquet` |

Method: decision cutoff = 12Z run start + 3.5 h publish latency. Outcome = the
**next actual trading-day close** over the last close on-or-before the cycle date
— no calendar forward-filling, so weekends/holidays are skipped, not fabricated.
Features exclude forecast-valid times before the publish cutoff (as-published
constraint). Freeze feature = fraction of (cell × lead-hour) pairs with t2m < 0 °C
within 48 h of publish.

## 2. The claim under test

`pakhi/signals/freeze.py` docstring: *"Historical freezes have driven 15–40% OJ
price spikes within 48 hours."* The `FreezeSignal` goes LONG when
`freeze_prob > 0.6` (entry) and temperature is below freezing.

## 3. Findings

### 3.1 The signal never fires on real data
- **0 of 1612** PIT days produce a LONG signal (1612 FLAT).
- Max `freeze_prob` by season: **21.8%** (2025/26), 15.6% (2022/23), 12.3%
  (2024/25), 8.9% (2021/22), 5.9% (2023/24) — all **far below** the 0.6 entry
  threshold. The feature definition (fraction of cell-hours < 0 °C, diluted by
  daytime warmth and warm cells) is structurally incompatible with the 0.6
  threshold.

### 3.2 The relationship is negative and significant
Forward OJ return by freeze bucket (n=1612):

| bucket | n | mean fwd return |
|---|---|---|
| no freeze cells | 1557 | +0.11 % |
| trace (0–5 %) | 39 | −0.44 % |
| low (5–20 %) | 15 | −2.40 % |
| mid (20–50 %) | 1 | −10.8 % |

Spearman(`freeze_prob`, `fwd_return`) = **−0.062** (p=0.013): **statistically
significant and negative.** Freeze forecasts tend to precede OJ *declines*, not
spikes.

### 3.3 Flagship events (weather ground truth)
| Event | GFS forecast (wide-FL bbox) | OJ behavior |
|---|---|---|
| Jan 2022 hard freeze | 2022-01-29 cycle: min −2.5 °C, freeze_prob 5.9% (Jan-30 cycle already warmed: +4.0 °C, 0%) | next-session OJ **fell** −2.6 %; week fell 8.6 % |
| Jul 2025 +12.9% (07-07) / +11.6% (07-09) | +22–24 °C, freeze_prob 0 | big rallies with **zero** freeze weather (Brazil supply news) |
| Apr 2025 +43.6% in 5 d | +9–10 °C, freeze_prob 0 | not freeze-driven |
| Oct 2025 +11.4% (10-22) | +10.1 °C, freeze_prob 0 | not freeze-driven |
| Sep 2024 max close 555.5 | hurricane season | not freeze-driven |

The 8 largest forward OJ moves of the window (2025-07-07 … 2025-03-18, +9.5% to
+12.9%) all carry `freeze_prob = 0.0`.

### 3.4 Verdict
**REFUTED.** On the 5-season real PIT dataset the "15–40% OJ spike within 48 h
of freeze" claim does not hold: the signal never triggers, and where real
freezing forecasts appear (Jan 2022) OJ *declined*. The largest OJ moves of
2021–2026 occurred with no freezing weather in Florida.

**Caveats (bounding the conclusion):**
- Freeze feature is a bbox-wide cell-hour fraction; a finer event definition
  (duration below 0 °C at citrus-belt stations, cold-pool depth) could behave
  differently — but the Jan-2022 hard freeze was detected and still no spike.
- Only 1 PIT row lands in the mid (20–50 %) bucket; the significant Spearman is
  driven by the trace/low buckets.
- Yahoo continuous chain (adjusted) used for prices; individual ICE contracts
  are not on Yahoo. Cross-checked against raw chain — same events, same picture.
- 0p50 grid (vs 0p25) may understate cold-cell fractions on small cold pools.

## 4. Recommendation for G0
Treat `FreezeSignal` as **unsupported by real data** in its current form. If the
freeze thesis is pursued: (a) redefine the feature (e.g., min t2m < −2 °C with
duration at citrus-belt cells, or NWS freeze-warning as ground truth),
(b) re-estimate entry/exit thresholds from the PIT frame, and (c) expect the
relationship to be weak and possibly negative. Do not cite the 15–40% docstring
claim without qualification.
