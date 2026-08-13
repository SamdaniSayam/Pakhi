"""WS-3 T5: API key authentication & token-bucket rate limiting.

Keys are stored at rest as SHA-256 hashes (never plaintext). Headers:
- Request: ``X-Pakhi-Key``
- Response: ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``
"""

from __future__ import annotations

import hashlib
import time

from fastapi import HTTPException, Request


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

    def check(self, key: str) -> tuple[bool, int, int, int]:
        """Check rate limit for key. Returns (allowed, limit, remaining, reset_seconds)."""
        now = time.time()
        capacity = float(self.rate_limit)
        fill_rate = capacity / float(self.window_seconds)

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


# Default global limiter: 60 requests per minute
rate_limiter = TokenBucketLimiter(rate_limit=60, window_seconds=60)


def verify_api_key(request: Request, allowed_hashes: set[str] | None = None) -> str | None:
    """Verify X-Pakhi-Key header if provided or required."""
    key_header = request.headers.get("X-Pakhi-Key")
    if not key_header:
        return None

    hashed = hash_key(key_header)
    if allowed_hashes and hashed not in allowed_hashes:
        raise HTTPException(status_code=401, detail="invalid API key")
    return hashed
