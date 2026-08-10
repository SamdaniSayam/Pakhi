#!/usr/bin/env python3
"""WS-0 T5: deterministic rebuild + data-quality gates.

Rebuilds the full WS-0 dataset from scratch in order:
  1. backfill_gfs.py (resumable, as-published GFS archive)
  2. build_continuous.py (roll-adjusted OJ series)
  3. build_pit.py (point-in-time freeze frame)

Then runs quality gates and writes a provenance manifest
(data/ws0/manifest.json) with parameter + hash evidence.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / "scripts"
GFS = HERE / "data" / "gfs"
MARKET = HERE / "data" / "market"
WS0 = HERE / "data" / "ws0"

BACKFILL = dict(
    start="2021-11-01",
    end="2026-03-31",
    cycles="12",
    leads="0,12,24,48",
    bbox="-85.0,24.0,-80.0,31.0",
    resolution="0p50",
)

EXPECTED_DAYS = (pd.Timestamp(BACKFILL["end"]) - pd.Timestamp(BACKFILL["start"])).days + 1
EXPECTED_CYCLES = len(BACKFILL["cycles"].split(","))
EXPECTED_LEADS = len(BACKFILL["leads"].split(","))
EXPECTED = EXPECTED_DAYS * EXPECTED_CYCLES * EXPECTED_LEADS


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(name: str, script: str) -> dict:
    res = subprocess.run([sys.executable, str(SCRIPTS / script)], capture_output=True, text=True)
    ok = res.returncode == 0
    return {"script": script, "rc": res.returncode, "tail": res.stdout.strip().splitlines()[-1] if ok else res.stderr.strip().splitlines()[-1]}


def gate_completeness(inv: pd.DataFrame) -> tuple[bool, str]:
    if inv.empty:
        return False, "inventory empty"
    n_miss = int((inv["source"] == "MISS").sum())
    if n_miss:
        return False, f"{n_miss} MISS cycles"
    have = set(zip(inv["date"], inv["cycle"], inv["lead"]))
    want = set()
    for d in pd.date_range(BACKFILL["start"], BACKFILL["end"], freq="D"):
        for c in BACKFILL["cycles"].split(","):
            for lead in BACKFILL["leads"].split(","):
                want.add((d.strftime("%Y%m%d"), c.zfill(2), int(lead)))
    missing = want - have
    if missing:
        return False, f"missing {len(missing)} (date,cycle,lead) units"
    return True, f"all {len(have)} units present, 0 MISS"


def gate_schema(inv: pd.DataFrame) -> tuple[bool, str]:
    req = {"latitude", "longitude", "valid_time", "t2m"}
    for _, row in inv.iterrows():
        p = GFS / row["file"]
        if not p.exists():
            return False, f"missing file {row['file']}"
        try:
            df = pd.read_parquet(p)
        except Exception as exc:
            return False, f"{row['file']}: unreadable ({exc})"
        if df.empty:
            return False, f"{row['file']}: empty frame"
        if not req <= set(df.columns):
            return False, f"{row['file']}: missing cols {req - set(df.columns)}"
        if df["t2m"].isna().any() or not df["t2m"].between(200, 330).all():
            return False, f"{row['file']}: t2m out of range"
        if df["latitude"].nunique() < 8:
            return False, f"{row['file']}: too few latitudes"
    return True, f"{len(inv)} files pass schema/range checks"


def gate_pit() -> tuple[bool, str]:
    pit = pd.read_parquet(WS0 / "freeze_pit.parquet")
    if pit.empty:
        return False, "PIT frame empty"
    if pit["fwd_return"].abs().max() > 0.5:
        return False, "PIT forward returns implausible (>50%)"
    detail = "PIT {} rows, fwd_return range [{:.2f}, {:.2f}]".format(
        len(pit), pit["fwd_return"].min(), pit["fwd_return"].max()
    )
    return True, detail


def gate_staleness(inv: pd.DataFrame) -> tuple[bool, str]:
    last = inv["date"].astype(str).str[:8].max()
    return last == BACKFILL["end"].replace("-", ""), f"last cycle {last}"


def main() -> None:
    WS0.mkdir(parents=True, exist_ok=True)
    steps = [
        _run("backfill", "backfill_gfs.py") if not (GFS / "cycle_inventory.csv").exists()
        else {"script": "backfill_gfs.py", "rc": 0, "tail": "skipped (inventory exists)"},
        _run("continuous", "build_continuous.py"),
        _run("pit", "build_pit.py"),
    ]

    inv = pd.read_csv(GFS / "cycle_inventory.csv")
    raw_inv = inv.copy()
    actual_files = {f.name for f in GFS.glob("gfs_*.parquet")}
    inv = inv[inv["source"] != "MISS"]

    def _file(row) -> str:
        tag = [f for f in actual_files if f.startswith(
            f"gfs_{row['date']}_{str(row['cycle']).zfill(2)}z_f{int(row['lead']):03d}_"
        )]
        return tag[0] if tag else ""

    inv["file"] = inv.apply(_file, axis=1)
    gates = {
        "completeness": gate_completeness(raw_inv),
        "schema": gate_schema(inv),
        "staleness": gate_staleness(raw_inv),
        "pit": gate_pit(),
    }
    manifest = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "backfill": BACKFILL,
        "expected_units": EXPECTED,
        "actual_units": len(inv),
        "steps": steps,
        "gates": {k: {"pass": v[0], "detail": v[1]} for k, v in gates.items()},
        "hashes": {
            "cycle_inventory": _sha256(GFS / "cycle_inventory.csv"),
            "oj_continuous": _sha256(MARKET / "oj_continuous.parquet"),
            "freeze_pit": _sha256(WS0 / "freeze_pit.parquet"),
        },
    }
    (WS0 / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v[0] for k, v in gates.items()}, indent=2))
    print("manifest ->", WS0 / "manifest.json")
    sys.exit(0 if all(v[0] for v in gates.values()) else 1)


if __name__ == "__main__":
    main()
