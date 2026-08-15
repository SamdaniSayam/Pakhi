"""WS-4 T1: identity-resolution middleware — sets ``request.state.ws4_scope``.

Added *outside* ``AuthAndRateLimitMiddleware`` (last added = outermost), so it
resolves identity before handlers run, while key validity and rate limiting
stay with the WS-3 middleware. Resolves the single ``TenantScope`` from either
lane:

- **Human:** validate the ``Authorization: Bearer`` HS256 JWT (signature, exp,
  iss, required claims) → scope from claims.
- **Machine:** ``X-Pakhi-Key`` present → bootstrap-key scope. T1 keys are the
  env/file bootstrap keys and carry the ``admin`` grant (§3.1 bootstrap/admin
  key); T2 maps DB per-tenant keys to their stored roles (default ``operator``)
  and keeps env/file keys as bootstrap admin.
- **Neither:** anonymous ``viewer`` (health, preflight, the auth-exempt refresh
  path which authenticates its own body credential).

WS-3 key flow is byte-identical: key *validity* is still enforced by
``AuthAndRateLimitMiddleware``; this middleware never rejects a request for a
bad key.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError
from starlette.middleware.base import BaseHTTPMiddleware

from pakhi.api.auth import AUTH_EXEMPT_PATHS, _bearer_token, hash_key
from pakhi.api.errors import error_body
from pakhi.api.settings import API_VERSION
from pakhi.ws4.service import lookup_key
from pakhi.ws4.tenant import DEFAULT_TENANT_ID, TenantScope
from pakhi.ws4.tokens import claims_to_roles, decode_access_token


class Ws4AuthMiddleware(BaseHTTPMiddleware):
    """Resolve ``request.state.ws4_scope`` from the human/machine lanes."""

    def __init__(self, app: Any, jwt_secret: str, issuer: str = "pakhi") -> None:
        super().__init__(app)
        self.jwt_secret = jwt_secret
        self.issuer = issuer

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        bearer = _bearer_token(request)

        if path in AUTH_EXEMPT_PATHS:
            request.state.ws4_scope = TenantScope(actor_type="anonymous")
            return await call_next(request)

        if bearer is not None:
            try:
                claims = decode_access_token(bearer, self.jwt_secret, issuer=self.issuer)
                roles = claims_to_roles(claims)
            except InvalidTokenError:
                return self._auth_error(request, "invalid or expired access token")
            scope = TenantScope(
                tenant_id=claims["tenant_id"],
                roles=frozenset(roles),
                actor_id=claims["sub"],
                actor_type="human",
                tier=claims.get("tier", "free"),
                scoped=True,
            )
        elif request.headers.get("X-Pakhi-Key") or request.query_params.get("key"):
            raw = request.headers.get("X-Pakhi-Key") or request.query_params.get("key")
            scope = self._machine_scope(request, hash_key(raw), raw)
        else:
            scope = TenantScope(actor_type="anonymous")

        request.state.ws4_scope = scope
        return await call_next(request)

    def _machine_scope(self, request: Request, key_hash: str, raw: str) -> TenantScope:
        """Machine lane: DB per-tenant key wins if present; otherwise the
        env/file bootstrap key = admin on the default tenant (§3.1). DB down:
        fall through to bootstrap so the WS-3 Auth middleware's independent
        hash validation still decides — DB-only keys fail closed there."""
        engine = getattr(request.app.state, "write_engine", None)
        if engine is not None:
            try:
                ident = lookup_key(engine, key_hash)
            except Exception:
                ident = None
            if ident is not None:
                return TenantScope(
                    tenant_id=ident.tenant_id,
                    roles=frozenset(ident.roles),
                    actor_id=f"key_{ident.key_id}",
                    actor_type="machine",
                    tier=ident.tier,
                    scoped=True,
                )
        return TenantScope(
            tenant_id=DEFAULT_TENANT_ID,
            roles=frozenset(("admin",)),
            actor_id=f"key_{key_hash[:12]}",
            actor_type="machine",
            scoped=True,
        )

    def _auth_error(self, request: Request, message: str) -> JSONResponse:
        response = JSONResponse(
            status_code=401,
            content=error_body("unauthorized", message),
        )
        response.headers["X-Pakhi-Version"] = API_VERSION
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID") or "-"
        return response
