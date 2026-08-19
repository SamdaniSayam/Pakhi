#!/usr/bin/env python3
"""Refresh raw daily futures chains for all Yahoo-sourced evaluation instruments.

Downloads OJ=F, ZC=F (Corn), NG=F (NatGas), ZW=F (Wheat) from Yahoo and writes
a per-instrument raw parquet into ``data/market/``. ERCOT has no Yahoo ticker
(``price_source="ercot_settlement"``) and is skipped with a clear notice; its
price feed is a Phase 1B deliverable and must not be fabricated.

This is the Contract V2 (S1) multi-instrument feed. It supersedes
``scripts/refresh_oj.py`` for the broader evaluation, but is NOT yet wired into
the live daily wrapper (``pakhi_orchestrator_run.sh``) — that swap happens in
Phase 1B once the continuous-series rebuild covers all instruments. Running it
manually is safe and idempotent (overwrites the regenerable raw parquets).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Ensure this repo's own `pakhi` package takes precedence over any editable
# install (e.g. Pakhi-private) so the script runs against the code it ships
# with, not whatever `import pakhi` happens to resolve to in the environment.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pakhi.src.yahoo import YahooFuturesConnector
from pakhi.ws1.instruments import INSTRUMENTS, YAHOO_TICKERS

MARKET = Path("/home/megalith/Desktop/pakhi/data/market")


def _slug(ticker: str) -> str:
    # Keep the legacy "_F" futures suffix (e.g. OJ=F -> OJ_F) so the output
    # matches what build_continuous.py / the live pipeline already expect.
    return ticker.replace("=", "_")


def main() -> None:
    MARKET.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tickers = list(YAHOO_TICKERS.values())
    yf = YahooFuturesConnector(tickers=tickers, auto_adjust=False)
    hist = yf.history(start="2015-01-01", end=end, interval="1d")

    for key, ticker in YAHOO_TICKERS.items():
        if ticker not in hist:
            print(f"WARN: no {ticker} ({key}) history returned from Yahoo")
            continue
        df = hist[ticker].copy().reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
        df["Date"] = pd.to_datetime(df["Date"])
        df = (
            df[["Date", "Open", "High", "Low", "Close", "Volume"]]
            .dropna(subset=["Close"])
            .sort_values("Date")
        )
        out = MARKET / f"{_slug(ticker)}_daily_raw.parquet"
        df.to_parquet(out, index=False)
        print(
            f"wrote {out}: {len(df)} rows, "
            f"{df['Date'].min().date()} -> {df['Date'].max().date()}"
        )

    for key, inst in INSTRUMENTS.items():
        if inst.price_source != "yahoo":
            print(
                f"SKIP {key} ({inst.ticker}): price_source={inst.price_source} "
                f"is not Yahoo — feed pending (Phase 1B)"
            )


if __name__ == "__main__":
    main()
