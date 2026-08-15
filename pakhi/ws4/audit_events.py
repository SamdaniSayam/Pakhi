"""WS-4 T4: audit DB layer — atomic appender + chain verification + sweep.

Implements the §3.5 split *without exception*:

- **Mutations** (token issue/refresh, key create/revoke, backtest submit, tenant
  create) call ``apply_audit(session, spec)`` **inside the same session that
  performs the mutation** — one commit covers both, so a commit without its
  audit row is a transaction failure and a rolled-back action never leaves a
  phantom audit row.
- **Reads** are appended post-response by ``Ws4AuditMiddleware`` (best-effort,
  non-transactional) and are covered by the omission-reconciliation sweep whose
  input is the *independently written* nginx access log, never app middleware.
- Chain links are computed with the pure ``audit.chain_hash`` so the T4 tests
  and the runtime share byte-identical logic.

Appends serialize on a process-wide lock: the chain head is read, the link is
sealed, then the row is added — the single-writer posture the WS-4 contract
documents for the API process.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pakhi.ws4.audit import ChainedRow, verify_chain
from pakhi.ws4.db import AuditEvent

_APPEND_LOCK = threading.Lock()
_TZ = timezone.utc


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat()


@dataclass(frozen=True)
class AuditSpec:
    """What to write for one auditable action (route builds it from request
    context; the service appends it atomically in the mutation's transaction)."""

    request_id: str
    tenant_id: str
    actor_id: str
    action: str
    resource: str
    resource_id: str | None = None
    outcome: str = "success"
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str | None = None  # None -> now

    def with_resource_id(self, resource_id: str) -> AuditSpec:
        if self.resource_id is None:
            return replace(self, resource_id=resource_id)
        return self


def chain_head(session: Session) -> str | None:
    """Hash of the current tail — the prev_hash for the next link."""
    return session.execute(
        select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)
    ).scalar_one_or_none()


def _acquire_cross_process_lock(session: Session) -> None:
    """Serialize chain appends across uvicorn workers.

    WS-5 T1: the in-process ``_APPEND_LOCK`` is per-worker; with N workers the
    chain would race. Postgres serializes the chain-head read + insert with a
    named advisory transaction lock (``AUDIT_APPEND_LOCK_ID`` from the
    reliability contract), released at commit/rollback of the caller's
    transaction. The locked block is strictly chain-head read + seal + add —
    no external calls. sqlite keeps the in-process lock only (file-level write
    serialization is inherent).
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    from sqlalchemy import text

    from pakhi.ws5.contract import audit_append_lock_id

    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": audit_append_lock_id()})


def apply_audit(session: Session, spec: AuditSpec) -> AuditEvent:
    """Seal and queue an audit row in the caller's session (commit is the
    caller's — the same commit that must accompany the mutation)."""
    with _APPEND_LOCK:
        _acquire_cross_process_lock(session)
        prev = chain_head(session)
        row = ChainedRow(
            request_id=spec.request_id,
            action=spec.action,
            resource=spec.resource,
            tenant_id=spec.tenant_id,
            actor_id=spec.actor_id,
            outcome=spec.outcome,
            ts=spec.ts or _now_iso(),
            payload=dict(spec.payload),
        )
        row.seal(prev)
        event = AuditEvent(
            request_id=spec.request_id,
            tenant_id=spec.tenant_id,
            actor_id=spec.actor_id,
            action=spec.action,
            resource=spec.resource,
            resource_id=spec.resource_id,
            outcome=spec.outcome,
            ts=row.ts,
            prev_hash=row.prev_hash,
            hash=row.hash,
            payload=dict(spec.payload),
        )
        session.add(event)
        return event


def _to_chained(event: AuditEvent) -> ChainedRow:
    return ChainedRow(
        request_id=event.request_id,
        action=event.action,
        resource=event.resource,
        tenant_id=event.tenant_id,
        actor_id=event.actor_id,
        outcome=event.outcome,
        ts=event.ts,
        payload=event.payload or {},
        prev_hash=event.prev_hash,
        hash=event.hash,
    )


def verify_chain_in_store(engine: Engine) -> tuple[bool, int | None]:
    """Replay the stored chain. Returns ``(ok, first_bad_index)`` — a tampered
    middle row breaks every subsequent link and is reported at its own index."""
    with Session(engine) as session:
        rows = session.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars().all()
    return verify_chain(_to_chained(r) for r in rows)


def query_audit(
    engine: Engine,
    *,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Admin-only read surface: paginated, filterable by tenant/actor/action."""
    stmt = select(AuditEvent)
    if tenant_id is not None:
        stmt = stmt.where(AuditEvent.tenant_id == tenant_id)
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    stmt = stmt.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
    with Session(engine) as session:
        rows = session.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "request_id": r.request_id,
            "tenant_id": r.tenant_id,
            "actor_id": r.actor_id,
            "action": r.action,
            "resource": r.resource,
            "resource_id": r.resource_id,
            "outcome": r.outcome,
            "ts": r.ts,
            "prev_hash": r.prev_hash,
            "hash": r.hash,
            "payload": r.payload or {},
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Omission reconciliation — nginx access-log input
# ---------------------------------------------------------------------------

# Ships with the nginx config (deploy/nginx/pakhi-nginx.conf): the access-log
# stanza that logs $request_id per request. The sweep parses exactly this shape,
# so a fixture access log can stand in for nginx in the T4 omission test.
_NGINX_ACCESS_RE = re.compile(
    r'^\S+\s+(?P<rid>\S+)\s+"(?P<method>[A-Z]+)\s+(?P<path>\S+)[^"]*"\s+(?P<status>\d+)'
)


def parse_nginx_access_line(line: str) -> dict[str, str] | None:
    """Parse one nginx access-log line (pakhi log_format) -> {request_id, path}.

    Returns None for lines that don't match (e.g. a health check without the
    stanza) — the sweep skips those rather than failing on them.
    """
    match = _NGINX_ACCESS_RE.match(line.strip())
    if match is None:
        return None
    return {"request_id": match.group("rid"), "path": match.group("path")}


def load_access_log(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        entries: list[dict[str, str]] = []
        for raw in handle:
            parsed = parse_nginx_access_line(raw)
            if parsed is not None:
                entries.append(parsed)
        return entries


def mutating_path_prefixes() -> tuple[str, ...]:
    """Request path prefixes that must have an audit row (the §3.5 mutation
    list). ``POST /v1/admin/keys/.../revoke`` and ``tokens/refresh`` fall under
    the ``/v1/admin/keys`` / ``/v1/admin/tokens`` prefixes."""
    return (
        "/v1/admin/tokens",
        "/v1/admin/keys",
        "/v1/admin/tenants",
        "/v1/backtests",
    )
