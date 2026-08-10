#!/usr/bin/env python3
"""WS-0 T6: G0 evidence tables — freeze feature vs OJ outcomes on real PIT data.

Reads the full-window PIT frame (data/ws0/freeze_pit.parquet) and reports:
  1. freeze_prob distribution per freeze season (Nov-Mar)
  2. how often the freeze signal fires (LONG vs FLAT)
  3. forward OJ returns conditioned on freeze_prob buckets
  4. the flagship events (Jan-2022 freeze, Apr/Jul-2025, Sep-2024) callouts
  5. effect size: Spearman(freeze_prob, fwd_return) + LONG-vs-FLAT t-test

Writes data/ws0/g0_evidence.csv. A companion doc (docs/WS0_G0_REPORT.md) is
filled from the printed output.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats

from pakhi.signals.base import Action
from pakhi.signals.freeze import FreezeSignal

HERE = Path(__file__).resolve().parent.parent
WS0 = HERE / "data" / "ws0"


def season(d: pd.Timestamp) -> str:
    """Freeze season label (Nov of year N -> season 'N/N+1')."""
    m = d.month
    y = d.year
    if m >= 11:
        return f"{y}/{y + 1}"
    if m <= 3:
        return f"{y - 1}/{y}"
    return f"{y}/{y + 1} (off-season)"


def main() -> None:
    pit = pd.read_parquet(WS0 / "freeze_pit.parquet")
    pit["date"] = pd.to_datetime(pit["date"])
    pit["season"] = pit["date"].apply(season)
    if pit.empty:
        print("PIT frame empty.")
        return

    print("=== 1. freeze_prob per season (wide-FL bbox) ===")
    seas = pit.groupby("season")["freeze_prob"].agg(["count", "mean", "max", lambda s: (s > 0).sum()])
    seas.columns = ["days", "mean_prob", "max_prob", "days_with_freeze"]
    print(seas.to_string())

    sig = FreezeSignal(entry_threshold=0.6, exit_threshold=0.2)
    actions = []
    for _, r in pit.iterrows():
        actions.append(
            sig.generate(
                {
                    "freeze_prob": float(r["freeze_prob"]),
                    "event_peak_time": r["event_peak_time"],
                    "temperature_min": float(r["temperature_min"]),
                    "current_time": r["publish_time"],
                }
            ).action.value
        )
    pit["action"] = actions

    print("\n=== 2. signal firing ===")
    print(pit["action"].value_counts().to_string())

    print("\n=== 3. fwd return by freeze_prob bucket ===")
    pit["bucket"] = pd.cut(
        pit["freeze_prob"],
        bins=[-1e-9, 0.0, 0.05, 0.2, 0.5, 1.01],
        labels=["none", "trace(0-5%)", "low(5-20%)", "mid(20-50%)", "high(50%+)"],
    )
    b = pit.groupby("bucket", observed=True)["fwd_return"].agg(["count", "mean", "std"])
    print(b.to_string())

    print("\n=== 4. flagship events ===")
    flags = ["2022-01-29", "2022-01-30", "2025-07-08", "2025-07-10", "2025-04-14", "2025-10-23", "2024-09-06"]
    ev = pit[pit["date"].dt.strftime("%Y-%m-%d").isin(flags)]
    if ev.empty:
        print("  (dates fall on weekends/non-trading days or not yet backfilled)")
    else:
        print(ev[["date", "season", "freeze_prob", "temperature_min", "fwd_return", "action"]].to_string(index=False))

    print("\n=== 5. effect size ===")
    rho, pval = stats.spearmanr(pit["freeze_prob"], pit["fwd_return"])
    print(f"Spearman(freeze_prob, fwd_return) = {rho:+.3f}  (p={pval:.3f})")
    longs = pit.loc[pit["action"] == Action.LONG.value, "fwd_return"]
    flats = pit.loc[pit["action"] == Action.FLAT.value, "fwd_return"]
    if len(longs) and len(flats):
        t, tp = stats.ttest_ind(longs, flats, equal_var=False)
        print(f"LONG n={len(longs)} mean={longs.mean()*100:+.2f}% | FLAT n={len(flats)} mean={flats.mean()*100:+.2f}% | t={t:+.2f} (p={tp:.3f})")
    else:
        print("no LONG signals — signal never fired")

    pit.to_csv(WS0 / "g0_evidence.csv", index=False)
    print("\n-> data/ws0/g0_evidence.csv")


if __name__ == "__main__":
    main()
