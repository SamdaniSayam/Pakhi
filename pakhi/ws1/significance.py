"""WS-1 T5: statistical significance engine for event-based OJ backtests.

Blueprint T5 + Evaluation Contract §3.4 ("consecutive-day freeze forecasts are
highly autocorrelated ... purged/Newey-West standard errors to prevent
overstated t-stats") and §8 (locked decision rules).  This module adds the
statistical machinery the G1 report applies:

- **Newey-West HAC t-statistic** on the event-trade returns (autocorrelation-
  robust standard error of the mean), alongside the classic ``mean / (σ/√N)``.
- **Bootstrap CI + one-sided p-value** for the net-of-benchmark edge (10 000
  resamples, ``np.random.default_rng(42)`` — the *same* stream that produces the
  locked CI, so CI and p-value are consistent).
- **N gate** (centralised, locked): N ≥ 30 full-power; N_min = 8 shrunk edge
  claim; N < 8 ⇒ UNDER-POWERED.
- **Decision gate** (§8, a-priori): ZERO_TRADES / UNDER_POWERED / PASS /
  FAIL_PIVOT.
- **Overlap/purge check** on the event windows, so sparse-trade variance cannot
  be overstated by overlapping 2-session holds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pakhi.ws1.metrics import _bootstrap_sharpes, annualized_sharpe, bootstrap_ci, t_stat
from pakhi.ws1.pit import COST

__all__ = [
    "N_FULL",
    "N_MIN",
    "SHARPE_GATE",
    "bootstrap_pvalue",
    "decision_gate",
    "newey_west_lag",
    "newey_west_se",
    "newey_west_tstat",
    "significance_report",
]

N_MIN = 8  # locked: minimum OOS event-trades for a shrunk edge claim (§3)
N_FULL = 30  # full-power trade count (structurally unreachable for freezes)
SHARPE_GATE = 1.0  # locked: net-of-benchmark event Sharpe to clear (§8)

_BOOTSTRAP_RESAMPLES = 10_000
_BOOTSTRAP_SEED = 42


def newey_west_lag(n: int) -> int:
    """Newey-West (1994) truncation lag, clamped to ``[1, n//2]``."""
    return max(1, min(int(4 * (n / 100) ** (2 / 9)), max(1, n // 2)))


def newey_west_se(returns: np.ndarray, lag: int | None = None) -> float:
    """Newey-West HAC standard error of the mean (autocorrelation-robust).

    ``lag`` defaults to :func:`newey_west_lag`.  Returns ``nan`` for N < 2.
    """
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2:
        return float("nan")
    if lag is None:
        lag = newey_west_lag(n)
    demeaned = returns - returns.mean()
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    long_run = gamma0
    for j in range(1, lag + 1):
        gamma_j = float(np.dot(demeaned[j:], demeaned[:-j]) / n)
        long_run += 2 * (1 - j / (lag + 1)) * gamma_j
    return float(np.sqrt(long_run / n))


def newey_west_tstat(returns: np.ndarray, lag: int | None = None) -> float:
    """Autocorrelation-robust t-statistic: mean / Newey-West SE."""
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2:
        return 0.0
    se = newey_west_se(returns, lag)
    if not np.isfinite(se) or se < 1e-15:
        return 0.0
    return float(returns.mean() / se)


def bootstrap_pvalue(
    returns: np.ndarray,
    span_years: float,
    n_resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int = _BOOTSTRAP_SEED,
) -> float:
    """One-sided bootstrap p-value: P(bootstrap Sharpe <= 0) under H1 edge > 0.

    Shares the exact resample stream of the locked CI (``_bootstrap_sharpes``).
    A small p-value means the net-of-benchmark edge is unlikely to be
    non-positive by chance; with N this small the CI width is the real warning.
    """
    returns = np.asarray(returns, dtype=np.float64)
    n = len(returns)
    if n < 2:
        return 1.0
    stats = _bootstrap_sharpes(returns, span_years, n_resamples, seed)
    return float((1 + int((stats <= 0.0).sum())) / (n_resamples + 1))


def decision_gate(
    n_events: int,
    net_of_benchmark_sharpe: float,
    ci_lower: float,
    mean_net_of_benchmark: float,
) -> dict:
    """Locked §8 decision rules (a-priori, applied in order)."""
    if n_events == 0:
        return {
            "outcome": "ZERO_TRADES",
            "reason": "architecture success: fast, rigorous disproof -> documented pivot",
        }
    if n_events < N_MIN:
        return {
            "outcome": "UNDER_POWERED",
            "reason": f"N={n_events} < N_min={N_MIN}: no conclusion; G1 recorded UNDER-POWERED, "
            "freeze thesis defers to Phase 2 live paper-trading to accumulate events",
        }
    passed = bool(net_of_benchmark_sharpe > SHARPE_GATE and ci_lower > 0)
    if passed:
        return {
            "outcome": "PASS",
            "reason": f"N={n_events} >= {N_MIN}, net-of-bench Sharpe {net_of_benchmark_sharpe:.3f} > "
            f"{SHARPE_GATE} and bootstrap CI lower bound {ci_lower:.3f} > 0 -> proceed to WS-2",
        }
    return {
        "outcome": "FAIL_PIVOT",
        "reason": f"N={n_events} >= {N_MIN} but edge not proven (CI includes 0 or mean net "
        f"{mean_net_of_benchmark:+.4f} <= 0) -> documented pivot (cat-bonds / reinsurance analytics)",
    }


def _distribution_summary(returns: np.ndarray, span_years: float) -> dict:
    """Bootstrap distribution percentiles of the annualized net-of-bench Sharpe."""
    stats = _bootstrap_sharpes(returns, span_years, _BOOTSTRAP_RESAMPLES, _BOOTSTRAP_SEED)
    pct = [1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0]
    vals = np.percentile(stats, pct)
    return {
        "n_resamples": _BOOTSTRAP_RESAMPLES,
        "percentiles": {f"p{p:g}": float(v) for p, v in zip(pct, vals)},
    }


def _overlap_check(ledger: pd.DataFrame, hold_sessions: int = 2) -> dict:
    """Count events whose 2-session windows overlap a prior event's window.

    Consecutive freeze episodes are >= 3 trading sessions apart (locked episode
    rule) so overlapping holds are structurally impossible; this verifies it on
    the scored ledger so sparse-trade variance cannot be overstated.
    """
    if ledger.empty:
        return {"n_overlapping_events": 0, "purging_needed": False}
    order = ledger.sort_values("entry_session")
    prev_end = None
    overlapping = 0
    for _, ev in order.iterrows():
        start = pd.Timestamp(ev["entry_session"])
        if prev_end is not None and start < prev_end:
            overlapping += 1
        prev_end = start + pd.Timedelta(days=1) * (hold_sessions + 1)
    return {
        "n_overlapping_events": int(overlapping),
        "purging_needed": bool(overlapping > 0),
    }


def significance_report(
    trades: pd.DataFrame,
    benchmark_mean: float,
    span_years: float,
    hold_sessions: int = 2,
) -> dict:
    """Full T5 significance table for a scored event-trade ledger.

    ``trades`` must carry ``gross``, ``net``, ``net_of_benchmark`` and
    ``entry_session`` columns.  Exposes the probability distribution and
    p-values so the G1 report can judge whether sparse-trade variance is too
    high (blueprint T5 exit).
    """
    if trades.empty:
        return {
            "n_events": 0,
            "power_class": "no trades",
            "classic_t": 0.0,
            "newey_west_t": 0.0,
            "newey_west_lag": 0,
            "ci_95_net_of_benchmark_sharpe": (0.0, 0.0),
            "bootstrap_pvalue_edge_gt_zero": 1.0,
            "distribution": {},
            "overlap_check": _overlap_check(trades, hold_sessions),
            "decision": decision_gate(0, 0.0, 0.0, 0.0),
            "_cost": COST,
        }

    nb = trades["net_of_benchmark"].to_numpy(dtype=np.float64)
    n = len(nb)
    sharpe = annualized_sharpe(nb, span_years)
    ci_lo, ci_hi = bootstrap_ci(nb, span_years)
    p = bootstrap_pvalue(nb, span_years)
    nw_t = newey_west_tstat(nb)
    lag = newey_west_lag(n)

    power_class = (
        "full-power (N >= 30)"
        if n >= N_FULL
        else f"shrunk edge claim (N_min = {N_MIN})"
        if n >= N_MIN
        else "under-powered (N < N_min)"
    )

    return {
        "n_events": n,
        "power_class": power_class,
        "mean_net_of_benchmark": float(nb.mean()),
        "classic_t": t_stat(nb),
        "newey_west_t": nw_t,
        "newey_west_lag": lag,
        "net_of_benchmark_sharpe": sharpe,
        "ci_95_net_of_benchmark_sharpe": (ci_lo, ci_hi),
        "bootstrap_pvalue_edge_gt_zero": p,
        "distribution": _distribution_summary(nb, span_years),
        "overlap_check": _overlap_check(trades, hold_sessions),
        "decision": decision_gate(n, sharpe, ci_lo, float(nb.mean())),
        "_cost": COST,
    }
