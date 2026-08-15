"""WS-5 T5: base backup of the Pakhi store with a pinned, self-verifying manifest.

Topology (contract twin ``dr.backup``): ``base_snapshot`` + ``wal_archive`` +
``off_host_copy``.

- ``base_snapshot``: a consistent, complete snapshot, dialect-aware:
    * Postgres — ``pg_dump -Fc`` (custom format; the runner needs
      ``postgresql-client`` on PATH, e.g. ``apt-get install postgresql-client``).
    * SQLite  — the SQLite Online Backup API (``sqlite3`` ``backup()``).
- ``wal_archive``: the *continuous* archive is the primary's job
  (``archive_mode=on``); it bounds the gap between this base and the last
  archived segment to RPO (``dr.rpo_cycles``). The manifest records the
  snapshot point and the latest published cycle so that gap is measurable.
- ``off_host_copy``: ``--off-host-dir`` copies the base + manifest outside the
  primary host — the policy's versioned off-host requirement (backup-policy §5).

Policy §5 integrity gate: a backup is refused when the source audit chain does
not verify (a backup whose chain cannot be verified is not trusted; the drill
would restart from an older trusted point anyway — better not to take it).

Exit 0 on success; 1 with a message on failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text

from pakhi.ws4.audit_events import verify_chain_in_store
from pakhi.ws5.contract import rpo_cycles, rto_hours


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sqlite_path(url: str) -> Path:
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix) :])
    raise ValueError(f"not a sqlite URL: {url!r}")


def pg_core_url(url: str) -> str:
    """Strip the SQLAlchemy ``postgresql+psycopg://`` prefix for pg_dump."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    if url.startswith("postgresql://"):
        return url
    raise ValueError(f"not a postgres URL: {url!r}")


def mask_url(url: str) -> str:
    """Redact the password so the manifest never stores a secret (policy §5)."""
    return re.sub(r"(://[^:/@]+:)[^@/]+(@)", r"\1***\2", url)


def base_snapshot(source_url: str, dest: Path) -> str:
    """Create the base snapshot; returns the tool used (``pg_dump``/``sqlite``)."""
    engine = create_engine(source_url)
    if engine.dialect.name == "sqlite":
        src = sqlite3.connect(sqlite_path(source_url))
        try:
            dst = sqlite3.connect(dest)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return "sqlite online backup"
    if engine.dialect.name == "postgresql":
        pg_dump = os.environ.get("PAKHI_PG_DUMP", "pg_dump")
        proc = subprocess.run(
            [
                pg_dump,
                "-Fc",
                "-Z9",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                pg_core_url(source_url),
            ],
            stdout=dest.open("wb"),
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {proc.stderr.decode()[-2000:]}")
        return "pg_dump -Fc"
    raise ValueError(f"unsupported dialect: {engine.dialect.name}")


def _count(engine, table: str) -> int:
    if not inspect(engine).has_table(table):
        return 0
    with engine.begin() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def ledger_state(source_url: str) -> dict:
    """Pin what the backup must restore: latest cycle + ledger/chain row counts."""
    engine = create_engine(source_url)
    state = {
        "cycle_id": None,
        "cycle_published_utc": None,
        "counts": {
            "forecast_cycles": _count(engine, "forecast_cycles"),
            "signals": _count(engine, "signals"),
            "paper_ledger": _count(engine, "paper_ledger"),
            "audit_events": _count(engine, "audit_events"),
            "tenants": _count(engine, "tenants"),
            "api_keys": _count(engine, "api_keys"),
        },
    }
    if inspect(engine).has_table("forecast_cycles"):
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, publication_ts FROM forecast_cycles "
                    "ORDER BY publication_ts DESC LIMIT 1"
                )
            ).first()
        if row:
            state["cycle_id"] = row[0]
            ts = row[1]
            state["cycle_published_utc"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return state


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_backup(
    source_url: str,
    backup_dir: Path,
    off_host_dir: Path | None = None,
    keep: int = 30,
    label: str = "",
) -> dict:
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Integrity gate (policy §5): never take a backup we couldn't trust back.
    engine = create_engine(source_url)
    ok, first_bad = verify_chain_in_store(engine)
    if not ok:
        raise RuntimeError(
            f"audit chain does not verify (first bad row index {first_bad}); "
            "refusing to back up an untrusted store (backup-policy §5)"
        )

    state = ledger_state(source_url)
    cycle = state["cycle_id"] or "empty"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_path = backup_dir / f"{stamp}_{label}_{cycle}.base"
    tool = base_snapshot(source_url, base_path)
    digest = sha256_file(base_path)

    manifest = {
        "backup_id": f"{stamp}_{label}",
        "created_utc": _now_utc_iso(),
        "source": {
            "dialect": engine.dialect.name,
            "url": mask_url(source_url),
        },
        "base": {
            "file": base_path.name,
            "size_bytes": base_path.stat().st_size,
            "sha256": digest,
            "tool": tool,
        },
        "ledger": state,
        "verify_chain_before_backup": True,
        "layers": {
            "base_snapshot": True,
            "wal_archive": "primary archive_mode=on; manifest pins the base point so the base->last-WAL gap is bounded by dr.rpo_cycles",
            "off_host_copy": bool(off_host_dir),
        },
        "targets": {
            "rpo_cycles": rpo_cycles(),
            "rto_hours": rto_hours(),
        },
        "retention_days": keep,
    }
    manifest_path = base_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    if off_host_dir:
        off = Path(off_host_dir)
        off.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_path, off / base_path.name)
        shutil.copy2(manifest_path, off / manifest_path.name)

    # Retention: prune base + manifest pairs older than `keep` days.
    cutoff = datetime.now(timezone.utc).timestamp() - keep * 86400
    for f in list(backup_dir.glob("*.base")) + list(backup_dir.glob("*.manifest.json")):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)

    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source-url", required=True, help="store URL to back up")
    ap.add_argument(
        "--backup-dir",
        default="deploy/backups",
        help="where base snapshots + manifests land",
    )
    ap.add_argument("--off-host-dir", help="copy base + manifest off the primary host (policy §5)")
    ap.add_argument("--keep", type=int, default=30, help="base retention in days")
    ap.add_argument("--label", default="manual", help="backup label (e.g. drill-<sha>)")
    args = ap.parse_args()

    manifest = run_backup(
        source_url=args.source_url,
        backup_dir=Path(args.backup_dir),
        off_host_dir=Path(args.off_host_dir) if args.off_host_dir else None,
        keep=args.keep,
        label=args.label,
    )
    print(f"backup id      : {manifest['backup_id']}")
    print(f"base           : {manifest['base']['file']} ({manifest['base']['tool']})")
    print(f"sha256         : {manifest['base']['sha256'][:16]}…")
    print(f"latest cycle   : {manifest['ledger']['cycle_id'] or '(empty store)'}")
    print(f"paper_ledger   : {manifest['ledger']['counts']['paper_ledger']} rows")
    print(f"audit_events   : {manifest['ledger']['counts']['audit_events']} rows")
    print(f"chain verified : {manifest['verify_chain_before_backup']}")
    print(f"RPO target     : {manifest['targets']['rpo_cycles']} cycle")
    print(f"RTO target     : {manifest['targets']['rto_hours']} h")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
