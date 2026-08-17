"""WS-4 T1: human-lane credentials — HS256 access JWT + opaque refresh tokens.

Pure, import-clean. JWT encoding/decoding (PyJWT, HS256, 15-min access) and
opaque refresh tokens (hashed at rest via SHA-256). Rotation and reuse-revokes
live in ``pakhi.ws4.service`` (they touch the store); this module is the
credential mechanics with no DB dependency.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError

from pakhi.ws4.contract import access_algorithm, access_token_ttl_minutes

ACCESS_TOKEN_TTL_MINUTES = access_token_ttl_minutes()  # locked twin §identity
REFRESH_TOKEN_TTL_DAYS = 30
ACCESS_ALGORITHM = access_algorithm()  # locked twin §identity (single source of truth)

GENESIS_ISSUER = "pakhi"
_ISSUER = GENESIS_ISSUER

# Locked role set (contract §4). Tokens must not carry roles outside this set.
_ALLOWED_ROLES = frozenset({"viewer", "operator", "admin"})


def hash_token(token: str) -> str:
    """SHA-256 hash of a refresh token — the only form stored at rest."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> str:
    """Opaque high-entropy refresh token (shown to the client exactly once)."""
    return secrets.token_urlsafe(48)


def create_access_token(
    *,
    sub: str,
    tenant_id: str,
    roles: list[str],
    secret: str,
    tier: str = "free",
    expires_minutes: int = ACCESS_TOKEN_TTL_MINUTES,
    issuer: str = _ISSUER,
) -> str:
    """Create a short-lived HS256 access JWT with the locked claims."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": sorted(roles),
        "tier": tier,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "iss": issuer,
    }
    return jwt.encode(payload, secret, algorithm=ACCESS_ALGORITHM)


def decode_access_token(token: str, secret: str, issuer: str = _ISSUER) -> dict[str, Any]:
    """Decode + validate signature/exp/iss. Raises ``InvalidTokenError`` on any
    failure (expired, malformed, wrong signature, wrong issuer)."""
    return jwt.decode(
        token,
        secret,
        algorithms=[ACCESS_ALGORITHM],
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "tenant_id", "roles"]},
    )


def claims_to_roles(claims: dict[str, Any]) -> list[str]:
    """Validate/normalize the ``roles`` claim (must be a non-empty list of
    strings drawn from the locked role set; unknown roles are dropped so a
    token can never smuggle in a privilege the contract does not define)."""
    roles = claims.get("roles")
    if not isinstance(roles, list) or not roles or not all(isinstance(r, str) for r in roles):
        raise InvalidTokenError("invalid roles claim")
    allowed = [r for r in roles if r in _ALLOWED_ROLES]
    if not allowed:
        raise InvalidTokenError("invalid roles claim")
    return list(dict.fromkeys(allowed))
