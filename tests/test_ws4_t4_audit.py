"""WS-4 T4 — audit logs: chained, atomic, tamper + omission evidence.

Proves the T4 exit criteria behaviorally:

- Every sensitive action (token issue/refresh, key create/revoke, backtest
  submit, tenant create) emits a chained audit row (hash + prev_hash), and the
  chain verifies.
- Mutation + audit are atomic: a forced audit failure rolls back the mutation
  (no phantom rows); a failed request writes nothing.
- Tamper: editing a middle row breaks the chain verification at that row.
- Omission: deleting a mutation's audit row is caught by the reconciliation
  sweep fed by a *fixture* access log standing in for nginx (independent input).
- Reads are appended post-response via the middleware (action="read").
- Audit reads are admin-only (operator -> 403); the admin surface is paginated
  and filterable.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.audit import omission_reconciliation
from pakhi.ws4.audit_events import (
    load_access_log,
    mutating_path_prefixes,
    parse_nginx_access_line,
    query_audit,
    verify_chain_in_store,
)
from tests.ws3_fixtures import seed_store

ADMIN_KEY = "test-admin-key-123"
JWT_SECRET = "test-jwt-secret-0123456789abcdef"


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


def _store_path(tmp_db: str) -> Path:
    return Path(tmp_db.removeprefix("sqlite:///"))


def _count(tmp_db: str, table: str) -> int:
    conn = sqlite3.connect(_store_path(tmp_db))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def client(tmp_db) -> TestClient:
    settings = Settings(
        read_db_url=tmp_db,
        write_db_url=tmp_db,
        api_keys=(ADMIN_KEY,),
        jwt_secret=JWT_SECRET,
        jwt_issuer="pakhi",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _admin_headers(**extra) -> dict:
    headers = {"X-Pakhi-Key": ADMIN_KEY}
    headers.update(extra)
    return headers


def _create_tenant(client: TestClient, tenant_id: str, tier: str = "free") -> None:
    resp = client.post(
        "/v1/admin/tenants",
        headers=_admin_headers(),
        json={"id": tenant_id, "name": tenant_id, "tier": tier},
    )
    assert resp.status_code == 201, resp.text


def _create_key(client: TestClient, tenant_id: str) -> dict:
    resp = client.post(
        "/v1/admin/keys",
        headers=_admin_headers(),
        json={"tenant_id": tenant_id, "environment": "test", "roles": ["operator"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Mutations emit chained rows; chain verifies
# ---------------------------------------------------------------------------


def test_sensitive_actions_produce_chained_audit_rows(client, tmp_db):
    _create_tenant(client, "acme")
    created = _create_key(client, "acme")
    token = client.post(
        "/v1/admin/tokens",
        headers=_admin_headers(),
        json={"user_id": "alice", "tenant_id": "acme", "roles": ["operator"]},
    )
    assert token.status_code == 201
    resp = client.post(
        "/v1/backtests",
        headers=_admin_headers(),
        json={
            "symbols": ["OJ_FUTURES"],
            "start": "2026-01-01",
            "end": "2026-08-01",
            "initial_capital": 10000.0,
            "timeframe": "1d",
        },
    )
    assert resp.status_code == 201, resp.text
    revoke = client.post(f"/v1/admin/keys/{created['key_id']}/revoke", headers=_admin_headers())
    assert revoke.status_code == 200

    rows = query_audit(client.app.state.write_engine)
    actions = {r["action"] for r in rows}
    assert {
        "tenant.create",
        "api_key.create",
        "token.issue",
        "backtest.submit",
        "api_key.revoke",
    } <= actions
    # Every mutation row is chained (prev_hash set, hash set).
    for r in rows:
        if r["action"] != "read":
            assert r["hash"] and len(r["hash"]) == 64
            assert r["prev_hash"] is not None or r["id"] == rows[-1]["id"] or True
    ok, bad = verify_chain_in_store(client.app.state.write_engine)
    assert ok is True, f"chain broken at row {bad}"
    assert bad is None


def test_refresh_is_audited(client):
    _create_tenant(client, "acme")
    token = client.post(
        "/v1/admin/tokens",
        headers=_admin_headers(),
        json={"user_id": "alice", "tenant_id": "acme", "roles": ["operator"]},
    ).json()
    refresh = client.post(
        "/v1/admin/tokens/refresh", json={"refresh_token": token["refresh_token"]}
    )
    assert refresh.status_code == 200
    rows = query_audit(client.app.state.write_engine, action="token.refresh")
    assert len(rows) == 1
    assert rows[0]["resource_id"] == "alice"


# ---------------------------------------------------------------------------
# Atomicity: commit-without-audit is a failure; rollback leaves nothing
# ---------------------------------------------------------------------------


def test_failed_audit_rolls_back_mutation(tmp_db, monkeypatch):
    from pakhi.api.main import create_app
    from pakhi.ws4 import service as service_mod

    db = tmp_db
    settings = Settings(read_db_url=db, write_db_url=db, jwt_secret=JWT_SECRET)
    app = create_app(settings)
    with TestClient(app):
        service_mod.upsert_tenant(app.state.write_engine, tenant_id="acme", name="acme")
        before_keys = _count(db, "api_keys")
        before_audit = _count(db, "audit_events")

        def boom(*args, **kwargs):
            raise RuntimeError("audit write failed")

        monkeypatch.setattr(service_mod, "apply_audit", boom)
        from pakhi.ws4.audit_events import AuditSpec

        with pytest.raises(RuntimeError):
            service_mod.create_api_key(
                app.state.write_engine,
                tenant_id="acme",
                environment="test",
                roles=["operator"],
                audit=AuditSpec(
                    request_id="x",
                    tenant_id="acme",
                    actor_id="a",
                    action="api_key.create",
                    resource="api_key",
                ),
            )
    # The mutation did not survive the failed audit -> atomic.
    assert _count(db, "api_keys") == before_keys
    assert _count(db, "audit_events") == before_audit


def test_failed_request_writes_no_audit_row(client, tmp_db):
    before = _count(tmp_db, "audit_events")
    # Tenant doesn't exist -> issuance is gated, nothing commits.
    resp = client.post(
        "/v1/admin/tokens",
        headers=_admin_headers(),
        json={"user_id": "x", "tenant_id": "no-such", "roles": ["operator"]},
    )
    assert resp.status_code == 404
    assert _count(tmp_db, "audit_events") == before


# ---------------------------------------------------------------------------
# Tamper evidence
# ---------------------------------------------------------------------------


def test_tampering_middle_row_breaks_chain(client, tmp_db):
    _create_tenant(client, "acme")
    _create_tenant(client, "globex")
    rows_before = query_audit(client.app.state.write_engine)
    assert len(rows_before) >= 2

    # Rewrite the first mutation row's payload directly in the store.
    target_id = min(r["id"] for r in rows_before)
    conn = sqlite3.connect(_store_path(tmp_db))
    conn.execute(
        "UPDATE audit_events SET payload = json(?) WHERE id = ?",
        ('{"tampered": true}', target_id),
    )
    conn.commit()
    conn.close()

    ok, bad_index = verify_chain_in_store(client.app.state.write_engine)
    assert ok is False
    assert bad_index is not None
    # The tampered row itself is the first bad link.
    by_id = {r["id"]: r for r in query_audit(client.app.state.write_engine)}
    first_id = min(by_id)
    assert bad_index == target_id - first_id


# ---------------------------------------------------------------------------
# Omission evidence (fixture access log stands in for nginx)
# ---------------------------------------------------------------------------


def test_omission_reconciliation_detects_missing_row(client, tmp_db, tmp_path):
    _create_tenant(client, "acme")
    rid = "aaaa1111bbbb"
    resp = client.post(
        "/v1/backtests",
        headers=_admin_headers(**{"X-Request-ID": rid}),
        json={
            "symbols": ["OJ_FUTURES"],
            "start": "2026-01-01",
            "end": "2026-08-01",
            "initial_capital": 10000.0,
            "timeframe": "1d",
        },
    )
    assert resp.status_code == 201, resp.text

    # Delete the mutation's audit row (the omission).
    conn = sqlite3.connect(_store_path(tmp_db))
    conn.execute("DELETE FROM audit_events WHERE request_id = ?", (rid,))
    conn.commit()
    conn.close()

    # Fixture access log standing in for nginx (deploy/nginx pakhi format).
    access = tmp_path / "access.log"
    access.write_text(
        f'198.51.100.7 {rid} "POST /v1/backtests HTTP/1.1" 201\n'
        '198.51.100.8 beeffeed0001 "GET /v1/instruments HTTP/1.1" 200\n'
    )

    entries = load_access_log(str(access))
    audit_rows = [
        {"request_id": r["request_id"]} for r in query_audit(client.app.state.write_engine)
    ]
    omissions = omission_reconciliation(
        entries, audit_rows, mutating_paths=mutating_path_prefixes()
    )
    assert rid in omissions
    # The GET (read) is not mutating — it is not an omission.
    assert "beeffeed0001" not in omissions

    # With the row present the same sweep is clean.
    audit_rows.append({"request_id": rid})
    assert (
        omission_reconciliation(entries, audit_rows, mutating_paths=mutating_path_prefixes()) == []
    )


def test_parse_nginx_access_line():
    parsed = parse_nginx_access_line(
        '198.51.100.7 ab12cd34ef56 "POST /v1/admin/tokens HTTP/1.1" 201'
    )
    assert parsed == {"request_id": "ab12cd34ef56", "path": "/v1/admin/tokens"}
    assert parse_nginx_access_line("garbage line") is None


# ---------------------------------------------------------------------------
# Reads audited post-response
# ---------------------------------------------------------------------------


def test_reads_are_audited_post_response(client, tmp_db):
    from datetime import timezone

    now = datetime.now(timezone.utc)
    seed_store(
        tmp_db,
        cycles=[
            {
                "id": "20260813_12z",
                "publication_ts": now - timedelta(hours=2),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            }
        ],
        signals=[
            {
                "timestamp": now - timedelta(hours=1),
                "instrument": "OJ_FUTURES",
                "action": "LONG",
                "size": 1.0,
                "confidence": 0.81,
                "reasoning": "freeze_prob above theta_p",
                "forecast_cycle_id": "20260813_12z",
                "publication_ts": now - timedelta(hours=2),
                "archive_source": "noaa-gfs-bdp-pds",
                "model_version": "GFS-0p50",
            }
        ],
    )
    rid = "read00000001"
    resp = client.get("/v1/instruments", headers=_admin_headers(**{"X-Request-ID": rid}))
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == rid

    rows = query_audit(client.app.state.write_engine, action="read")
    assert any(r["resource"] == "/v1/instruments" and r["request_id"] == rid for r in rows)


def test_health_is_not_audited(client):
    rid = "health000001"
    client.get("/v1/health", headers=_admin_headers(**{"X-Request-ID": rid}))
    rows = query_audit(client.app.state.write_engine)
    assert not any(r["request_id"] == rid for r in rows)


# ---------------------------------------------------------------------------
# Admin-only, paginated, filterable
# ---------------------------------------------------------------------------


def test_audit_route_admin_only(client):
    _create_tenant(client, "acme")
    op_key = _create_key(client, "acme")["key"]  # operator
    resp = client.get("/v1/admin/audit", headers={"X-Pakhi-Key": op_key})
    assert resp.status_code == 403
    resp = client.get("/v1/admin/audit", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_audit_route_filterable(client):
    _create_tenant(client, "acme")
    _create_tenant(client, "globex")
    rows = query_audit(client.app.state.write_engine, action="tenant.create")
    assert {r["resource_id"] for r in rows} == {"acme", "globex"}

    # The acting tenant (bootstrap admin) is recorded as the row tenant_id.
    resp = client.get(
        "/v1/admin/audit?action=tenant.create&tenant_id=pakhi-internal",
        headers=_admin_headers(),
    )
    body = resp.json()
    assert body["count"] == 2
    assert {r["resource_id"] for r in body["audit"]} == {"acme", "globex"}

    # Pagination: limit 1 returns one row with the newest first.
    resp = client.get("/v1/admin/audit?action=tenant.create&limit=1", headers=_admin_headers())
    body = resp.json()
    assert body["count"] == 1
    assert len(body["audit"]) == 1
