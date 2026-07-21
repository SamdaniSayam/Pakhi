"""Profit-and-Loss tracking and performance analytics.

Computes standard trading performance metrics from trade logs and
generates equity curves for visualisation and reporting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import numpy as np

__all__ = [
    "PnLResult",
    "TradeLog",
    "calculate_pnl",
    "compute_equity_curve",
]

logger = logging.getLogger(__name__)


@dataclass
class PnLResult:
    """Aggregated PnL and performance metrics.

    Attributes
    ----------
    total_return : float
        Total return as a fraction (e.g. ``0.15`` = 15%).
    sharpe : float
        Annualised Sharpe Ratio (daily frequency assumed).
    sortino : float
        Annualised Sortino Ratio (downside deviation only).
    max_drawdown : float
        Maximum drawdown from peak as a positive fraction.
    win_rate : float
        Fraction of trades that were profitable.
    profit_factor : float
        Gross profit divided by gross loss.  ``inf`` if no losses.
    equity_curve : np.ndarray
        Cumulative equity values over time.
    """

    total_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))


# Type alias for individual trade records.
TradeLog = list[tuple[datetime, datetime, str, str, float, float, float]]


def compute_equity_curve(
    initial_capital: float,
    trade_pnls: Sequence[float],
) -> np.ndarray:
    """Build an equity curve from a sequence of trade PnL values.

    Parameters
    ----------
    initial_capital : float
        Starting capital.
    trade_pnls : sequence of float
        PnL per trade (can be negative).

    Returns
    -------
    np.ndarray
        Equity curve of length ``len(trade_pnls) + 1``.
    """
    equity = np.empty(len(trade_pnls) + 1, dtype=np.float64)
    equity[0] = initial_capital
    for i, pnl in enumerate(trade_pnls):
        equity[i + 1] = equity[i] + pnl
    return equity


def calculate_pnl(
    trades: TradeLog,
    prices: np.ndarray | None = None,
    initial_capital: float = 1_000_000.0,
) -> PnLResult:
    """Compute aggregated PnL metrics from a trade log.

    Parameters
    ----------
    trades : list of tuples
        Each entry is ``(entry_date, exit_date, instrument, direction,
        entry_price, exit_price, pnl)``.
    prices : array, optional
        Not used in the basic calculation; reserved for future
        mark-to-market analytics.
    initial_capital : float
        Starting capital for equity curve construction.

    Returns
    -------
    PnLResult
    """
    if not trades:
        logger.warning("Empty trade log; returning zero PnLResult.")
        return PnLResult(equity_curve=np.array([initial_capital]))

    trade_pnls = np.array([t[6] for t in trades], dtype=np.float64)
    equity = compute_equity_curve(initial_capital, trade_pnls)

    # --- Returns-based metrics ---
    period_returns = np.diff(equity) / equity[:-1]
    period_returns = period_returns[np.isfinite(period_returns)]

    total_return = (equity[-1] - initial_capital) / initial_capital if initial_capital > 0 else 0.0

    sharpe = _sharpe(period_returns)
    sortino = _sortino(period_returns)
    max_dd = _max_drawdown(equity)

    # --- Trade-based metrics ---
    n_trades = len(trades)
    wins = int(np.sum(trade_pnls > 0))
    win_rate = wins / n_trades if n_trades > 0 else 0.0

    gross_profit = float(np.sum(trade_pnls[trade_pnls > 0]))
    gross_loss = float(np.abs(np.sum(trade_pnls[trade_pnls < 0])))
    if gross_loss < 1e-15:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    result = PnLResult(
        total_return=total_return,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        win_rate=win_rate,
        profit_factor=profit_factor,
        equity_curve=equity,
    )

    logger.info(
        "PnL: return=%.2f%%, sharpe=%.2f, sortino=%.2f, max_dd=%.2f%%, win_rate=%.1f%%, trades=%d",
        total_return * 100,
        sharpe,
        sortino,
        max_dd * 100,
        win_rate * 100,
        n_trades,
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sharpe(returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
    """Annualised Sharpe Ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    rf_per_day = risk_free_rate / 252
    excess = returns - rf_per_day
    mu = np.mean(excess)
    sigma = np.std(excess, ddof=1)
    if sigma < 1e-15:
        return 0.0
    return float(mu / sigma * np.sqrt(252))


def _sortino(returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
    """Annualised Sortino Ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    rf_per_day = risk_free_rate / 252
    excess = returns - rf_per_day
    mu = np.mean(excess)
    downside = excess[excess < 0]
    if len(downside) == 0:
        return 0.0
    downside_std = np.sqrt(np.mean(downside**2))
    if downside_std < 1e-15:
        return 0.0
    return float(mu / downside_std * np.sqrt(252))


def _max_drawdown(equity: np.ndarray) -> float:
    """Maximum drawdown from peak as a positive fraction."""
    eq = np.asarray(equity, dtype=np.float64)
    eq = eq[np.isfinite(eq)]
    if len(eq) < 2:
        return 0.0
    peak = eq[0]
    max_dd = 0.0
    for val in eq:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return float(max_dd)
