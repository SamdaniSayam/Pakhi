"""Locked error envelope — ``{error: {code, message, details?}}``.

Every error the API emits, from FastAPI's 422 validation errors to unhandled
exceptions, is mapped to this envelope so no route ever leaks the framework
default shape (``{detail: [...]}`` / plain-text "Internal Server Error").

The generic 500 handler runs inside Starlette's ``ServerErrorMiddleware``
(which sits above all user middleware), so it must stamp the response headers
itself: ``X-Pakhi-Version`` and ``X-Request-ID`` on every response is a locked
contract row, and the 500 path never traverses the request middleware.
"""

from __future__ import annotations

import logging
import time

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pakhi.api.logcfg import access_logger
from pakhi.api.settings import API_VERSION

logger = logging.getLogger("pakhi.api.error")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    501: "not_implemented",
    503: "db_unavailable",
}


def error_body(code: str, message: str, details=None) -> dict:
    """Build the locked ``{error: {code, message, details?}}`` payload."""
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def code_for_status(status: int) -> str:
    return _STATUS_CODES.get(status, "http_error")


def _stamp(response: JSONResponse, request, rid: str) -> JSONResponse:
    """Contract headers on responses that bypass the request middleware (500s)."""
    response.headers["X-Pakhi-Version"] = API_VERSION
    response.headers["X-Request-ID"] = rid
    settings = getattr(getattr(getattr(request, "app", None), "state", None), "settings", None)
    cors_origins = getattr(settings, "cors_origins", ()) or ()
    origin = request.headers.get("origin")
    if origin in cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


def _rid(request) -> str:
    return request.headers.get("X-Request-ID") or "-"


async def request_validation_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "request validation failed", exc.errors()),
    )


async def http_exception_handler(request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code_for_status(exc.status_code), str(exc.detail)),
    )


async def unhandled_exception_handler(request, exc: Exception):
    """500 envelope + contract headers + access line (the 500 path bypasses
    RequestContextMiddleware, so headers/logging are done here)."""
    rid = _rid(request)
    logger.exception("unhandled exception: %s", exc)
    start = time.perf_counter()
    response = JSONResponse(
        status_code=500,
        content=error_body("internal_error", "internal server error"),
    )
    response = _stamp(response, request, rid)
    access_logger.info(
        "%s %s -> 500 0ms",
        request.method,
        request.url.path,
        extra={
            "request_id": rid,
            "json_fields": {
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "error": "internal_error",
            },
        },
    )
    return response
