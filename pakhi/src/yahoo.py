"""Yahoo Finance commodity futures connector.

Fetches commodity futures prices via yfinance for weather-sensitive
instruments: crude oil, natural gas, orange juice, corn, soybeans.

Example:
    >>> from pakhi.src.yahoo import YahooFuturesConnector
    >>> yf = YahooFuturesConnector()
    >>> prices = yf.current_price()
    >>> hist = yf.history(period="2y")
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

__all__ = ["YahooFuturesConnector"]

logger = logging.getLogger(__name__)

DEFAULT_TICKERS: dict[str, str] = {
    "CL=F": "Crude Oil",
    "NG=F": "Natural Gas",
    "OJ=F": "Orange Juice",
    "ZC=F": "Corn",
    "ZS=F": "Soybeans",
    "ZW=F": "Wheat",
    "LE=F": "Live Cattle",
    "HE=F": "Lean Hogs",
    "RB=F": "RBOB Gasoline",
    "HO=F": "Heating Oil",
}

VALID_PERIODS = [
    "1d",
    "5d",
    "1mo",
    "3mo",
    "6mo",
    "1y",
    "2y",
    "5y",
    "10y",
    "ytd",
    "max",
]

VALID_INTERVALS = [
    "1m",
    "2m",
    "5m",
    "15m",
    "30m",
    "60m",
    "90m",
    "1h",
    "1d",
    "5d",
    "1wk",
    "1mo",
    "3mo",
]


class YahooFuturesConnector:
    """Connector for commodity futures data via Yahoo Finance.

    Uses the yfinance library to fetch real-time and historical prices
    for weather-sensitive commodity futures.

    Args:
        tickers: Dict of ticker symbols to descriptions, or a list of
                 ticker strings. Uses DEFAULT_TICKERS if not specified.
        auto_adjust: Whether to auto-adjust for splits/dividends.

    Example:
        >>> yf = YahooFuturesConnector(tickers=["CL=F", "NG=F", "OJ=F"])
        >>> current = yf.current_price()
        >>> history = yf.history(period="2y")
    """

    def __init__(
        self,
        tickers: dict[str, str] | list[str] | None = None,
        auto_adjust: bool = True,
    ) -> None:
        if tickers is None:
            self.tickers = dict(DEFAULT_TICKERS)
        elif isinstance(tickers, list):
            self.tickers = {t: t for t in tickers}
        else:
            self.tickers = dict(tickers)
        self.auto_adjust = auto_adjust
        self._yf: Any | None = None

    def _get_yf(self) -> Any:
        """Lazy import of yfinance."""
        if self._yf is not None:
            return self._yf
        try:
            import yfinance as yf

            self._yf = yf
            return yf
        except ImportError as exc:
            raise ImportError("yfinance is required. Install with: pip install yfinance") from exc

    def current_price(self) -> pd.DataFrame:
        """Get the current price for all tickers.

        Returns:
            DataFrame with columns: ticker, price, change, change_pct,
            volume, market_time.
        """
        yf = self._get_yf()
        records: list[dict[str, Any]] = []
        for ticker_symbol in self.tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                hist = ticker.history(period="2d")
                if hist.empty or len(hist) < 1:
                    logger.warning("No data for %s", ticker_symbol)
                    continue

                last = hist.iloc[-1]
                price = float(last["Close"])
                prev = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else price
                change = price - prev
                change_pct = (change / prev * 100) if prev != 0 else 0.0
                volume = int(last.get("Volume", 0))

                records.append(
                    {
                        "ticker": ticker_symbol,
                        "name": self.tickers.get(ticker_symbol, ticker_symbol),
                        "price": price,
                        "change": change,
                        "change_pct": change_pct,
                        "volume": volume,
                        "market_time": hist.index[-1],
                    }
                )
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", ticker_symbol, exc)
                continue

        if not records:
            raise RuntimeError("No price data could be fetched for any ticker")
        return pd.DataFrame(records)

    def history(
        self,
        period: str = "2y",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical price data for all tickers.

        Args:
            period: Time period — "1d", "5d", "1mo", "3mo", "6mo",
                    "1y", "2y", "5y", "10y", "ytd", "max".
            interval: Data interval — "1d", "1wk", "1mo", etc.
            start: Start date "YYYY-MM-DD" (overrides period if both given).
            end: End date "YYYY-MM-DD".

        Returns:
            Dict mapping ticker symbol to DataFrame with OHLCV data.
        """
        if period not in VALID_PERIODS and start is None:
            raise ValueError(f"Invalid period '{period}'. Valid: {VALID_PERIODS}")
        if interval not in VALID_INTERVALS:
            raise ValueError(f"Invalid interval '{interval}'. Valid: {VALID_INTERVALS}")

        yf = self._get_yf()
        result: dict[str, pd.DataFrame] = {}
        for ticker_symbol in self.tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                if start is not None:
                    df = ticker.history(
                        start=start, end=end, interval=interval, auto_adjust=self.auto_adjust
                    )
                else:
                    df = ticker.history(
                        period=period, interval=interval, auto_adjust=self.auto_adjust
                    )
                if df.empty:
                    logger.warning("Empty history for %s", ticker_symbol)
                    continue
                result[ticker_symbol] = df
            except Exception as exc:
                logger.warning("Failed to fetch history for %s: %s", ticker_symbol, exc)
                continue

        if not result:
            raise RuntimeError("No historical data could be fetched")
        return result

    def latest(self) -> dict[str, float]:
        """Get the latest closing price for each ticker.

        Returns:
            Dict mapping ticker symbol to latest price.
        """
        yf = self._get_yf()
        prices: dict[str, float] = {}
        for ticker_symbol in self.tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                hist = ticker.history(period="1d")
                if not hist.empty:
                    prices[ticker_symbol] = float(hist["Close"].iloc[-1])
            except Exception as exc:
                logger.warning("Latest price failed for %s: %s", ticker_symbol, exc)
                continue
        return prices

    def spread(
        self,
        ticker_long: str,
        ticker_short: str,
        period: str = "1y",
    ) -> pd.Series:
        """Compute the price spread between two tickers.

        Useful for inter-commodity spreads (e.g. crack spread components).

        Args:
            ticker_long: Long leg ticker.
            ticker_short: Short leg ticker.
            period: History period.

        Returns:
            pd.Series of spread values indexed by date.
        """
        history = self.history(period=period)
        if ticker_long not in history:
            raise KeyError(f"{ticker_long} not in fetched data")
        if ticker_short not in history:
            raise KeyError(f"{ticker_short} not in fetched data")

        long_close = history[ticker_long]["Close"]
        short_close = history[ticker_short]["Close"]
        spread = long_close - short_close
        spread.name = f"{ticker_long} - {ticker_short}"
        return spread

    def __repr__(self) -> str:
        tickers_str = ", ".join(self.tickers.keys())
        return f"YahooFuturesConnector(tickers=[{tickers_str}])"
