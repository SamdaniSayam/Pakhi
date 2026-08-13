#!/usr/bin/env python3
"""WS-2 T1 CLI: ingest the locked 12Z GFS cycle + OJ daily close (live armor).

Usage:
    python scripts/run_ws2_t1_ingest.py                    # latest completed 12Z
    python scripts/run_ws2_t1_ingest.py --cycle 20260812    # specific cycle
    python scripts/run_ws2_t1_ingest.py --source aws        # force AWS archive
    python scripts/run_ws2_t1_ingest.py --dry-run           # validate + gate only

Exit 0 on a persisted ingest; exit 1 on a loud rejection (DataStalenessError /
UpstreamMissingError / RejectCycleError) — the pipeline never drops silently.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from pakhi.ws2.ingest import IngestError, ingest_cycle, latest_12z_cycle

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("ws2.t1.ingest")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cycle",
        default=None,
        help="Cycle date YYYYMMDD (default: latest completed 12Z cycle)",
    )
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "nomads", "aws"],
        help="Upstream: NOMADS primary with AWS fallback (auto, default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + validate + run armor but do not persist anything",
    )
    args = parser.parse_args()

    cycle = args.cycle or latest_12z_cycle()
    logger.info("ingesting 12Z cycle %s (source=%s, persist=%s)", cycle, args.source, not args.dry_run)
    try:
        record = ingest_cycle(cycle, source=args.source, persist=not args.dry_run)
    except IngestError as exc:
        logger.error("REJECT %s: %s", type(exc).__name__, exc)
        print(json.dumps({"ok": False, "cycle": cycle, "error": str(exc), "type": type(exc).__name__}))
        return 1

    print(json.dumps(record, indent=2, default=str))
    f = record["features"]
    logger.info(
        "OK %s: freeze_prob=%.4f temperature_min=%.2f °C armor=%s vintage_sha=%s",
        record["forecast_cycle_id"],
        f["freeze_prob"],
        f["temperature_min"],
        record["armor"]["pass"],
        record["vintage"]["sha256"][:12],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
