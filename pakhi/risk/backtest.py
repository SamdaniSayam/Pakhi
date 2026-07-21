"""Backtesting engine with walk-forward validation.

Provides ``BacktestEngine`` for signal-based strategy evaluation with
realistic commission and slippage modelling, and walk-forward rolling
window optimisation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import numpy as np
import pandas as pd

from pakhi.signals.base import Action, Signal

__all__ = ["BacktestEngine", "BacktestResult"]

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for backtest performance results.

    Attributes
    ----------
    equity_curve : np.ndarray
        Daily equity values.
    sharpe : float
        Annualised Sharpe Ratio.
    max_drawdown : float
        Maximum drawdown (positive fraction).
    win_rate : float
        Fraction of winning days.
    profit_factor : float
        Gross profit / gross loss.
    total_return : float
        Total return fraction.
    trades : list of dict
        Individual trade records.
    """

    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_return: float = 0.0
    trades: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.equity_curve = np.asarray(self.equity_curve, dtype=np.float64)


class BacktestEngine:
    """Event-driven backtesting engine with commission and slippage.

    Parameters
    ----------
    price_column : str
        Column name for prices in the data. Default ``"close"``.

    Examples
    --------
    >>> engine = BacktestEngine()
    >>> result = engine.run(
    ...     signal_generator=my_signal_fn,
    ...     instrument="NG_FUTURES",
    ...     start=datetime(2023, 1, 1),
    ...     end=datetime(2024, 1, 1),
    ...     initial_capital=1_000_000,
    ...     commission_bps=5,
    ...     slippage_bps=2,
    ... )
    """

    __all__ = ["run", "walk_forward"]

    def __init__(self, price_column: str = "close") -> None:
        self.price_column = price_column

    def run(
        self,
        signal_generator: Callable[[pd.DataFrame, int], Signal],
        data: pd.DataFrame,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        initial_capital: float = 1_000_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 2.0,
        instrument: str = "UNKNOWN",
    ) -> BacktestResult:
        """Run a single backtest.

        Parameters
        ----------
        signal_generator : callable
            ``(data, step_index) -> Signal``.  Called at each time step.
            May return FLAT to stay out of the market.
        data : DataFrame
            Must have a ``price_column`` and a datetime index.
        start, end : datetime or str, optional
            Backtest window.  ``None`` uses full data range.
        initial_capital : float
            Starting capital.
        commission_bps : float
            Commission in basis points per trade. Default 5.
        slippage_bps : float
            Slippage in basis points per trade. Default 2.
        instrument : str
            Instrument label for logging.

        Returns
        -------
        BacktestResult
        """
        if self.price_column not in data.columns:
            raise ValueError(f"Column '{self.price_column}' not found in data.")

        prices = data[self.price_column].copy()
        prices = prices.dropna()

        if start is not None:
            prices = prices[prices.index >= pd.Timestamp(start)]
        if end is not None:
            prices = prices[prices.index <= pd.Timestamp(end)]

        if len(prices) < 2:
            return BacktestResult()

        equity = np.zeros(len(prices), dtype=np.float64)
        equity[0] = initial_capital
        trades: list[dict] = []

        position = 0.0  # current position size as fraction
        entry_price = 0.0
        entry_idx = 0
        entry_equity = 0.0

        commission_rate = commission_bps / 10_000
        slippage_rate = slippage_bps / 10_000

        for i in range(1, len(prices)):
            price_now = float(prices.iloc[i])
            price_prev = float(prices.iloc[i - 1])
            daily_return = (price_now - price_prev) / price_prev if price_prev != 0 else 0.0

            portfolio_return = position * daily_return
            equity[i] = equity[i - 1] * (1.0 + portfolio_return)

            signal = signal_generator(data.iloc[: i + 1], i)

            new_position = self._signal_to_position(signal)
            if new_position != position:
                if position != 0:
                    pnl = equity[i] - entry_equity
                    trades.append(
                        {
                            "entry_idx": entry_idx,
                            "exit_idx": i,
                            "entry_price": entry_price,
                            "exit_price": price_now,
                            "pnl": float(pnl),
                            "return": float(pnl / entry_equity) if entry_equity != 0 else 0.0,
                        }
                    )

                trade_cost = (
                    abs(new_position - position) * equity[i] * (commission_rate + slippage_rate)
                )
                equity[i] -= trade_cost

                if new_position != 0:
                    entry_price = price_now
                    entry_idx = i
                    entry_equity = equity[i]

                position = new_position

        if position != 0:
            price_last = float(prices.iloc[-1])
            pnl = equity[-1] - entry_equity
            trades.append(
                {
                    "entry_idx": entry_idx,
                    "exit_idx": len(prices) - 1,
                    "entry_price": entry_price,
                    "exit_price": price_last,
                    "pnl": float(pnl),
                    "return": float(pnl / entry_equity) if entry_equity != 0 else 0.0,
                }
            )

        returns = np.diff(equity) / equity[:-1]
        returns = returns[np.isfinite(returns)]

        sharpe = self._sharpe(returns)
        mdd = self._max_dd(equity)
        win_rate = self._win_rate(trades)
        pf = self._profit_factor(trades)
        total_ret = (equity[-1] - initial_capital) / initial_capital if initial_capital > 0 else 0.0

        logger.info(
            "Backtest %s: return=%.2f%%, sharpe=%.2f, max_dd=%.2f%%, trades=%d",
            instrument,
            total_ret * 100,
            sharpe,
            mdd * 100,
            len(trades),
        )

        return BacktestResult(
            equity_curve=equity,
            sharpe=sharpe,
            max_drawdown=mdd,
            win_rate=win_rate,
            profit_factor=pf,
            total_return=total_ret,
            trades=trades,
        )

    def walk_forward(
        self,
        signal_generator: Callable[[pd.DataFrame, int], Signal],
        data: pd.DataFrame,
        train_window: int = 252,
        test_window: int = 63,
        initial_capital: float = 1_000_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 2.0,
        instrument: str = "UNKNOWN",
    ) -> list[BacktestResult]:
        """Rolling window walk-forward backtest.

        Parameters
        ----------
        signal_generator : callable
            ``(data, step_index) -> Signal``.
        data : DataFrame
            Price data with datetime index.
        train_window : int
            Training window in bars. Default 252 (~1 year daily).
        test_window : int
            Testing window in bars. Default 63 (~1 quarter daily).
        initial_capital : float
            Starting capital per fold.
        commission_bps : float
            Commission per trade.
        slippage_bps : float
            Slippage per trade.
        instrument : str
            Instrument label.

        Returns
        -------
        list of BacktestResult
            One result per walk-forward fold.
        """
        prices = data[self.price_column].dropna()
        n = len(prices)

        if n < train_window + test_window:
            logger.warning(
                "Data length %d < train_window + test_window = %d. Running single fold.",
                n,
                train_window + test_window,
            )
            return [
                self.run(
                    signal_generator,
                    data,
                    initial_capital=initial_capital,
                    commission_bps=commission_bps,
                    slippage_bps=slippage_bps,
                    instrument=instrument,
                )
            ]

        results: list[BacktestResult] = []
        start = 0

        while start + train_window + test_window <= n:
            test_start = start + train_window
            test_end = min(test_start + test_window, n)

            test_data = data.iloc[test_start:test_end]

            result = self.run(
                signal_generator,
                test_data,
                initial_capital=initial_capital,
                commission_bps=commission_bps,
                slippage_bps=slippage_bps,
                instrument=instrument,
            )
            results.append(result)
            logger.info(
                "Walk-forward fold %d: start=%s, return=%.2f%%",
                len(results),
                test_data.index[0],
                result.total_return * 100,
            )

            start += test_window

        return results

    @staticmethod
    def _signal_to_position(signal: Signal) -> float:
        """Convert a Signal to a position multiplier: +size, -size, or 0."""
        if signal.action == Action.LONG:
            return signal.size
        elif signal.action == Action.SHORT:
            return -signal.size
        return 0.0

    @staticmethod
    def _sharpe(returns: np.ndarray) -> float:
        if len(returns) < 2:
            return 0.0
        mu = np.mean(returns)
        sigma = np.std(returns, ddof=1)
        if sigma < 1e-15:
            return 0.0
        return float(mu / sigma * np.sqrt(252))

    @staticmethod
    def _max_dd(equity: np.ndarray) -> float:
        peak = equity[0]
        max_dd = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return float(max_dd)

    @staticmethod
    def _win_rate(trades: list[dict]) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t["pnl"] > 0)
        return wins / len(trades)

    @staticmethod
    def _profit_factor(trades: list[dict]) -> float:
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        if gross_loss < 1e-15:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
