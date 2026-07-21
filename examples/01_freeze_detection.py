#!/usr/bin/env python3
"""
01 — Freeze Detection Pipeline
================================
End-to-end freeze risk assessment for Florida citrus country.

Workflow:
  1. Load synthetic hourly temperature data (simulating Open-Meteo)
  2. Compute freeze probability from ensemble-like forecasts
  3. Build frost-day features
  4. Generate a FreezeSignal for OJ futures
  5. Print formatted results

Usage:
    pip install pakhi
    python examples/01_freeze_detection.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from pakhi.features.climate import ClimateFeatures
from pakhi.signals.base import Action
from pakhi.signals.freeze import FreezeSignal
from pakhi.targets.temperature import freeze_probability

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

DIVIDER = "=" * 64
SUBDIV = "-" * 64


def section(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def subsection(title: str) -> None:
    print(f"\n  {SUBDIV}")
    print(f"  {title}")
    print(f"  {SUBDIV}")


# ──────────────────────────────────────────────────────────────────────
# 1. Generate synthetic Florida temperature data
# ──────────────────────────────────────────────────────────────────────

section("1. SYNTHETIC DATA — Florida Hourly Temperatures")

np.random.seed(42)
n_hours = 168  # 7 days
base_time = datetime(2024, 1, 15, 0, 0)

# Simulate a cold front passage: temps drop from ~18°C to -2°C then recover
hours = np.arange(n_hours)
diurnal = 4.0 * np.sin(2 * np.pi * (hours - 6) / 24)  # day/night cycle
cold_front = 20.0 * np.exp(-((hours - 60) ** 2) / 800)  # cooling pulse
baseline = 18.0 - cold_front + diurnal
noise = np.random.normal(0, 1.5, n_hours)
temps_celsius = baseline + noise

# Create 10 "ensemble members" by adding perturbations
n_members = 10
ensemble = np.stack(
    [temps_celsius + np.random.normal(0, 0.8, n_hours) for _ in range(n_members)], axis=1
)

times = pd.date_range(base_time, periods=n_hours, freq="h")
df = pd.DataFrame(
    {
        "time": times,
        "temp_mean": temps_celsius,
        "temp_min": temps_celsius - 2.5,
        "temp_max": temps_celsius + 1.5,
    }
)
df = df.set_index("time")

print("  Location : Central Florida (28.5°N, 81.5°W)")
print(
    f"  Period   : {times[0].strftime('%Y-%m-%d %H:%M')} → {times[-1].strftime('%Y-%m-%d %H:%M')}"
)
print(f"  Hours    : {n_hours}")
print(f"  T range  : {temps_celsius.min():.1f}°C → {temps_celsius.max():.1f}°C")
print(f"  Ensemble : {n_members} members")

# ──────────────────────────────────────────────────────────────────────
# 2. Compute freeze probability
# ──────────────────────────────────────────────────────────────────────

section("2. FREEZE PROBABILITY")

# Method 1: Ensemble-based freeze probability (flattened for the API)
ensemble_flat = ensemble.flatten()
prob_ensemble = freeze_probability(
    ensemble_flat, threshold_celsius=0.0, window_days=7, method="ensemble_mean"
)
prob_worst = freeze_probability(
    ensemble_flat, threshold_celsius=0.0, window_days=7, method="worst_case"
)
prob_q10 = freeze_probability(
    ensemble_flat, threshold_celsius=0.0, window_days=7, method="quantile_10"
)

print("  Method            Probability")
print(f"  {'─' * 36}")
print(f"  Ensemble mean     {prob_ensemble:.1%}")
print(f"  10th percentile   {prob_q10:.1%}")
print(f"  Worst case        {prob_worst:.1%}")

# Find the coldest 24h window
rolling_24h_min = df["temp_min"].rolling(24, min_periods=1).min()
coldest_idx = rolling_24h_min.idxmin()
coldest_temp = rolling_24h_min.min()
print(f"\n  Coldest 24h min   : {coldest_temp:.1f}°C at {coldest_idx}")

# ──────────────────────────────────────────────────────────────────────
# 3. Climate features — frost days
# ──────────────────────────────────────────────────────────────────────

section("3. CLIMATE FEATURES")

cf = ClimateFeatures()
frost_mask = cf.frost_days(df["temp_min"].values, threshold_celsius=0.0)
n_frost_days = int(np.sum(frost_mask))
print(f"  Frost days (min ≤ 0°C) : {n_frost_days} out of {n_hours // 24} days")

# Degree days
hdd = cf.hdd(df["temp_mean"].values, base_celsius=18.3)
print(f"  Total HDD (base 18.3)  : {np.nansum(hdd):.1f}")

# Identify the freeze window
freeze_hours = np.where(frost_mask)[0]
if len(freeze_hours) > 0:
    freeze_start = times[freeze_hours[0]]
    freeze_end = times[freeze_hours[-1]]
    print(f"  Freeze window          : {freeze_start} → {freeze_end}")
    print(f"  Freeze duration        : {len(freeze_hours)} hours")
else:
    print("  No frost hours detected")

# ──────────────────────────────────────────────────────────────────────
# 4. Generate FreezeSignal for OJ futures
# ──────────────────────────────────────────────────────────────────────

section("4. TRADING SIGNAL — OJ Futures")

sig_gen = FreezeSignal(
    entry_threshold=0.5,
    exit_threshold=0.15,
    time_decay_hours=48.0,
    instrument="OJ_FUTURES",
    max_size=0.20,
)

peak_time = coldest_idx.to_pydatetime()
current_time = base_time + timedelta(hours=60)  # signal generated mid-event

forecast_dict = {
    "freeze_prob": prob_ensemble,
    "event_peak_time": peak_time,
    "temperature_min": float(coldest_temp),
    "current_time": current_time,
}

signal = sig_gen.generate(forecast_dict)

print(f"  Signal time     : {signal.timestamp}")
print(f"  Action          : {signal.action.value}")
print(f"  Position size   : {signal.size:.3f} ({signal.size:.1%} of capital)")
print(f"  Confidence      : {signal.confidence:.3f}")
print(f"  Instrument      : {signal.instrument}")
print()
print("  Reasoning:")
for line in signal.reasoning.split(". "):
    if line.strip():
        print(f"    • {line.strip()}")

if signal.metadata:
    subsection("Signal Metadata")
    for k, v in signal.metadata.items():
        if isinstance(v, float):
            print(f"    {k:24s} : {v:.4f}")
        else:
            print(f"    {k:24s} : {v}")

# ──────────────────────────────────────────────────────────────────────
# 5. Summary
# ──────────────────────────────────────────────────────────────────────

section("5. SUMMARY")

action_color = "LONG" if signal.action == Action.LONG else "FLAT"
print("  ┌─────────────────────────────────────────────────────┐")
print("  │  Freeze Risk Assessment                            │")
print("  │                                                     │")
print(f"  │  Ensemble freeze probability : {prob_ensemble:>6.1%}              │")
print(f"  │  Minimum temperature         : {coldest_temp:>6.1f} °C            │")
print(f"  │  Frost hours                 : {len(freeze_hours):>6d}                │")
print(f"  │  OJ signal                   : {action_color:>6s}                │")
print(f"  │  Position size               : {signal.size:>6.1%}              │")
print(f"  │  Confidence                  : {signal.confidence:>6.1%}              │")
print("  └─────────────────────────────────────────────────────┘")

print(f"\n{DIVIDER}")
print("  Done. Run with: python examples/01_freeze_detection.py")
print(DIVIDER)
