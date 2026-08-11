#!/usr/bin/env python3
"""WS-0 T1 exit criterion / G0 pre-check: FreezeSignal on the real PIT frame.

Runs the existing FreezeSignal over every PIT row and compares forward OJ
returns after freeze signals vs all-clear days. This is the honest test of the
"15-40% OJ spike within 48h of freeze" docstring claim.

Outputs a printed verdict + data/ws0/freeze_signal_eval.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pakhi.signals.base import Action
from pakhi.signals.freeze import FreezeSignal

HERE = Path(__file__).resolve().parent.parent
WS0 = HERE / "data" / "ws0"


def main() -> None:
    pit = pd.read_parquet(WS0 / "freeze_pit.parquet")
    if pit.empty:
        print("PIT frame empty — nothing to evaluate yet.")
        return

    sig = FreezeSignal(entry_threshold=0.6, exit_threshold=0.2)
    rows = []
    for _, r in pit.iterrows():
        forecast = {
            "freeze_prob": float(r["freeze_prob"]),
            "event_peak_time": r["event_peak_time"],
            "temperature_min": float(r["temperature_min"]),
            "current_time": r["publish_time"],
        }
        signal = sig.generate(forecast)
        rows.append(
            {
                "date": r["date"],
                "action": signal.action.value,
                "confidence": signal.confidence,
                "fwd_return": float(r["fwd_return"]),
                "freeze_prob": float(r["freeze_prob"]),
                "t2m_min_c": float(r["temperature_min"]),
            }
        )

    ev = pd.DataFrame(rows)
    ev.to_csv(WS0 / "freeze_signal_eval.csv", index=False)

    n_long = (ev["action"] == Action.LONG.value).sum()
    n_flat = (ev["action"] == Action.FLAT.value).sum()
    print(f"PIT days: {len(ev)}   LONG signals: {n_long}   FLAT: {n_flat}")

    if n_long:
        long_ret = ev.loc[ev["action"] == Action.LONG.value, "fwd_return"]
        print(f"LONG days mean fwd return: {long_ret.mean() * 100:+.2f}%  (n={len(long_ret)})")
    flat = ev.loc[ev["action"] == Action.FLAT.value, "fwd_return"]
    print(f"FLAT days mean fwd return:  {flat.mean() * 100:+.2f}%  (n={len(flat)})")

    cold = ev[ev["freeze_prob"] > 0.0]
    print(
        f"\nany sub-freezing cells forecast: {len(cold)} days "
        f"(max freeze_prob={cold['freeze_prob'].max() if len(cold) else 0:.3f})"
    )
    top = ev.nlargest(8, "fwd_return")
    print("\nlargest forward OJ moves:")
    print(top[["date", "freeze_prob", "t2m_min_c", "fwd_return"]].to_string(index=False))

    verdict = (
        "REFUTED-dormant: no sub-freezing forecasts, signal never fires"
        if n_long == 0
        else "INCONCLUSIVE"
    )
    print(f"\nVERDICT: {verdict}")


if __name__ == "__main__":
    main()
