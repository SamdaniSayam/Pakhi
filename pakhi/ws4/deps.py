"""WS-4 FastAPI dependencies — tenant scope + role guard (wired in T2).

Not imported by ``pakhi.ws4`` (the core package stays framework-free); this
module is imported only where the FastAPI app lives. The middleware resolves
identity once into ``request.state.ws4_scope``; these dependencies hand that
single ``TenantScope`` to handlers, so handlers never re-parse tokens/keys.

T2 enforces the locked 403 envelope for ``PermissionDeniedError``.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, Request

from pakhi.ws4.tenant import PermissionDeniedError, TenantScope


def get_tenant_scope(request: Request) -> TenantScope:
    """Resolve the request's identity (populated by the middleware once)."""
    scope = getattr(request.state, "ws4_scope", None)
    if not isinstance(scope, TenantScope):
        raise PermissionDeniedError("", ("viewer",))
    return scope


def require_role(*roles: str) -> Callable[[TenantScope], TenantScope]:
    """Dependency factory: enforce a minimum role for a route."""

    def _dep(scope: TenantScope = Depends(get_tenant_scope)) -> TenantScope:
        scope.require(*roles)
        return scope

    return _dep
