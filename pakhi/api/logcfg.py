"""JSON-lines logging + request-id / access-log middleware.

Every request gets a request id (``X-Request-ID`` header, echoed back), the
response carries ``X-Pakhi-Version``, and each request is logged as one JSON
line with the request id attached — the structured-log discipline the rest of
the platform already follows (WS-2 ``orchestrate.jsonl``).
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware

from pakhi.api.settings import API_VERSION

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

access_logger = logging.getLogger("pakhi.api.access")


class JsonFormatter(logging.Formatter):
    """JSON-lines formatter; honors ``request_id`` (explicit or contextvar) and
    a ``json_fields`` dict on the record for extra structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or request_id_var.get()
        if rid != "-":
            payload["request_id"] = rid
        for key, value in getattr(record, "json_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Attach a JSON handler to the ``pakhi`` logger (idempotent)."""
    root = logging.getLogger("pakhi")
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    root.handlers = [
        handler for handler in root.handlers if not isinstance(handler, logging.StreamHandler)
    ]
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign/echo a request id, stamp ``X-Pakhi-Version``, log one JSON access
    line per request."""

    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid  # WS-4 T4: audit appender + middleware read it
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Pakhi-Version"] = API_VERSION
        access_logger.info(
            "%s %s -> %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "request_id": rid,
                "json_fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                },
            },
        )
        return response
