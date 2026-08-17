"""WS-3 T5: API key authentication & thread-safe token-bucket rate limiting.

Keys are stored at rest as SHA-256 hashes (never plaintext). Headers on all responses:
- Request: ``X-Pakhi-Key``
- Response: ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``

The ``AuthAndRateLimitMiddleware`` enforces the contract's key policy (unknown key
→ 401) and token-bucket limits (exceeded → 429), and stamps the ``X-RateLimit-*``
headers on every response it passes through. It is wired in ``create_app`` and
takes its allowed keys from ``Settings.api_keys`` (PAKHI_API_KEYS env /
``data/ws3/api_keys.json``). When no keys are configured, auth is disabled so the
API stays usable by default; once any key is configured, every request must carry
a valid key.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pakhi.api.errors import error_body
from pakhi.api.settings import API_VERSION

# WS-5 T1: Redis-backed buckets raise this when the shared store is unreachable;
# the middleware maps it to the locked fail-closed 503 (never a loosened quota).
from pakhi.ws5.redis_limiter import RedisUnavailableError

# WS-4 T1: the human-lane refresh endpoint is authenticated by the opaque
# refresh token in its body, not by a key/bearer, so both middlewares treat it
# as auth-exempt (still rate-limited by client IP).
AUTH_EXEMPT_PATHS = {"/v1/admin/tokens/refresh"}


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def hash_key(key: str) -> str:
    """Compute SHA-256 hash of API key."""
    return hashlib.sha256(key.strip().encode()).hexdigest()


class TokenBucketLimiter:
    """In-memory token bucket rate limiter per API key / IP.

    ``check`` and ``peek`` are serialized with a lock: sync ``def`` handlers run
    in the anyio threadpool, so concurrent requests must never interleave the
    read-modify-write on the token dictionaries.
    """

    def __init__(self, rate_limit: int = 60, window_seconds: int = 60) -> None:
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self._tokens: dict[str, float] = {}
        self._last_updated: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup_expired(self, now: float) -> None:
        """Periodic cleanup of expired tokens to prevent memory leaks."""
        if now - self._last_cleanup > self.window_seconds * 2:
            expired = [k for k, last in self._last_updated.items() if now - last > self.window_seconds]
            for k in expired:
                del self._last_updated[k]
                self._tokens.pop(k, None)
            self._last_cleanup = now

    def check(self, key: str) -> tuple[bool, int, int, int]:
        """Check rate limit for key. Returns (allowed, limit, remaining, reset_seconds)."""
        now = time.time()
        capacity = float(self.rate_limit)
        fill_rate = capacity / float(self.window_seconds)

        with self._lock:
            self._cleanup_expired(now)
            last = self._last_updated.get(key, now)
            tokens = self._tokens.get(key, capacity)

            # Replenish tokens
            elapsed = now - last
            tokens = min(capacity, tokens + elapsed * fill_rate)

            if tokens >= 1.0:
                tokens -= 1.0
                self._tokens[key] = tokens
                self._last_updated[key] = now
                remaining = int(tokens)
                reset_secs = int((capacity - tokens) / fill_rate)
                return True, self.rate_limit, remaining, reset_secs

            remaining = 0
            reset_secs = int((1.0 - tokens) / fill_rate) + 1
            return False, self.rate_limit, remaining, reset_secs

    def peek(self, key: str) -> tuple[int, int, int]:
        """Non-consuming view of the bucket: (limit, remaining, reset_seconds).

        Used for preflight (OPTIONS) responses, which must carry the headers but
        must never be rejected or consume quota.
        """
        now = time.time()
        capacity = float(self.rate_limit)
        fill_rate = capacity / float(self.window_seconds)

        with self._lock:
            self._cleanup_expired(now)
            last = self._last_updated.get(key, now)
            tokens = min(capacity, self._tokens.get(key, capacity) + (now - last) * fill_rate)
            remaining = int(tokens)
            reset_secs = int((capacity - tokens) / fill_rate)
            return self.rate_limit, remaining, reset_secs

    def reset(self) -> None:
        """Reset internal bucket state (used for clean test isolation / app startup)."""
        with self._lock:
            self._tokens.clear()
            self._last_updated.clear()


# Default global limiter: 60 requests per minute. Reset on app startup so tests
# and deployments each start from a clean bucket.
rate_limiter = TokenBucketLimiter(rate_limit=60, window_seconds=60)


class AuthAndRateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing X-Pakhi-Key auth and X-RateLimit-* headers on all responses.

    CORS preflights (OPTIONS) are passed straight through after stamping the
    rate-limit headers — they never consume quota and are never rejected, so
    the locked CORS contract (preflight → 204/200 with allow headers) holds
    even when auth is enabled.
    """

    def __init__(
        self,
        app: Any,
        allowed_keys: set[str] | None = None,
        require_auth: bool = False,
        limiter: TokenBucketLimiter | None = None,
        tier_limiters: dict[str, TokenBucketLimiter] | None = None,
        db_key_validator: Callable[[Request, str], bool] | None = None,
    ) -> None:
        super().__init__(app)
        self.allowed_keys = allowed_keys or set()
        self.require_auth = require_auth
        self.limiter = limiter or rate_limiter
        # WS-4 T2: per-tier buckets (free/pro/labs) resolved from ws4_scope,
        # which the outer Ws4AuthMiddleware sets before this one runs. When no
        # scope/tier (no jwt_secret configured), falls back to the global one.
        self.tier_limiters = tier_limiters or {}
        # WS-4 T2: DB per-tenant keys are valid credentials too. Bootstrap keys
        # stay validated against allowed_keys; anything else must pass this
        # validator (DB lookup, fail-closed on DB errors).
        self.db_key_validator = db_key_validator

    def _limiter_for(self, scope: Any) -> TokenBucketLimiter:
        tier = getattr(scope, "tier", None) if scope is not None else None
        if tier and tier in self.tier_limiters:
            return self.tier_limiters[tier]
        return self.limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # WS-5 T4: /v1/health is now DB-free probe liveness — exempt from auth
        # AND rate limiting (probes must never poison the anonymous bucket and
        # must stay green through a Redis outage). Deep readiness/freshness
        # moved to /v1/status (rate-limited, authed, cached — contract §6).
        # WS-5 T2: /metrics is unauthenticated, admin network only (contract
        # §3.2) — never 401/429, never quota consumption; network ACL is the
        # deployment's job, not a request header.
        if request.url.path in ("/metrics", "/v1/health", "/v1/billing/webhook"):
            return await call_next(request)

        key_header = request.headers.get("X-Pakhi-Key") or request.query_params.get("key")
        bearer = _bearer_token(request)
        is_refresh = request.url.path in AUTH_EXEMPT_PATHS
        scope = getattr(request.state, "ws4_scope", None)
        limiter = self._limiter_for(scope)

        # CORS preflight: never 401/429, never consume quota — headers only.
        # Auth-exempt paths (WS-4 refresh) behave the same: rate-limited, never
        # rejected for missing credentials.
        if request.method == "OPTIONS" or (is_refresh and not key_header and not bearer):
            client = self._client_id(request, key_header, bearer, scope)
            try:
                limit, remaining, reset_secs = limiter.peek(client)
            except RedisUnavailableError:
                return self._redis_503(request)
            response = await call_next(request)
            self._stamp_rate_headers(response, limit, remaining, reset_secs)
            return response

        if key_header:
            hashed = hash_key(key_header)
            if self.allowed_keys and hashed not in self.allowed_keys:
                valid_db_key = bool(
                    self.db_key_validator and self.db_key_validator(request, hashed)
                )
                if not valid_db_key:
                    return self._auth_error(request, 401, "unauthorized", "invalid API key")
            client = f"key_{hashed[:12]}"
        elif bearer:
            # WS-4 human lane: the JWT itself is validated by Ws4AuthMiddleware
            # (runs outside this one); here it only consumes quota — keyed per
            # user (sub) via the resolved scope, against the user's tier bucket.
            client = self._client_id(request, None, bearer, scope)
        elif self.require_auth:
            return self._auth_error(
                request, 401, "unauthorized", "missing required X-Pakhi-Key header"
            )
        else:
            client = request.client.host if request.client else "127.0.0.1"

        try:
            allowed, limit, remaining, reset_secs = limiter.check(client)
        except RedisUnavailableError:
            return self._redis_503(request)
        if not allowed:
            from pakhi.ws5 import metrics as ws5_metrics

            ws5_metrics.record_ratelimit_rejection(getattr(scope, "tier", None) or "anonymous")
            return self._auth_error(
                request,
                429,
                "rate_limit_exceeded",
                "rate limit exceeded",
                limit=limit,
                remaining=remaining,
                reset_secs=reset_secs,
            )

        response = await call_next(request)
        self._stamp_rate_headers(response, limit, remaining, reset_secs)
        return response

    @staticmethod
    def _client_id(
        request: Request,
        key_header: str | None,
        bearer: str | None = None,
        scope: Any | None = None,
    ) -> str:
        if key_header:
            return f"key_{hash_key(key_header)[:12]}"
        actor_id = getattr(scope, "actor_id", None)
        if bearer and actor_id:
            return f"user_{actor_id}"
        return request.client.host if request.client else "127.0.0.1"

    @staticmethod
    def _stamp_rate_headers(response: Response, limit: int, remaining: int, reset_secs: int):
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_secs)

    @staticmethod
    def _redis_503(request: Request) -> JSONResponse:
        """WS-5 fail-closed: shared rate-limit store unreachable -> 503, never a
        loosened or over-counted quota across workers. The response is tagged so
        the WS-5 error-budget ledger records it as *fail-closed* (contract §2:
        planned fail-closed 503s are recorded separately, never hidden)."""
        request.state.ws5_fail_closed = True
        return JSONResponse(
            status_code=503,
            content=error_body(
                "redis_unavailable",
                "rate-limit store unavailable (multi-worker mode)",
            ),
        )

    def _auth_error(
        self,
        request: Request,
        status: int,
        code: str,
        message: str,
        *,
        limit: int | None = None,
        remaining: int | None = None,
        reset_secs: int | None = None,
    ) -> JSONResponse:
        """Build the locked-envelope error. This middleware runs outside
        RequestContextMiddleware, so it stamps the contract headers itself."""
        response = JSONResponse(
            status_code=status,
            content=error_body(code, message),
        )
        response.headers["X-Pakhi-Version"] = API_VERSION
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID") or "-"
        if limit is not None:
            self._stamp_rate_headers(response, limit, remaining, reset_secs)
        return response
