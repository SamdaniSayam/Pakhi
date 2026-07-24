"""Tests for pakhi.trading — pnl, portfolio, instruments."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from pakhi.trading.pnl import PnLResult, TradeLog, calculate_pnl, compute_equity_curve
from pakhi.trading.portfolio import Portfolio, SizingMethod
from pakhi.trading.instruments import (
    Instrument,
    NG_FUTURES,
    OJ_FUTURES,
    ZC_FUTURES,
    ERCOT_FUTURES,
    PJM_FUTURES,
    CAT_BONDS,
    get_instrument,
)


class TestEquityCurve:
    def test_basic(self):
        eq = compute_equity_curve(100000, [1000, -500, 2000])
        assert eq[0] == 100000
        assert eq[1] == 101000
        assert eq[2] == 100500
        assert eq[3] == 102500

    def test_empty(self):
        eq = compute_equity_curve(100000, [])
        assert len(eq) == 1
        assert eq[0] == 100000


class TestCalculatePnl:
    def test_basic(self):
        now = datetime.now(timezone.utc)
        trades: TradeLog = [
            (now, now, "X", "LONG", 100.0, 110.0, 1000.0),
            (now, now, "X", "LONG", 110.0, 105.0, -500.0),
            (now, now, "X", "LONG", 105.0, 120.0, 1500.0),
        ]
        result = calculate_pnl(trades)
        assert isinstance(result, PnLResult)
        assert result.win_rate == pytest.approx(2 / 3)
        assert result.total_return > 0

    def test_empty_trades(self):
        result = calculate_pnl([])
        assert result.total_return == 0.0
        assert len(result.equity_curve) == 1

    def test_all_wins(self):
        now = datetime.now(timezone.utc)
        trades: TradeLog = [
            (now, now, "X", "LONG", 100, 110, 1000),
            (now, now, "X", "LONG", 100, 120, 2000),
        ]
        result = calculate_pnl(trades)
        assert result.win_rate == 1.0
        assert result.profit_factor == float("inf")


class TestPortfolio:
    def test_kelly(self):
        p = Portfolio(max_position=0.10, kelly_fraction=0.5)
        size = p.kelly_criterion(0.7, odds=2.0)
        assert 0.0 < size <= 0.10

    def test_kelly_negative_edge(self):
        p = Portfolio()
        assert p.kelly_criterion(0.1, odds=2.0) == 0.0

    def test_equal_weight(self):
        p = Portfolio(max_position=0.5)
        w = p.equal_weight(4)
        assert w == pytest.approx(0.25)

    def test_equal_weight_one(self):
        p = Portfolio(max_position=0.5)
        w = p.equal_weight(1)
        assert w == pytest.approx(0.5)

    def test_equal_weight_invalid(self):
        p = Portfolio()
        with pytest.raises(ValueError):
            p.equal_weight(0)

    def test_risk_parity(self):
        p = Portfolio()
        returns = np.random.randn(100, 3) * 0.01
        weights = p.risk_parity(returns)
        assert len(weights) == 3
        assert weights.sum() == pytest.approx(1.0)

    def test_position_size_kelly(self):
        p = Portfolio(max_position=0.10)
        size = p.position_size(0.7, method="kelly", odds=2.0)
        assert 0.0 <= size <= 0.10

    def test_position_size_equal_weight(self):
        p = Portfolio(max_position=0.5)
        size = p.position_size(0.7, method="equal_weight", n_instruments=4)
        assert size == pytest.approx(0.25)

    def test_position_size_risk_parity(self):
        p = Portfolio()
        returns = np.random.randn(100, 2) * 0.01
        size = p.position_size(0.7, method="risk_parity", returns_matrix=returns)
        assert 0.0 <= size <= 1.0

    def test_position_size_unknown(self):
        p = Portfolio()
        with pytest.raises(ValueError, match="Unknown"):
            p.position_size(0.7, method="bad")

    def test_invalid_max_position(self):
        with pytest.raises(ValueError):
            Portfolio(max_position=0.0)

    def test_repr(self):
        p = Portfolio()
        assert "max_position" in repr(p)


class TestInstruments:
    def test_get_instrument(self):
        inst = get_instrument("NG_FUTURES")
        assert inst.name == "Natural Gas Futures"
        assert inst.exchange == "NYMEX"

    def test_get_instrument_unknown(self):
        with pytest.raises(KeyError, match="Unknown instrument"):
            get_instrument("ZZZZ")

    def test_constants(self):
        assert OJ_FUTURES.exchange == "ICE"
        assert ZC_FUTURES.exchange == "CBOT"
        assert ERCOT_FUTURES.exchange == "ERCOT"
        assert PJM_FUTURES.exchange == "PJM"
        assert CAT_BONDS.exchange == "OTC"

    def test_instrument_frozen(self):
        inst = get_instrument("NG_FUTURES")
        with pytest.raises(AttributeError):
            inst.name = "Changed"
