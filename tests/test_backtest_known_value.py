"""WS-1 T1: known-value exactness test for ``BacktestEngine``.

Proves the engine's daily equity path, per-trade PnL, costs, and metrics are
*mathematically exact* against a hand-computed oracle implemented in
:mod:`fractions.Fraction` (exact rational arithmetic), not a re-run of the
engine's own float code.

Locked assumptions (Evaluation Contract v1.0):
- costs: commission 5 bps + slippage 10 bps **per position change**
  (entry + exit = 30 bps round trip);
- fill timing: signal at step ``i`` -> fill at close of step ``i``;
- ``signal_generator(data.iloc[:i+1], i)`` never sees data beyond step ``i``.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from pakhi.risk.backtest import BacktestEngine
from pakhi.signals.base import Action, Signal

# 10 business days of deterministic prices (returns are exactly 0.00 or 0.10).
PRICES = [100, 100, 110, 121, 121, 121, 133.1, 133.1, 133.1, 146.41]
IDX = pd.date_range("2023-01-02", periods=10, freq="B")

# Position size the signal intends to hold at each engine step ``i``.
SCHEDULE = {1: 0.5, 2: 0.5, 3: 0.0, 4: 0.0, 5: 1.0, 6: 1.0, 7: 0.0, 8: 0.0, 9: 0.0}


def _prices_fraction() -> list[Fraction]:
    return [Fraction(x) for x in PRICES]


def _cost_rate() -> Fraction:
    # 5 bps commission + 10 bps slippage = 15 bps per position change.
    return Fraction(15, 10000)


def make_signal_generator(schedule: dict[int, float]):
    """Deterministic signal generator scripting ``schedule[i]`` as size."""

    def gen(data: pd.DataFrame, i: int) -> Signal:
        # Light lookahead guard: the engine must never hand data beyond step i.
        # (Holds for both full-data and walk-forward fold slices.)
        assert len(data) == i + 1, "engine leaked future rows to the signal"
        size = float(schedule[i])
        if size > 0:
            return Signal(
                action=Action.LONG,
                size=size,
                confidence=0.8,
                instrument="TEST",
                timestamp=data.index[-1],
                reasoning="known-value test",
            )
        return Signal(
            action=Action.FLAT,
            size=0.0,
            confidence=0.0,
            instrument="TEST",
            timestamp=data.index[-1],
            reasoning="known-value test",
        )

    return gen


def make_data() -> pd.DataFrame:
    return pd.DataFrame({"close": PRICES}, index=IDX)


class TestBacktestKnownValue:
    """Exact, hand-computed validation of ``BacktestEngine``."""

    def _oracle(self):
        """Exact re-derivation using :class:`fractions.Fraction`.

        Returns (equity, trades, returns, max_dd, total_return) as exact
        values. Sharpe is derived from the exact returns at the end.
        """
        p = _prices_fraction()
        cost = _cost_rate()
        ic = Fraction(100_000)
        eq = [ic]
        pos = Fraction(0)
        entry_eq: Fraction | None = None
        entry_idx: int | None = None
        entry_price: Fraction | None = None
        trades: list[dict] = []

        for i in range(1, len(p)):
            r = (p[i] - p[i - 1]) / p[i - 1]
            e = eq[-1] * (1 + pos * r)
            new_pos = Fraction(SCHEDULE[i])
            if new_pos != pos:
                if pos != 0:
                    pnl = e - entry_eq
                    trades.append(
                        {
                            "entry_idx": entry_idx,
                            "exit_idx": i,
                            "entry_time": IDX[entry_idx],
                            "exit_time": IDX[i],
                            "entry_price": float(entry_price),
                            "exit_price": float(p[i]),
                            "pnl": float(pnl),
                            "return": float(pnl / entry_eq),
                        }
                    )
                e = e - abs(new_pos - pos) * e * cost
                if new_pos != 0:
                    entry_eq = e
                    entry_idx = i
                    entry_price = p[i]
                pos = new_pos
            eq.append(e)

        returns = [(eq[i] - eq[i - 1]) / eq[i - 1] for i in range(1, len(eq))]
        # Exact max drawdown: max (peak - trough) / peak.
        peak = eq[0]
        max_dd = Fraction(0)
        for v in eq:
            peak = max(peak, v)
            max_dd = max(max_dd, (peak - v) / peak)
        total_ret = (eq[-1] - ic) / ic
        return eq, trades, returns, max_dd, total_ret

    def test_hand_computed_equity_pnl_costs_exact(self):
        eq_exp, _, _, dd_exp, ret_exp = self._oracle()
        result = BacktestEngine().run(
            make_signal_generator(SCHEDULE),
            make_data(),
            initial_capital=100_000,
            commission_bps=5,
            slippage_bps=10,
            instrument="TEST",
        )

        equity_float = np.asarray([float(v) for v in eq_exp])
        np.testing.assert_allclose(result.equity_curve, equity_float, rtol=1e-9, atol=1e-9)
        assert result.equity_curve[0] == 100_000.0

        # Hardcoded spot values (hand-derived, machine-checked by the oracle).
        assert len(result.trades) == 2

        t1, t2 = result.trades
        assert t1["entry_idx"] == 1 and t1["exit_idx"] == 3
        assert t1["entry_time"] == IDX[1] and t1["exit_time"] == IDX[3]
        assert t1["entry_price"] == 100.0 and t1["exit_price"] == 121.0
        assert t1["pnl"] == pytest.approx(10242.3125)
        assert t1["return"] == pytest.approx(0.1025)

        assert t2["entry_idx"] == 5 and t2["exit_idx"] == 7
        assert t2["entry_time"] == IDX[5] and t2["exit_time"] == IDX[7]
        assert t2["entry_price"] == 121.0 and t2["exit_price"] == 133.1
        assert t2["pnl"] == pytest.approx(10991.95599851015625)
        assert t2["return"] == pytest.approx(0.10)

        assert result.total_return == pytest.approx(float(ret_exp), rel=1e-12)
        assert result.total_return == pytest.approx(0.2073014870963630)
        assert result.max_drawdown == pytest.approx(float(dd_exp), rel=1e-12)
        assert result.max_drawdown == pytest.approx(0.0015)
        assert result.win_rate == 1.0
        assert result.profit_factor == pytest.approx(float("inf"))

    def test_sharpe_matches_exact_returns(self):
        _, _, returns_exp, _, _ = self._oracle()
        result = BacktestEngine().run(
            make_signal_generator(SCHEDULE),
            make_data(),
            initial_capital=100_000,
            commission_bps=5,
            slippage_bps=10,
        )

        # Recompute the daily-equity Sharpe from the exact returns (float-converted
        # only at the very end), reproducing BacktestEngine._sharpe's formula.
        rf_day = 0.02 / 252
        r = np.asarray([float(v) for v in returns_exp])
        excess = r - rf_day
        mu = excess.mean()
        sigma = excess.std(ddof=1)
        expected_sharpe = mu / sigma * np.sqrt(252)
        assert result.sharpe == pytest.approx(float(expected_sharpe), rel=1e-9)

    def test_cost_semantics_30bps_round_trip(self):
        # Flat prices: a single LONG 1.0 -> FLAT round trip must cost exactly
        # 30 bps (15 bps per position change) on ~notional.
        data = pd.DataFrame({"close": [100.0] * 4}, index=IDX[:4])
        schedule = {1: 1.0, 2: 1.0, 3: 0.0}
        result = BacktestEngine().run(
            make_signal_generator(schedule),
            data,
            initial_capital=100_000,
            commission_bps=5,
            slippage_bps=10,
        )
        # Entry cost 150.0; exit cost 149.775; final equity 99700.225.
        assert result.equity_curve[-1] == pytest.approx(99_700.225)
        assert result.total_return == pytest.approx(-0.00299775)
        assert len(result.trades) == 1
        assert result.trades[0]["pnl"] == pytest.approx(0.0)

    def test_walk_forward_slicing_exact(self):
        # train_window=5, test_window=2 on 10 rows -> folds test [5:7] and [7:9].
        data = make_data()
        engine = BacktestEngine()
        results = engine.walk_forward(
            make_signal_generator(SCHEDULE),
            data,
            train_window=5,
            test_window=2,
            initial_capital=100_000,
            commission_bps=5,
            slippage_bps=10,
        )
        assert len(results) == 2
        for fold, (lo, hi) in zip(results, [(5, 7), (7, 9)]):
            expected = engine.run(
                make_signal_generator(SCHEDULE),
                data.iloc[lo:hi],
                initial_capital=100_000,
                commission_bps=5,
                slippage_bps=10,
            )
            np.testing.assert_allclose(fold.equity_curve, expected.equity_curve, rtol=1e-12)
            assert fold.sharpe == pytest.approx(expected.sharpe)
            assert fold.total_return == pytest.approx(expected.total_return)

    def test_walk_forward_retrain_sees_train_slice_only(self):
        data = make_data()
        seen: list[tuple[pd.Timestamp, pd.Timestamp]] = []

        def retrain_fn(train_data: pd.DataFrame):
            seen.append((train_data.index[0], train_data.index[-1]))
            return make_signal_generator(SCHEDULE)

        engine = BacktestEngine()
        results = engine.walk_forward(
            retrain_fn=retrain_fn,
            signal_generator=make_signal_generator(SCHEDULE),
            data=data,
            train_window=5,
            test_window=2,
        )
        assert len(results) == 2
        # Fold 1 train = rows 0:5, fold 2 train = rows 2:7.
        assert seen[0] == (IDX[0], IDX[4])
        assert seen[1] == (IDX[2], IDX[6])
