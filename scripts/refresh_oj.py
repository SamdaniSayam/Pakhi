#!/usr/bin/env python3
"""Refresh OJ=F raw daily chain from Yahoo and rebuild the continuous series.

Keeps the live paper-trading feed fresh so the OJ-staleness armor (max 7d)
does not reject daily cycles. Invoked by ``scripts/pakhi_orchestrator_run.sh``
immediately before the WS-2 T3 orchestrator.

Writes only the raw chain; ``scripts/build_continuous.py`` (run by the wrapper)
rebuilds the back-adjusted continuous series from it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pakhi.src.yahoo import YahooFuturesConnector

MARKET = Path("/home/megalith/Desktop/pakhi/data/market")


def main() -> None:
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yf = YahooFuturesConnector(tickers=["OJ=F"], auto_adjust=False)
    hist = yf.history(start="2015-01-01", end=end, interval="1d")
    if "OJ=F" not in hist:
        raise RuntimeError("No OJ=F history returned from Yahoo")
    df = hist["OJ=F"].copy().reset_index()
    if "Date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(
        subset=["Close"]
    ).sort_values("Date")
    out = MARKET / "OJ_F_daily_raw.parquet"
    df.to_parquet(out, index=False)
    print(
        f"wrote {out}: {len(df)} rows, "
        f"{df['Date'].min().date()} -> {df['Date'].max().date()}"
    )


if __name__ == "__main__":
    main()
