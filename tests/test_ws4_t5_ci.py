"""WS-4 T5 — Postgres-backed compliance evidence.

These tests are the CI evidence behind the access-control / change-management
controls: the full WS-4 security surface (tenancy, RBAC, identity, audit chain)
must pass against the *real* deployment store, not just sqlite.

They are skipped unless ``WS4_TEST_DB_URL`` is set — which the dedicated
``ws4-security`` workflow (.github/workflows/ws4-security.yml) always does,
against a Postgres 16 service container. A green run is the machine-checkable
part of the WS-4 exit criteria for every control in docs/compliance/.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.audit_events import AuditSpec, query_audit, verify_chain_in_store
from pakhi.ws4.db import init_db, migrate
from pakhi.ws4.service import (
    create_api_key,
    issue_tokens,
    lookup_key,
    upsert_tenant,
)

JWT_SECRET = "test-jwt-secret-0123456789abcdef"
ADMIN_KEY = "test-admin-key-123"

DB_URL = os.environ.get("WS4_TEST_DB_URL")


def _pg() -> str:
    if not DB_URL:
        pytest.skip("WS4_TEST_DB_URL not set (runs under the ws4-security workflow)")
    return DB_URL


@pytest.fixture
def engine():
    from sqlalchemy import create_engine, text

    eng = create_engine(_pg())
    init_db(eng)
    migrate(eng)  # pre-existing stores get the additive tenant_id column
    # Each test gets a clean store so chain assertions are independent.
    with eng.begin() as conn:
        for table in (
            "audit_events",
            "backtest_jobs",
            "refresh_tokens",
            "api_keys",
            "users",
            "tenants",
        ):
            conn.execute(text(f"TRUNCATE {table} RESTART IDENTITY"))
    try:
        yield eng
    finally:
        eng.dispose()


def test_postgres_migration_and_tenancy_surface(engine):
    upsert_tenant(engine, tenant_id="pg-acme", name="pg-acme", tier="pro")
    created = create_api_key(engine, tenant_id="pg-acme", environment="ci", roles=["operator"])
    digest = hashlib.sha256(created.key.encode()).hexdigest()
    identity = lookup_key(engine, digest)
    assert identity is not None and identity.tenant_id == "pg-acme"
    assert identity.roles == ["operator"]

    pair = issue_tokens(
        engine,
        user_id="pg-alice",
        tenant_id="pg-acme",
        roles=["operator"],
        secret=JWT_SECRET,
    )
    assert pair.access_token and pair.refresh_token
    # A DB key resolves from the raw key, proving the hashed-at-rest lane works
    # on Postgres too.
    assert lookup_key(engine, digest) == identity


def test_postgres_audit_chain_and_admin_read(engine):
    upsert_tenant(
        engine,
        tenant_id="pg-cedar",
        name="pg-cedar",
        audit=AuditSpec(
            request_id="pg-cedar-1",
            tenant_id="pg-cedar",
            actor_id="pg-admin",
            action="tenant.create",
            resource="tenant",
        ),
    )
    created = create_api_key(
        engine,
        tenant_id="pg-cedar",
        environment="ci",
        roles=["operator"],
        audit=AuditSpec(
            request_id="pg-cedar-2",
            tenant_id="pg-cedar",
            actor_id="pg-admin",
            action="api_key.create",
            resource="api_key",
        ),
    )
    ok, bad = verify_chain_in_store(engine)
    assert ok is True, f"chain broken at {bad}"
    rows = query_audit(engine, action="api_key.create")
    assert len(rows) == 1
    assert rows[0]["resource_id"] == created.key_id


def test_postgres_full_app_flow(client) -> None:
    resp = client.post(
        "/v1/admin/tenants",
        headers={"X-Pakhi-Key": ADMIN_KEY},
        json={"id": "pg-full", "name": "pg-full", "tier": "free"},
    )
    assert resp.status_code == 201, resp.text
    key = client.post(
        "/v1/admin/keys",
        headers={"X-Pakhi-Key": ADMIN_KEY},
        json={"tenant_id": "pg-full", "environment": "live", "roles": ["operator"]},
    ).json()["key"]
    resp = client.post(
        "/v1/backtests",
        headers={"X-Pakhi-Key": key},
        json={
            "symbols": ["OJ_FUTURES"],
            "start": "2026-01-01",
            "end": "2026-08-01",
            "initial_capital": 10000.0,
            "timeframe": "1d",
        },
    )
    assert resp.status_code == 201, resp.text
    resp = client.get("/v1/admin/audit", headers={"X-Pakhi-Key": ADMIN_KEY})
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2  # tenant.create + backtest.submit (+ reads)
    ok, bad = verify_chain_in_store(client.app.state.write_engine)
    assert ok is True, f"chain broken at {bad}"


@pytest.fixture
def client(engine) -> TestClient:
    settings = Settings(
        read_db_url=DB_URL,
        write_db_url=DB_URL,
        api_keys=(ADMIN_KEY,),
        jwt_secret=JWT_SECRET,
        jwt_issuer="pakhi",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
