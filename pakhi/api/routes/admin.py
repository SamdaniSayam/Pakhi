"""WS-4 T1+T2: admin surface — tokens, tenants, per-tenant API keys.

T1
- ``POST /v1/admin/tokens`` — admin-gated (admin key or admin JWT). Issues an
  HS256 access JWT (15 min) + opaque rotating refresh token for a user.
- ``POST /v1/admin/tokens/refresh`` — auth-exempt by middleware contract: the
  opaque refresh token in the body *is* the credential. Rotates the pair;
  presenting an already-revoked token revokes the whole family (reuse
  detection). Any failure maps to the locked 401 envelope.

T2 (multi-tenancy)
- ``POST /v1/admin/tenants`` — create/update a tenant (tier -> limit_per_min).
- ``GET /v1/admin/tenants`` — list tenants (admin).
- ``POST /v1/admin/keys`` — create a per-tenant API key (raw key returned once).
- ``POST /v1/admin/keys/{key_id}/revoke`` — revoke (immediate on next request).
- ``GET /v1/admin/keys?tenant_id=`` — list prefixes only (raw key never
  returned; store keeps only the sha256).

WS-3 ``X-Pakhi-Key`` flow is untouched; this is a new admin surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from pakhi.ws4.audit_events import AuditSpec, query_audit
from pakhi.ws4.deps import require_role
from pakhi.ws4.service import (
    DEFAULT_TENANT_ID,
    RefreshFailure,
    TenantNotFoundError,
    create_api_key,
    issue_tokens,
    list_api_keys,
    list_tenants,
    refresh_tokens,
    revoke_api_key,
    upsert_tenant,
)

if TYPE_CHECKING:
    from pakhi.ws4.tenant import TenantScope

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_VALID_ROLES = {"viewer", "operator", "admin"}


def _resolve_scope_tenant_id(scope: TenantScope, requested: str | None) -> str | None:
    """Cross-tenant read-leak guard for the per-tenant admin surfaces.

    A non-root caller may only ever read its own tenant: any caller-supplied
    ``tenant_id`` is ignored and the caller's scope tenant is forced.  The
    internal admin tenant (``pakhi-internal``) may read an arbitrary tenant
    (when one is requested) or, when no tenant is supplied, list *all*
    tenants/keys — the intended admin capability.
    """
    if scope.tenant_id == DEFAULT_TENANT_ID:
        return requested
    return scope.tenant_id


class TokenRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(default="pakhi-internal", min_length=1, max_length=128)
    roles: list[str] = Field(default=["operator"])
    tier: Literal["free", "pro", "labs"] = "free"

    def validated_roles(self) -> list[str]:
        if not self.roles or not set(self.roles) <= _VALID_ROLES:
            raise HTTPException(
                status_code=422, detail=f"roles must be a subset of {sorted(_VALID_ROLES)}"
            )
        return sorted(set(self.roles))


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class TenantCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    tier: Literal["free", "pro", "labs"] = "free"


class ApiKeyCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    environment: Literal["live", "test"] = "test"
    roles: list[str] = Field(default=["operator"])

    def validated_roles(self) -> list[str]:
        if not self.roles or not set(self.roles) <= _VALID_ROLES:
            raise HTTPException(
                status_code=422, detail=f"roles must be a subset of {sorted(_VALID_ROLES)}"
            )
        return sorted(set(self.roles))


def _jwt_secret(request: Request) -> str:
    secret = getattr(request.app.state, "jwt_secret", None)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="JWT signing key is not configured (PAKHI_JWT_SECRET)",
        )
    return secret


def _tenant_404(exc: TenantNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"tenant {exc.tenant_id!r} does not exist")


def _audit_spec(
    request: Request,
    scope: TenantScope,
    action: str,
    resource: str,
    outcome: str = "success",
    **payload: object,
) -> AuditSpec:
    """Build the audit spec from the resolved request context (T4)."""
    return AuditSpec(
        request_id=getattr(request.state, "request_id", "-"),
        tenant_id=scope.tenant_id,
        actor_id=scope.actor_id or "-",
        action=action,
        resource=resource,
        outcome=outcome,
        payload=payload,
    )


@router.post("/tokens", status_code=201)
def issue_token(
    request: Request,
    body: TokenRequest,
    scope: TenantScope = Depends(require_role("admin")),
):
    """Issue a human access/refresh pair. Requires an admin credential."""
    try:
        result = issue_tokens(
            request.app.state.write_engine,
            user_id=body.user_id,
            tenant_id=body.tenant_id,
            roles=body.validated_roles(),
            secret=_jwt_secret(request),
            tier=body.tier,
            created_by=scope.actor_id,
            audit=_audit_spec(request, scope, "token.issue", "token", tenant_id=body.tenant_id),
        )
    except TenantNotFoundError as exc:
        raise _tenant_404(exc) from exc
    return JSONResponse(
        status_code=201,
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
            "expires_in": result.expires_in,
            "user_id": result.user_id,
            "tenant_id": result.tenant_id,
        },
    )


@router.post("/tokens/refresh", status_code=200)
def refresh_token(request: Request, body: RefreshRequest):
    """Rotate a refresh token. The body token is the credential (auth-exempt)."""
    result = refresh_tokens(
        request.app.state.write_engine,
        refresh_token=body.refresh_token,
        secret=_jwt_secret(request),
        audit=AuditSpec(
            request_id=getattr(request.state, "request_id", "-"),
            tenant_id="pakhi-internal",
            actor_id="-",
            action="token.refresh",
            resource="token",
        ),
    )
    if isinstance(result, RefreshFailure):
        raise HTTPException(status_code=401, detail="invalid or revoked refresh token")
    return {
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "token_type": result.token_type,
        "expires_in": result.expires_in,
        "user_id": result.user_id,
        "tenant_id": result.tenant_id,
    }


@router.post("/tenants", status_code=201)
def create_tenant(
    request: Request,
    body: TenantCreateRequest,
    scope: TenantScope = Depends(require_role("admin")),
):
    """Create (or update) a tenant. Tier re-derives limit_per_min."""
    tenant = upsert_tenant(
        request.app.state.write_engine,
        tenant_id=body.id,
        name=body.name,
        tier=body.tier,
        created_by=scope.actor_id,
        audit=_audit_spec(request, scope, "tenant.create", "tenant", tier=body.tier),
    )
    return JSONResponse(status_code=201, content=tenant)


@router.get("/tenants")
def tenants_list(
    request: Request,
    tenant_id: str | None = Query(default=None, min_length=1),
    scope: TenantScope = Depends(require_role("admin")),
):
    effective = _resolve_scope_tenant_id(scope, tenant_id)
    tenants = list_tenants(request.app.state.write_engine)
    if effective is not None:
        tenants = [t for t in tenants if t["id"] == effective]
    return {"tenants": tenants, "tenant_id": effective}


@router.post("/keys", status_code=201)
def create_key(
    request: Request,
    body: ApiKeyCreateRequest,
    scope: TenantScope = Depends(require_role("admin")),
):
    """Create a per-tenant API key. The raw key appears exactly once."""
    created = create_api_key(
        request.app.state.write_engine,
        tenant_id=body.tenant_id,
        environment=body.environment,
        roles=body.validated_roles(),
        created_by=scope.actor_id,
        audit=_audit_spec(
            request,
            scope,
            "api_key.create",
            "api_key",
            tenant_id=body.tenant_id,
            environment=body.environment,
        ),
    )
    return JSONResponse(
        status_code=201,
        content={
            "key_id": created.key_id,
            "prefix": created.prefix,
            "key": created.key,
            "tenant_id": created.tenant_id,
            "environment": created.environment,
            "roles": created.roles,
            "note": "store this key now — only its hash is kept",
        },
    )


@router.post("/keys/{key_id}/revoke")
def revoke_key(
    request: Request,
    key_id: str,
    scope: TenantScope = Depends(require_role("admin")),
):
    if not revoke_api_key(
        request.app.state.write_engine,
        key_id=key_id,
        audit=_audit_spec(request, scope, "api_key.revoke", "api_key"),
    ):
        raise HTTPException(status_code=404, detail=f"no api key {key_id!r}")
    return {"key_id": key_id, "revoked": True}


@router.get("/keys")
def keys_list(
    request: Request,
    tenant_id: str | None = Query(default=None, min_length=1),
    scope: TenantScope = Depends(require_role("admin")),
):
    """Prefixes only — the raw key never leaves the create response."""
    effective = _resolve_scope_tenant_id(scope, tenant_id)
    try:
        keys = list_api_keys(request.app.state.write_engine, tenant_id=effective)
    except TenantNotFoundError as exc:
        raise _tenant_404(exc) from exc
    return {"tenant_id": effective, "keys": keys}


@router.get("/audit")
def audit_list(
    request: Request,
    tenant_id: str | None = Query(default=None, min_length=1),
    actor_id: str | None = Query(default=None, min_length=1),
    action: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: TenantScope = Depends(require_role("admin")),
):
    """Admin-only, paginated, filterable view of the tamper-evident chain."""
    effective = _resolve_scope_tenant_id(scope, tenant_id)
    rows = query_audit(
        request.app.state.write_engine,
        tenant_id=effective,
        actor_id=actor_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return {"audit": rows, "tenant_id": effective, "limit": limit, "offset": offset, "count": len(rows)}
