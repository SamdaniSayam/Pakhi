#!/usr/bin/env python3
"""
02 — Power Grid Demand Forecasting
====================================
Forecast ERCOT power demand using temperature-driven features.

Workflow:
  1. Generate synthetic ERCOT summer temperatures
  2. Compute HDD/CDD degree-day features
  3. Train a persistence baseline (and optionally GradientForecaster)
  4. Forecast 7-day power demand
  5. Print results

Usage:
    pip install pakhi
    python examples/02_power_forecast.py

    For the ML model, also install:
    pip install pakhi[ml]
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from pakhi.features.climate import ClimateFeatures
from pakhi.models.base import StandardScaler, compute_metrics
from pakhi.models.persistence import PersistenceModel

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
# 1. Generate synthetic ERCOT temperature data
# ──────────────────────────────────────────────────────────────────────

section("1. SYNTHETIC DATA — ERCOT Summer Temperatures")

np.random.seed(2024)
n_days = 365
base_time = datetime(2023, 1, 1)

# Synthetic daily max temperatures for ERCOT (Texas): sinusoidal seasonal + heat waves
days = np.arange(n_days)
seasonal = 28.0 + 12.0 * np.sin(2 * np.pi * (days - 80) / 365)  # peak ~July
noise = np.random.normal(0, 2.5, n_days)
daily_max_temp = seasonal + noise

# Inject 3 heat wave events (consecutive days > 38°C)
heatwave_starts = [170, 200, 230]
for hw_start in heatwave_starts:
    hw_len = np.random.randint(4, 8)
    hw_boost = np.linspace(0, 6, hw_len)
    daily_max_temp[hw_start : hw_start + hw_len] += hw_boost

daily_mean_temp = daily_max_temp - np.random.uniform(5, 8, n_days)

times = pd.date_range(base_time, periods=n_days, freq="D")
df = pd.DataFrame(
    {
        "temp_max": daily_max_temp,
        "temp_mean": daily_mean_temp,
    },
    index=times,
)

print("  Region   : ERCOT (Texas)")
print(f"  Period   : {times[0].strftime('%Y-%m-%d')} → {times[-1].strftime('%Y-%m-%d')}")
print(f"  Days     : {n_days}")
print(f"  T max    : {daily_max_temp.min():.1f}°C → {daily_max_temp.max():.1f}°C")

# ──────────────────────────────────────────────────────────────────────
# 2. Compute demand-proxy features
# ──────────────────────────────────────────────────────────────────────

section("2. DEMAND FEATURES — HDD / CDD")

cf = ClimateFeatures()

hdd_vals = cf.hdd(df["temp_mean"].values, base_celsius=18.3)
cdd_vals = cf.cdd(df["temp_mean"].values, base_celsius=18.3)

# Synthetic power demand model: base load + CDD-driven + noise
base_load = 35000  # MW base load
cdd_sensitivity = 800  # MW per CDD
wind_factor = np.random.uniform(0.85, 1.15, n_days)  # random wind supply
demand = (base_load + cdd_vals * cdd_sensitivity) * wind_factor + np.random.normal(0, 500, n_days)
demand = np.maximum(demand, 20000)  # floor at 20 GW

df["demand_mw"] = demand
df["hdd"] = hdd_vals
df["cdd"] = cdd_vals

total_hdd = np.nansum(hdd_vals)
total_cdd = np.nansum(cdd_vals)
print(f"  Total HDD         : {total_hdd:.0f}")
print(f"  Total CDD         : {total_cdd:.0f}")
print(f"  Peak demand       : {demand.max():.0f} MW")
print(f"  Mean demand       : {demand.mean():.0f} MW")

# Heatwave detection
hw_mask = cf.heatwave_days(df["temp_max"].values, threshold_celsius=38.0, consecutive_days=3)
n_hw_days = int(np.sum(hw_mask))
print(f"  Heatwave days     : {n_hw_days}")

# ──────────────────────────────────────────────────────────────────────
# 3. Train/test split and model
# ──────────────────────────────────────────────────────────────────────

section("3. MODEL TRAINING")

# Features: lagged demand + degree days
feature_cols = ["demand_mw", "cdd", "hdd"]
df["demand_lag1"] = df["demand_mw"].shift(1)
df["demand_lag7"] = df["demand_mw"].shift(7)
df["cdd_lag1"] = df["cdd"].shift(1)
df = df.dropna()

feature_names = ["demand_lag1", "demand_lag7", "cdd", "hdd", "cdd_lag1"]
X = df[feature_names].values
y = df["demand_mw"].values

split = int(len(X) * 0.8)
X_train, X_test = X[:split], X[split:]
y_train, y_test = y[:split], y[split:]

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

# Persistence baseline
persistence = PersistenceModel(forecast_horizon=1)
persistence.fit(X_train_s, y_train)
result_persist = persistence.predict(X_test_s)
metrics_persist = compute_metrics(
    y_test, result_persist.deterministic.ravel(), metrics=["rmse", "mae"]
)

print(f"  Train samples      : {len(X_train)}")
print(f"  Test samples       : {len(X_test)}")
print(f"  Features           : {feature_names}")
print()
print("  Persistence baseline:")
print(f"    RMSE : {metrics_persist['rmse']:.0f} MW")
print(f"    MAE  : {metrics_persist['mae']:.0f} MW")

# Try GradientForecaster if available
try:
    from pakhi.models.gradient import GradientForecaster

    ml_available = True
except ImportError:
    ml_available = False

if ml_available:
    subsection("Gradient Forecaster (LightGBM)")
    try:
        model = GradientForecaster(
            backend="lightgbm",
            n_estimators=500,
            max_depth=5,
            learning_rate=0.05,
            early_stopping_rounds=50,
            random_state=42,
            feature_names=feature_names,
        )
        model.fit(X_train_s, y_train, X_val=X_test_s, y_val=y_test)
        result_ml = model.predict(X_test_s)
        metrics_ml = compute_metrics(
            y_test, result_ml.deterministic.ravel(), metrics=["rmse", "mae", "acc"]
        )

        print(f"    RMSE : {metrics_ml['rmse']:.0f} MW")
        print(f"    MAE  : {metrics_ml['mae']:.0f} MW")
        print(f"    ACC  : {metrics_ml['acc']:.4f}")
        print()
        print("    Top 5 feature importances:")
        for fname, imp in model.feature_importance_top(5):
            bar = "#" * int(imp * 50)
            print(f"      {fname:16s} {imp:.3f} {bar}")

        # Use ML model for the 7-day forecast
        forecast_model = model
        forecast_label = "GradientForecaster"
    except Exception as e:
        print(f"    LightGBM failed ({e}), falling back to persistence")
        ml_available = False

if not ml_available:
    forecast_model = persistence
    forecast_label = "Persistence"
    result_ml = result_persist
    metrics_ml = metrics_persist

# ──────────────────────────────────────────────────────────────────────
# 4. 7-day demand forecast
# ──────────────────────────────────────────────────────────────────────

section("4. 7-DAY DEMAND FORECAST")

last_features = X_test_s[-7:]  # Use last 7 rows of test set as "current"
forecast_result = forecast_model.predict(last_features)
forecast_values = forecast_result.deterministic.ravel()

forecast_times = pd.date_range(df.index[-1] + timedelta(days=1), periods=7, freq="D")

print(f"  Model    : {forecast_label}")
print(f"  From     : {forecast_times[0].strftime('%Y-%m-%d')}")
print(f"  To       : {forecast_times[-1].strftime('%Y-%m-%d')}")
print()
print(f"  {'Date':>12s}  {'Forecast (MW)':>14s}  {'CDD':>6s}  {'HDD':>6s}")
print(f"  {'─' * 44}")
for i, t in enumerate(forecast_times):
    idx = len(df) - 7 + i
    cdd_val = df["cdd"].iloc[idx] if idx < len(df) else 0
    hdd_val = df["hdd"].iloc[idx] if idx < len(df) else 0
    print(
        f"  {t.strftime('%Y-%m-%d'):>12s}  {forecast_values[i]:>14,.0f}  {cdd_val:>6.1f}  {hdd_val:>6.1f}"
    )

print()
print(f"  Peak forecast  : {forecast_values.max():>10,.0f} MW")
print(f"  Mean forecast  : {forecast_values.mean():>10,.0f} MW")

# ──────────────────────────────────────────────────────────────────────
# 5. Summary
# ──────────────────────────────────────────────────────────────────────

section("5. SUMMARY")

print("  ┌─────────────────────────────────────────────────────┐")
print("  │  ERCOT Power Demand Forecast                       │")
print("  │                                                     │")
print("  │  Region              : ERCOT (Texas)               │")
print(f"  │  Base load           : {base_load:>8,} MW            │")
print(f"  │  CDD sensitivity     : {cdd_sensitivity:>8} MW/CDD      │")
print("  │  Forecast period     : 7 days                      │")
print(f"  │  Peak demand (fcast) : {forecast_values.max():>8,.0f} MW      │")
print(f"  │  Model RMSE          : {metrics_ml['rmse']:>8,.0f} MW      │")
print(f"  │  Heatwave days (yr)  : {n_hw_days:>8d}              │")
print("  └─────────────────────────────────────────────────────┘")

print(f"\n{DIVIDER}")
print("  Done. Run with: python examples/02_power_forecast.py")
print(DIVIDER)
