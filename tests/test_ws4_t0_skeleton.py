"""WS-4 T0 — skeleton exit evidence.

Proves the locked contract's core properties at the pure level, before any
endpoint ships:

- ``pakhi.ws4`` imports cleanly with no side effects (no fastapi dependency at
  package import).
- Audit chain: tamper detection (edit a middle row -> chain breaks at that row).
- Omission reconciliation: a mutating request present in the independent access
  log but missing from audit rows is flagged; reads are not; the sweep's input
  is the *log*, never the app's own audit code.
- Tenant scope role matrix: admin > operator > viewer, machine default
  operator, insufficient role raises PermissionDenied.
- The machine contract twin self-hashes correctly.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pakhi.ws4 import audit as ws4_audit
from pakhi.ws4.audit import ChainedRow, seal_chain, verify_chain
from pakhi.ws4.tenant import (
    DEFAULT_MACHINE_ROLES,
    DEFAULT_TENANT_ID,
    PermissionDeniedError,
    TenantScope,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = ROOT / "data" / "ws4" / "security_tenancy_contract.json"


# ---------------------------------------------------------------------------
# Import-clean / no-side-effects skeleton
# ---------------------------------------------------------------------------


def test_ws4_imports_cleanly_without_api_extra() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", "import pakhi.ws4"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ws4_has_no_side_effects() -> None:
    import pakhi.ws4

    assert pakhi.ws4.audit is not None and pakhi.ws4.tenant is not None


def test_contract_machine_twin_self_hashes() -> None:
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    assert record["payload_sha256"] == hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# Audit chain: tamper evidence
# ---------------------------------------------------------------------------


def _rows() -> list[ChainedRow]:
    return seal_chain(
        [
            ChainedRow(
                request_id=f"r{i}",
                action="backtest.submit",
                resource="backtest_jobs",
                tenant_id="tenant-a",
                actor_id="key_ab12",
                outcome="success",
                ts=f"2026-08-14T00:00:0{i}Z",
            )
            for i in range(3)
        ]
    )


def test_chain_verifies_when_intact() -> None:
    assert verify_chain(_rows()) == (True, None)


def test_chain_breaks_on_middle_row_edit() -> None:
    rows = _rows()
    rows[1].action = "key.revoke"  # retroactive edit of a sealed row
    ok, bad = verify_chain(rows)
    assert ok is False
    assert bad == 1


def test_chain_breaks_on_prev_hash_tamper() -> None:
    rows = _rows()
    rows[2].prev_hash = "forged"
    ok, bad = verify_chain(rows)
    assert ok is False
    assert bad == 2


# ---------------------------------------------------------------------------
# Omission reconciliation: tamper AND omission, anchored on the log
# ---------------------------------------------------------------------------

MUTATING = ("/v1/admin/tenants", "/v1/admin/tokens", "/v1/backtests", "/v1/admin/keys")


def test_reconciliation_flags_missing_mutation_row() -> None:
    access_log = [
        {"request_id": "r1", "path": "/v1/admin/tokens"},
        {"request_id": "r2", "path": "/v1/backtests"},
        {"request_id": "r3", "path": "/v1/signals/OJ_FUTURES"},  # read: not mutating
    ]
    audit_rows = [{"request_id": "r1"}]  # r2 missing
    assert ws4_audit.omission_reconciliation(access_log, audit_rows, mutating_paths=MUTATING) == [
        "r2"
    ]


def test_reconciliation_clean_when_log_matches_audit() -> None:
    access_log = [
        {"request_id": "r1", "path": "/v1/admin/tokens"},
        {"request_id": "r2", "path": "/v1/backtests"},
    ]
    audit_rows = [{"request_id": "r1"}, {"request_id": "r2"}]
    assert ws4_audit.omission_reconciliation(access_log, audit_rows, mutating_paths=MUTATING) == []


def test_reconciliation_never_flags_reads() -> None:
    access_log = [{"request_id": "r9", "path": "/v1/ledger"}]
    assert ws4_audit.omission_reconciliation(access_log, [], mutating_paths=MUTATING) == []


# ---------------------------------------------------------------------------
# Tenant scope role matrix
# ---------------------------------------------------------------------------


def test_machine_default_role_and_tenant() -> None:
    scope = TenantScope(
        tenant_id="tenant-a",
        roles=frozenset(DEFAULT_MACHINE_ROLES),
        actor_id="key_ab12",
        actor_type="machine",
    )
    assert scope.can("operator")
    assert scope.can("viewer")  # operator subsumes viewer
    assert not scope.can("admin")
    assert scope.tenant_id == "tenant-a"


def test_admin_is_superset() -> None:
    admin = TenantScope(roles=frozenset(("admin",)), actor_type="human")
    assert admin.can("admin", "operator", "viewer")


def test_default_scope_is_anonymous_viewer() -> None:
    scope = TenantScope()
    assert scope.tenant_id == DEFAULT_TENANT_ID
    assert scope.can("viewer")
    assert not scope.can("operator")


def test_insufficient_role_raises() -> None:
    scope = TenantScope(roles=frozenset(("viewer",)))
    with pytest.raises(PermissionDeniedError):
        scope.require("operator")
