#!/usr/bin/env python3
"""
05 — Full Pipeline Integration
================================
Complete end-to-end weather quant workflow: Data → Features → Model →
Prediction → Signal → Risk, all with synthetic data.

Workflow:
  1. Data Ingestion    : Synthetic weather + price data
  2. Feature Engine    : Climate, temporal, and derived features
  3. Model Training    : Persistence + optional GradientForecaster
  4. Prediction        : 7-day temperature forecast
  5. Signal Generation : Freeze + Power signals
  6. Risk Management   : Portfolio risk metrics and alerts
  7. Summary           : Formatted results at each stage

Usage:
    pip install pakhi
    python examples/05_full_pipeline.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from pakhi.features.climate import ClimateFeatures
from pakhi.models.base import ForecastResult, StandardScaler, compute_metrics
from pakhi.models.persistence import PersistenceModel
from pakhi.risk.alerts import AlertManager
from pakhi.risk.metrics import max_drawdown, sharpe_ratio, var
from pakhi.signals.freeze import FreezeSignal
from pakhi.signals.heat import PowerSignal
from pakhi.targets.temperature import heat_index, wind_chill

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

DIVIDER = "=" * 64
SUBDIV = "-" * 64
STEP_NUM = [0]


def section(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def subsection(title: str) -> None:
    print(f"\n  {SUBDIV}")
    print(f"  {title}")
    print(f"  {SUBDIV}")


def step(title: str) -> None:
    STEP_NUM[0] += 1
    section(f"STEP {STEP_NUM[0]}: {title}")


# ══════════════════════════════════════════════════════════════════════
#  STEP 1: DATA INGESTION
# ══════════════════════════════════════════════════════════════════════

step("DATA INGESTION")

np.random.seed(42)
n_days = 365 * 2  # 2 years of daily data
base_time = datetime(2022, 1, 1)

# Synthetic weather data (Florida)
days = np.arange(n_days)
doy = np.array([(base_time + timedelta(days=int(d))).timetuple().tm_yday for d in days])

# Temperature: seasonal cycle + trends + noise (with significant weather noise)
# Random walk component captures weather regime changes (not predictable from lags)
random_walk = np.cumsum(np.random.normal(0, 0.5, n_days))
temp_mean = (
    22.0 + 8.0 * np.sin(2 * np.pi * (doy - 80) / 365) + random_walk + np.random.normal(0, 2, n_days)
)
# temp_max/min have independent measurement noise, not deterministic from temp_mean
temp_max = temp_mean + np.random.uniform(3, 7, n_days) + np.random.normal(0, 1.5, n_days)
temp_min = temp_mean - np.random.uniform(2, 5, n_days) + np.random.normal(0, 1.5, n_days)

# Inject winter cold snaps (Florida freeze events in Jan/Feb)
for yr_offset in [0, 1]:
    cold_start = yr_offset * 365 + np.random.randint(10, 40)
    cold_len = np.random.randint(3, 7)
    cold_drops = np.random.uniform(15, 22, cold_len)
    for j in range(cold_len):
        idx = cold_start + j
        if idx < n_days:
            temp_mean[idx] -= cold_drops[j] * 0.7
            temp_max[idx] -= cold_drops[j] * 0.5
            temp_min[idx] -= cold_drops[j]
wind_speed = np.random.exponential(12, n_days)  # km/h
humidity = np.clip(
    60 + 20 * np.sin(2 * np.pi * (doy - 180) / 365) + np.random.normal(0, 10, n_days), 20, 100
)
precip = np.random.exponential(3, n_days)
precip[np.random.random(n_days) > 0.6] = 0  # 40% chance of rain

# Synthetic OJ futures prices
oj_drift = 0.0003
oj_vol = 0.018
oj_returns = np.random.normal(oj_drift, oj_vol, n_days)
# Freeze events cause OJ spikes
freeze_mask = temp_min < 0
for i in range(n_days):
    if freeze_mask[i]:
        window = slice(i, min(i + 5, n_days))
        oj_returns[window] += np.array([0.12, 0.08, 0.04, 0.02, 0.01])[: min(5, n_days - i)]
oj_prices = 125.0 * np.cumprod(1 + oj_returns)

# Synthetic nat gas prices
ng_base = 3.50
ng_returns = np.random.normal(0.0001, 0.025, n_days)
ng_prices = ng_base * np.cumprod(1 + ng_returns)

times = pd.date_range(base_time, periods=n_days, freq="D")
df = pd.DataFrame(
    {
        "temp_mean": temp_mean,
        "temp_max": temp_max,
        "temp_min": temp_min,
        "wind_speed": wind_speed,
        "humidity": humidity,
        "precip": precip,
        "oj_close": oj_prices,
        "ng_close": ng_prices,
    },
    index=times,
)

print("  Location        : Central Florida")
print(f"  Period          : {times[0].strftime('%Y-%m-%d')} → {times[-1].strftime('%Y-%m-%d')}")
print(f"  Days            : {n_days}")
print(f"  Freeze days     : {int(np.sum(freeze_mask))}")
print(f"  OJ price range  : {oj_prices.min():.1f} → {oj_prices.max():.1f} ¢/lb")
print(f"  NG price range  : ${ng_prices.min():.2f} → ${ng_prices.max():.2f}")

# ══════════════════════════════════════════════════════════════════════
#  STEP 2: FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════

step("FEATURE ENGINEERING")

cf = ClimateFeatures()

# Degree-day features
df["hdd"] = cf.hdd(df["temp_mean"].values, base_celsius=18.3)
df["cdd"] = cf.cdd(df["temp_mean"].values, base_celsius=18.3)
df["frost_day"] = cf.frost_days(df["temp_min"].values, threshold_celsius=0.0).astype(int)
df["heatwave"] = cf.heatwave_days(
    df["temp_max"].values, threshold_celsius=35.0, consecutive_days=3
).astype(int)

# Derived weather features
df["heat_index"] = np.array(
    [heat_index(t, rh) for t, rh in zip(df["temp_max"], df["humidity"], strict=False)]
)
df["wind_chill_vals"] = np.array(
    [wind_chill(t, w) for t, w in zip(df["temp_min"], df["wind_speed"], strict=False)]
)
df["diurnal_range"] = df["temp_max"] - df["temp_min"]

# Lag features for ML
for lag in [1, 3, 7, 14]:
    df[f"oj_lag_{lag}"] = df["oj_close"].shift(lag)
    df[f"temp_lag_{lag}"] = df["temp_mean"].shift(lag)

# Rolling statistics (shifted by 1 to avoid lookahead — only use past data)
df["temp_roll7_mean"] = df["temp_mean"].shift(1).rolling(7, min_periods=1).mean()
df["temp_roll7_std"] = df["temp_mean"].shift(1).rolling(7, min_periods=2).std()
df["cdd_roll7_sum"] = df["cdd"].shift(1).rolling(7, min_periods=1).sum()

# Freeze probability (ensemble-like: use temp_min distribution)
df["freeze_prob_3d"] = (
    df["temp_min"].rolling(3, min_periods=1).apply(lambda x: float(np.mean(x <= 0.0)), raw=True)
)

df = df.dropna()

feature_cols = [
    "temp_max",
    "temp_min",
    "wind_speed",
    "humidity",
    "diurnal_range",
    "heat_index",
    "wind_chill_vals",
    "temp_roll7_mean",
    "temp_roll7_std",
    "freeze_prob_3d",
    "oj_lag_1",
    "oj_lag_3",
    "oj_lag_7",
    "oj_lag_14",
    "temp_lag_1",
    "temp_lag_3",
    "temp_lag_7",
    "temp_lag_14",
]

print(f"  Features created : {len(feature_cols)}")
print("  Feature names    :")
for i in range(0, len(feature_cols), 4):
    chunk = feature_cols[i : i + 4]
    print(f"    {', '.join(chunk)}")

subsection("Feature Statistics")
for col in ["hdd", "cdd", "freeze_prob_3d", "heatwave", "frost_day"]:
    vals = df[col]
    print(
        f"  {col:20s}  mean={vals.mean():.3f}  max={vals.max():.3f}  "
        f"nonzero={int((vals > 0).sum())}"
    )

# ══════════════════════════════════════════════════════════════════════
#  STEP 3: MODEL TRAINING
# ══════════════════════════════════════════════════════════════════════

step("MODEL TRAINING")

target_col = "temp_mean"
X = df[feature_cols].values
y = df[target_col].values

split = int(len(X) * 0.75)
X_train, X_test = X[:split], X[split:]
y_train, y_test = y[:split], y[split:]

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

# Simple linear regression baseline (has actual predictive skill)


class LinearRegressionWrapper:
    """Wrapper for sklearn LinearRegression to match pakhi model interface."""

    def __init__(self, model: LinearRegression):
        self.model = model

    def predict(self, X: np.ndarray) -> ForecastResult:
        preds = self.model.predict(X)
        return ForecastResult(
            deterministic=preds.reshape(-1, 1),
            quantiles={},
            skill_scores={},
            metadata={"model": "linear_regression"},
        )


lr_model = LinearRegression()
lr_model.fit(X_train_s, y_train)
lr_wrapper = LinearRegressionWrapper(lr_model)
lr_result = lr_wrapper.predict(X_test_s)
lr_metrics = compute_metrics(y_test, lr_result.deterministic.ravel())

# Persistence baseline for comparison
persistence = PersistenceModel()
persistence.fit(X_train_s, y_train)
persist_result = persistence.predict(X_test_s)
persist_metrics = compute_metrics(y_test, persist_result.deterministic.ravel())

print(f"  Train / Test     : {split} / {len(X) - split}")
print(f"  Target           : {target_col} (°C)")
print(f"  Persistence RMSE : {persist_metrics['rmse']:.2f}°C")
print(f"  Persistence MAE  : {persist_metrics['mae']:.2f}°C")
print(f"  Persistence ACC  : {persist_metrics['acc']:.4f}")
print(f"  LinearReg RMSE   : {lr_metrics['rmse']:.2f}°C")
print(f"  LinearReg MAE    : {lr_metrics['mae']:.2f}°C")
print(f"  LinearReg ACC    : {lr_metrics['acc']:.4f}")

# Try ML model
ml_available = False
try:
    from pakhi.models.gradient import GradientForecaster

    ml_model = GradientForecaster(
        backend="lightgbm",
        n_estimators=500,
        max_depth=5,
        learning_rate=0.05,
        early_stopping_rounds=50,
        random_state=42,
        feature_names=feature_cols,
    )
    ml_model.fit(X_train_s, y_train, X_val=X_test_s, y_val=y_test)
    ml_result = ml_model.predict(X_test_s)
    ml_metrics = compute_metrics(y_test, ml_result.deterministic.ravel())
    ml_available = True

    print(f"\n  LightGBM RMSE    : {ml_metrics['rmse']:.2f}°C")
    print(f"  LightGBM MAE     : {ml_metrics['mae']:.2f}°C")
    print(f"  LightGBM ACC     : {ml_metrics['acc']:.4f}")
    print()
    print("  Top 5 features:")
    for fname, imp in ml_model.feature_importance_top(5):
        bar = "#" * int(imp * 40)
        print(f"    {fname:20s} {imp:.3f} {bar}")

    best_model = ml_model
    best_metrics = ml_metrics
except ImportError:
    print("\n  (GradientForecaster unavailable, using LinearRegression)")
    best_model = lr_wrapper
    best_metrics = lr_metrics
except Exception as e:
    print(f"\n  (ML model failed: {e}, using LinearRegression)")
    best_model = lr_wrapper
    best_metrics = lr_metrics

# ══════════════════════════════════════════════════════════════════════
#  STEP 4: PREDICTION
# ══════════════════════════════════════════════════════════════════════

step("PREDICTION — 7-Day Temperature Forecast")

last_features = X_test_s[-7:]
pred_result = best_model.predict(last_features)
pred_temps = pred_result.deterministic.ravel()

forecast_times = pd.date_range(df.index[-1] + timedelta(days=1), periods=7, freq="D")

print(f"  {'Date':>12s}  {'Temp(°C)':>9s}  {'HDD':>6s}  {'CDD':>6s}  {'Freeze?':>7s}")
print(f"  {'─' * 46}")
for i, t in enumerate(forecast_times):
    temp = pred_temps[i]
    hdd_val = max(0, 18.3 - temp)
    cdd_val = max(0, temp - 18.3)
    freeze = "YES" if temp < 0 else "no"
    print(
        f"  {t.strftime('%Y-%m-%d'):>12s}  {temp:>9.1f}  {hdd_val:>6.1f}  {cdd_val:>6.1f}  {freeze:>7s}"
    )

prob_freeze_7d = float(np.mean(pred_temps < 0))
min_forecast_temp = float(np.min(pred_temps))
print(f"\n  7-day freeze prob : {prob_freeze_7d:.1%}")
print(f"  Min forecast temp : {min_forecast_temp:.1f}°C")

# ══════════════════════════════════════════════════════════════════════
#  STEP 5: SIGNAL GENERATION
# ══════════════════════════════════════════════════════════════════════

step("SIGNAL GENERATION")

subsection("Freeze Signal — OJ Futures")
freeze_sig = FreezeSignal(entry_threshold=0.4, max_size=0.20)
freeze_forecast = {
    "freeze_prob": prob_freeze_7d,
    "event_peak_time": df.index[-1] + timedelta(days=3),
    "temperature_min": min_forecast_temp,
    "current_time": df.index[-1],
}
oj_signal = freeze_sig.generate(freeze_forecast)
print(f"  Action      : {oj_signal.action.value}")
print(f"  Size        : {oj_signal.size:.3f}")
print(f"  Confidence  : {oj_signal.confidence:.3f}")
print(f"  Instrument  : {oj_signal.instrument}")
print(f"  Reason      : {oj_signal.reasoning[:80]}...")

subsection("Power Signal — ERCOT")
# Synthetic ERCOT temperature for next 7 days
ercot_temps = np.array([36, 38, 40, 41, 39, 37, 35])  # heat wave

power_sig = PowerSignal(heatwave_threshold=38.0, min_consecutive_days=3)
power_forecast = {
    "temperature_forecast": ercot_temps,
    "market": "ERCOT",
    "current_time": df.index[-1],
}
ercot_signal = power_sig.generate(power_forecast)
print(f"  Action      : {ercot_signal.action.value}")
print(f"  Size        : {ercot_signal.size:.3f}")
print(f"  Confidence  : {ercot_signal.confidence:.3f}")
print(f"  Instrument  : {ercot_signal.instrument}")
print(f"  Reason      : {ercot_signal.reasoning[:80]}...")

# ══════════════════════════════════════════════════════════════════════
#  STEP 6: RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

step("RISK MANAGEMENT")

subsection("Portfolio Risk Metrics")

# Simple portfolio: long OJ when freeze signal, else flat
oj_position = np.zeros(len(df))
for i in range(1, len(df)):
    if df["freeze_prob_3d"].iloc[i] > 0.4:
        oj_position[i] = 0.15  # 15% allocation

oj_prices_arr = df["oj_close"].values
oj_strategy_returns = oj_position[:-1] * (np.diff(oj_prices_arr) / oj_prices_arr[:-1])
oj_strategy_returns = oj_strategy_returns[np.isfinite(oj_strategy_returns)]

bh_returns = np.diff(oj_prices_arr) / oj_prices_arr[:-1]
bh_returns = bh_returns[np.isfinite(bh_returns)]

print(f"  {'Metric':<24s}  {'Strategy':>10s}  {'Buy&Hold':>10s}")
print(f"  {'─' * 48}")
print(
    f"  {'Sharpe Ratio':<24s}  {sharpe_ratio(oj_strategy_returns):>10.2f}  {sharpe_ratio(bh_returns):>10.2f}"
)
print(
    f"  {'Max Drawdown':<24s}  {max_drawdown(np.cumprod(1 + oj_strategy_returns)):>10.2%}  {max_drawdown(oj_prices_arr):>10.2%}"
)
print(
    f"  {'VaR (95%)':<24s}  {var(oj_strategy_returns, 0.95):>10.2%}  {var(bh_returns, 0.95):>10.2%}"
)

subsection("Risk Alerts")

mgr = AlertManager()

# Check freeze alert
freeze_alert = mgr.check_freeze(
    {
        "temperature_min": min_forecast_temp,
        "location": "Florida Citrus Belt",
    }
)
if freeze_alert:
    print(f"  [{freeze_alert.severity.value}] {freeze_alert.message}")

# Check heatwave alert
heat_alert = mgr.check_heatwave(
    {
        "temperature_forecast": ercot_temps,
        "location": "ERCOT (Texas)",
    }
)
if heat_alert:
    print(f"  [{heat_alert.severity.value}] {heat_alert.message}")

if not freeze_alert and not heat_alert:
    print("  No alerts triggered")

# ══════════════════════════════════════════════════════════════════════
#  STEP 7: SUMMARY
# ══════════════════════════════════════════════════════════════════════

step("PIPELINE SUMMARY")

_model = "LightGBM" if ml_available else "Persistence"
_freeze = prob_freeze_7d
_sharpe = sharpe_ratio(oj_strategy_returns)
_alert = "Yes" if freeze_alert or heat_alert else "No"


def _box_line(text, width=56):
    inner = f"  {text}"
    pad = width - len(inner)
    return f"  │{inner}{' ' * max(0, pad)}│"


def _box_center(text, width=56):
    pad_l = (width - len(text)) // 2
    pad_r = width - len(text) - pad_l
    return f"  │{' ' * pad_l}{text}{' ' * pad_r}│"


div = "  ┌" + "─" * 56 + "┐"
bot = "  └" + "─" * 56 + "┘"

print(f"""
{div}
{_box_center("Pakhi Full Pipeline — Weather Quant Platform")}
{_box_line("")}
{_box_line(f"Data        : {n_days} days synthetic, Central Florida")}
{_box_line(f"Features    : {len(feature_cols)} engineered features")}
{_box_line(f"Model       : {_model}")}
{_box_line(f"Test RMSE   : {best_metrics['rmse']:>6.2f}°C")}
{_box_line(f"Test ACC    : {best_metrics['acc']:>6.4f}")}
{_box_line("")}
{_box_line("Signals:")}
{_box_line(f"  OJ   : {oj_signal.action.value:>5s} (conf={oj_signal.confidence:.2f}, size={oj_signal.size:.3f})")}
{_box_line(f"  ERCOT: {ercot_signal.action.value:>5s} (conf={ercot_signal.confidence:.2f}, size={ercot_signal.size:.3f})")}
{_box_line("")}
{_box_line("Risk:")}
{_box_line(f"  7-day freeze prob : {_freeze:>5.1%}")}
{_box_line(f"  Strategy Sharpe   : {_sharpe:>5.2f}")}
{_box_line(f"  Alerts            : {_alert:>5s}")}
{bot}
""")

print(DIVIDER)
print("  Done. Run with: python examples/05_full_pipeline.py")
print(DIVIDER)
