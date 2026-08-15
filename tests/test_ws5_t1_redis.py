"""WS-5 T1 — Redis multi-worker state + fail-closed + multi-worker audit.

Proves the T1 exit criteria:

- ``RedisTokenBucketLimiter`` implements the exact ``check``/``peek`` interface
  and shares one bucket across independent limiter instances backed by the same
  Redis — N workers cannot multiply quota.
- Tokens replenish at the locked fill rate (window_seconds scaling).
- **Fail-closed:** with ``PAKHI_REDIS_URL`` set and Redis unreachable, a
  rate-limited request is 503 ``redis_unavailable`` — never a loosened quota;
  while ``/v1/health`` (liveness) stays 200 through the outage.
- **Single-worker posture byte-identical:** with no Redis URL the in-memory
  path serves X-RateLimit-* headers and consumes quota exactly as WS-3/WS-4.
- **Workers gate:** ``Settings(workers>1)`` without ``PAKHI_REDIS_URL`` is a
  construction error; with it, it boots.
- **Multi-worker audit appends (Postgres-gated):** concurrent appends in
  separate sessions produce a valid, non-colliding chain
  (``verify_chain_in_store`` passes; skipped without ``WS4_TEST_DB_URL``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from pakhi.api.main import create_app
from pakhi.api.settings import Settings
from pakhi.ws4.audit_events import AuditSpec, apply_audit, verify_chain_in_store
from pakhi.ws5.redis_limiter import (
    RedisTokenBucketLimiter,
    RedisUnavailableError,
)

JWT_SECRET = "test-jwt-secret-0123456789abcdef"
ADMIN_KEY = "test-admin-key-123"


# ---------------------------------------------------------------------------
# Shared bucket across limiter instances (the multi-worker guarantee)
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


def _two_limiters(server: fakeredis.FakeServer, rate_limit: int = 30):
    a = RedisTokenBucketLimiter(
        fakeredis.FakeRedis(server=server), rate_limit=rate_limit, window_seconds=60
    )
    b = RedisTokenBucketLimiter(
        fakeredis.FakeRedis(server=server), rate_limit=rate_limit, window_seconds=60
    )
    return a, b


def test_shared_bucket_cannot_multiply_quota(redis_server):
    a, b = _two_limiters(redis_server, rate_limit=5)
    for i in range(5):
        assert a.check("key:alice")[0] is True, f"worker A request {i}"
    # Worker B sees the SAME bucket: exhausted, not a fresh 5.
    allowed, limit, remaining, _ = b.check("key:alice")
    assert allowed is False
    assert limit == 5 and remaining == 0
    # A distinct key still has its own full bucket.
    assert b.check("key:bob")[0] is True


def test_redis_limiter_replenishes_at_fill_rate(redis_server):
    limiter = RedisTokenBucketLimiter(
        fakeredis.FakeRedis(server=redis_server), rate_limit=2, window_seconds=1
    )
    assert limiter.check("k")[0] and limiter.check("k")[0]
    assert limiter.check("k")[0] is False
    time.sleep(0.7)  # fill = 2 tokens/sec -> +1 token
    assert limiter.check("k")[0] is True


def test_peek_is_non_consuming(redis_server):
    limiter = RedisTokenBucketLimiter(
        fakeredis.FakeRedis(server=redis_server), rate_limit=3, window_seconds=60
    )
    assert limiter.peek("k") == (3, 3, 0)
    assert limiter.peek("k") == (3, 3, 0)  # twice: still 3, nothing consumed


def test_redis_limiter_same_interface_as_in_memory(redis_server):
    from pakhi.api.auth import TokenBucketLimiter

    mem = TokenBucketLimiter(rate_limit=3, window_seconds=60)
    rds = RedisTokenBucketLimiter(
        fakeredis.FakeRedis(server=redis_server), rate_limit=3, window_seconds=60
    )
    assert rds.check("k") == mem.check("k")  # (allowed, limit, remaining, reset)
    assert rds.peek("k") == mem.peek("k")


# ---------------------------------------------------------------------------
# Fail-closed 503 (Redis configured but down) + liveness survives
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_down_app():
    # 127.0.0.1:1 -> instant ECONNREFUSED; URL set => multi-worker posture.
    settings = Settings(
        read_db_url=f"sqlite:///{Path('/tmp/ws5-rl-down.db')}",
        write_db_url=f"sqlite:///{Path('/tmp/ws5-rl-down.db')}",
        jwt_secret=JWT_SECRET,
        redis_url="redis://127.0.0.1:1/0",
    )
    return create_app(settings)


def test_redis_down_is_503_not_loosened_quota(redis_down_app):
    with TestClient(redis_down_app) as client:
        resp = client.get("/v1/instruments", headers={"X-Pakhi-Key": ADMIN_KEY})
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "redis_unavailable"


def test_health_is_fail_closed_503_in_t1(redis_down_app):
    # WS-5 T4: /v1/health is DB-free probe liveness and stays 200 through the
    # outage. The deep /v1/status page is rate-limited (contract §6), so a down
    # shared store is a fail-closed 503 there — never a loosened or silent quota.
    with TestClient(redis_down_app) as client:
        probe = client.get("/v1/health")
        assert probe.status_code == 200
        assert probe.json() == {"status": "ok"}

        resp = client.get("/v1/status")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "redis_unavailable"


def test_redis_unavailable_exception_carries_cause():
    import redis

    bad = redis.Redis.from_url("redis://127.0.0.1:1/0")
    limiter = RedisTokenBucketLimiter(bad, rate_limit=1, window_seconds=60)
    with pytest.raises(RedisUnavailableError):
        limiter.check("k")


# ---------------------------------------------------------------------------
# Single-worker posture byte-identical (no Redis URL)
# ---------------------------------------------------------------------------


def test_unset_redis_keeps_in_memory_tier_buckets(tmp_path):
    # Same posture as test_ws4_t2: ws4 enabled, bootstrap admin key -> the
    # per-tier in-memory buckets (free=30) that Redis replaces when a URL is
    # set. Proves the no-Redis path stays byte-identical to WS-3/WS-4.
    db = f"sqlite:///{tmp_path / 'store.db'}"
    settings = Settings(
        read_db_url=db,
        write_db_url=db,
        api_keys=(ADMIN_KEY,),
        jwt_secret=JWT_SECRET,
        jwt_issuer="pakhi",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert app.state.redis_url is None
        r1 = client.get("/v1/instruments", headers={"X-Pakhi-Key": ADMIN_KEY})
        assert r1.status_code == 404  # empty store, but auth+limit worked
        assert r1.headers["X-RateLimit-Limit"] == "30"
        remaining_1 = int(r1.headers["X-RateLimit-Remaining"])
        r2 = client.get("/v1/instruments", headers={"X-Pakhi-Key": ADMIN_KEY})
        remaining_2 = int(r2.headers["X-RateLimit-Remaining"])
        assert remaining_2 == remaining_1 - 1  # quota consumed, in-memory


def test_health_remains_rate_limited_in_t1(tmp_path):
    # WS-5 T4: /v1/health is liveness (no rate headers, no auth); deep page
    # /v1/status carries the X-RateLimit-* headers (contract §6).
    db = f"sqlite:///{tmp_path / 'store.db'}"
    settings = Settings(read_db_url=db, write_db_url=db, api_keys=(ADMIN_KEY,))
    app = create_app(settings)
    with TestClient(app) as client:
        probe = client.get("/v1/health")
        assert probe.status_code == 200
        assert "X-RateLimit-Limit" not in probe.headers

        resp = client.get("/v1/status", headers={"X-Pakhi-Key": ADMIN_KEY})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers


# ---------------------------------------------------------------------------
# Workers gate
# ---------------------------------------------------------------------------


def test_workers_gt_one_requires_redis():
    with pytest.raises(ValueError, match="PAKHI_WORKERS > 1"):
        Settings(read_db_url="sqlite:///x.db", write_db_url="sqlite:///x.db", workers=2)
    s = Settings(
        read_db_url="sqlite:///x.db",
        write_db_url="sqlite:///x.db",
        workers=2,
        redis_url="redis://localhost:6379/0",
    )
    assert s.workers == 2 and s.redis_url


# ---------------------------------------------------------------------------
# Real-Redis gate (runs under the ws4-security workflow's redis container)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set (runs under the ws4-security workflow)",
)
def test_real_redis_limiter_matches_in_memory():
    import redis

    from pakhi.api.auth import TokenBucketLimiter

    mem = TokenBucketLimiter(rate_limit=10, window_seconds=60)
    rds = RedisTokenBucketLimiter(
        redis.Redis.from_url(os.environ["REDIS_URL"]),
        rate_limit=10,
        window_seconds=60,
    )
    key = "real-redis-gate"
    for _ in range(10):
        assert rds.check(key) == mem.check(key)
    assert rds.check(key)[0] is False
    assert rds.peek(key) == mem.peek(key)


# ---------------------------------------------------------------------------
# Multi-worker audit appends (Postgres-gated, runs in ws4-security CI)
# ---------------------------------------------------------------------------

PG_URL = os.environ.get("WS4_TEST_DB_URL")


@pytest.mark.skipif(
    not PG_URL,
    reason="WS4_TEST_DB_URL not set (runs under the ws4-security workflow)",
)
def test_concurrent_audit_appends_chain_valid():
    import threading

    import sqlalchemy
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from pakhi.ws4.audit_events import query_audit
    from pakhi.ws4.db import init_db, migrate

    engine = create_engine(PG_URL)
    init_db(engine)
    migrate(engine)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("TRUNCATE audit_events RESTART IDENTITY"))

    def append(tag: str) -> None:
        with Session(engine) as session:
            apply_audit(
                session,
                AuditSpec(
                    request_id=f"req-{tag}",
                    tenant_id="pg-audit",
                    actor_id="ci",
                    action="concurrent.test",
                    resource="audit_events",
                ),
            )
            session.commit()

    threads = [threading.Thread(target=append, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = query_audit(engine, action="concurrent.test")
    assert len(rows) == 8
    prev_hashes = {r["prev_hash"] for r in rows}
    assert len(prev_hashes) == 8  # all eight links distinct
    ok, bad = verify_chain_in_store(engine)
    assert ok is True, f"chain broken at {bad}"
    engine.dispose()
