#!/usr/bin/env python3
"""WS-0 T3: build roll-adjusted continuous OJ series with provenance.

Inputs:
    data/market/OJ_F_daily.parquet      Yahoo continuous front-month (adjusted)
    data/market/OJ_F_daily_raw.parquet  Yahoo raw chain (auto_adjust=False)
    data/market/oj_contract_calendar.csv ICE roll calendar

Outputs:
    data/market/oj_continuous.parquet       back-adjusted series
    data/market/oj_roll_provenance.csv      per-roll provenance + flags
    data/market/oj_roll_assertions.csv      flagged moves near roll dates
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pakhi.ws0.roll import back_adjust, roll_jump_assertion

HERE = Path(__file__).resolve().parent.parent
MARKET = HERE / "data" / "market"


def main() -> None:
    cal = pd.read_csv(MARKET / "oj_contract_calendar.csv")
    raw = pd.read_parquet(MARKET / "OJ_F_daily_raw.parquet")
    raw["Date"] = pd.to_datetime(raw["Date"])
    series = raw.set_index("Date")["Close"].sort_index().dropna()
    series.index = series.index.tz_localize(None)

    out = back_adjust(series, cal, roll_rule="FND", n_sigma=5.0, sigma_window=30)
    out.prices.name = "close_adj"
    adj = pd.DataFrame(out.prices)
    adj["close_raw"] = out.raw
    adj.to_parquet(MARKET / "oj_continuous.parquet")

    prov = out.provenance_frame()
    prov.to_csv(MARKET / "oj_roll_provenance.csv", index=False)

    flags = roll_jump_assertion(
        series, pd.to_datetime(cal["first_notice_day"]), n_sigma=5.0, window_days=3
    )
    flags.to_csv(MARKET / "oj_roll_assertions.csv", index=False)

    print(f"series: {len(series)} rows  {series.index.min().date()} -> {series.index.max().date()}")
    print(f"rolls in window: {len(prov)}   flagged: {prov['flagged'].sum() if len(prov) else 0}")
    if not flags.empty:
        print(f"assertions flagged: {len(flags)}")
        print(flags.head(10).to_string(index=False))
    else:
        print("assertions flagged: 0")
    print(
        f"largest adj-vs-raw drift: {float((adj['close_adj'] - adj['close_raw']).abs().max()):.3f}"
    )


if __name__ == "__main__":
    main()
