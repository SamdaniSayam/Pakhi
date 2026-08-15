"""WS-4 T3 — secrets management.

Proves the T3 exit criteria behaviorally:

- The tracked tree carries no secret-shaped value (tree-walk scan passes) and
  no committed ``.env``.
- A weak JWT secret is a construction/boot error (Settings raises), never a
  served 500 — the test asserts the response cannot even exist.
- A missing secret is a boot error when WS-4 is enabled; the WS-3 key-only
  dev posture still boots and serves (old env-key path stays green).
- DB-stored API keys are prefix-hashed (no plaintext at rest) — the T2 property
  re-asserted here as the T3 "no plaintext key in the store" check.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.secret_scan import scan_tree

GOOD_SECRET = "a-really-long-jwt-signing-key-0123456789abcdef"
ADMIN_KEY = "test-admin-key-123"


def _tmp_db(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'store.db'}"


# ---------------------------------------------------------------------------
# Tree-walk scan
# ---------------------------------------------------------------------------


def test_tracked_tree_has_no_secret_shaped_values():
    findings = scan_tree()
    assert findings == [], f"secret scan found: {findings}"


def test_no_committed_dotenv():
    root = Path(__file__).resolve().parents[1]
    findings = scan_tree(root)
    assert not any(f.rule == "dotenv" for f in findings)
    # And it is not even a tracked file (gitignore honored).
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Fail-fast secret gate
# ---------------------------------------------------------------------------


def test_weak_secret_is_boot_error_not_served_response(tmp_path):
    # Weak (too short): Settings() raises before any app can serve a 500.
    with pytest.raises(ValueError, match="weak"):
        Settings(read_db_url=_tmp_db(tmp_path), write_db_url=_tmp_db(tmp_path), jwt_secret="short")


def test_obvious_default_secret_is_boot_error(tmp_path):
    # Long enough to pass the length floor but still an obvious default.
    with pytest.raises(ValueError, match="obvious default"):
        Settings(
            read_db_url=_tmp_db(tmp_path), write_db_url=_tmp_db(tmp_path), jwt_secret="changeme" * 4
        )


def test_missing_secret_refuses_boot_when_ws4_enabled(tmp_path):
    env = {"PAKHI_WS4_ENABLED": "1"}
    with pytest.raises(ValueError, match="required"):
        Settings.from_env(env)


def test_missing_secret_allowed_in_ws3_dev_posture(tmp_path):
    # No WS-4: the key-only path boots and serves (old env-key path stays green).
    settings = Settings(
        read_db_url=_tmp_db(tmp_path), write_db_url=_tmp_db(tmp_path), api_keys=(ADMIN_KEY,)
    )
    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.get("/v1/health", headers={"X-Pakhi-Key": ADMIN_KEY})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_strong_secret_boots_with_ws4(tmp_path):
    settings = Settings(
        read_db_url=_tmp_db(tmp_path),
        write_db_url=_tmp_db(tmp_path),
        jwt_secret=GOOD_SECRET,
        ws4_enabled=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200


def test_ws4_enabled_from_env_with_strong_secret(tmp_path):
    env = {
        "PAKHI_WS4_ENABLED": "1",
        "PAKHI_JWT_SECRET": GOOD_SECRET,
        "PAKHI_DB_READ_URL": _tmp_db(tmp_path),
        "PAKHI_DB_WRITE_URL": _tmp_db(tmp_path),
    }
    settings = Settings.from_env(env)
    assert settings.ws4_enabled is True
    assert settings.jwt_secret == GOOD_SECRET


# ---------------------------------------------------------------------------
# No plaintext key at rest (T2 property re-asserted)
# ---------------------------------------------------------------------------


def test_db_api_key_is_hashed_not_plaintext(tmp_path):
    from pakhi.ws4.service import create_api_key, upsert_tenant

    db_url = _tmp_db(tmp_path)
    settings = Settings(read_db_url=db_url, write_db_url=db_url, jwt_secret=GOOD_SECRET)
    app = create_app(settings)
    # Seed directly through the service (no HTTP round-trip); the TestClient
    # enter/exit only runs lifespan so the tables exist for the service calls.
    with TestClient(app):
        upsert_tenant(app.state.write_engine, tenant_id="acme", name="acme")
        created = create_api_key(
            app.state.write_engine, tenant_id="acme", environment="test", roles=["operator"]
        )
    conn = sqlite3.connect(db_url.removeprefix("sqlite:///"))
    digest = conn.execute("SELECT key_hash FROM api_keys").fetchone()[0]
    conn.close()
    assert digest != created.key
    assert len(digest) == 64
