#!/usr/bin/env python3
"""WS-0 T4: build the point-in-time freeze frame (features | outcome).

For every trading day with an as-published 12Z GFS cycle in data/gfs/:

  decision cutoff : GFS publish time (~15:35 UTC of date D)
  features        : freeze features from the D 12Z cycle (0-48h horizon)
  outcome         : OJ front-month return close[D+1]/close[D] - 1

Outputs data/ws0/freeze_pit.parquet with columns:
  date, cycle, publish_time, temperature_min, freeze_prob, grid_cells,
  horizon_cells, ojd_close, ojd_next_close, fwd_return
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from pakhi.ws0.features import freeze_features

HERE = Path(__file__).resolve().parent.parent
GFS = HERE / "data" / "gfs"
MARKET = HERE / "data" / "market"
OUT = HERE / "data" / "ws0"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adj = pd.read_parquet(MARKET / "oj_continuous.parquet").reset_index()
    adj["Date"] = pd.to_datetime(adj["Date"])
    px = adj.set_index("Date")["close_adj"].sort_index()
    ojd = px.resample("D").last().ffill()

    files = sorted(GFS.glob("gfs_*_12z_f000.parquet"))
    rows = []
    for f in files:
        cycle_date = pd.Timestamp(f.name.split("_")[1])
        frame = pd.read_parquet(f)
        feats = freeze_features(frame)
        nxt = ojd.index[ojd.index > cycle_date]
        if nxt.empty:
            continue
        next_close = float(ojd.loc[nxt[0]])
        cur = float(ojd.get(cycle_date, np.nan))
        if np.isnan(cur):
            continue
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
            }
        )

    pit = pd.DataFrame(rows)
    pit.to_parquet(OUT / "freeze_pit.parquet", index=False)
    print(f"PIT rows: {len(pit)}  {pit['date'].min()} -> {pit['date'].max()}" if len(pit) else "PIT rows: 0")
    if len(pit) >= 2:
        cold = pit[pit["freeze_prob"] > 0.2]
        hot = pit[pit["freeze_prob"] == 0]
        print(f"freeze_prob>0.2: {len(cold)} rows | all-clear: {len(hot)} rows")
        print("mean fwd return | freeze_prob>0.2: "
              f"{cold['fwd_return'].mean()*100:+.2f}%  all-clear: {hot['fwd_return'].mean()*100:+.2f}%"
              if len(cold) >= 2 else "not enough cold rows")
        if len(cold):
            print(cold.nlargest(5, "fwd_return")[["date", "temperature_min", "freeze_prob", "fwd_return"]].to_string(index=False))


if __name__ == "__main__":
    main()
