#!/usr/bin/env python3
"""WS-2 T2 CLI: compute the frozen-θ ColdGrip signal for an ingested cycle.

Usage:
    python scripts/run_ws2_t2_compute.py                       # latest ingested cycle
    python scripts/run_ws2_t2_compute.py --cycle 20260812_12z  # explicit cycle
    python scripts/run_ws2_t2_compute.py --db sqlite:///data/ws2/paper.db

Reads the T1 ingest record (``data/ws2/ingested/<cycle>/cycle.json``), runs the
frozen-θ gate with the stored-vs-offline equivalence check, and UPSERTs the
forecast-cycle / signal / paper-ledger rows into the configured database.

Exit 0 on a clean compute (equivalence gate PASS); 1 on EquivalenceError /
RejectCycleError / any loud failure — never a silent drop.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pakhi.ws1.pit import benchmark_2sess, load_oj, load_pit
from pakhi.ws2.compute import ComputeError, compute_cycle
from pakhi.ws2.db import get_engine, init_db
from pakhi.ws2.ingest import INGESTED_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ws2.t2.compute")


def _next_episode_id(engine) -> int:
    from sqlalchemy import func, select

    from pakhi.ws2.db import PaperLedger

    with engine.connect() as conn:
        mx = conn.execute(select(func.max(PaperLedger.episode_id))).scalar()
    return int(mx) + 1 if mx is not None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cycle",
        default=None,
        help="Cycle id YYYYMMDD_12z (default: the latest ingested cycle)",
    )
    parser.add_argument(
        "--db",
        default="sqlite:///data/ws2/paper.db",
        help="SQLAlchemy URL (default: sqlite:///data/ws2/paper.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + gate only; do not write to the database",
    )
    args = parser.parse_args()

    ingested = Path(INGESTED_DIR)
    if args.cycle:
        record_path = ingested / args.cycle / "cycle.json"
    else:
        cycles = sorted(d for d in ingested.iterdir() if (d / "cycle.json").exists())
        if not cycles:
            logger.error("no ingested cycles under %s", ingested)
            return 1
        record_path = cycles[-1] / "cycle.json"
    record = json.loads(record_path.read_text())
    logger.info("computing %s (persist=%s)", record["forecast_cycle_id"], not args.dry_run)

    engine = None
    if not args.dry_run:
        engine = get_engine(args.db)
        init_db(engine)

    try:
        result = compute_cycle(
            record,
            engine=engine,
            sessions=load_oj().index,
            oj=load_oj(),
            rbar=benchmark_2sess(load_pit()),
            episode_id=_next_episode_id(engine) if engine is not None else None,
            persist=not args.dry_run,
        )
    except (ComputeError, Exception) as exc:
        logger.error("REJECT %s: %s", type(exc).__name__, exc)
        print(json.dumps({"ok": False, "cycle": record["forecast_cycle_id"], "error": str(exc)}))
        return 1

    print(json.dumps(result, indent=2, default=str))
    d = result["decision"]
    logger.info(
        "OK %s: fires=%s freeze_prob=%.4f (theta_p=%.6f) equivalence=%s",
        record["forecast_cycle_id"],
        d["fires"],
        d["freeze_prob"],
        d["theta_p"],
        d["equivalence"]["pass"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
