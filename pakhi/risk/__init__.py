"""Risk management module — metrics, uncertainty, alerts, and backtesting.

Submodules
----------
metrics
    VaR, CVaR, Sharpe, Sortino, drawdown, Calmar, and information ratio.
uncertainty
    Ensemble spread, calibration error, sharpness, and coverage.
alerts
    Weather risk alert manager with severity levels.
backtest
    Signal-based backtesting engine with walk-forward validation.
"""

from __future__ import annotations

from pakhi.risk.alerts import Alert, AlertManager, AlertSeverity, send_alert
from pakhi.risk.backtest import BacktestEngine, BacktestResult
from pakhi.risk.metrics import (
    calmar_ratio,
    cvar,
    information_ratio,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    var,
)
from pakhi.risk.uncertainty import (
    calibration_error,
    coverage,
    ensemble_spread,
    sharpness,
)

__all__ = [
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "BacktestEngine",
    "BacktestResult",
    "calibration_error",
    "calmar_ratio",
    "coverage",
    "cvar",
    "ensemble_spread",
    "information_ratio",
    "max_drawdown",
    "send_alert",
    "sharpe_ratio",
    "sharpness",
    "sortino_ratio",
    "var",
]
