"""WS-1 event-based (trade-level) metrics, per Evaluation Contract v1.0 §6-8.

The headline G1 metric is the **net-of-benchmark event-trade Sharpe**:

    annualized = mean / std(ddof=1) × sqrt(N / span_years)

pooled across OOS event trades, with a t-statistic and a percentile bootstrap
95 % CI (10 000 resamples, ``np.random.default_rng(42)``) — both locked in the
contract.  T5 (Statistical Significance Engine) will extend this module with
purged / Newey-West standard errors; the point estimates here are final.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pakhi.ws1.pit import COST

__all__ = [
    "_bootstrap_sharpes",
    "annualized_sharpe",
    "bootstrap_ci",
    "event_metrics",
    "t_stat",
]

_BOOTSTRAP_RESAMPLES = 10_000
_BOOTSTRAP_SEED = 42
_CI = 0.95


def _bootstrap_sharpes(
    returns: np.ndarray,
    span_years: float,
    n_resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int = _BOOTSTRAP_SEED,
) -> np.ndarray:
    """Annualized net-of-bench Sharpe of ``n_resamples`` bootstrap resamples.

    Single deterministic resample stream (``np.random.default_rng(seed)``) so
    the CI (``bootstrap_ci``) and the T5 p-value share identical draws.
    Degenerate resamples (zero variance) fall back to the point estimate so the
    CI stays finite.
    """
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    rng = np.random.default_rng(seed)
    point = returns.mean() / returns.std(ddof=1) if returns.std(ddof=1) > 1e-15 else 0.0
    scale = np.sqrt(n / span_years)
    stats = np.empty(n_resamples)
    for k in range(n_resamples):
        boot = returns[rng.integers(0, n, size=n)]
        sigma = boot.std(ddof=1)
        if sigma < 1e-15:
            stats[k] = point * scale
        else:
            stats[k] = boot.mean() / sigma * scale
    return stats


def bootstrap_ci(
    returns: np.ndarray,
    span_years: float,
    n_resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Percentile 95 % CI of the annualized Sharpe over ``n_resamples`` resamples.

    Deterministic under a fixed ``seed`` (locked to 42).  Degenerate resamples
    (zero variance) fall back to the point estimate so the CI stays finite.
    """
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2:
        return (0.0, 0.0)
    stats = _bootstrap_sharpes(returns, span_years, n_resamples, seed)
    alpha = 1.0 - _CI
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def annualized_sharpe(returns: np.ndarray, span_years: float) -> float:
    """mean / std(ddof=1) × sqrt(N / span_years) — locked annualisation."""
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2 or span_years <= 0:
        return 0.0
    sigma = returns.std(ddof=1)
    if sigma < 1e-15:
        return 0.0
    return float(returns.mean() / sigma * np.sqrt(n / span_years))


def t_stat(returns: np.ndarray) -> float:
    """mean / (std(ddof=1) / sqrt(N))."""
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2:
        return 0.0
    sigma = returns.std(ddof=1)
    if sigma < 1e-15:
        return 0.0
    return float(returns.mean() / (sigma / np.sqrt(n)))


def event_metrics(
    trades: pd.DataFrame,
    benchmark_mean: float,
    span_years: float,
) -> dict:
    """Full locked metric table for a scored event-trade ledger.

    ``trades`` must carry ``gross`` (2-session return fraction), ``net``
    (gross − 30 bps) and ``net_of_benchmark`` columns (see ``harness.py``).
    """
    if trades.empty:
        return {
            "n_events": 0,
            "mean_gross": 0.0,
            "mean_net": 0.0,
            "mean_net_of_benchmark": 0.0,
            "gross_sharpe": 0.0,
            "net_sharpe": 0.0,
            "net_of_benchmark_sharpe": 0.0,
            "t_stat": 0.0,
            "ci_95_net_of_benchmark_sharpe": (0.0, 0.0),
            "win_rate": 0.0,
        }

    gross = trades["gross"].to_numpy(dtype=np.float64)
    net = trades["net"].to_numpy(dtype=np.float64)
    nb = trades["net_of_benchmark"].to_numpy(dtype=np.float64)

    ci = bootstrap_ci(nb, span_years)
    return {
        "n_events": len(trades),
        "mean_gross": float(gross.mean()),
        "mean_net": float(net.mean()),
        "mean_net_of_benchmark": float(nb.mean()),
        "gross_sharpe": annualized_sharpe(gross, span_years),
        "net_sharpe": annualized_sharpe(net, span_years),
        "net_of_benchmark_sharpe": annualized_sharpe(nb, span_years),
        "t_stat": t_stat(nb),
        "ci_95_net_of_benchmark_sharpe": ci,
        "win_rate": float((net > 0.0).mean()),
        "_cost": COST,
    }
