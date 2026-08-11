"""WS-0 backfill: as-published GFS archive for the wedge bbox (parallel).

Downloads per-cycle, per-lead GRIB2 messages from the NOAA AWS as-published
archive (byte-range extraction), subsets to the wedge bounding box, and stores
one Parquet per cycle-lead. A worker pool parallelizes across cycles.

Resumable: existing Parquet files are skipped. Re-run to continue.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pakhi.src.noaa import GFSConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ws0.backfill")

FLORIDA_BBOX = [-85.0, 24.0, -80.0, 31.0]  # wide FL: captures north-FL hard freezes
WS0_VARIABLES = [
    "temperature_2m",
    "wind_10m",
    "msl_pressure",
    "geopotential_500",
    "temperature_850",
    "precipitation",
]


def _bbox_tag(bbox: list[float]) -> str:
    return f"W{bbox[1]:g}S{bbox[0]:g}E{bbox[3]:g}N{bbox[2]:g}".replace(".", "_")


_worker_conn = None


def _new_conn(bbox, resolution, variables) -> GFSConnector:
    return GFSConnector(
        variables=variables,
        bbox=bbox,
        resolution=resolution,
        timeout=60,
        max_retries=3,
        retry_delay=2.0,
    )


def _worker_init(bbox, resolution, variables):
    """Per-worker state: one long-lived connector (reuses connections / DNS)."""
    global _worker_conn
    _worker_conn = _new_conn(bbox, resolution, variables)


def _work(args: tuple) -> dict | None:
    global _worker_conn
    date_str, cycle_str, lead, bbox, resolution, variables, out, retries = args
    tag = _bbox_tag(bbox)
    parquet = Path(out) / f"gfs_{date_str}_{cycle_str}z_f{lead:03d}_{tag}.parquet"
    if parquet.exists() and parquet.stat().st_size > 0:
        return None
    t0 = time.time()
    for attempt in range(1, retries + 1):
        conn = _worker_conn
        try:
            ds = conn._fetch_archive_cycle(date_str, cycle_str, lead)
            ds = conn._subset_bbox(ds)
            df = ds.to_dataframe().reset_index()
            df["date"] = date_str
            df["cycle"] = cycle_str
            df["lead"] = lead
            df.to_parquet(parquet)
            return {
                "date": date_str,
                "cycle": cycle_str,
                "lead": lead,
                "file": parquet.name,
                "source": "aws",
                "vars": ",".join(sorted(ds.data_vars)),
                "grid_lat": ds.sizes.get("latitude", 0),
                "grid_lon": ds.sizes.get("longitude", 0),
                "nbytes": parquet.stat().st_size,
                "fetch_s": round(time.time() - t0, 1),
            }
        except Exception as exc:
            try:
                conn.close()
            finally:
                _worker_conn = _new_conn(bbox, resolution, variables)
            if attempt < retries:
                backoff = min(5.0 * 2 ** (attempt - 1), 60.0)
                time.sleep(backoff)
            else:
                logger.warning("MISS %s %sZ f%03d — %s", date_str, cycle_str, lead, exc)
                return {"date": date_str, "cycle": cycle_str, "lead": lead, "file": "", "source": "MISS", "nbytes": 0}
    return None  # pragma: no cover


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--cycles", default="12", help="Comma-separated cycles, e.g. 0,12")
    parser.add_argument("--leads", default="0,12,24,48", help="Comma-separated forecast hours")
    parser.add_argument("--bbox", default=",".join(map(str, FLORIDA_BBOX)), help="w,s,e,n")
    parser.add_argument("--resolution", default="0p50", choices=["0p25", "0p50", "1p00"])
    parser.add_argument("--out", default="data/gfs", help="Output directory")
    parser.add_argument("--inventory", default="data/gfs/cycle_inventory.csv", help="Inventory CSV")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=6, help="Whole-job retry attempts w/ backoff")
    args = parser.parse_args()

    cycles = [c.strip().zfill(2) for c in args.cycles.split(",") if c.strip()]
    leads = [int(x) for x in args.leads.split(",")]
    bbox = [float(x) for x in args.bbox.split(",")]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inventory_path = Path(args.inventory)

    dates = pd.date_range(args.start, args.end, freq="D")
    jobs = [(d.strftime("%Y%m%d"), c, lead, bbox, args.resolution, WS0_VARIABLES, str(out), args.retries)
            for d in dates for c in cycles for lead in leads]
    existing = {f.name for f in out.glob("gfs_*.parquet")}
    jobs = [
        j
        for j in jobs
        if f"gfs_{j[0]}_{j[1]}z_f{j[2]:03d}_{_bbox_tag(bbox)}.parquet" not in existing
    ]
    total = len(jobs)
    logger.info("Jobs to fetch: %d (skipping %d existing parquets)", total, len(existing))

    if total == 0:
        return

    from multiprocessing import Pool

    rows = []
    t_start = time.time()
    with Pool(args.workers, initializer=_worker_init, initargs=(bbox, args.resolution, WS0_VARIABLES)) as pool:
        for i, row in enumerate(pool.imap_unordered(_work, jobs), 1):
            if row is not None:
                rows.append(row)
            if i % 50 == 0 or i == total:
                rate = i / (time.time() - t_start)
                mb = sum(r["nbytes"] for r in rows) / 1e6
                logger.info("%d/%d cycles (%.2f cycles/s, %.1f MB)", i, total, rate, mb)

    pd.DataFrame(rows).to_csv(inventory_path, index=False)
    n_ok = sum(1 for r in rows if r["source"] != "MISS")
    n_miss = len(rows) - n_ok
    logger.info(
        "Backfill finished: %d OK, %d MISS, %.1f MB, %.1f min",
        n_ok,
        n_miss,
        sum(r["nbytes"] for r in rows) / 1e6,
        (time.time() - t_start) / 60,
    )


if __name__ == "__main__":
    main()
