"""WS-4 T1 — human-lane JWT + refresh tokens.

Proves the T1 exit criteria behaviorally:

- Admin key issues a 15-min HS256 access JWT (claims sub/tenant_id/roles) + a
  refresh token; the refresh token is hashed at rest (never plaintext in the
  store).
- Valid JWT is accepted; expired / malformed / wrong-issuer JWT → 401 locked
  envelope.
- Refresh rotation revokes the old token; reuse of a revoked token revokes the
  whole family (reuse detection).
- The auth-exempt refresh route needs no key/bearer.
- WS-3 ``X-Pakhi-Key`` flow still works untouched (no regression).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.tokens import decode_access_token

ADMIN_KEY = "test-admin-key-123"
JWT_SECRET = "test-jwt-secret-0123456789abcdef"
HUMAN_SECRET = "another-secret"


@pytest.fixture
def tmp_db(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


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


def _issue(client: TestClient, **overrides) -> dict:
    body = {"user_id": "alice", "tenant_id": "tenant-a", "roles": ["admin"], "tier": "pro"}
    body.update(overrides)
    # T2: issuance is gated on the tenant existing — create it first.
    tenant = client.post(
        "/v1/admin/tenants",
        headers={"X-Pakhi-Key": ADMIN_KEY},
        json={"id": body["tenant_id"], "name": body["tenant_id"], "tier": body.get("tier", "free")},
    )
    assert tenant.status_code == 201, tenant.text
    resp = client.post("/v1/admin/tokens", headers={"X-Pakhi-Key": ADMIN_KEY}, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _store_path(tmp_db: str) -> Path:
    return Path(tmp_db.removeprefix("sqlite:///"))


def _row_count(tmp_db: str, table: str) -> int:
    conn = sqlite3.connect(_store_path(tmp_db))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


def test_admin_key_issues_token_pair(client, tmp_db):
    data = _issue(client)
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900
    claims = decode_access_token(data["access_token"], JWT_SECRET)
    assert claims["sub"] == "alice"
    assert claims["tenant_id"] == "tenant-a"
    assert claims["roles"] == ["admin"]
    assert claims["tier"] == "pro"
    # Refresh token is hashed at rest: no plaintext value equals the DB hash cell.
    conn = sqlite3.connect(_store_path(tmp_db))
    row = conn.execute("SELECT token_hash FROM refresh_tokens").fetchone()
    conn.close()
    assert row is not None
    assert row[0] != data["refresh_token"]
    assert len(row[0]) == 64  # sha256 hex
    assert _row_count(tmp_db, "users") == 1


def test_issue_requires_admin_key(client):
    resp = client.post(
        "/v1/admin/tokens",
        headers={"X-Pakhi-Key": "not-a-real-key"},
        json={"user_id": "mallory", "roles": ["admin"]},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_issue_rejects_invalid_roles(client):
    resp = client.post(
        "/v1/admin/tokens",
        headers={"X-Pakhi-Key": ADMIN_KEY},
        json={"user_id": "bob", "roles": ["root"]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# JWT acceptance / rejection
# ---------------------------------------------------------------------------


def test_valid_jwt_accepted_on_admin_route(client):
    data = _issue(client)
    resp = client.post(
        "/v1/admin/tokens",
        headers={"Authorization": f"Bearer {data['access_token']}"},
        json={"user_id": "carol", "roles": ["operator"]},
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == "carol"


def test_expired_jwt_rejected(client):
    from pakhi.ws4.tokens import create_access_token

    token = create_access_token(
        sub="expired-user",
        tenant_id="tenant-a",
        roles=["admin"],
        secret=JWT_SECRET,
        expires_minutes=-1,
    )
    resp = client.post(
        "/v1/admin/tokens",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "x", "roles": ["operator"]},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_malformed_and_wrong_secret_jwt_rejected(client):
    resp = client.post(
        "/v1/admin/tokens",
        headers={"Authorization": "Bearer not.a.jwt"},
        json={"user_id": "x", "roles": ["operator"]},
    )
    assert resp.status_code == 401

    from pakhi.ws4.tokens import create_access_token

    forged = create_access_token(
        sub="eve", tenant_id="tenant-a", roles=["admin"], secret=HUMAN_SECRET
    )
    resp = client.post(
        "/v1/admin/tokens",
        headers={"Authorization": f"Bearer {forged}"},
        json={"user_id": "x", "roles": ["operator"]},
    )
    assert resp.status_code == 401


def test_insufficient_role_rejected_with_403(client):
    data = _issue(client, user_id="viewer1", roles=["viewer"], tenant_id="tenant-a")
    resp = client.post(
        "/v1/admin/tokens",
        headers={"Authorization": f"Bearer {data['access_token']}"},
        json={"user_id": "x", "roles": ["operator"]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# Refresh rotation + reuse detection
# ---------------------------------------------------------------------------


def test_refresh_rotates_and_revokes_old(client, tmp_db):
    from pakhi.ws4.tokens import hash_token

    data = _issue(client)
    resp = client.post("/v1/admin/tokens/refresh", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 200, resp.text
    new = resp.json()
    assert new["refresh_token"] != data["refresh_token"]
    assert new["user_id"] == "alice"
    assert new["tenant_id"] == "tenant-a"

    # Old token now revoked and replaced (replaced_by points at the new hash).
    conn = sqlite3.connect(_store_path(tmp_db))
    row = conn.execute(
        "SELECT revoked_at, replaced_by FROM refresh_tokens WHERE token_hash = ?",
        (hash_token(data["refresh_token"]),),
    ).fetchone()
    conn.close()
    assert row is not None and row[0] is not None
    assert row[1] == hash_token(new["refresh_token"])


def test_refresh_reuse_revokes_family(client, tmp_db):
    data = _issue(client)
    first = client.post(
        "/v1/admin/tokens/refresh", json={"refresh_token": data["refresh_token"]}
    ).json()
    # Presenting the rotated-away token is reuse -> 401 and family revoked.
    resp = client.post("/v1/admin/tokens/refresh", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 401
    # The fresh token from the same family is now dead too.
    resp2 = client.post("/v1/admin/tokens/refresh", json={"refresh_token": first["refresh_token"]})
    assert resp2.status_code == 401
    conn = sqlite3.connect(_store_path(tmp_db))
    revoked = conn.execute(
        "SELECT COUNT(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert revoked == 2


def test_refresh_unknown_token_rejected(client):
    resp = client.post("/v1/admin/tokens/refresh", json={"refresh_token": "x" * 64})
    assert resp.status_code == 401


def test_refresh_route_needs_no_key(client):
    # Explicitly no X-Pakhi-Key header: the refresh token is the credential.
    data = _issue(client)
    resp = client.post("/v1/admin/tokens/refresh", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# WS-3 key flow unchanged
# ---------------------------------------------------------------------------


def test_ws3_key_flow_untouched(client):
    resp = client.get("/v1/status", headers={"X-Pakhi-Key": ADMIN_KEY})
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is True


def test_ws3_key_401_without_credential(client):
    resp = client.get("/v1/status")
    assert resp.status_code == 401
