"""WS-4 T4: read/access audit middleware.

Per the §3.5 split: mutations are audited atomically inside their transactions
(never here); this middleware appends **read** rows post-response — best-effort
and non-transactional, which is exactly why the omission-reconciliation sweep is
anchored on the *independently written* nginx access log, never on this code
path. A bug that suppresses a read row cannot also suppress the evidence
against it.

Only GET reads on the public data surface are audited (instruments, signals,
ledger, backtests, ensemble); admin/health paths are excluded. Errors never
break the response — a failed append is logged and the omission sweep (or the
next successful append) catches up.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from pakhi.ws4.audit_events import AuditSpec, apply_audit

logger = logging.getLogger("pakhi.ws4.audit")

_READ_PREFIXES = (
    "/v1/instruments",
    "/v1/signals",
    "/v1/ledger",
    "/v1/backtests",
    "/v1/ensemble",
)


class Ws4AuditMiddleware(BaseHTTPMiddleware):
    """Append a chained read row post-response for public GET reads."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        try:
            if (
                request.method == "GET"
                and response.status_code < 400
                and _is_read(request.url.path)
            ):
                self._append_read(request, response)
        except Exception:
            logger.warning("read audit append failed for %s", request.url.path, exc_info=True)
        return response

    @staticmethod
    def _append_read(request: Request, response: Response) -> None:
        engine = getattr(request.app.state, "write_engine", None)
        if engine is None:
            return
        scope = getattr(request.state, "ws4_scope", None)
        spec = AuditSpec(
            request_id=getattr(request.state, "request_id", "-"),
            tenant_id=(scope.tenant_id if scope is not None else "pakhi-internal"),
            actor_id=(scope.actor_id if scope is not None else "-"),
            action="read",
            resource=_route_template(request),
            outcome="success",
            payload={"status": response.status_code},
        )
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            apply_audit(session, spec)
            session.commit()


def _is_read(path: str) -> bool:
    if path.startswith(("/v1/admin", "/v1/health")):
        return False
    return path.startswith(_READ_PREFIXES)


def _route_template(request: Request) -> str:
    """Route template for the audited read (no user-supplied path segments).

    Storing the raw path would persist tenant/account identifiers (PII-ish) from
    the URL; the matched route template (``/v1/signals/{instrument}``) is the
    audited resource instead. Falls back to the raw path only when no route was
    matched (true 404s), which never carries a resolved identity anyway.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if template else request.url.path
