#!/usr/bin/env python3
"""
04 — Historical Backtest
==========================
Backtest a freeze-signal strategy on synthetic OJ futures data.

Workflow:
  1. Generate synthetic historical freeze events and OJ prices
  2. Build a signal generator that triggers on freeze probability
  3. Run backtest via BacktestEngine
  4. Compute risk metrics (Sharpe, drawdown, win rate, etc.)
  5. Compare to buy-and-hold
  6. Print equity curve (text) and results

Usage:
    pip install pakhi
    python examples/04_historical_backtest.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from pakhi.risk.backtest import BacktestEngine
from pakhi.risk.metrics import (
    calmar_ratio,
    cvar,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    var,
)
from pakhi.signals.base import Action, Signal

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


def print_equity_curve(equity: np.ndarray, width: int = 50, height: int = 15) -> None:
    """Print a text-based equity curve chart."""
    if len(equity) < 2:
        print("  (no data)")
        return

    eq = equity[:: max(1, len(equity) // width)]
    eq = eq[:width]

    eq_min = float(np.nanmin(eq))
    eq_max = float(np.nanmax(eq))
    eq_range = eq_max - eq_min if eq_max > eq_min else 1.0

    # Create the chart grid
    grid = [[" " for _ in range(width)] for _ in range(height)]

    for x, val in enumerate(eq):
        if x >= width:
            break
        y = int((val - eq_min) / eq_range * (height - 1))
        y = max(0, min(height - 1, y))
        grid[height - 1 - y][x] = "█"

    # Print with Y-axis labels
    for row_idx in range(height):
        eq_val = eq_max - (row_idx / (height - 1)) * eq_range
        label = f"{eq_val:>12,.0f}"
        row_str = "".join(grid[row_idx])
        print(f"  {label} │{row_str}│")

    print(f"  {'':>12s} └{'─' * width}┘")


def print_drawdown_curve(equity: np.ndarray, width: int = 50, height: int = 8) -> None:
    """Print a text-based drawdown curve."""
    if len(equity) < 2:
        print("  (no data)")
        return

    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak > 0, peak, 1.0)

    dd = dd[:: max(1, len(dd) // width)]
    dd = dd[:width]

    dd_max = float(np.nanmax(dd))
    if dd_max == 0:
        dd_max = 0.01

    grid = [[" " for _ in range(width)] for _ in range(height)]

    for x, val in enumerate(dd):
        if x >= width:
            break
        y = int(val / dd_max * (height - 1))
        y = max(0, min(height - 1, y))
        grid[y][x] = "█"

    for row_idx in range(height):
        dd_val = (row_idx / (height - 1)) * dd_max
        label = f"{dd_val:>11.1%}"
        row_str = "".join(grid[row_idx])
        print(f"  {label} │{row_str}│")

    print(f"  {'':>11s} └{'─' * width}┘")


# ──────────────────────────────────────────────────────────────────────
# 1. Generate synthetic historical data
# ──────────────────────────────────────────────────────────────────────

section("1. SYNTHETIC DATA — OJ Futures & Freeze Events")

np.random.seed(2022)
n_days = 756  # ~3 years of trading days
base_time = datetime(2021, 1, 1)

# Generate temperature anomalies (standardized)
temp_anomaly = np.random.normal(0, 1, n_days)
# Add seasonal pattern
days_of_year = np.array(
    [(base_time + timedelta(days=i)).timetuple().tm_yday for i in range(n_days)]
)
seasonal_cold = -1.5 * np.cos(2 * np.pi * (days_of_year - 15) / 365)  # coldest in Jan
temp_anomaly = temp_anomaly + seasonal_cold

# Freeze events: when temp anomaly < -2 for 2+ consecutive days
is_freeze_trigger = temp_anomaly < -2.0
# Smooth into freeze probability (0-1)
freeze_prob = np.clip(-0.3 * (temp_anomaly + 1.5), 0, 1)

# OJ futures price: base + drift + reaction to freeze events
base_price = 120.0  # cents/lb
drift = 0.0001  # slight upward drift
returns = np.random.normal(drift, 0.015, n_days)  # base volatility

# Add spikes when freeze probability is high
for i in range(1, n_days):
    if freeze_prob[i] > 0.5:
        # OJ spikes 5-25% within a few days of freeze
        spike_magnitude = freeze_prob[i] * 0.15
        returns[i] += spike_magnitude
        if i + 1 < n_days:
            returns[i + 1] += spike_magnitude * 0.5
        if i + 2 < n_days:
            returns[i + 2] += spike_magnitude * 0.2

prices = base_price * np.cumprod(1 + returns)

times = pd.date_range(base_time, periods=n_days, freq="B")  # business days
df = pd.DataFrame(
    {
        "close": prices,
        "temp_anomaly": temp_anomaly,
        "freeze_prob": freeze_prob,
    },
    index=times,
)

# Count freeze events
n_freeze_events = 0
in_event = False
for fp in freeze_prob:
    if fp > 0.5 and not in_event:
        n_freeze_events += 1
        in_event = True
    elif fp < 0.3:
        in_event = False

print(f"  Period          : {times[0].strftime('%Y-%m-%d')} → {times[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days    : {n_days}")
print(f"  Price range     : {prices.min():.1f} → {prices.max():.1f} ¢/lb")
print(f"  Freeze events   : {n_freeze_events}")
print(f"  Mean freeze prob: {freeze_prob.mean():.1%}")

# ──────────────────────────────────────────────────────────────────────
# 2. Define signal generator
# ──────────────────────────────────────────────────────────────────────

section("2. SIGNAL GENERATOR")

ENTRY_THRESHOLD = 0.5
EXIT_THRESHOLD = 0.2
POSITION_SIZE = 0.15


def freeze_signal_generator(data: pd.DataFrame, step: int) -> Signal:
    """Signal generator for the backtest engine.

    Goes LONG on OJ when freeze probability exceeds entry threshold.
    Goes FLAT when it drops below exit threshold.
    """
    if step < 1:
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="OJ_FUTURES",
            timestamp=data.index[step],
            reasoning="Initial step, no position.",
        )

    fp = data["freeze_prob"].iloc[step]
    temp = data["temp_anomaly"].iloc[step]

    if fp > ENTRY_THRESHOLD and temp < -1.5:
        size = min(POSITION_SIZE, fp * 0.25)
        return Signal(
            action=Action.LONG,
            size=size,
            confidence=float(fp),
            instrument="OJ_FUTURES",
            timestamp=data.index[step],
            reasoning=f"Freeze prob {fp:.1%} > {ENTRY_THRESHOLD:.0%}, anomaly {temp:.1f}σ.",
        )

    return Signal(
        action=Action.FLAT,
        size=0.0,
        confidence=0.0,
        instrument="OJ_FUTURES",
        timestamp=data.index[step],
        reasoning=f"Freeze prob {fp:.1%} below threshold.",
    )


print(f"  Entry threshold : {ENTRY_THRESHOLD:.0%}")
print(f"  Exit threshold  : {EXIT_THRESHOLD:.0%}")
print(f"  Position size   : {POSITION_SIZE:.0%}")

# ──────────────────────────────────────────────────────────────────────
# 3. Run backtest
# ──────────────────────────────────────────────────────────────────────

section("3. BACKTEST — Freeze Signal Strategy")

engine = BacktestEngine(price_column="close")
result = engine.run(
    signal_generator=freeze_signal_generator,
    data=df,
    initial_capital=1_000_000.0,
    commission_bps=5.0,
    slippage_bps=2.0,
    instrument="OJ_FUTURES",
)

print(f"  Initial capital : ${result.equity_curve[0]:>12,.0f}")
print(f"  Final equity    : ${result.equity_curve[-1]:>12,.0f}")
print(f"  Total return    : {result.total_return:>12.2%}")
print(f"  Sharpe ratio    : {result.sharpe:>12.2f}")
print(f"  Max drawdown    : {result.max_drawdown:>12.2%}")
print(f"  Win rate        : {result.win_rate:>12.1%}")
print(f"  Profit factor   : {result.profit_factor:>12.2f}")
print(f"  Number of trades: {len(result.trades):>12d}")

# ──────────────────────────────────────────────────────────────────────
# 4. Detailed risk metrics
# ──────────────────────────────────────────────────────────────────────

section("4. RISK METRICS")

equity = result.equity_curve
strat_returns = np.diff(equity) / equity[:-1]
strat_returns = strat_returns[np.isfinite(strat_returns)]

# Buy-and-hold benchmark
bh_equity = 1_000_000.0 * prices / prices[0]
bh_returns = np.diff(bh_equity) / bh_equity[:-1]
bh_returns = bh_returns[np.isfinite(bh_returns)]

print(f"  {'Metric':<28s}  {'Strategy':>12s}  {'Buy&Hold':>12s}")
print(f"  {'─' * 56}")
print(
    f"  {'Sharpe Ratio':<28s}  {sharpe_ratio(strat_returns):>12.2f}  {sharpe_ratio(bh_returns):>12.2f}"
)
print(
    f"  {'Sortino Ratio':<28s}  {sortino_ratio(strat_returns):>12.2f}  {sortino_ratio(bh_returns):>12.2f}"
)
print(f"  {'Max Drawdown':<28s}  {max_drawdown(equity):>12.2%}  {max_drawdown(bh_equity):>12.2%}")
print(
    f"  {'Calmar Ratio':<28s}  {calmar_ratio(strat_returns):>12.2f}  {calmar_ratio(bh_returns):>12.2f}"
)
print(f"  {'VaR (95%)':<28s}  {var(strat_returns, 0.95):>12.2%}  {var(bh_returns, 0.95):>12.2%}")
print(f"  {'CVaR (95%)':<28s}  {cvar(strat_returns, 0.95):>12.2%}  {cvar(bh_returns, 0.95):>12.2%}")
print(
    f"  {'Total Return':<28s}  {result.total_return:>12.2%}  {(bh_equity[-1] / bh_equity[0] - 1):>12.2%}"
)

# ──────────────────────────────────────────────────────────────────────
# 5. Equity curve visualization (text)
# ──────────────────────────────────────────────────────────────────────

section("5. EQUITY CURVES")

subsection("Strategy Equity")
print_equity_curve(equity, width=56, height=12)

subsection("Strategy Drawdown")
print_drawdown_curve(equity, width=56, height=8)

# ──────────────────────────────────────────────────────────────────────
# 6. Trade log
# ──────────────────────────────────────────────────────────────────────

section("6. TRADE LOG (last 10)")

for trade in result.trades[-10:]:
    entry_time = times[min(trade["entry_idx"], len(times) - 1)]
    exit_time = times[min(trade["exit_idx"], len(times) - 1)]
    direction = "LONG" if trade["pnl"] > 0 or trade["return"] > 0 else "LONG"
    print(
        f"  {entry_time.strftime('%Y-%m-%d')} → {exit_time.strftime('%Y-%m-%d')}  "
        f"Entry: {trade['entry_price']:>7.1f}  Exit: {trade['exit_price']:>7.1f}  "
        f"P&L: ${trade['pnl']:>+10,.0f}  ({trade['return']:>+.2%})"
    )

# ──────────────────────────────────────────────────────────────────────
# 7. Summary
# ──────────────────────────────────────────────────────────────────────

section("7. SUMMARY")

print("  ┌─────────────────────────────────────────────────────┐")
print("  │  OJ Freeze Signal Backtest                         │")
print("  │                                                     │")
print(f"  │  Period          : {times[0].strftime('%Y-%m')} → {times[-1].strftime('%Y-%m'):12s}  │")
print(f"  │  Freeze events   : {n_freeze_events:>6d}                       │")
print(f"  │  Trades          : {len(result.trades):>6d}                       │")
print(f"  │  Total return    : {result.total_return:>7.2%}                      │")
print(f"  │  Sharpe ratio    : {result.sharpe:>7.2f}                        │")
print(f"  │  Max drawdown    : {result.max_drawdown:>7.2%}                      │")
print(f"  │  Win rate        : {result.win_rate:>7.1%}                       │")
print(f"  │  Profit factor   : {result.profit_factor:>7.2f}                        │")
print("  └─────────────────────────────────────────────────────┘")

print(f"\n{DIVIDER}")
print("  Done. Run with: python examples/04_historical_backtest.py")
print(DIVIDER)
