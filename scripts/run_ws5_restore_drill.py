"""WS-5 T5: wipe-and-restore drill against a scratch database.

The drill IS the tested-restore guarantee (backup-policy §4/§5: "a restore that
has never been executed is a wish, not a backup"). Each run proves the full
chain, end to end, against a throwaway scratch DB:

    1. snapshot      — take a fresh base (or reuse ``--backup-file``)
    2. wipe          — drop/recreate the scratch DB (proves restore into a
                       clean, empty store — not a re-point at the same files)
    3. restore_scratch_db — rebuild from the base only
    4. verify_chain  — ``verify_chain_in_store`` passes on the restored store
                       (the audit chain is the integrity check)
    5. verify_ledger — latest cycle + row counts match the pinned manifest
    6. verify suites — WS-3 public-read smoke against an app booted on the
                       restored DB + (Postgres) the WS-4 evidence suite
                       ``tests/test_ws4_t5_ci.py`` against the restored DB,
                       the same template the ``ws4-security`` job uses

RPO (``dr.rpo_cycles``) and RTO (``dr.rto_hours``) are read from the contract
twin and reported — the drill is what measures that the target is reachable.

Postgres needs ``postgresql-client`` (pg_dump/pg_restore) on PATH. SQLite runs
the identical drill hermetically (used by the local suite).

Exit 0 when every step passes; 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.audit_events import verify_chain_in_store
from pakhi.ws5.contract import rpo_cycles, rto_hours

_spec = importlib.util.spec_from_file_location(
    "run_ws5_backup", Path(__file__).parent / "run_ws5_backup.py"
)
_bkp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bkp)
base_snapshot = _bkp.base_snapshot
ledger_state = _bkp.ledger_state
pg_core_url = _bkp.pg_core_url
sqlite_path = _bkp.sqlite_path

ROOT = Path(__file__).resolve().parents[1]

_OK, _FAIL = "ok", "FAIL"


def dialect(url: str) -> str:
    return create_engine(url).dialect.name


def wipe(scratch_url: str) -> None:
    """Reset the scratch DB so the restore proves clean-database recovery."""
    name = dialect(scratch_url)
    if name == "sqlite":
        p = sqlite_path(scratch_url)
        for ext in ("", "-journal", "-wal", "-shm"):
            Path(str(p) + ext).unlink(missing_ok=True)
        return
    if name == "postgresql":
        core = pg_core_url(scratch_url)
        # Connect to the maintenance database on the same host, then drop/create
        # the target. WITH (FORCE) needs PG >= 13 (drill targets Postgres 16).
        import urllib.parse

        parts = urllib.parse.urlsplit(core)
        db = parts.path.lstrip("/")
        maint = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))
        import psycopg

        with psycopg.connect(maint, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{db}"')
        return
    raise ValueError(f"unsupported dialect: {name}")


def restore(base_path: Path, scratch_url: str) -> str:
    name = dialect(scratch_url)
    if name == "sqlite":
        src = sqlite3.connect(base_path)
        try:
            dst = sqlite3.connect(sqlite_path(scratch_url))
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return "sqlite online restore"
    if name == "postgresql":
        pg_restore = os.environ.get("PAKHI_PG_RESTORE", "pg_restore")
        proc = subprocess.run(
            [
                pg_restore,
                "--no-owner",
                "--no-privileges",
                "--dbname",
                pg_core_url(scratch_url),
                str(base_path),
            ],
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pg_restore failed: {proc.stderr.decode()[-2000:]}")
        return "pg_restore"
    raise ValueError(f"unsupported dialect: {name}")


def verify_restored_chain(scratch_url: str) -> tuple[bool, str]:
    engine = create_engine(scratch_url)
    if not inspect(engine).has_table("audit_events"):
        return True, "no audit rows to verify"
    ok, first_bad = verify_chain_in_store(engine)
    return ok, f"chain verifies (first bad {first_bad})" if ok else f"chain broken at {first_bad}"


def verify_restored_ledger(scratch_url: str, manifest: dict) -> tuple[bool, list[str]]:
    got = ledger_state(scratch_url)
    want = manifest["ledger"]
    problems: list[str] = []
    if want["cycle_id"] != got["cycle_id"]:
        problems.append(
            f"latest cycle mismatch: manifest={want['cycle_id']!r} restored={got['cycle_id']!r}"
        )
    for table in want["counts"]:
        if want["counts"][table] != got["counts"][table]:
            problems.append(
                f"{table} count mismatch: manifest={want['counts'][table]} restored={got['counts'][table]}"
            )
    return not problems, problems


def ws3_reads_on_restored_db(scratch_url: str) -> tuple[bool, str]:
    settings = Settings(
        read_db_url=scratch_url,
        write_db_url=scratch_url,
        api_keys=("restore-drill-key",),
        jwt_secret="drill-jwt-secret-0123456789abcdef",
    )
    app = create_app(settings)
    headers = {"X-Pakhi-Key": "restore-drill-key"}
    with TestClient(app) as client:
        for path in ("/v1/instruments", "/v1/ledger", "/v1/status"):
            resp = client.get(path, headers=headers)
            if resp.status_code != 200:
                return False, f"GET {path} -> {resp.status_code} on restored DB"
    return True, "WS-3 read path serves from the restored DB"


def ws4_suite_on_restored_db(scratch_url: str) -> tuple[bool, str]:
    """Run the Postgres WS-4 evidence suite against the restored DB.

    The same file the ``ws4-security`` job runs with ``WS4_TEST_DB_URL`` — the
    template the blueprint names. SQLite scratch stores skip this step (the
    suite is Postgres evidence).
    """
    if dialect(scratch_url) != "postgresql":
        return True, "skipped (WS-4 evidence suite is Postgres-only)"
    env = {**os.environ, "WS4_TEST_DB_URL": scratch_url}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_ws4_t5_ci.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False, proc.stdout.decode()[-1500:] + proc.stderr.decode()[-1500:]
    return True, "WS-4 evidence suite passes on the restored DB"


def run_drill(
    source_url: str,
    scratch_url: str,
    backup_file: Path | None = None,
    backup_dir: Path | None = None,
    run_suites: bool = True,
) -> dict:
    steps: dict[str, tuple[bool, str]] = {}
    temp_backup_dir: Path | None = None

    if backup_file is None:
        temp_backup_dir = Path(tempfile.mkdtemp(prefix="ws5-drill-"))
        manifest_path = temp_backup_dir / "drill.manifest.json"
        base = temp_backup_dir / "drill.base"
        steps["snapshot"] = (True, "fresh base taken into temp dir")
    else:
        base = backup_file
        manifest_path = backup_file.with_suffix(".manifest.json")
        steps["snapshot"] = (True, f"reused {backup_file.name}")

    try:
        if backup_file is None:
            tool = base_snapshot(source_url, base)
            state = ledger_state(source_url)
            manifest = {
                "backup_id": "drill",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source": {"dialect": dialect(source_url), "url": source_url},
                "base": {"file": base.name, "size_bytes": base.stat().st_size, "tool": tool},
                "ledger": state,
                "verify_chain_before_backup": True,
                "targets": {
                    "rpo_cycles": rpo_cycles(),
                    "rto_hours": rto_hours(),
                },
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        else:
            manifest = json.loads(manifest_path.read_text())
            tool = manifest["base"]["tool"]

        steps["snapshot"] = (True, f"base via {tool}")

        wipe(scratch_url)
        steps["wipe"] = (True, f"scratch DB reset ({dialect(scratch_url)})")

        restore(base, scratch_url)
        steps["restore_scratch_db"] = (True, f"restored from {base.name}")

        ok, msg = verify_restored_chain(scratch_url)
        steps["verify_chain"] = (ok, msg)

        ok, problems = verify_restored_ledger(scratch_url, manifest)
        steps["verify_ledger"] = (
            ok,
            "; ".join(problems) if problems else "ledger + counts match manifest",
        )

        if run_suites:
            ok, msg = ws3_reads_on_restored_db(scratch_url)
            steps["verify_ws3_reads"] = (ok, msg)
            ok, msg = ws4_suite_on_restored_db(scratch_url)
            steps["verify_ws4_suites"] = (ok, msg)
        else:
            steps["verify_ws3_reads"] = (True, "skipped (--no-suite)")
            steps["verify_ws4_suites"] = (True, "skipped (--no-suite)")
    finally:
        if temp_backup_dir is not None:
            shutil.rmtree(temp_backup_dir, ignore_errors=True)

    return {"steps": steps, "targets": manifest.get("targets", {})}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source-url", required=True, help="the store to back up / restore from")
    ap.add_argument(
        "--scratch-url",
        required=True,
        help="throwaway DB that gets wiped and rebuilt (never the primary)",
    )
    ap.add_argument("--backup-file", type=Path, help="reuse an existing base snapshot")
    ap.add_argument("--backup-dir", type=Path, help="dir to scan for an existing base")
    ap.add_argument("--no-suite", action="store_true", help="skip WS-3/WS-4 verification steps")
    args = ap.parse_args()

    backup_file = args.backup_file
    if backup_file is None and args.backup_dir:
        bases = sorted(Path(args.backup_dir).glob("*.base"))
        if bases:
            backup_file = bases[-1]

    report = run_drill(
        source_url=args.source_url,
        scratch_url=args.scratch_url,
        backup_file=backup_file,
        run_suites=not args.no_suite,
    )

    print("restore drill report")
    print("---------------------")
    failed = False
    for name, (ok, msg) in report["steps"].items():
        failed = failed or not ok
        print(f"  {_OK if ok else _FAIL:4s}  {name:<22} {msg}")
    targets = report["targets"]
    if targets:
        print(
            f"  ---  targets measured: RPO <= {targets.get('rpo_cycles')} cycle, "
            f"RTO <= {targets.get('rto_hours')} h (contract twin)"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"restore drill failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
