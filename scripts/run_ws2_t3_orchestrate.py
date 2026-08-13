#!/usr/bin/env python3
"""WS-2 T3 CLI: orchestration & failover — daily ingest→compute→store loop.

Usage:
    python scripts/run_ws2_t3_orchestrate.py                 # live: latest 12Z cycle
    python scripts/run_ws2_t3_orchestrate.py --replay 20260301 20260331
    python scripts/run_ws2_t3_orchestrate.py --replay --n-days 30
    python scripts/run_ws2_t3_orchestrate.py --db sqlite:///data/ws2/paper.db
    python scripts/run_ws2_t3_orchestrate.py --replay-db sqlite:///data/ws2/replay.db

Live mode runs ingest→compute→persist for the latest completed 12Z cycle into
the live paper-ledger database.  Replay mode (the 48 h autonomy harness) drives
the identical pipeline over cached GFS parquets offline — each cycle with its
own ``ref_time``, into a **separate** replay database so the live ledger is
never polluted by backfilled infrastructure runs.

Every outcome is logged as JSONL to ``data/ws2/logs/orchestrate.jsonl`` and any
failure raises an alert.  Exit 0 if all cycles ran (including designed loud
rejects); exit 1 if any worker failed unexpectedly.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import pandas as pd

from pakhi.ws2.db import get_engine, init_db
from pakhi.ws2.orchestrate import (
    DEFAULT_REPLAY_DB,
    CycleOutcome,
    replay_cycles,
    run_orchestration,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("ws2.t3.orchestrate")


def _dates(start: str, end: str) -> list[str]:
    d0, d1 = pd.Timestamp(start), pd.Timestamp(end)
    if d1 < d0:
        raise SystemExit(f"end {end} is before start {start}")
    n = (d1 - d0).days + 1
    return [(d0 + pd.Timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _recent_dates(n_days: int) -> list[str]:
    today = pd.Timestamp.now("UTC").normalize()
    return [(today - pd.Timedelta(days=i)).strftime("%Y%m%d") for i in range(n_days)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="sqlite:///data/ws2/paper.db",
        help="Live paper-ledger DB (default: sqlite:///data/ws2/paper.db)",
    )
    parser.add_argument(
        "--replay-db",
        default=DEFAULT_REPLAY_DB,
        help="Replay/autonomy DB (default: sqlite:///data/ws2/replay.db)",
    )
    parser.add_argument("--replay", nargs="*", default=None, metavar="START END")
    parser.add_argument("--n-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Gate everything, persist nothing")
    args = parser.parse_args()

    if args.replay is not None:
        if len(args.replay) == 2:
            dates = _dates(args.replay[0], args.replay[1])
        elif len(args.replay) == 0:
            dates = _recent_dates(args.n_days)
        else:
            raise SystemExit("--replay takes START END (two dates) or --n-days")
        db_url = args.replay_db
    else:
        dates = None
        db_url = args.db

    engine = None if args.dry_run else get_engine(db_url)
    if engine is not None:
        init_db(engine)

    if dates is not None:
        logger.info("replay %d cached cycles -> %s (persist=%s)", len(dates), db_url, not args.dry_run)
        summary = replay_cycles(
            dates,
            engine=engine,
            log_sink="data/ws2/logs/orchestrate.jsonl",
        )
        print(json.dumps(summary, indent=2, default=str))
        counts = summary["counts"]
        print(
            f"replay done: {counts[CycleOutcome.OK]} ok | "
            f"{counts[CycleOutcome.REJECTED]} rejected (loud skip) | "
            f"{counts[CycleOutcome.FAILED]} failed | {summary['fired']} fired | "
            f"{summary['ledger_rows']} ledger rows"
        )
        return 1 if counts[CycleOutcome.FAILED] else 0

    record = run_orchestration(engine=engine, persist=not args.dry_run)
    print(json.dumps(record, indent=2, default=str))
    return 0 if record["status"] == CycleOutcome.OK else 1


if __name__ == "__main__":
    sys.exit(main())
