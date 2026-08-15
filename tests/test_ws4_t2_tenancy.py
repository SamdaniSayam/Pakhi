"""WS-4 T2 — multi-tenancy + RBAC.

Proves the T2 exit criteria behaviorally:

- Tenant + per-tenant API-key admin surface: create tenant (tier ->
  limit_per_min), create key (raw key returned exactly once, only sha256
  stored), list prefixes, revoke (next request with that key -> 401).
- Cross-tenant isolation: tenant A's backtest job is a 404 for tenant B and
  visible to tenant A. Admin data reads are tenant-scoped like everyone else.
- RBAC: operator key can read public data but is denied admin routes (403);
  admin-only ledger is denied to operator, allowed to admin; the unauthenticated
  dev posture keeps the WS-3 ledger behavior (open).
- Per-tier rate limit: pro key gets X-RateLimit-Limit 120, free key 30.
- The WS-3 ``X-Pakhi-Key`` flow still works untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings

ADMIN_KEY = "test-admin-key-123"
JWT_SECRET = "test-jwt-secret-0123456789abcdef"


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


def _store_path(tmp_db: str) -> Path:
    return Path(tmp_db.removeprefix("sqlite:///"))


def _row_count(tmp_db: str, table: str) -> int:
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


def _admin_headers() -> dict:
    return {"X-Pakhi-Key": ADMIN_KEY}


def _create_tenant(client: TestClient, tenant_id: str, tier: str = "free") -> dict:
    resp = client.post(
        "/v1/admin/tenants",
        headers=_admin_headers(),
        json={"id": tenant_id, "name": tenant_id, "tier": tier},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_key(client: TestClient, tenant_id: str, roles=("operator",)) -> dict:
    resp = client.post(
        "/v1/admin/keys",
        headers=_admin_headers(),
        json={"tenant_id": tenant_id, "environment": "test", "roles": list(roles)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tenant + API-key admin surface
# ---------------------------------------------------------------------------


def test_create_tenant_and_tier_limits(client):
    body = _create_tenant(client, "acme", tier="pro")
    assert body["id"] == "acme"
    assert body["tier"] == "pro"
    assert body["limit_per_min"] == 120


def test_tenants_list_contains_default_and_created(client):
    _create_tenant(client, "acme", tier="pro")
    resp = client.get("/v1/admin/tenants", headers=_admin_headers())
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()["tenants"]}
    assert ids == {"pakhi-internal", "acme"}


def test_issue_token_for_missing_tenant_is_404(client):
    resp = client.post(
        "/v1/admin/tokens",
        headers=_admin_headers(),
        json={"user_id": "ghost", "tenant_id": "no-such-tenant", "roles": ["operator"]},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_create_api_key_returns_raw_once_and_stores_hash(client, tmp_db):
    _create_tenant(client, "acme")
    created = _create_key(client, "acme")
    raw = created["key"]
    assert created["prefix"].startswith("pk_test_")
    assert created["tenant_id"] == "acme"
    assert "note" in created

    # Only the sha256 is stored; the raw key is not retrievable via the API.
    conn = sqlite3.connect(_store_path(tmp_db))
    digest = conn.execute("SELECT key_hash FROM api_keys").fetchone()[0]
    conn.close()
    assert digest != raw
    assert len(digest) == 64

    listed = client.get("/v1/admin/keys?tenant_id=acme", headers=_admin_headers()).json()
    assert listed["keys"][0]["prefix"] == created["prefix"]
    # Prefixes only: the raw key never appears in listings.
    assert all("key" not in k or k["key"] is None for k in listed["keys"])
    assert raw not in str(listed)


def test_revoked_key_fails_closed(client):
    _create_tenant(client, "acme")
    created = _create_key(client, "acme")
    resp = client.post(f"/v1/admin/keys/{created['key_id']}/revoke", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    # WS-5 T4 migration: auth semantics live on the deep /v1/status page
    # (/v1/health is unauthenticated probe liveness).
    resp2 = client.get("/v1/status", headers={"X-Pakhi-Key": created["key"]})
    assert resp2.status_code == 401


def test_machine_key_resolves_own_tenant_scope(client, tmp_db):
    _create_tenant(client, "acme")
    created = _create_key(client, "acme")
    # Machine key with an operator role is still a valid credential for WS-3
    # public reads (viewer+), proving the DB-key lane resolves, not the admin
    # bootstrap lane. Probed against the deep /v1/status page (WS-5 T4: health
    # is unauthenticated liveness).
    resp = client.get("/v1/status", headers={"X-Pakhi-Key": created["key"]})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cross-tenant isolation (backtest jobs)
# ---------------------------------------------------------------------------


def _submit_backtest(client: TestClient, key: str) -> dict:
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
    return resp.json()


def test_cross_tenant_job_is_404(client):
    _create_tenant(client, "acme")
    _create_tenant(client, "globex")
    acme_key = _create_key(client, "acme")["key"]
    globex_key = _create_key(client, "globex")["key"]

    job = _submit_backtest(client, acme_key)
    job_id = job["job_id"]

    # Owner sees it.
    resp = client.get(f"/v1/backtests/{job_id}", headers={"X-Pakhi-Key": acme_key})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id

    # Cross-tenant read is the same as not existing: 404, not 403, not data.
    resp = client.get(f"/v1/backtests/{job_id}", headers={"X-Pakhi-Key": globex_key})
    assert resp.status_code == 404

    # Result endpoint enforces the same boundary.
    resp = client.get(f"/v1/backtests/{job_id}/result", headers={"X-Pakhi-Key": globex_key})
    assert resp.status_code == 404


def test_anonymous_cannot_see_secured_job(client):
    _create_tenant(client, "acme")
    key = _create_key(client, "acme")["key"]
    job = _submit_backtest(client, key)
    resp = client.get(f"/v1/backtests/{job['job_id']}")
    assert resp.status_code == 401


def test_jobs_are_stamped_with_tenant(client, tmp_db):
    _create_tenant(client, "acme")
    key = _create_key(client, "acme")["key"]
    _submit_backtest(client, key)
    conn = sqlite3.connect(_store_path(tmp_db))
    row = conn.execute(
        "SELECT tenant_id FROM backtest_jobs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "acme"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_operator_key_denied_admin_routes(client):
    _create_tenant(client, "acme")
    op_key = _create_key(client, "acme", roles=("operator",))["key"]
    headers = {"X-Pakhi-Key": op_key}

    resp = client.post(
        "/v1/admin/tenants",
        headers=headers,
        json={"id": "hacked", "name": "hacked", "tier": "labs"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"

    resp = client.post(
        "/v1/admin/keys", headers=headers, json={"tenant_id": "acme", "roles": ["admin"]}
    )
    assert resp.status_code == 403

    resp = client.post(
        "/v1/admin/tokens",
        headers=headers,
        json={"user_id": "x", "tenant_id": "acme", "roles": ["admin"]},
    )
    assert resp.status_code == 403


def test_ledger_admin_only_when_secured(client):
    _create_tenant(client, "acme")
    op_key = _create_key(client, "acme", roles=("operator",))["key"]
    admin_key = _create_key(client, "acme", roles=("admin",))["key"]

    resp = client.get("/v1/ledger", headers={"X-Pakhi-Key": op_key})
    assert resp.status_code == 403

    resp = client.get("/v1/ledger", headers={"X-Pakhi-Key": admin_key})
    assert resp.status_code == 200
    assert resp.json()["ledger"]["label"] == "paper / not live capital"


def test_ledger_open_in_unauthenticated_dev_posture(tmp_path):
    """No keys configured -> require_auth off -> WS-3 behavior preserved."""
    db = f"sqlite:///{tmp_path / 'plain.db'}"
    settings = Settings(read_db_url=db, write_db_url=db)
    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.get("/v1/ledger")
        assert resp.status_code == 200
        assert resp.json()["ledger"]["scored_count"] == 0


def test_operator_can_read_public_data(client):
    _create_tenant(client, "acme")
    op_key = _create_key(client, "acme", roles=("operator",))["key"]
    resp = client.get("/v1/instruments", headers={"X-Pakhi-Key": op_key})
    # Empty store is an honest 404, but proves operator access passes auth.
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Per-tier rate limiting
# ---------------------------------------------------------------------------


def test_per_tier_rate_limit_headers(client):
    _create_tenant(client, "acme-free")
    _create_tenant(client, "acme-pro", tier="pro")
    free_key = _create_key(client, "acme-free")["key"]
    pro_key = _create_key(client, "acme-pro")["key"]

    resp = client.get("/v1/status", headers={"X-Pakhi-Key": free_key})
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "30"

    resp = client.get("/v1/status", headers={"X-Pakhi-Key": pro_key})
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "120"


def test_ws3_bootstrap_key_still_admin(client):
    resp = client.get("/v1/status", headers=_admin_headers())
    assert resp.status_code == 200
    # Bootstrap key = admin on the default tenant: can create tenants/keys.
    resp = client.post(
        "/v1/admin/tenants",
        headers=_admin_headers(),
        json={"id": "via-bootstrap", "name": "v", "tier": "free"},
    )
    assert resp.status_code == 201
