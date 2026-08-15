"""WS-4 tenancy core — scope + RBAC (T0 skeleton, enforced by T2).

Pure, import-clean. ``TenantScope`` is the single identity object the
middleware resolves once per request and handlers receive — handlers never
re-parse tokens/keys (§3.1). The role hierarchy and default grants are the
locked contract's §4.

FastAPI wiring lives in ``pakhi.ws4.deps``; this module stays framework-free
so the role matrix and scope logic are testable without the ``api`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Locked contract §3: the default tenant existing WS-3 ``client_id`` semantics
# migrate under, and the machine-key default grant.
DEFAULT_TENANT_ID = "pakhi-internal"
DEFAULT_MACHINE_ROLES = ("operator",)

_ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass(frozen=True)
class TenantScope:
    """Resolved identity: what the request may and may not do.

    ``roles`` is a frozenset of role names; ``actor_type`` is
    ``machine``/``human``/``anonymous`` (anonymous exists only for unauthenticated
    preflight/health paths that still resolve a scope with no powers).
    """

    tenant_id: str = DEFAULT_TENANT_ID
    roles: frozenset[str] = frozenset(("viewer",))
    actor_id: str = ""
    actor_type: Literal["machine", "human", "anonymous"] = "anonymous"
    tier: str = "free"
    scoped: bool = field(default=False)

    def has_role(self, role: str) -> bool:
        """True when this scope carries ``role`` (or a superset of it)."""
        return _ROLE_RANK.get(role, -1) <= _ROLE_RANK.get(_top_role(self.roles), -1)

    def can(self, *required: str) -> bool:
        """True when this scope satisfies at least one of the required roles."""
        return any(self.has_role(r) for r in required)

    def require(self, *required: str) -> None:
        """Raise ``PermissionDeniedError`` unless ``can(*required)``.

        Kept here (not in deps) so the pure core has one source of truth for
        the role matrix; deps maps it onto the locked 403 envelope.
        """
        if not self.can(*required):
            raise PermissionDeniedError(self.tenant_id, required)


def _top_role(roles: frozenset[str]) -> str:
    return max(roles, key=lambda r: _ROLE_RANK.get(r, -1), default="viewer")


class PermissionDeniedError(Exception):
    """Raised when a resolved scope fails a route's minimum role.

    T2 maps this to the locked-envelope 403; the core raises it so the role
    logic itself has no HTTP dependency.
    """

    def __init__(self, tenant_id: str, required: tuple[str, ...]) -> None:
        self.tenant_id = tenant_id
        self.required = required
        super().__init__(f"permission denied: requires {'/'.join(required)}")
