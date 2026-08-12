#!/usr/bin/env python3
"""WS-0 T4 / WS-1 T1: build the point-in-time freeze frame (features | outcome).

For every trading day with an as-published 12Z GFS cycle in data/gfs/:

  decision cutoff : GFS publish time (~15:35 UTC of date D)
  features        : freeze features from the D 12Z cycle (0-48h horizon)
  outcome         : OJ front-month returns over the executable fill base

**Fill-timing (v1.1, no lookahead):** the fill session is the **first trading
session on/after** the cycle date — the same-day close for trading-day cycles
(GFS publish 15:35Z precedes the OJ close) and the **next** trading-day close
(Monday) for weekend/holiday cycles.  A Saturday cycle is never filled at the
prior Friday close (that would trade on information not yet published).

Outcomes: fwd_return = close[base+1]/close[base] - 1 and
          fwd2_return = close[base+2]/close[base] - 1 (WS-1 T1: 2-session hold)

Outputs data/ws0/freeze_pit.parquet with columns:
  date, cycle, publish_time, temperature_min, freeze_prob, grid_cells,
  horizon_cells, ojd_close, ojd_next_close, fwd_return, ojd_next2_close,
  fwd2_return, source

``source`` = the as-published GFS archive bucket (``noaa-gfs-bdp-pds``),
traced per row for the T3 vintage armor.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pakhi.ws0.features import freeze_features
from pakhi.ws1.provenance import ARCHIVE

HERE = Path(__file__).resolve().parent.parent
GFS = HERE / "data" / "gfs"
MARKET = HERE / "data" / "market"
OUT = HERE / "data" / "ws0"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adj = pd.read_parquet(MARKET / "oj_continuous.parquet").reset_index()
    adj["Date"] = pd.to_datetime(adj["Date"])
    px = adj.set_index("Date")["close_adj"].sort_index()
    ojd = px  # Keep only actual trading days

    files = sorted(GFS.glob("gfs_*_12z_f000*.parquet"))
    rows = []
    for f in files:
        cycle_date = pd.Timestamp(f.name.split("_")[1])
        prefix = f.name.rsplit("f000", 1)[0]
        leads = sorted(GFS.glob(prefix + "f*.parquet"))
        frame = pd.concat([pd.read_parquet(p) for p in leads], ignore_index=True)
        feats = freeze_features(frame)

        # Fill base (v1.1): first trading session ON/AFTER the cycle date.
        # Same-day close for trading-day cycles; the NEXT trading close for
        # weekend/holiday cycles.  Never the prior Friday close.
        base = ojd.index[ojd.index >= cycle_date]

        if base.empty:
            continue

        base_date = base[0]
        after = ojd.index[ojd.index > base_date]

        if after.empty:
            continue

        cur = float(ojd.loc[base_date])
        next_close = float(ojd.loc[after[0]])
        next2_close = float(ojd.loc[after[1]]) if len(after) >= 2 else float("nan")
        rows.append(
            {
                "date": cycle_date.date(),
                "cycle": int(f.name.split("_")[2].rstrip("z")),
                "publish_time": feats["current_time"],
                "event_peak_time": feats["event_peak_time"],
                "temperature_min": feats["temperature_min"],
                "freeze_prob": feats["freeze_prob"],
                "t2m_min_k": feats["t2m_min_k"],
                "grid_cells": feats["grid_cells"],
                "horizon_cells": feats["horizon_cells"],
                "ojd_close": cur,
                "ojd_next_close": next_close,
                "fwd_return": next_close / cur - 1.0,
                "ojd_next2_close": next2_close,
                "fwd2_return": next2_close / cur - 1.0,
                "source": ARCHIVE,
            }
        )

    pit = pd.DataFrame(rows)
    pit.to_parquet(OUT / "freeze_pit.parquet", index=False)
    print(
        f"PIT rows: {len(pit)}  {pit['date'].min()} -> {pit['date'].max()}"
        if len(pit)
        else "PIT rows: 0"
    )
    missing2 = int(pit["fwd2_return"].isna().sum()) if len(pit) else 0
    print(f"2-session outcomes missing: {missing2}/{len(pit)}")
    if len(pit) >= 2:
        cold = pit[pit["freeze_prob"] > 0.2]
        hot = pit[pit["freeze_prob"] == 0]
        print(f"freeze_prob>0.2: {len(cold)} rows | all-clear: {len(hot)} rows")
        print(
            "mean fwd return | freeze_prob>0.2: "
            f"{cold['fwd_return'].mean() * 100:+.2f}%  all-clear: {hot['fwd_return'].mean() * 100:+.2f}%"
            if len(cold) >= 2
            else "not enough cold rows"
        )
        if len(cold):
            print(
                cold.nlargest(5, "fwd_return")[
                    ["date", "temperature_min", "freeze_prob", "fwd_return"]
                ].to_string(index=False)
            )


if __name__ == "__main__":
    main()
