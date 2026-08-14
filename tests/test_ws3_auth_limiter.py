"""WS-3 T5 tests: Auth enforcement, 401, 429, and X-RateLimit-* header stamping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pakhi.api.auth import hash_key, rate_limiter
from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from tests.ws3_fixtures import seed_store


@pytest.fixture(autouse=True)
def _reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def auth_app(tmp_path):
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    settings = Settings(
        read_db_url=f"sqlite:///{read_db}",
        write_db_url=f"sqlite:///{write_db}",
    )
    app = create_app(settings)
    return app


def test_rate_limit_headers_present(auth_app):
    with TestClient(auth_app) as client:
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers


def test_invalid_api_key_401(tmp_path):
    read_db = tmp_path / "read.db"
    write_db = tmp_path / "write.db"
    seed_store(f"sqlite:///{read_db}")
    seed_store(f"sqlite:///{write_db}")

    valid_key = "secret_key_123"
    valid_hash = hash_key(valid_key)

    settings = Settings(
        read_db_url=f"sqlite:///{read_db}",
        write_db_url=f"sqlite:///{write_db}",
    )
    app = create_app(settings)
    # Inject allowed key into middleware
    from pakhi.api.auth import AuthAndRateLimitMiddleware

    for middleware in app.user_middleware:
        if middleware.cls is AuthAndRateLimitMiddleware:
            middleware.kwargs["allowed_keys"] = {valid_hash}
            middleware.kwargs["require_auth"] = True

    # Re-build app stack
    app.middleware_stack = app.build_middleware_stack()

    with TestClient(app) as client:
        # Missing key -> 401
        res1 = client.get("/v1/health")
        assert res1.status_code == 401

        # Wrong key -> 401
        res2 = client.get("/v1/health", headers={"X-Pakhi-Key": "wrong_key"})
        assert res2.status_code == 401

        # Valid key -> 200
        res3 = client.get("/v1/health", headers={"X-Pakhi-Key": valid_key})
        assert res3.status_code == 200


def test_rate_limit_exceeded_429(auth_app):
    # Set low rate limit on global limiter for testing
    rate_limiter.rate_limit = 2
    rate_limiter.window_seconds = 60

    with TestClient(auth_app) as client:
        r1 = client.get("/v1/health")
        assert r1.status_code == 200

        r2 = client.get("/v1/health")
        assert r2.status_code == 200

        r3 = client.get("/v1/health")
        assert r3.status_code == 429
        err = r3.json()
        assert err["error"]["code"] == "rate_limit_exceeded"
        assert "X-RateLimit-Limit" in r3.headers

    # Restore default rate limit
    rate_limiter.rate_limit = 60
