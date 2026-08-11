# WS-0 G0 Report — Freeze → OJ Relationship on Real PIT Data

Generated: 2026-08-11. Everything in this report is computed from
**as-published** GFS archive data and Yahoo front-month OJ futures, assembled
into a point-in-time frame. The pipeline is deterministic and rebuildable via
`scripts/rebuild_dataset.py` (manifest: `data/ws0/manifest.json`).

## 1. Dataset

| Layer | Coverage | Content | Status |
|---|---|---|---|
| Weather (GFS) | 2021-11-01 → 2026-03-31, 12Z, leads f000/f012/f024/f048 | 0p50, bbox [-85,24,-80,31], t2m/prate/mslet/u10/v10/gh500/t850 | 6448 parquets, **0 MISS**, all DQ gates pass |
| Market | 2015-01-02 → 2026-08-10 | OJ=F continuous (Yahoo), back-adjusted at 34 ICE FND roll dates | provenance CSV, 1 real event flagged |
| PIT frame | 1612 trading days | freeze features \| next-trading-day OJ return | `data/ws0/freeze_pit.parquet` |

Decision cutoff = 12Z run start + 3.5 h publish latency. Outcome = next-day
close return. Freeze feature = fraction of (cell × lead-hour) pairs with
t2m < 0 °C within 48 h of publish.

## 2. The claim under test

`pakhi/signals/freeze.py` docstring: *"Historical freezes have driven 15–40% OJ
price spikes within 48 hours."* The `FreezeSignal` goes LONG when
`freeze_prob > 0.6` (entry) and temperature is below freezing.

## 3. Findings

### 3.1 The signal never fires on real data
- **0 of 1612** PIT days produce a LONG signal.
- Max `freeze_prob` over the whole window: **18.0%** (2022/23), 16.4% (2025/26),
  12.9% (2024/25), 6.7% (2021/22), 4.4% (2023/24) — all **far below** the 0.6
  entry threshold. The feature definition (fraction of cell-hours < 0 °C, diluted
  by daytime warmth and warm cells) is structurally incompatible with the 0.6
  threshold.

### 3.2 The relationship is negative, not positive
Forward OJ return by freeze bucket (n=1612):

| bucket | n | mean fwd return |
|---|---|---|
| no freeze cells | 1537 | +0.08 % |
| trace (0–5 %) | 59 | −0.22 % |
| low (5–20 %) | 16 | −1.27 % |

Spearman(`freeze_prob`, `fwd_return`) = **−0.040** (p=0.106): weak, negative,
not significant. Freeze forecasts tend to precede OJ *declines*, not spikes.

### 3.3 Flagship events (weather ground truth)
| Event | GFS forecast (wide-FL bbox) | OJ behavior |
|---|---|---|
| Jan 29–30 2022 freeze | min −2.2 to −2.8 °C, 70–99 freeze cells | **fell** 8.6% (161.6→147.6) that week; freeze-week fwd returns 0% / −2.6% |
| Jul 2025 +12.9% / +11.6% days | +22–24 °C, freeze_prob 0 | big rallies with **zero** freeze weather (Brazil supply news) |
| Apr 2025 +43.6% in 5 d | +10–14 °C, freeze_prob 0 | not freeze-driven |
| Sep 2024 max close 555.5 | hurricane season | not freeze-driven |

### 3.4 Verdict
**REFUTED.** On the 5-season real PIT dataset the "15–40% OJ spike within 48 h
of freeze" claim does not hold: the signal never triggers, and where real
freezing forecasts appear (Jan 2022) OJ *declined*. The largest OJ moves of
2021–2026 occurred with no freezing weather in Florida.

**Caveats (bounding the conclusion):**
- Freeze feature is a bbox-wide cell-hour fraction; a finer event definition
  (duration below 0 °C at citrus-belt stations, cold-pool depth) could behave
  differently — but the Jan-2022 hard freeze was detected and still no spike.
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
