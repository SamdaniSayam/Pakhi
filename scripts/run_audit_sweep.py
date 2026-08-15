"""WS-4 T4: omission-reconciliation sweep.

Replays the nginx access log (deploy/nginx/pakhi-nginx.conf, `pakhi` format)
against ``audit_events`` by ``request_id`` and reports any *mutating*
request_id that has no audit row. The log is written by the proxy — outside the
app's code path — so a bug that suppresses an audit row cannot also erase the
evidence against it (§3.5). A missing row never breaks the chain; this sweep is
what catches the omission.

Usage:
  python scripts/run_audit_sweep.py --access-log <nginx-log> --db-url <url>

Exit 0 when clean; 1 + a listing of omitted request_ids otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from pakhi.ws4.audit import omission_reconciliation
from pakhi.ws4.audit_events import (
    load_access_log,
    mutating_path_prefixes,
)
from pakhi.ws4.db import AuditEvent


def _audit_request_ids(db_url: str) -> list[dict[str, str]]:
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.execute(select(AuditEvent.request_id)).scalars().all()
    return [{"request_id": rid} for rid in rows]


def run(access_log: str, db_url: str) -> int:
    access = load_access_log(access_log)
    audit_rows = _audit_request_ids(db_url)
    omissions = omission_reconciliation(access, audit_rows, mutating_paths=mutating_path_prefixes())
    if not omissions:
        print(f"audit sweep: clean ({len(access)} logged requests, {len(audit_rows)} audit rows)")
        return 0
    print(f"audit sweep: {len(omissions)} omission(s) — mutating request_id(s) with no audit row:")
    for rid in omissions:
        print(f"  {rid}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-log", required=True, help="nginx access log (pakhi format)")
    parser.add_argument("--db-url", required=True, help="store (write) database URL")
    args = parser.parse_args()
    return run(args.access_log, args.db_url)


if __name__ == "__main__":
    sys.exit(main())
