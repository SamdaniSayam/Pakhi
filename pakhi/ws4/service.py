"""WS-4 T1: token service — user store + refresh rotation on top of ``tokens``.

Mutations go through the app's ``write_engine``. Rotation: each refresh issues
a new access token and a new refresh token in the same ``family_id``, revoking
the presented one (``replaced_by``). **Reuse detection:** presenting an already
revoked token revokes the entire family (a stolen-token signal), per the
locked contract §2.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import RefreshToken, User
from pakhi.ws4.tokens import (
    REFRESH_TOKEN_TTL_DAYS,
    create_access_token,
    hash_token,
    new_refresh_token,
)

_TZ = timezone.utc
DEFAULT_ROLES = ["operator"]


def _as_aware(value: datetime | None) -> datetime | None:
    """Normalize naive datetimes (sqlite round-trips) to aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_TZ)
    return value.astimezone(_TZ)


@dataclass(frozen=True)
class TokenResult:
    access_token: str
    refresh_token: str
    expires_in: int  # seconds
    token_type: str = "bearer"
    user_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class RefreshFailure:
    reason: str  # "not_found" | "revoked_family" | "expired" | "unknown_user"


def upsert_user(
    engine: Engine,
    *,
    user_id: str,
    tenant_id: str,
    roles: list[str],
    tier: str = "free",
    created_by: str | None = None,
) -> None:
    """Create the user row if missing; leave roles/tier untouched if present
    (issuance is not a privilege-escalation vector for existing users)."""
    now = datetime.now(_TZ)
    with Session(engine) as session:
        existing = session.get(User, user_id)
        if existing is None:
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    roles=roles,
                    tier=tier,
                    created_at=now,
                    created_by=created_by,
                )
            )
            session.commit()


def issue_tokens(
    engine: Engine,
    *,
    user_id: str,
    tenant_id: str,
    roles: list[str],
    secret: str,
    tier: str = "free",
    created_by: str | None = None,
    audit: AuditSpec | None = None,
) -> TokenResult:
    """Upsert the user then issue a fresh access + refresh pair (new family).
    When ``audit`` is given, the audit row is sealed in the same session and
    commits with it (atomic-with-mutation)."""
    with Session(engine) as session:
        _tenant_row(engine, tenant_id, session)  # issuance is gated on the tenant
    upsert_user(
        engine,
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        tier=tier,
        created_by=created_by,
    )
    access = create_access_token(
        sub=user_id,
        tenant_id=tenant_id,
        roles=roles,
        tier=tier,
        secret=secret,
    )
    refresh = new_refresh_token()
    now = datetime.now(_TZ)
    with Session(engine) as session:
        session.add(
            RefreshToken(
                token_hash=hash_token(refresh),
                user_id=user_id,
                tenant_id=tenant_id,
                family_id=uuid.uuid4().hex,
                created_at=now,
                expires_at=now + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            )
        )
        if audit is not None:
            apply_audit(session, audit.with_resource_id(user_id))
        session.commit()
    return TokenResult(
        access_token=access,
        refresh_token=refresh,
        expires_in=15 * 60,
        user_id=user_id,
        tenant_id=tenant_id,
    )


def refresh_tokens(
    engine: Engine,
    *,
    refresh_token: str,
    secret: str,
    audit: AuditSpec | None = None,
) -> TokenResult | RefreshFailure:
    """Rotate a refresh token. Returns a new pair on success; a typed failure
    otherwise (route maps any failure to the locked 401). Mutation + audit row
    commit together; the reuse-revocation is audited atomically too."""
    token_hash = hash_token(refresh_token)
    now = datetime.now(_TZ)

    with Session(engine) as session:
        row = session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()
        if row is None:
            return RefreshFailure("not_found")

        if row.revoked_at is not None:
            # Reuse of a rotated token: revoke the whole family.
            family = session.execute(
                select(RefreshToken).where(RefreshToken.family_id == row.family_id)
            ).scalars()
            for member in family:
                if member.revoked_at is None:
                    member.revoked_at = now
            if audit is not None:
                apply_audit(
                    session,
                    replace(
                        audit.with_resource_id(row.user_id),
                        outcome="revoked_family",
                        payload={**audit.payload, "family_id": row.family_id},
                    ),
                )
            session.commit()
            return RefreshFailure("revoked_family")

        if _as_aware(row.expires_at) is None or _as_aware(row.expires_at) < now:
            return RefreshFailure("expired")

        user = session.get(User, row.user_id)
        if user is None:
            return RefreshFailure("unknown_user")

        roles = user.roles or DEFAULT_ROLES
        tier = user.tier or "free"
        user_id = user.id
        tenant_id = user.tenant_id
        access = create_access_token(
            sub=user_id,
            tenant_id=tenant_id,
            roles=list(roles),
            tier=tier,
            secret=secret,
        )
        new_refresh = new_refresh_token()
        session.add(
            RefreshToken(
                token_hash=hash_token(new_refresh),
                user_id=user_id,
                tenant_id=tenant_id,
                family_id=row.family_id,  # same family: rotation chain
                created_at=now,
                expires_at=now + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            )
        )
        row.revoked_at = now
        row.replaced_by = hash_token(new_refresh)
        if audit is not None:
            apply_audit(session, audit.with_resource_id(user_id))
        session.commit()

    return TokenResult(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=15 * 60,
        user_id=user_id,
        tenant_id=tenant_id,
    )


DEFAULT_TENANT_ID = "pakhi-internal"

# Locked contract §2: tier -> requests/min from the tenant row. Free is the
# default; pro/labs raise the cap. Never a throughput or performance claim —
# strictly an API-policy bound enforced by the limiter.
TIER_LIMIT_PER_MIN: dict[str, int] = {
    "free": 30,
    "pro": 120,
    "labs": 300,
}


def _tenant_row(engine: Engine, tenant_id: str, session: Session):
    from pakhi.ws4.db import Tenant

    row = session.get(Tenant, tenant_id)
    if row is None:
        session.rollback()
        raise TenantNotFoundError(tenant_id)
    return row


class TenantNotFoundError(Exception):
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"tenant {tenant_id!r} does not exist")


def upsert_tenant(
    engine: Engine,
    *,
    tenant_id: str,
    name: str,
    tier: str = "free",
    created_by: str | None = None,
    audit: AuditSpec | None = None,
) -> dict:
    """Create or update the tenant row. Tier change re-derives limit_per_min.
    Audit row commits atomically with the tenant row."""
    from pakhi.ws4.db import Tenant

    now = datetime.now(_TZ)
    limit = TIER_LIMIT_PER_MIN.get(tier)
    if limit is None:
        raise ValueError(f"unknown tier {tier!r}: expected free|pro|labs")
    with Session(engine) as session:
        row = session.get(Tenant, tenant_id)
        if row is None:
            row = Tenant(
                id=tenant_id,
                name=name,
                tier=tier,
                limit_per_min=limit,
                created_at=now,
                created_by=created_by,
            )
            session.add(row)
        else:
            row.name = name
            row.tier = tier
            row.limit_per_min = limit
        if audit is not None:
            apply_audit(session, audit.with_resource_id(tenant_id))
        session.commit()
        return {
            "id": row.id,
            "name": row.name,
            "tier": row.tier,
            "limit_per_min": row.limit_per_min,
        }


def list_tenants(engine: Engine) -> list[dict]:
    from pakhi.ws4.db import Tenant

    with Session(engine) as session:
        rows = session.execute(select(Tenant).order_by(Tenant.id)).scalars().all()
    return [
        {"id": t.id, "name": t.name, "tier": t.tier, "limit_per_min": t.limit_per_min} for t in rows
    ]


def get_tenant_tier(engine: Engine, tenant_id: str) -> str:
    from pakhi.ws4.db import Tenant

    with Session(engine) as session:
        row = session.get(Tenant, tenant_id)
        if row is None:
            raise TenantNotFoundError(tenant_id)
        return row.tier


@dataclass(frozen=True)
class ApiKeyCreated:
    key_id: str  # prefix form, e.g. pk_live_ab12
    prefix: str
    key: str  # raw, shown exactly once
    tenant_id: str
    environment: str
    roles: list[str]


def create_api_key(
    engine: Engine,
    *,
    tenant_id: str,
    environment: str,
    roles: list[str],
    created_by: str | None = None,
    audit: AuditSpec | None = None,
) -> ApiKeyCreated:
    """Create a per-tenant API key. Raw key returned once; only the sha256 is
    stored. Prefix (pk_live_/pk_test_) is the stable identifier for listings.
    Audit row commits atomically with the key row."""
    import hashlib
    import secrets as _secrets

    from pakhi.ws4.db import ApiKey

    with Session(engine) as session:
        _tenant_row(engine, tenant_id, session)  # tenant must exist
        env = environment if environment in ("live", "test") else "test"
        key_id = f"pk_{env}_{_secrets.token_hex(8)}"
        raw = _secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        session.add(
            ApiKey(
                id=key_id,
                tenant_id=tenant_id,
                key_hash=digest,
                prefix=key_id,
                environment=env,
                roles=list(roles) if roles else ["operator"],
                created_at=datetime.now(_TZ),
                created_by=created_by,
            )
        )
        if audit is not None:
            apply_audit(session, audit.with_resource_id(key_id))
        session.commit()
    return ApiKeyCreated(
        key_id=key_id,
        prefix=key_id,
        key=raw,
        tenant_id=tenant_id,
        environment=env,
        roles=list(roles) if roles else ["operator"],
    )


def revoke_api_key(engine: Engine, *, key_id: str, audit: AuditSpec | None = None) -> bool:
    from pakhi.ws4.db import ApiKey

    now = datetime.now(_TZ)
    with Session(engine) as session:
        row = session.get(ApiKey, key_id)
        if row is None:
            return False
        row.revoked_at = now
        if audit is not None:
            apply_audit(session, audit.with_resource_id(key_id))
        session.commit()
        return True


def list_api_keys(engine: Engine, *, tenant_id: str | None = None) -> list[dict]:
    """Prefixes only — the raw key never leaves the create response.

    When ``tenant_id`` is ``None`` (root admin listing without a scope) every
    tenant's keys are returned.
    """
    from pakhi.ws4.db import ApiKey

    with Session(engine) as session:
        stmt = select(ApiKey).order_by(ApiKey.created_at)
        if tenant_id is not None:
            _tenant_row(engine, tenant_id, session)
            stmt = stmt.where(ApiKey.tenant_id == tenant_id)
        rows = session.execute(stmt).scalars().all()
    return [
        {
            "key_id": k.id,
            "prefix": k.prefix,
            "environment": k.environment,
            "roles": k.roles or ["operator"],
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k in rows
    ]


@dataclass(frozen=True)
class KeyIdentity:
    key_id: str
    tenant_id: str
    roles: list[str]
    tier: str
    environment: str
    limit_per_min: int


def lookup_key(engine: Engine, key_hash: str) -> KeyIdentity | None:
    """Resolve a DB-stored API key hash to its tenant identity. Used by the
    machine lane of Ws4AuthMiddleware so DB keys scope to their tenant/roles
    instead of the bootstrap admin. Returns None for unknown/revoked keys
    (the WS-3 Auth middleware still validates bootstrap keys independently)."""
    from pakhi.ws4.db import ApiKey, Tenant

    with Session(engine) as session:
        row = session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        tenant = session.get(Tenant, row.tenant_id)
        tier = tenant.tier if tenant is not None else "free"
        limit = TIER_LIMIT_PER_MIN.get(tier, 30)
        return KeyIdentity(
            key_id=row.id,
            tenant_id=row.tenant_id,
            roles=row.roles or DEFAULT_ROLES,
            tier=tier,
            environment=row.environment,
            limit_per_min=limit,
        )
