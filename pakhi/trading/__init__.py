"""Trading module — portfolio management, instruments, PnL, and execution.

Submodules
----------
portfolio
    Position sizing via Kelly criterion, equal weight, and risk parity.
instruments
    Weather-linked futures and derivatives catalogue.
pnl
    Trade-level PnL tracking and performance analytics.
execution
    Paper trading engine for backtesting and simulation.
"""

from __future__ import annotations

from pakhi.trading.execution import PaperTrader, Trade, TradeDirection
from pakhi.trading.instruments import (
    CAT_BONDS,
    CL_FUTURES,
    ERCOT_FUTURES,
    HE_FUTURES,
    LE_FUTURES,
    NG_FUTURES,
    OJ_FUTURES,
    PJM_FUTURES,
    ZC_FUTURES,
    ZS_FUTURES,
    ZW_FUTURES,
    Instrument,
    get_instrument,
)
from pakhi.trading.pnl import PnLResult, calculate_pnl, compute_equity_curve
from pakhi.trading.portfolio import Portfolio, SizingMethod

__all__ = [
    "CAT_BONDS",
    "CL_FUTURES",
    "ERCOT_FUTURES",
    "HE_FUTURES",
    "LE_FUTURES",
    "NG_FUTURES",
    "OJ_FUTURES",
    "PJM_FUTURES",
    "ZC_FUTURES",
    "ZS_FUTURES",
    "ZW_FUTURES",
    "Instrument",
    "PaperTrader",
    "PnLResult",
    "Portfolio",
    "SizingMethod",
    "Trade",
    "TradeDirection",
    "calculate_pnl",
    "compute_equity_curve",
    "get_instrument",
]
