"""Paper trading execution engine for backtesting and live simulation.

Handles order routing, position tracking, and average entry price
calculation without connecting to any real broker.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pakhi.signals.base import Action, Signal

__all__ = [
    "PaperTrader",
    "Trade",
    "TradeDirection",
]

logger = logging.getLogger(__name__)


class TradeDirection(str, Enum):
    """Direction of a trade."""

    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Trade:
    """Represents a single open or closed position.

    Attributes
    ----------
    trade_id : str
        Unique identifier.
    instrument : str
        Instrument ticker.
    direction : TradeDirection
        LONG or SHORT.
    entry_price : float
        Weighted average entry price.
    quantity : float
        Number of contracts / units.
    entry_time : datetime
        Time the position was opened.
    exit_price : float | None
        Price at which the position was closed.  ``None`` if still open.
    exit_time : datetime | None
        Time the position was closed.  ``None`` if still open.
    pnl : float | None
        Realised PnL.  ``None`` if still open.
    status : str
        ``"open"`` or ``"closed"``.
    metadata : dict
        Arbitrary extra data.
    """

    trade_id: str
    instrument: str
    direction: TradeDirection
    entry_price: float
    quantity: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)


class PaperTrader:
    """Simulated order execution engine for backtesting.

    Tracks open positions, computes average entry prices across partial
    fills, and closes positions at a specified price.

    Parameters
    ----------
    initial_capital : float
        Starting cash balance.  Default ``1_000_000``.
    commission_per_trade : float
        Flat commission in USD per round-trip.  Default ``0.0``.
    slippage_bps : float
        Slippage in basis points applied to each fill.  Default ``0.0``.

    Examples
    --------
    >>> trader = PaperTrader(initial_capital=100_000)
    >>> signal = Signal(
    ...     action=Action.LONG, size=0.1, confidence=0.7,
    ...     instrument="NG_FUTURES", timestamp=datetime.now(),
    ...     reasoning="Freeze expected"
    ... )
    >>> trade = trader.execute(signal, current_price=3.45)
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission_per_trade: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_per_trade = commission_per_trade
        self.slippage_bps = slippage_bps

        self._open_trades: dict[str, Trade] = {}
        self._closed_trades: list[Trade] = []

    def execute(self, signal: Signal, current_price: float) -> Trade:
        """Execute a paper trade based on a signal.

        Parameters
        ----------
        signal : Signal
            Trading signal with action, size, and instrument.
        current_price : float
            Current market price for the instrument.

        Returns
        -------
        Trade
            The executed trade record.
        """
        if signal.action == Action.FLAT:
            logger.debug("Signal is FLAT; no trade executed.")
            return Trade(
                trade_id="FLAT",
                instrument=signal.instrument,
                direction=TradeDirection.LONG,
                entry_price=0.0,
                quantity=0.0,
                entry_time=signal.timestamp,
            )

        fill_price = self._apply_slippage(current_price, signal.action)

        direction = TradeDirection.LONG if signal.action == Action.LONG else TradeDirection.SHORT

        quantity = signal.size * self.cash / fill_price if fill_price > 0 else 0.0
        if quantity <= 0:
            logger.warning("Computed quantity is zero; skipping trade.")
            return Trade(
                trade_id="SKIP",
                instrument=signal.instrument,
                direction=direction,
                entry_price=fill_price,
                quantity=0.0,
                entry_time=signal.timestamp,
            )

        # Check for an existing open position on the same instrument + direction.
        existing_id = self._find_open(signal.instrument, direction)
        if existing_id is not None:
            trade = self._average_in(existing_id, fill_price, quantity, signal.timestamp)
        else:
            trade_id = str(uuid.uuid4())[:8]
            trade = Trade(
                trade_id=trade_id,
                instrument=signal.instrument,
                direction=direction,
                entry_price=fill_price,
                quantity=quantity,
                entry_time=signal.timestamp,
                metadata={"confidence": signal.confidence},
            )
            self._open_trades[trade_id] = trade

        self.cash -= (fill_price * quantity) + self.commission_per_trade

        logger.info(
            "EXECUTE %s %s %.2f @ %.4f (qty=%.4f, confidence=%.2f)",
            direction.value,
            signal.instrument,
            quantity,
            fill_price,
            quantity,
            signal.confidence,
        )

        return trade

    def get_open_positions(self) -> list[Trade]:
        """Return all currently open trades.

        Returns
        -------
        list of Trade
        """
        return list(self._open_trades.values())

    def close_position(
        self,
        trade_id: str,
        price: float,
        fill_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> Trade:
        """Close an open position at the given price.

        Parameters
        ----------
        trade_id : str
            ID of the trade to close.
        price : float
            Exit price.
        fill_price : float, optional
            Actual fill price.  If provided, slippage is bypassed.

        Returns
        -------
        Trade
            The closed trade with realised PnL populated.

        Raises
        ------
        KeyError
            If no open trade with the given ID exists.
        """
        if trade_id not in self._open_trades:
            raise KeyError(f"No open trade with id '{trade_id}'.")

        trade = self._open_trades.pop(trade_id)

        if fill_price is not None:
            exit_price = fill_price
        else:
            exit_price = self._apply_slippage(
                price,
                Action.SHORT if trade.direction == TradeDirection.LONG else Action.LONG,
            )

        if trade.direction == TradeDirection.LONG:
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - exit_price) * trade.quantity

        from datetime import timezone
        trade.exit_price = exit_price
        trade.exit_time = timestamp if timestamp is not None else datetime.now(timezone.utc)
        trade.pnl = pnl
        trade.status = "closed"

        self.cash += trade.entry_price * trade.quantity + pnl - self.commission_per_trade
        self._closed_trades.append(trade)

        logger.info(
            "CLOSE %s %s @ %.4f → PnL=%.2f",
            trade.direction.value,
            trade.instrument,
            exit_price,
            pnl,
        )

        return trade

    def get_closed_trades(self) -> list[Trade]:
        """Return all closed (historical) trades.

        Returns
        -------
        list of Trade
        """
        return list(self._closed_trades)

    def get_equity(self, current_prices: dict[str, float]) -> float:
        """Compute total portfolio equity (cash + unrealised PnL).

        Parameters
        ----------
        current_prices : dict
            Mapping from instrument name to current price.

        Returns
        -------
        float
        """
        unrealised = 0.0
        for trade in self._open_trades.values():
            price = current_prices.get(trade.instrument, trade.entry_price)
            unrealised += trade.entry_price * trade.quantity
            if trade.direction == TradeDirection.LONG:
                unrealised += (price - trade.entry_price) * trade.quantity
            else:
                unrealised += (trade.entry_price - price) * trade.quantity
        return self.cash + unrealised

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: float, action: Action) -> float:
        """Adjust fill price for slippage."""
        factor = self.slippage_bps / 10_000
        if action == Action.LONG:
            return price * (1 + factor)
        return price * (1 - factor)

    def _find_open(self, instrument: str, direction: TradeDirection) -> str | None:
        """Find an open trade matching instrument and direction."""
        for tid, trade in self._open_trades.items():
            if trade.instrument == instrument and trade.direction == direction:
                return tid
        return None

    def _average_in(
        self,
        trade_id: str,
        price: float,
        quantity: float,
        timestamp: datetime,
    ) -> Trade:
        """Add to an existing position, recalculating average entry."""
        trade = self._open_trades[trade_id]
        total_qty = trade.quantity + quantity
        if total_qty > 0:
            trade.entry_price = (trade.entry_price * trade.quantity + price * quantity) / total_qty
        trade.quantity = total_qty
        trade.metadata["last_add_time"] = timestamp.isoformat()
        return trade

    def __repr__(self) -> str:
        return (
            f"PaperTrader(cash={self.cash:.2f}, "
            f"open={len(self._open_trades)}, "
            f"closed={len(self._closed_trades)})"
        )
