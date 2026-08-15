"""WS-6 T3 — onboarding + 14-day trial lifecycle (hermetic, SQLite).

Contract §6 exactly: 14 days from tenant creation; one trial per contact/org
(a second attempt is refused *and audited*); expiry is a downgrade to ``free``
never a deletion; conversion hooks the subscription flow; notices are
webhook-deliverable (outbox), and lifecycle transitions never count as
billable API calls (T1/T3 ``INTERNAL_ACTIONS``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws4.db import AuditEvent, Tenant
from pakhi.ws4.service import upsert_tenant
from pakhi.ws6 import metering
from pakhi.ws6.contract import billing_contract, contract_consistent
from pakhi.ws6.db import TenantTrial, init_db
from pakhi.ws6.trial import (
    convert_trial,
    deliver_outbox,
    expire_due_trials,
    onboard_tenant,
    outbox_pending,
    start_trial,
    trial_days,
    trial_status,
)

_NOW = datetime.now(timezone.utc)


def _engine():
    eng = create_engine("sqlite://", future=True)
    init_db(eng)
    return eng


def _trial(eng, tenant: str, contact: str, expires_at: datetime):
    return start_trial(eng, tenant, contact, now=expires_at - timedelta(days=14))


def test_contract_locks_trial_policy() -> None:
    assert contract_consistent()
    assert trial_days() == 14
    assert billing_contract()["trial"]["one_per_org"] is True
    assert billing_contract()["trial"]["expiry"] == "downgrade to free, never delete"
    assert billing_contract()["trial"]["conversion"] == "opens paid subscription"


def test_onboarding_checklist_provisions_tenant_key_and_trial() -> None:
    eng = _engine()
    result = onboard_tenant(eng, tenant_id="acme", name="acme", contact_id="bob@x.com")
    assert result["tenant_id"] == "acme"
    assert len(result["key"]) > 0  # raw key returned once
    assert result["key_id"].startswith("pk_")
    assert result["trial"]["outcome"] == "started"
    status = trial_status(eng, "acme", now=_NOW)
    assert status["state"] == "active" and status["days_left"] == 14
    with eng.connect() as conn:
        tier = conn.execute(select(Tenant.tier).where(Tenant.id == "acme")).scalar()
        actions = set(conn.execute(select(AuditEvent.action)).scalars())
    assert tier == "free"
    assert {
        "onboarding.tenant_provisioned",
        "api_key.create",
        "trial.started",
    } <= actions


def test_one_trial_per_org_second_attempt_refused_and_audited() -> None:
    eng = _engine()
    onboard_tenant(eng, tenant_id="acme", name="acme", contact_id="bob@x.com")
    again = start_trial(eng, "acme", "bob@x.com")
    assert again["outcome"] == "refused"
    # same contact, different tenant -> also refused (one per contact)
    same_contact = start_trial(eng, "acme2", "bob@x.com")
    assert same_contact["outcome"] == "refused"
    with eng.connect() as conn:
        denied = conn.execute(select(AuditEvent).where(AuditEvent.action == "trial.denied")).all()
        rows = conn.execute(select(TenantTrial)).all()
    assert len(denied) == 2
    assert len(rows) == 1  # one trial row ever for this org


def test_expiry_downgrades_to_free_never_deletes() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="free")
    expires = _NOW - timedelta(days=1)
    _trial(eng, "acme", "bob@x.com", expires_at=expires)
    applied = expire_due_trials(eng, now=_NOW)
    assert applied[0]["outcome"] == "downgraded_to_free"
    with Session(eng) as session:
        tenant = session.execute(select(Tenant).where(Tenant.id == "acme")).scalar_one()
        rows = session.execute(select(TenantTrial)).all()
        actions = set(session.execute(select(AuditEvent.action)).scalars())
    assert tenant.tier == "free"  # already at the trial tier; never deleted
    assert len(rows) == 1  # data never held hostage
    assert "trial.expired" in actions
    # idempotent: a second pass does nothing new
    assert expire_due_trials(eng, now=_NOW) == []
    assert trial_status(eng, "acme", now=_NOW)["state"] == "downgraded"


def test_expiry_keeps_admin_upgraded_paid_tier() -> None:
    """The fatal case: an admin upgrades a trial tenant to pro by hand
    (bypassing convert_trial, so converted_at stays None). The expiry clock
    must NOT yank a paying enterprise tier — it marks the trial closed and
    leaves the current tier untouched."""
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="free")
    _trial(eng, "acme", "bob@x.com", expires_at=_NOW - timedelta(days=1))
    with Session(eng) as session:  # admin manual upgrade, not convert_trial
        tenant = session.execute(select(Tenant).where(Tenant.id == "acme")).scalar_one()
        tenant.tier = "pro"
        tenant.limit_per_min = 120
        session.commit()
    applied = expire_due_trials(eng, now=_NOW)
    assert applied[0]["outcome"] == "kept_paid_tier"
    with Session(eng) as session:
        tenant = session.execute(select(Tenant).where(Tenant.id == "acme")).scalar_one()
        trial = session.execute(select(TenantTrial)).scalar_one()
        actions = set(session.execute(select(AuditEvent.action)).scalars())
    assert tenant.tier == "pro"  # the paying tier survived the trial clock
    assert tenant.limit_per_min == 120
    assert "billing.tier_downgrade" not in actions
    assert trial.downgraded_at is not None  # the trial record is closed
    assert "trial.expired" in actions
    assert trial_status(eng, "acme", now=_NOW)["state"] == "downgraded"
    # idempotent: the second pass does nothing (never flips to downgrading)
    assert expire_due_trials(eng, now=_NOW) == []
    with Session(eng) as session:
        tenant = session.execute(select(Tenant).where(Tenant.id == "acme")).scalar_one()
    assert tenant.tier == "pro"


def test_expiry_notice_is_webhook_deliverable_outbox() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="free")
    _trial(eng, "acme", "bob@x.com", expires_at=_NOW - timedelta(days=1))
    expire_due_trials(eng, now=_NOW)
    pending = outbox_pending(eng)
    assert any(n["kind"] == "trial.expired" for n in pending)
    # Pre-expiry "trial.expiring" queued for a trial inside the notice window
    upsert_tenant(eng, tenant_id="fresh", name="fresh", tier="free")
    _trial(eng, "fresh", "carol@x.com", expires_at=_NOW + timedelta(days=1))
    expire_due_trials(eng, now=_NOW)
    kinds = {n["kind"] for n in outbox_pending(eng)}
    assert "trial.expiring" in kinds


def test_deliver_outbox_marks_sent_and_keeps_failures_pending() -> None:
    eng = _engine()
    upsert_tenant(eng, tenant_id="acme", name="acme", tier="free")
    _trial(eng, "acme", "bob@x.com", expires_at=_NOW - timedelta(days=1))
    expire_due_trials(eng, now=_NOW)

    seen: list[str] = []
    fail_once = iter(["trial.expired"])

    def deliver(n: dict) -> None:
        if n["kind"] == next(fail_once, None):
            raise RuntimeError("webhook down")
        seen.append(n["kind"])

    first = deliver_outbox(eng, deliver)
    pending_after = outbox_pending(eng)
    # the failed one stayed pending; retry succeeds
    assert first == 0
    assert len(pending_after) == 1
    assert deliver_outbox(eng, deliver) == 1
    assert outbox_pending(eng) == []
    assert "trial.expired" in seen


def test_conversion_hooks_subscription_and_upgrades_tier() -> None:
    eng = _engine()
    onboard_tenant(eng, tenant_id="acme", name="acme", contact_id="bob@x.com")
    result = convert_trial(eng, "acme", subscription_ref="sub_123", tier="pro")
    assert result["outcome"] == "converted"
    with Session(eng) as session:
        tenant = session.execute(select(Tenant).where(Tenant.id == "acme")).scalar_one()
        actions = set(session.execute(select(AuditEvent.action)).scalars())
    assert tenant.tier == "pro"
    assert tenant.limit_per_min == 120
    assert {"trial.converted", "billing.subscription_created", "billing.tier_upgrade"} <= actions
    assert trial_status(eng, "acme", now=_NOW)["state"] == "converted"
    # trial row retained as evidence; converting twice is not a double-convert
    convert_trial(eng, "acme", subscription_ref="sub_124", tier="pro")
    with Session(eng) as session:
        assert session.execute(select(TenantTrial)).scalar_one().converted_at is not None
    assert trial_status(eng, "acme", now=_NOW)["state"] == "converted"


def test_trial_transitions_never_count_as_api_calls() -> None:
    eng = _engine()
    onboard_tenant(eng, tenant_id="acme", name="acme", contact_id="bob@x.com")
    convert_trial(eng, "acme", subscription_ref="sub_1", tier="pro")
    # one real API call
    from sqlalchemy.orm import Session

    with Session(eng) as s:
        apply_audit(
            s,
            AuditSpec(
                request_id="req-real-1",
                tenant_id="acme",
                actor_id="t",
                action="read",
                resource="res",
                ts=_NOW.isoformat(),
            ),
        )
        s.commit()
    calls = metering.api_calls_by_tenant(
        metering.chain_events(eng, "2020-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00")
    )
    assert calls.get("acme", 0) == 2  # read + api_key.create are client actions
    assert {
        "trial.started",
        "billing.subscription_created",
        "billing.tier_upgrade",
    } <= metering.INTERNAL_ACTIONS
