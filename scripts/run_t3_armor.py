#!/usr/bin/env python3
"""WS-1 T3: run the full Lookahead Armor (timestamp + vintage) and fail loudly.

The two gates behind Evaluation Contract §9.1/§9.2:

- **Timestamp layer** — no PIT feature references data published after its
  executable decision cutoff (the ICE OJ 14:00 America/New_York close of the
  v1.1 fill session), the 48 h feature window is respected, and feature
  columns are separated from outcome columns.
- **Vintage layer** — every feature traces to the as-published
  ``noaa-gfs-bdp-pds`` archive; the pinned per-cycle content hash must match
  the raw bytes currently on disk (archive drift ⇒ rewritten data ⇒ fail).

Any violation ⇒ exit code 1 (the run is INVALID, contract §9).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pakhi.ws1.armor import (
    GFS,
    MANIFEST_PATH,
    LookaheadError,
    build_vintage_manifest,
    run_armor,
)
from pakhi.ws1.pit import load_oj, load_pit

HERE = Path(__file__).resolve().parent.parent
MARKET = HERE / "data" / "market"
WS0 = HERE / "data" / "ws0"


def main() -> None:
    if not MANIFEST_PATH.exists():
        print("building vintage manifest ->", MANIFEST_PATH)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(build_vintage_manifest(GFS), indent=1))

    pit = load_pit()
    sessions = load_oj().index

    try:
        summary = run_armor(pit, sessions, manifest=None, gfs_dir=GFS)
    except LookaheadError as exc:
        print("LOOKAHEAD ARMOR FAILED:", exc)
        sys.exit(1)

    ts, vg = summary["timestamp"], summary["vintage"]
    print("T3 Lookahead Armor: PASS")
    print(
        f"  timestamp: {ts['n_rows']} rows | publish-after-cutoff {ts['publish_after_cutoff']} | "
        f"min margin {ts['min_publish_margin_hours']:.2f}h | horizon {ts['event_peak_outside_horizon']} violations | "
        f"feature/outcome separated {ts['feature_outcome_separation']}"
    )
    print(
        f"  vintage  : {vg['archive']} | {vg['n_cycles_in_manifest']}/{vg['n_pit_cycles']} cycles | "
        f"source match {vg['source_match']} | hash drift {vg['n_hash_drift']}"
    )
    print(f"  manifest : {MANIFEST_PATH} ({vg['recorded_utc']})")
    sys.exit(0)


if __name__ == "__main__":
    main()
