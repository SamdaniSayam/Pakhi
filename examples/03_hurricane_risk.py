#!/usr/bin/env python3
"""
03 — Hurricane Risk Assessment
================================
Assess hurricane risk and generate natural gas trading signals.

Workflow:
  1. Generate synthetic hurricane track approaching Florida
  2. Classify using Saffir-Simpson scale
  3. Estimate rapid intensification probability
  4. Compute wind radius and storm surge
  5. Generate HurricaneSignal for nat gas futures
  6. Print risk assessment

Usage:
    pip install pakhi
    python examples/03_hurricane_risk.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from pakhi.risk.alerts import AlertManager, send_alert
from pakhi.signals.hurricane import HurricaneSignal
from pakhi.targets.hurricane import (
    rainfall_accumulation,
    rapid_intensification_probability,
    saffir_simpson,
    wind_radius_estimate,
)

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


def estimate_storm_surge(category: int, distance_km: float, coastal_slope: float = 0.001) -> float:
    """Estimate storm surge height (meters) based on category and distance.

    Uses a simplified SLOSH-like empirical relationship:
        surge = Vmax^2 / (2 * g) * factor / (1 + distance / Rmax)
    """
    cat_params = {
        1: (38.0, 60.0),  # (Vmax m/s, Rmax km)
        2: (48.0, 50.0),
        3: (58.0, 40.0),
        4: (68.0, 30.0),
        5: (80.0, 25.0),
    }
    vmax, rmax = cat_params.get(category, (38.0, 60.0))
    g = 9.81
    rho_seawater = 1025.0
    rho_air = 1.15

    # Wind stress setup
    wind_stress = 0.5 * rho_air * vmax**2
    setup = wind_stress / (rho_seawater * g * coastal_slope)

    # Decay with distance from eye
    distance_factor = 1.0 / (1.0 + max(distance_km, 0.1) / rmax)

    surge = setup * distance_factor * 1.5  # empirical scaling
    return float(np.clip(surge, 0.0, 10.0))


# ──────────────────────────────────────────────────────────────────────
# 1. Generate synthetic hurricane track
# ──────────────────────────────────────────────────────────────────────

section("1. SYNTHETIC HURRICANE TRACK")

# Hurricane approaching Florida from the Caribbean
np.random.seed(7)
n_steps = 72  # 72 hours of track data
base_time = datetime(2024, 9, 25, 0, 0)

# Track: starting south of Cuba, heading NW toward Tampa Bay
track_lat = np.linspace(19.5, 28.0, n_steps) + np.random.normal(0, 0.1, n_steps)
track_lon = np.linspace(-82.0, -83.5, n_steps) + np.random.normal(0, 0.15, n_steps)

# Intensification: starts as Cat 1, intensifies to Cat 4
hours = np.arange(n_steps)
pressure = 1000 - 35 * (1 - np.exp(-hours / 30))  # deepening pressure
wind_kmh = 120 + 80 * (1 - np.exp(-hours / 25))  # increasing winds

# Tampa Bay coordinates
tampa_lat, tampa_lon = 27.95, -82.46

# Distance from track point to Tampa at each step
distances_km = np.sqrt(
    ((track_lat - tampa_lat) * 111.0) ** 2
    + ((track_lon - tampa_lon) * 111.0 * np.cos(np.radians(28.0))) ** 2
)

times = pd.date_range(base_time, periods=n_steps, freq="h")

subsection("Track Points (every 12 hours)")
print(f"  {'Hours':>6s}  {'Lat':>7s}  {'Lon':>8s}  {'Wind':>8s}  {'Press':>7s}  {'Dist':>8s}")
print(f"  {'─' * 50}")
for i in range(0, n_steps, 12):
    print(
        f"  {i:>6d}  {track_lat[i]:>7.2f}  {track_lon[i]:>8.2f}  "
        f"{wind_kmh[i]:>7.0f}  {pressure[i]:>6.1f}  {distances_km[i]:>7.0f} km"
    )

# ──────────────────────────────────────────────────────────────────────
# 2. Saffir-Simpson classification
# ──────────────────────────────────────────────────────────────────────

section("2. SAFFIR-SIMPSON CLASSIFICATION")

categories = [saffir_simpson(pressure[i], wind_kmh[i]) for i in range(n_steps)]
max_category = max(categories)
peak_wind = float(np.max(wind_kmh))
min_pressure = float(np.min(pressure))

cat_names = {
    0: "Tropical Storm",
    1: "Category 1",
    2: "Category 2",
    3: "Category 3 (Major)",
    4: "Category 4 (Major)",
    5: "Category 5 (Major)",
}

subsection("Classification Timeline")
for i in range(0, n_steps, 12):
    cat = categories[i]
    label = cat_names.get(cat, f"Category {cat}")
    bar = "#" * (cat * 4) if cat > 0 else "."
    print(f"  T+{i:>3d}h  Cat-{cat}  {label:24s}  {bar}")

print(f"\n  Peak intensity : Cat-{max_category}")
print(f"                 : {cat_names.get(max_category, 'Unknown')}")
print(f"  Peak wind      : {peak_wind:.0f} km/h ({peak_wind / 1.852:.0f} kt)")
print(f"  Min pressure   : {min_pressure:.1f} hPa")

# ──────────────────────────────────────────────────────────────────────
# 3. Rapid intensification probability
# ──────────────────────────────────────────────────────────────────────

section("3. RAPID INTENSIFICATION (Kaplan–DeMaria)")

# Compute RI probability at different points
subsection("RI Probability Over Time")
print(f"  {'Hours':>6s}  {'dP24(hPa)':>10s}  {'SST(°C)':>8s}  {'Shear(m/s)':>11s}  {'P(RI)':>7s}")
print(f"  {'─' * 48}")

for i in range(24, n_steps, 12):
    dp24 = max(0, pressure[i - 24] - pressure[i])  # pressure drop in 24h
    sst = 29.5 + np.random.normal(0, 0.3)  # warm Caribbean waters
    shear = max(2.0, 12.0 - 0.1 * i + np.random.normal(0, 2))  # decreasing shear
    ri_prob = rapid_intensification_probability(dp24, sst, shear)
    print(f"  T+{i:>3d}h  {dp24:>10.1f}  {sst:>8.1f}  {shear:>11.1f}  {ri_prob:>6.1%}")

# ──────────────────────────────────────────────────────────────────────
# 4. Wind radius and storm surge
# ──────────────────────────────────────────────────────────────────────

section("4. WIND FIELD & STORM SURGE")

subsection(f"Tangential Wind Profile (at peak Cat-{max_category})")
radii = [25, 50, 75, 100, 150, 200, 300, 500]
print(f"  {'Radius(km)':>10s}  {'Wind(m/s)':>10s}  {'Wind(km/h)':>11s}  {'Beaufort':>8s}")
print(f"  {'─' * 45}")
for r in radii:
    v = wind_radius_estimate(max_category, r)
    v_kmh = v * 3.6
    # Simplified Beaufort mapping
    if v < 1:
        bf = 0
    elif v < 2:
        bf = 1
    elif v < 4:
        bf = 2
    elif v < 6:
        bf = 3
    elif v < 9:
        bf = 4
    elif v < 13:
        bf = 5
    elif v < 18:
        bf = 6
    elif v < 25:
        bf = 7
    elif v < 33:
        bf = 8
    elif v < 42:
        bf = 9
    elif v < 50:
        bf = 10
    else:
        bf = 11
    print(f"  {r:>10d}  {v:>10.1f}  {v_kmh:>11.1f}  {bf:>8d}")

subsection("Storm Surge Estimates")
surge_distances = [10, 25, 50, 100, 200]
print(f"  {'Distance(km)':>12s}  {'Surge(m)':>9s}  {'Surge(ft)':>10s}  {'Threat':>10s}")
print(f"  {'─' * 46}")
for d in surge_distances:
    surge_m = estimate_storm_surge(max_category, d)
    surge_ft = surge_m * 3.281
    if surge_m > 3.0:
        threat = "EXTREME"
    elif surge_m > 2.0:
        threat = "HIGH"
    elif surge_m > 1.0:
        threat = "MODERATE"
    elif surge_m > 0.5:
        threat = "LOW"
    else:
        threat = "MINIMAL"
    print(f"  {d:>12d}  {surge_m:>9.2f}  {surge_ft:>10.1f}  {threat:>10s}")

subsection("Rainfall Accumulation")
for cat in range(1, max_category + 1):
    rain = rainfall_accumulation(cat, forward_speed_kmh=20.0, duration_hours=18.0)
    print(f"  Cat-{cat}: {rain:.0f} mm ({rain / 25.4:.1f} in) over 18h at 20 km/h forward speed")

# ──────────────────────────────────────────────────────────────────────
# 5. Generate HurricaneSignal for nat gas
# ──────────────────────────────────────────────────────────────────────

section("5. TRADING SIGNAL — Natural Gas Futures")

sig_gen = HurricaneSignal(
    entry_threshold=0.3,
    gulf_proximity_miles=250.0,
    max_size=0.20,
)

# Use the most threatening forecast point (peak intensity, closest approach)
peak_idx = int(np.argmax(wind_kmh))
closest_idx = int(np.argmin(distances_km))
signal_idx = min(peak_idx, closest_idx + 12)  # a bit before closest approach

track_forecast = {
    "landfall_prob": 0.72,
    "category": max_category,
    "closest_approach_miles": distances_km[closest_idx] * 0.621,  # km to miles
    "hours_to_landfall": float(n_steps - signal_idx),
    "current_time": base_time + timedelta(hours=signal_idx),
}

signal = sig_gen.generate(track_forecast)

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

# ──────────────────────────────────────────────────────────────────────
# 6. Risk alerts
# ──────────────────────────────────────────────────────────────────────

section("6. RISK ALERTS")

mgr = AlertManager()

alert = mgr.check_hurricane(track_forecast)
if alert:
    print(f"  [{alert.severity.value}] {alert.message}")
    send_alert(alert, channels=["log"])
else:
    print("  No hurricane alert triggered")

# ──────────────────────────────────────────────────────────────────────
# 7. Summary
# ──────────────────────────────────────────────────────────────────────

section("7. RISK ASSESSMENT SUMMARY")

print("  ┌─────────────────────────────────────────────────────┐")
print("  │  Hurricane Risk Assessment                         │")
print("  │                                                     │")
print("  │  Storm             : Synthetic Hurricane            │")
print(f"  │  Peak category     : Cat-{max_category}                        │")
print(f"  │  Peak wind         : {peak_wind:>5.0f} km/h                   │")
print(f"  │  Min pressure      : {min_pressure:>5.1f} hPa                    │")
print(f"  │  Landfall prob     : {track_forecast['landfall_prob']:>5.0%}                       │")
print(
    f"  │  Closest approach  : {track_forecast['closest_approach_miles']:>5.0f} miles                  │"
)
print(f"  │  Gulf shut-in risk : {signal.confidence:>5.0%}                       │")
print(f"  │  NG signal         : {signal.action.value:>5s}                       │")
print(f"  │  Position size     : {signal.size:>5.1%}                       │")
print("  └─────────────────────────────────────────────────────┘")

print(f"\n{DIVIDER}")
print("  Done. Run with: python examples/03_hurricane_risk.py")
print(DIVIDER)
