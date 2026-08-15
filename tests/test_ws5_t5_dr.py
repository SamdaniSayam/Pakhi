"""WS-5 T5 — DR: backup script + wipe-and-restore drill (hermetic, SQLite).

The same scripts run against real Postgres 16 in the ``ws5-dr`` CI job
(.github/workflows/ws5-dr.yml) using ``WS5_DR_SOURCE_URL`` /
``WS5_DR_SCRATCH_URL``; the blue print requires the drill to be *rehearsed*,
so these tests execute the exact CLI entry points end to end against a local
store — a restore that has never run is not a backup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pakhi.ws2.db import ForecastCycle, PaperLedger, Signal, init_db, upsert
from pakhi.ws4.audit_events import AuditSpec, apply_audit, verify_chain_in_store
from pakhi.ws4.service import upsert_tenant
from pakhi.ws5.contract import reliability_contract

REPO = Path(__file__).resolve().parents[1]
ADMIN_KEY = "restore-drill-key"

_NOW = datetime.now(timezone.utc)


def _seed(url: str) -> dict:
    """A store with a published cycle, a ledger row, a tenant and a sealed
    audit chain — the exact surface a backup must restore."""
    eng = create_engine(url)
    init_db(eng)
    upsert_tenant(eng, tenant_id="drill-acme", name="drill-acme", tier="pro")
    upsert(
        eng,
        ForecastCycle,
        {
            "id": "20260814_12z",
            "publication_ts": _NOW,
            "archive_source": "ci",
            "model_version": "v9",
        },
        ["id"],
    )
    upsert(
        eng,
        Signal,
        {
            "timestamp": _NOW,
            "instrument": "OJ_FUTURES",
            "action": "BUY",
            "size": 1.0,
            "confidence": 0.7,
            "reasoning": "drill",
            "forecast_cycle_id": "20260814_12z",
            "publication_ts": _NOW,
            "archive_source": "ci",
            "model_version": "v9",
        },
        ["forecast_cycle_id"],
    )
    upsert(
        eng,
        PaperLedger,
        {
            "episode_id": 1,
            "entry_cycle": _NOW,
            "entry_session": _NOW,
            "exit_session": _NOW,
            "gross": 1.0,
            "net": 1.0,
            "net_of_benchmark": 1.0,
            "fold": "oos",
            "in_oos": True,
            "embargoed": False,
            "entry_weekend": False,
            "next_close_fill": False,
            "fill_days_after_cycle": 1,
            "entry_freeze_prob": 0.1,
            "entry_temperature_min": 5.0,
            "forecast_cycle_id": "20260814_12z",
            "publication_ts": _NOW,
            "model_version": "v9",
            "scored": True,
            "archive_source": "ci",
            "vintage_hash": "0" * 64,
            "fetch_date": _NOW,
        },
        ["forecast_cycle_id"],
    )
    with Session(eng) as s, s.begin():
        apply_audit(
            s,
            AuditSpec(
                request_id="drill0001",
                tenant_id="drill-acme",
                actor_id="drill",
                action="tenant.create",
                resource="tenant",
                resource_id="drill-acme",
            ),
        )
        apply_audit(
            s,
            AuditSpec(
                request_id="drill0002",
                tenant_id="drill-acme",
                actor_id="drill",
                action="cycle.publish",
                resource="cycle",
                resource_id="20260814_12z",
            ),
        )
    ok, bad = verify_chain_in_store(eng)
    assert ok is True, f"seed chain broken at {bad}"
    return {
        "cycle_id": "20260814_12z",
        "audit_events": 2,
        "paper_ledger": 1,
        "signals": 1,
        "tenants": 1,
        "api_keys": 0,
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture
def store(tmp_path: Path) -> tuple[Path, dict]:
    src = tmp_path / "store.db"
    expected = _seed(f"sqlite:///{src}")
    return src, expected


def test_backup_manifest_pins_ledger_and_chain(store, tmp_path: Path) -> None:
    src, expected = store
    proc = _run_cli(
        "scripts/run_ws5_backup.py",
        f"--source-url=sqlite:///{src}",
        f"--backup-dir={tmp_path}/bk",
        f"--off-host-dir={tmp_path}/offhost",
        "--label=ut",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifests = list(Path(tmp_path / "bk").glob("*.manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())

    assert manifest["ledger"]["cycle_id"] == expected["cycle_id"]
    assert manifest["verify_chain_before_backup"] is True
    for table, count in expected.items():
        if table != "cycle_id":
            assert manifest["ledger"]["counts"][table] == count

    base = Path(tmp_path / "bk") / manifest["base"]["file"]
    assert base.exists()
    import hashlib

    assert manifest["base"]["sha256"] == hashlib.sha256(base.read_bytes()).hexdigest()
    # Off-host copy hook (policy §5): base + manifest land outside the primary.
    off = Path(tmp_path / "offhost")
    assert (off / base.name).exists()
    assert (off / manifests[0].name).exists()
    # The drill measures the twin's targets.
    assert manifest["targets"] == {
        "rpo_cycles": reliability_contract()["dr"]["rpo_cycles"],
        "rto_hours": reliability_contract()["dr"]["rto_hours"],
    }


def test_backup_refuses_a_store_with_a_broken_chain(store, tmp_path: Path) -> None:
    src, _ = store
    eng = create_engine(f"sqlite:///{src}")
    with eng.begin() as conn:
        conn.execute(text("UPDATE audit_events SET hash='tampered' WHERE id=1"))
    proc = _run_cli(
        "scripts/run_ws5_backup.py",
        f"--source-url=sqlite:///{src}",
        f"--backup-dir={tmp_path}/bk",
    )
    assert proc.returncode == 1
    assert "untrusted store" in proc.stderr
    assert not list(Path(tmp_path / "bk").glob("*.base"))


def test_drill_wipe_restore_verifies_chain_ledger_and_ws3_reads(store, tmp_path: Path) -> None:
    src, expected = store
    scratch = tmp_path / "scratch.db"
    proc = _run_cli(
        "scripts/run_ws5_restore_drill.py",
        f"--source-url=sqlite:///{src}",
        f"--scratch-url=sqlite:///{scratch}",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = proc.stdout
    for step in (
        "snapshot",
        "wipe",
        "restore_scratch_db",
        "verify_chain",
        "verify_ledger",
        "verify_ws3_reads",
    ):
        assert f"ok    {step}" in report, report
    # Targets from the twin are reported as what the drill measures.
    assert "RPO <= 1 cycle, RTO <= 4 h" in report, report

    # The restored DB really holds the pinned cycle + ledger + chain.
    eng = create_engine(f"sqlite:///{scratch}")
    with eng.connect() as conn:
        cycle = conn.execute(
            text("SELECT id FROM forecast_cycles ORDER BY publication_ts DESC LIMIT 1")
        ).scalar_one()
        assert cycle == expected["cycle_id"]
        assert (
            conn.execute(text("SELECT count(*) FROM paper_ledger")).scalar_one()
            == expected["paper_ledger"]
        )
    ok, bad = verify_chain_in_store(eng)
    assert ok is True, f"restored chain broken at {bad}"


def test_drill_reuse_backup_file_and_wipe_leaves_no_old_rows(store, tmp_path: Path) -> None:
    src, expected = store
    bk = tmp_path / "bk"
    _run_cli(
        "scripts/run_ws5_backup.py",
        f"--source-url=sqlite:///{src}",
        f"--backup-dir={bk}",
    )
    base = sorted(bk.glob("*.base"))[-1]

    # Corrupt the scratch DB with extra rows first: the drill must wipe it and
    # restore exactly the snapshot, never accumulating.
    scratch = tmp_path / "scratch.db"
    eng = create_engine(f"sqlite:///{scratch}")
    init_db(eng)
    upsert(
        eng,
        ForecastCycle,
        {
            "id": "poisoned_cycle",
            "publication_ts": _NOW,
            "archive_source": "ci",
            "model_version": "v9",
        },
        ["id"],
    )

    proc = _run_cli(
        "scripts/run_ws5_restore_drill.py",
        f"--source-url=sqlite:///{src}",
        f"--scratch-url=sqlite:///{scratch}",
        f"--backup-file={base}",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    eng = create_engine(f"sqlite:///{scratch}")
    with eng.connect() as conn:
        ids = conn.execute(text("SELECT id FROM forecast_cycles")).scalars().all()
    assert ids == [expected["cycle_id"]], "poisoned rows must not survive the wipe"
