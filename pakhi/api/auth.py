"""WS-3 T5: API key authentication & thread-safe token-bucket rate limiting.

Keys are stored at rest as SHA-256 hashes (never plaintext). Headers on all responses:
- Request: ``X-Pakhi-Key``
- Response: ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pakhi.api.errors import error_body

def hash_key(key: str) -> str:
    """Compute SHA-256 hash of API key."""
    return hashlib.sha256(key.strip().encode()).hexdigest()


class TokenBucketLimiter:
    """In-memory thread-safe token bucket rate limiter per API key / IP."""

    def __init__(self, rate_limit: int = 60, window_seconds: int = 60) -> None:
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self._tokens: dict[str, float] = {}
        self._last_updated: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int, int, int]:
        """Check rate limit for key. Returns (allowed, limit, remaining, reset_seconds)."""
        now = time.time()
        capacity = float(self.rate_limit)
        fill_rate = capacity / float(self.window_seconds)

        with self._lock:
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

    def reset(self) -> None:
        """Reset internal bucket state (used for clean test isolation)."""
        with self._lock:
            self._tokens.clear()
            self._last_updated.clear()


# Default global limiter: 60 requests per minute
rate_limiter = TokenBucketLimiter(rate_limit=60, window_seconds=60)


class AuthAndRateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing X-Pakhi-Key auth and X-RateLimit-* headers on all responses."""

    def __init__(
        self,
        app: Any,
        allowed_keys: set[str] | None = None,
        require_auth: bool = False,
        limiter: TokenBucketLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self.allowed_keys = allowed_keys or set()
        self.require_auth = require_auth
        self.limiter = limiter or rate_limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        key_header = request.headers.get("X-Pakhi-Key") or request.query_params.get("key")
        client_id = "anonymous"

        if key_header:
            hashed = hash_key(key_header)
            if self.allowed_keys and hashed not in self.allowed_keys:
                return JSONResponse(
                    status_code=401,
                    content=error_body("unauthorized", "invalid API key"),
                )
            client_id = f"key_{hashed[:12]}"
        elif self.require_auth:
            return JSONResponse(
                status_code=401,
                content=error_body("unauthorized", "missing required X-Pakhi-Key header"),
            )

        if not client_id or client_id == "anonymous":
            client_id = request.client.host if request.client else "127.0.0.1"

        # Rate limit check
        allowed, limit, remaining, reset_secs = self.limiter.check(client_id)
        if not allowed:
            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_secs),
            }
            return JSONResponse(
                status_code=429,
                content=error_body("rate_limit_exceeded", "rate limit exceeded"),
                headers=headers,
            )

        response = await call_next(request)

        # Stamp rate limit headers on all responses
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_secs)
        return response
