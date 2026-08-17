"""WS-6 T3 — onboarding + 14-day trial automation (audited lifecycle).

Contract §6 exactly: 14 days from tenant creation, **one trial per
contact/org** (a second attempt is refused *and audited*), expiry is a
downgrade to ``free`` — never a deletion — and conversion hooks the
subscription flow. Every transition writes an audit row
(``onboarding.*`` / ``trial.*`` / ``billing.*``) into the WS-4 chain and, where
the contract says webhook-deliverable, a ``notification_outbox`` row (email/
CRM is deferred — the contract is honest about that).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import Tenant
from pakhi.ws4.service import create_api_key, upsert_tenant
from pakhi.ws6.contract import billing_contract
from pakhi.ws6.db import NotificationOutbox, TenantTrial

_TZ = timezone.utc
EXPIRING_NOTICE_WINDOW = timedelta(days=2)


def trial_days() -> int:
    return int(billing_contract()["trial"]["days"])


def _utcnow() -> datetime:
    return datetime.now(_TZ)


def _aware(ts: datetime) -> datetime:
    return ts.replace(tzinfo=_TZ) if ts.tzinfo is None else ts.astimezone(_TZ)


def _audit(
    session: Session,
    *,
    tenant_id: str,
    action: str,
    payload: dict | None = None,
    request_id: str,
) -> None:
    apply_audit(
        session,
        AuditSpec(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_id="ws6.trial",
            action=action,
            resource="trial",
            resource_id=tenant_id,
            payload=payload or {},
        ),
    )


def _enqueue(session: Session, *, tenant_id: str, kind: str, payload: dict | None = None) -> None:
    session.add(
        NotificationOutbox(
            tenant_id=tenant_id,
            kind=kind,
            payload=payload or {},
            status="pending",
        )
    )


def start_trial(
    engine,
    tenant_id: str,
    contact_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Start the 14-day trial — or refuse a second trial for the same
    contact/org (anti-gaming, per contract §6). Refusal is audited, not silent.
    """
    now = _aware(now or _utcnow())
    days = trial_days()
    with Session(engine) as session:
        existing = (
            session.execute(
                select(TenantTrial).where(
                    (TenantTrial.tenant_id == tenant_id) | (TenantTrial.contact_id == contact_id)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            _audit(
                session,
                tenant_id=tenant_id,
                action="trial.denied",
                payload={
                    "contact_id": contact_id,
                    "reason": "one trial per contact/org",
                    "existing_tenant": existing.tenant_id,
                },
                request_id=f"trial-deny-{tenant_id}-{int(now.timestamp())}",
            )
            session.commit()
            return {"outcome": "refused", "reason": "one trial per contact/org"}
        expires = now + timedelta(days=days)
        try:
            session.add(
                TenantTrial(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    started_at=now,
                    expires_at=expires,
                    tier_at_trial="free",
                )
            )
            _audit(
                session,
                tenant_id=tenant_id,
                action="trial.started",
                payload={"contact_id": contact_id, "days": days, "expires_at": expires.isoformat()},
                request_id=f"trial-start-{tenant_id}-{int(now.timestamp())}",
            )
            session.commit()
        except IntegrityError:
            # A concurrent start_trial raced us past the in-session check and
            # hit the unique (tenant_id, contact_id) constraint first. Treat the
            # race loser as refused rather than surfacing a raw DB error.
            session.rollback()
            return {"outcome": "refused", "reason": "one trial per contact/org"}
    return {
        "outcome": "started",
        "tenant_id": tenant_id,
        "started_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "days": days,
    }


def onboard_tenant(
    engine,
    *,
    tenant_id: str,
    name: str,
    contact_id: str,
    environment: str = "test",
    now: datetime | None = None,
) -> dict:
    """Onboarding checklist (contract §3.3): provision tenant → issue an API
    key → start the trial. Every step audited; returns the raw key once."""
    from pakhi.ws4.audit_events import AuditSpec

    now = _aware(now or _utcnow())
    request_id = f"onboard-{tenant_id}-{int(now.timestamp())}"
    upsert_tenant(
        engine,
        tenant_id=tenant_id,
        name=name,
        tier="free",
        created_by="ws6.onboarding",
        audit=AuditSpec(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_id="ws6.onboarding",
            action="onboarding.tenant_provisioned",
            resource="tenant",
        ),
    )
    key = create_api_key(
        engine,
        tenant_id=tenant_id,
        environment=environment,
        roles=["operator"],
        created_by="ws6.onboarding",
        audit=AuditSpec(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_id="ws6.onboarding",
            action="api_key.create",
            resource="api_key",
        ),
    )
    trial = start_trial(engine, tenant_id, contact_id, now=now)
    return {"tenant_id": tenant_id, "key": key.key, "key_id": key.key_id, "trial": trial}


def trial_status(engine, tenant_id: str, *, now: datetime | None = None) -> dict:
    """Read-only status: trial row (if any) + derived state."""
    now = _aware(now or _utcnow())
    with Session(engine) as session:
        row = session.execute(
            select(TenantTrial).where(TenantTrial.tenant_id == tenant_id)
        ).scalar_one_or_none()
        tier = session.execute(select(Tenant.tier).where(Tenant.id == tenant_id)).scalar()
    if row is None:
        return {"tenant_id": tenant_id, "trial": False, "state": "none", "tier": tier or "free"}
    started, expires = _aware(row.started_at), _aware(row.expires_at)
    if row.converted_at is not None:
        state = "converted"
    elif row.downgraded_at is not None:
        state = "downgraded"
    elif now >= expires:
        state = "expired"
    else:
        state = "active"
    return {
        "tenant_id": tenant_id,
        "trial": True,
        "state": state,
        "tier": tier or "free",
        "started_at": started.isoformat(),
        "expires_at": expires.isoformat(),
        "days_left": max(0, (expires - now).days),
        "tier_at_trial": row.tier_at_trial,
    }


def expire_due_trials(engine, *, now: datetime | None = None) -> list[dict]:
    """Downgrade expired trials to ``free`` (never delete); enqueue
    webhook-deliverable notices. Idempotent: a downgraded/converted trial is
    never touched twice. Returns the transitions applied."""
    now = _aware(now or _utcnow())
    applied: list[dict] = []
    with Session(engine) as session:
        due = (
            session.execute(
                select(TenantTrial).where(
                    TenantTrial.expires_at <= now,
                    TenantTrial.downgraded_at.is_(None),
                    TenantTrial.converted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for trial in due:
            tenant_id = trial.tenant_id
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                continue
            if tenant.tier == trial.tier_at_trial:
                # Tenant is still at the trial tier (always "free"): the
                # contract's expiry "downgrade to free" is a no-op here and the
                # trial record is simply closed below. A genuine tier change
                # only happens via convert/upgrade paths, never on a free trial,
                # so there is no downgrade to apply in this branch.
                outcome = "downgraded_to_free"
            else:
                # Tier CHANGED since the trial started — either a conversion or
                # an admin moved this tenant to a paid tier (convert_trial sets
                # converted_at; an admin bypass leaves it None). The trial clock
                # does NOT own their billing: close the trial record, never
                # touch the current tier. Downgrading a paying tenant here is a
                # fatal bug, so this branch is explicitly pinned by a test.
                outcome = "kept_paid_tier"
            _audit(
                session,
                tenant_id=tenant_id,
                action="trial.expired",
                payload={
                    "expires_at": _aware(trial.expires_at).isoformat(),
                    "kept_tier": tenant.tier if outcome == "kept_paid_tier" else None,
                },
                request_id=f"trial-expire-{tenant_id}-{int(now.timestamp())}",
            )
            trial.downgraded_at = now
            _enqueue(
                session,
                tenant_id=tenant_id,
                kind="trial.expired",
                payload={"expires_at": _aware(trial.expires_at).isoformat()},
            )
            applied.append({"tenant_id": tenant_id, "outcome": outcome})
        # Pre-expiry notice: webhook-deliverable "trial.expiring" (not email),
        # enqueued once per trial regardless of expiries applied this run.
        expiring = (
            session.execute(
                select(TenantTrial).where(
                    TenantTrial.expires_at <= now + EXPIRING_NOTICE_WINDOW,
                    TenantTrial.expires_at > now,
                    TenantTrial.converted_at.is_(None),
                    TenantTrial.downgraded_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        already = {
            r[0]
            for r in session.execute(
                select(NotificationOutbox.tenant_id).where(
                    NotificationOutbox.kind == "trial.expiring"
                )
            ).all()
        }
        for trial in expiring:
            if trial.tenant_id not in already:
                _enqueue(
                    session,
                    tenant_id=trial.tenant_id,
                    kind="trial.expiring",
                    payload={"expires_at": _aware(trial.expires_at).isoformat()},
                )
        session.commit()
    return applied


def convert_trial(
    engine,
    tenant_id: str,
    *,
    subscription_ref: str,
    tier: str = "pro",
    now: datetime | None = None,
) -> dict:
    """Conversion hook: trial -> paid subscription (contract §6). Keeps the
    trial row (evidence), records conversion, sets the paid tier, audits
    ``trial.converted`` + ``billing.subscription_created``, enqueues notice."""
    from pakhi.ws4.audit_events import AuditSpec

    now = _aware(now or _utcnow())
    if tier not in ("pro", "labs"):
        raise ValueError(f"conversion requires a paid tier, got {tier!r}")
    with Session(engine) as session:
        trial = session.execute(
            select(TenantTrial).where(TenantTrial.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if trial is None:
            raise ValueError(f"no trial for tenant {tenant_id} — cannot convert")
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"unknown tenant {tenant_id}")
        trial.converted_at = now
        if tenant.tier != tier:
            apply_audit(
                session,
                AuditSpec(
                    request_id=f"billing-convert-{tenant_id}-{int(now.timestamp())}",
                    tenant_id=tenant_id,
                    actor_id="ws6.billing",
                    action="billing.tier_upgrade",
                    resource="tenant",
                    resource_id=tenant_id,
                    payload={
                        "from_tier": tenant.tier,
                        "to_tier": tier,
                        "subscription_ref": subscription_ref,
                    },
                ),
            )
            tenant.tier = tier
            tenant.limit_per_min = {"pro": 120, "labs": 300}[tier]
        _audit(
            session,
            tenant_id=tenant_id,
            action="trial.converted",
            payload={"subscription_ref": subscription_ref, "tier": tier},
            request_id=f"trial-convert-{tenant_id}-{int(now.timestamp())}",
        )
        _audit(
            session,
            tenant_id=tenant_id,
            action="billing.subscription_created",
            payload={"subscription_ref": subscription_ref, "tier": tier},
            request_id=f"billing-sub-{tenant_id}-{int(now.timestamp())}",
        )
        _enqueue(
            session,
            tenant_id=tenant_id,
            kind="trial.converted",
            payload={"subscription_ref": subscription_ref, "tier": tier},
        )
        session.commit()
    return {
        "tenant_id": tenant_id,
        "outcome": "converted",
        "tier": tier,
        "subscription_ref": subscription_ref,
    }


def outbox_pending(engine) -> list[dict]:
    """Pending webhook-deliverable notices (contract §6 honest wording)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(NotificationOutbox)
            .where(NotificationOutbox.status == "pending")
            .order_by(NotificationOutbox.id)
        ).all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "kind": r.kind,
            "payload": r.payload,
        }
        for r in rows
    ]


def deliver_outbox(engine, deliver: Callable[[dict], None]) -> int:
    """Deliver pending notices through an injectable transport; mark sent.
    A transport failure leaves the row pending (retried) — never dropped."""
    pending = outbox_pending(engine)
    sent = 0
    for notice in pending:
        try:
            deliver(notice)
        except Exception:
            continue
        with Session(engine) as session:
            row = session.get(NotificationOutbox, notice["id"])
            if row is not None:
                row.status = "sent"
                row.delivered_at = _utcnow()
                session.commit()
        sent += 1
    return sent


def count_trials(engine, *, contact_id: str | None = None, tenant_id: str | None = None) -> int:
    """Rows matching a contact or tenant — for the anti-gaming refusal check."""
    with engine.connect() as conn:
        stmt = select(func.count(TenantTrial.id))
        if contact_id:
            stmt = stmt.where(TenantTrial.contact_id == contact_id)
        if tenant_id:
            stmt = stmt.where(TenantTrial.tenant_id == tenant_id)
        return conn.execute(stmt).scalar() or 0
