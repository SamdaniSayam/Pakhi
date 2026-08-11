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


def _run(name: str, script: str, *extra: str) -> dict:
    cmd = [sys.executable, str(SCRIPTS / script), *extra]
    res = subprocess.run(cmd, capture_output=True, text=True)
    ok = res.returncode == 0
    out = (res.stdout or "").strip() or (res.stderr or "").strip()
    tail = out.splitlines()[-1] if out else ""
    return {"script": script, "rc": res.returncode, "tail": tail}


def _parse_unit(name: str) -> tuple[str, str, int]:
    body = name.replace("gfs_", "", 1)
    date_s, cycle_s, fpart = body.split("_")[0], body.split("_")[1], body.split("_f")[1]
    return date_s, cycle_s.rstrip("z"), int(fpart[:3])


def _units_from_files() -> set:
    units = set()
    for p in GFS.glob("gfs_*.parquet"):
        try:
            units.add(_parse_unit(p.name))
        except (IndexError, ValueError):
            continue
    return units


def _refresh_inventory() -> pd.DataFrame:
    rows = []
    for p in sorted(GFS.glob("gfs_*.parquet")):
        name = p.name
        date_s, cycle_s, lead = _parse_unit(name)
        rows.append(
            {
                "date": date_s,
                "cycle": cycle_s,
                "lead": lead,
                "file": name,
                "source": "aws",
                "nbytes": p.stat().st_size,
            }
        )
    inv = pd.DataFrame(rows)
    inv.to_csv(GFS / "cycle_inventory.csv", index=False)
    return inv


def gate_completeness(inv: pd.DataFrame) -> tuple[bool, str]:
    have = _units_from_files()
    if not have:
        return False, "no parquet files on disk"
    want = set()
    for d in pd.date_range(BACKFILL["start"], BACKFILL["end"], freq="D"):
        for c in BACKFILL["cycles"].split(","):
            for lead in BACKFILL["leads"].split(","):
                want.add((d.strftime("%Y%m%d"), c.zfill(2), int(lead)))
    missing = want - have
    if missing:
        return False, f"missing {len(missing)} (date,cycle,lead) units: " + str(sorted(missing)[:3])
    return True, f"all {len(have)} units present on disk"


def gate_schema(inv: pd.DataFrame) -> tuple[bool, str]:
    req = {"latitude", "longitude", "valid_time", "t2m"}
    n = 0
    for p in sorted(GFS.glob("gfs_*.parquet")):
        n += 1
        try:
            df = pd.read_parquet(p)
        except Exception as exc:
            return False, f"{p.name}: unreadable ({exc})"
        if df.empty:
            return False, f"{p.name}: empty frame"
        if not req <= set(df.columns):
            return False, f"{p.name}: missing cols {req - set(df.columns)}"
        if df["t2m"].isna().any() or not df["t2m"].between(200, 330).all():
            return False, f"{p.name}: t2m out of range"
        if df["latitude"].nunique() < 8:
            return False, f"{p.name}: too few latitudes"
    return True, f"{n} files pass schema/range checks"


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
    # Deterministic rebuild steps. Backfill skips existing files (resumable).
    steps = [
        _run("backfill", "backfill_gfs.py", "--start", BACKFILL["start"], "--end", BACKFILL["end"],
             "--out", str(GFS), "--inventory", str(GFS / "cycle_inventory.csv"),
             "--cycles", BACKFILL["cycles"], "--leads", BACKFILL["leads"],
             "--bbox=" + BACKFILL["bbox"], "--resolution", BACKFILL["resolution"],
             "--workers", "8", "--retries", "6"),
        _run("continuous", "build_continuous.py"),
        _run("pit", "build_pit.py"),
    ]
    inv = _refresh_inventory()  # full provenance inventory from files on disk
    raw_inv = inv.copy()

    gates = {
        "completeness": gate_completeness(raw_inv),
        "schema": gate_schema(inv),
        "staleness": gate_staleness(raw_inv),
        "pit": gate_pit(),
    }
    manifest = {
        "generated_utc": pd.Timestamp.now("UTC").isoformat(),
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
