"""WS-5 T1: Redis-backed token bucket — shared rate-limit state across workers.

Implements the exact ``check``/``peek`` interface of
``pakhi.api.auth.TokenBucketLimiter`` so middleware code never branches on
storage backend. Bucket mutations are atomic via a single Lua script (one
round-trip, no torn read-modify-write across processes).

Fail-closed discipline (locked in the reliability contract §4): when
``PAKHI_REDIS_URL`` is set and Redis is unreachable, every rate-limited request
fails with 503 — quota is never silently lifted or over-counted across workers.
With the URL unset the in-memory single-worker path is unchanged and byte
identical to WS-3/WS-4.

``pakhi.ws5`` core stays import-clean: ``redis`` is imported lazily inside
methods/factories, never at package import.
"""

from __future__ import annotations

import time
from typing import Any

_KEY_CHECK = """
local key = KEYS[1]
local ts_key = KEYS[2]
local capacity = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local fill = capacity / window
local last = tonumber(redis.call('GET', ts_key) or ARGV[3])
local tokens = math.min(capacity, tonumber(redis.call('GET', key) or capacity) + (now - last) * fill)
local expire = window * 2
if tokens >= 1 then
    tokens = tokens - 1
    redis.call('SET', key, tokens, 'EX', expire)
    redis.call('SET', ts_key, now, 'EX', expire)
    local remaining = math.floor(tokens)
    local reset = math.floor((capacity - tokens) / fill)
    return {1, capacity, remaining, reset}
else
    redis.call('SET', key, tokens, 'EX', expire)
    redis.call('SET', ts_key, now, 'EX', expire)
    local remaining = math.floor(tokens)
    local reset = math.floor((1 - tokens) / fill) + 1
    return {0, capacity, remaining, reset}
end
"""

_PEEK_LUA = """
local key = KEYS[1]
local ts_key = KEYS[2]
local capacity = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local fill = capacity / window
local last = tonumber(redis.call('GET', ts_key) or ARGV[3])
local tokens = math.min(capacity, tonumber(redis.call('GET', key) or capacity) + (now - last) * fill)
local remaining = math.floor(tokens)
local reset = math.floor((capacity - tokens) / fill)
return {capacity, remaining, reset}
"""


class RedisUnavailableError(RuntimeError):
    """Raised by Redis-backed limiters when the shared store is unreachable.

    The middleware maps this to the locked fail-closed 503 — never a silently
    loosened or over-counted quota."""


def _wrap(fn):
    def _inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except RedisUnavailableError:
            raise
        except Exception as exc:  # redis.ConnectionError, TimeoutError, ...
            raise RedisUnavailableError(f"Redis unreachable: {exc}") from exc

    return _inner


class RedisTokenBucketLimiter:
    """Token bucket whose state lives in a shared Redis (any client with the
    ``redis`` command surface — a real server or fakeredis in tests)."""

    def __init__(
        self,
        client: Any,
        rate_limit: int,
        window_seconds: int = 60,
        key_prefix: str = "pakhi:rl:",
    ) -> None:
        self.client = client
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self._check = client.register_script(_KEY_CHECK)
        self._peek = client.register_script(_PEEK_LUA)

    def _keys(self, key: str) -> list[str]:
        return [f"{self.key_prefix}{key}", f"{self.key_prefix}{key}:ts"]

    def check(self, key: str) -> tuple[bool, int, int, int]:
        """Consume one token. Returns ``(allowed, limit, remaining, reset_secs)``."""
        res = _wrap(self._check)(
            keys=self._keys(key),
            args=[self.rate_limit, self.window_seconds, time.time()],
        )
        allowed, limit, remaining, reset = (int(v) for v in res)
        return bool(allowed), limit, remaining, reset

    def peek(self, key: str) -> tuple[int, int, int]:
        """Non-consuming view: ``(limit, remaining, reset_secs)``."""
        res = _wrap(self._peek)(
            keys=self._keys(key),
            args=[self.rate_limit, self.window_seconds, time.time()],
        )
        limit, remaining, reset = (int(v) for v in res)
        return limit, remaining, reset

    def reset(self) -> None:
        """No-op for the shared store — buckets are global by design; a boot
        must not wipe shared quota. (In-memory limiters keep their reset.)"""


def build_tier_limiters(
    tier_limits: dict[str, int],
    *,
    redis_url: str | None,
    window_seconds: int = 60,
    workers: int = 1,
) -> tuple[dict[str, Any], Any | None]:
    """Build ``{tier: limiter}`` from the contract tier map.

    ``redis_url`` unset -> in-memory ``TokenBucketLimiter`` per tier (the WS-3/
    WS-4 single-worker posture, byte-identical). Set -> one ``redis`` client
    shared by every tier's ``RedisTokenBucketLimiter`` (multi-worker safe).
    Returns ``(tier_limiters, redis_client_or_None)``.

    Multi-worker without ``redis_url`` is fail-open on rate limits (each worker
    counts its own quota), so it is a hard boot error — mirroring the Prometheus
    multiprocess guard. ``Settings`` already rejects this; this guard is the
    defense-in-depth check at the limiter boundary.
    """
    if workers > 1 and not redis_url:
        raise ValueError(
            "workers > 1 requires PAKHI_REDIS_URL (shared rate-limit state); "
            "running multi-worker with in-memory buckets fails open on limits"
        )
    if not redis_url:
        from pakhi.api.auth import TokenBucketLimiter

        return {
            tier: TokenBucketLimiter(rate_limit=limit, window_seconds=window_seconds)
            for tier, limit in tier_limits.items()
        }, None
    import redis

    client = redis.Redis.from_url(redis_url)
    return {
        tier: RedisTokenBucketLimiter(client, rate_limit=limit, window_seconds=window_seconds)
        for tier, limit in tier_limits.items()
    }, client
