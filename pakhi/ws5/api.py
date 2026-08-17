"""WS-5 API surface — GET /metrics exporter + request metrics middleware.

``/metrics`` is unauthenticated (admin network only, contract §3.2) and returns
the Prometheus text exposition; in multiprocess mode it aggregates the shared
``PROMETHEUS_MULTIPROC_DIR`` files across every worker.

The middleware is the outermost HTTP middleware (added last in create_app) so
it records the *edge* status of every request — including 401/429/503 produced
by the inner auth/rate-limit middleware — and measures the full request
latency. The ``path`` label is the matched route *template* (never a raw path
with user values), so no keys, symbols, or query strings ever reach the metric
(contract no-PII rule).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from pakhi.ws5 import metrics
from pakhi.ws5.budget import budget

router = APIRouter()


def _route_template(request: Request) -> str:
    """Matched route template, or ``unmatched``.

    Runs in the middleware's ``finally``, i.e. after the router has run, so
    ``scope["route"]`` is the matched ``APIRoute`` whose ``.path`` is the
    template (``/v1/signals/{instrument}``) — never the raw path with user
    values (no-PII rule, contract §3.2). True 404s have no matched route and
    become ``unmatched`` (no raw-path cardinality).
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else "unmatched"


@router.get("/metrics")
def metrics_exposition() -> PlainTextResponse:
    body, content_type = metrics.render_metrics()
    return PlainTextResponse(body, media_type=content_type)


class MetricsMiddleware:
    """Outermost HTTP middleware: edge latency + status for the API SLIs."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from starlette.requests import Request

        request = Request(scope)
        # Never self-observe scrapes: /metrics must not generate its own noise.
        if request.url.path == "/metrics":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = [500]

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status[0] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            duration = time.perf_counter() - start
            edge_status = status[0]
            template = _route_template(request)
            metrics.record_http_request(
                scope.get("method", "GET"),
                template,
                edge_status,
                duration,
                fail_closed=bool(getattr(request.state, "ws5_fail_closed", False)),
            )
            # SLO-1 accounting: feed every edge 5xx to the error-budget ledger
            # (Redis fail-closed 503s tagged by AuthAndRateLimitMiddleware so
            # they are recorded separately, never consuming budget).
            budget.record_response(
                edge_status,
                endpoint=template,
                fail_closed=bool(getattr(request.state, "ws5_fail_closed", False)),
            )
            if edge_status >= 500:
                metrics.set_error_budget_remaining(budget.remaining_fraction())
