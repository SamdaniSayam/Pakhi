"""Portfolio risk metrics for weather quant strategies.

Standard financial risk measures: VaR, CVaR, Sharpe, Sortino,
drawdown, Calmar, and information ratio.
"""

from __future__ import annotations

import logging

import numpy as np

__all__ = [
    "calmar_ratio",
    "cvar",
    "information_ratio",
    "max_drawdown",
    "sharpe_ratio",
    "sortino_ratio",
    "var",
]

logger = logging.getLogger(__name__)


def _clean_returns(returns: np.ndarray) -> np.ndarray:
    """Remove NaN/Inf from a returns array."""
    arr = np.asarray(returns, dtype=np.float64)
    return arr[np.isfinite(arr)]


def var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Value at Risk (historical method).

    Parameters
    ----------
    returns : array-like
        Period returns.
    confidence : float
        Confidence level in ``(0, 1)``. Default 0.95.

    Returns
    -------
    float
        VaR as a positive number representing the loss at the given
        confidence level.
    """
    r = _clean_returns(returns)
    if len(r) == 0:
        return np.nan
    return float(-np.percentile(r, (1 - confidence) * 100))


def cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Conditional Value at Risk (Expected Shortfall).

    Parameters
    ----------
    returns : array-like
        Period returns.
    confidence : float
        Confidence level in ``(0, 1)``. Default 0.95.

    Returns
    -------
    float
        CVaR as a positive number.
    """
    r = _clean_returns(returns)
    if len(r) == 0:
        return np.nan
    cutoff = np.percentile(r, (1 - confidence) * 100)
    tail = r[r <= cutoff]
    if len(tail) == 0:
        return float(-cutoff)
    return float(-np.mean(tail))


def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
    """Annualised Sharpe Ratio.

    Parameters
    ----------
    returns : array-like
        Period returns (assumed daily).
    risk_free_rate : float
        Annualised risk-free rate. Default 0.02 (2%).

    Returns
    -------
    float
        Annualised Sharpe Ratio.
    """
    r = _clean_returns(returns)
    if len(r) < 2:
        return np.nan
    rf_per_period = risk_free_rate / 252
    excess = r - rf_per_period
    mu = np.mean(excess)
    sigma = np.std(excess, ddof=1)
    if sigma < 1e-15:
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
    """Annualised Sortino Ratio (downside deviation only).

    Parameters
    ----------
    returns : array-like
        Period returns (assumed daily).
    risk_free_rate : float
        Annualised risk-free rate. Default 0.02 (2%).

    Returns
    -------
    float
        Annualised Sortino Ratio.
    """
    r = _clean_returns(returns)
    if len(r) < 2:
        return np.nan
    rf_per_period = risk_free_rate / 252
    excess = r - rf_per_period
    mu = np.mean(excess)
    downside = excess[excess < 0]
    if len(downside) == 0:
        return np.nan
    # Use total N (not just downside count) to match the Sortino definition in
    # pakhi/trading/pnl.py so the two implementations agree.
    downside_std = np.sqrt(np.sum(downside**2) / len(r))
    if downside_std < 1e-15:
        return np.nan
    return float(mu / downside_std * np.sqrt(252))


def max_drawdown(equity_curve: np.ndarray) -> float:
    """Maximum drawdown from peak.

    Parameters
    ----------
    equity_curve : array-like
        Cumulative equity values over time.

    Returns
    -------
    float
        Maximum drawdown as a positive fraction (e.g. 0.10 = 10%).
    """
    eq = np.asarray(equity_curve, dtype=np.float64)
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


def calmar_ratio(returns: np.ndarray) -> float:
    """Calmar Ratio: annualised return / max drawdown.

    Parameters
    ----------
    returns : array-like
        Daily returns.

    Returns
    -------
    float
        Calmar Ratio.
    """
    r = _clean_returns(returns)
    if len(r) < 2:
        return np.nan

    n = len(r)
    total_return = float(np.prod(1 + r))
    cagr = total_return ** (252 / n) - 1 if n > 0 else 0.0

    equity = np.cumprod(1 + r)
    dd = max_drawdown(equity)

    if dd < 1e-15:
        return np.nan
    return cagr / dd


def information_ratio(returns: np.ndarray, benchmark_returns: np.ndarray) -> float:
    """Information Ratio: active return / tracking error.

    Parameters
    ----------
    returns : array-like
        Strategy returns.
    benchmark_returns : array-like
        Benchmark returns.

    Returns
    -------
    float
        Information Ratio.
    """
    r = np.asarray(returns, dtype=np.float64)
    b = np.asarray(benchmark_returns, dtype=np.float64)

    min_len = min(len(r), len(b))
    r = r[:min_len]
    b = b[:min_len]

    mask = np.isfinite(r) & np.isfinite(b)
    r = r[mask]
    b = b[mask]

    if len(r) < 2:
        return np.nan

    active = r - b
    te = np.std(active, ddof=1)
    if te < 1e-15:
        return np.nan
    return float(np.mean(active) / te * np.sqrt(252))
