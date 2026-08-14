"""WS-3 FastAPI application factory.

The app is built by ``create_app(settings)`` so tests inject their own
settings (sqlite engines, CORS allowlist); the module-level ``app`` is the
uvicorn entry (``uvicorn pakhi.api.main:app``) built from environment settings.

Policy (locked in T0, enforced by tests): data handlers are sync ``def`` —
blocking DB work runs in the anyio threadpool, never on the event loop.  Only
WebSocket endpoints are ``async def``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from pakhi.api import errors
from pakhi.api.auth import AuthAndRateLimitMiddleware, hash_key, rate_limiter
from pakhi.api.broadcast import start_notify_listener
from pakhi.api.db import build_engine
from pakhi.api.logcfg import RequestContextMiddleware, setup_logging
from pakhi.api.routes.backtest import router as backtest_router
from pakhi.api.routes.meta import router as meta_router
from pakhi.api.routes.read import router as read_router
from pakhi.api.routes.stream import router as stream_router
from pakhi.api.settings import API_VERSION, VERSION, Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    setup_logging(settings.log_level)

    allowed_hashes = {hash_key(k) for k in settings.api_keys}
    require_auth = bool(allowed_hashes)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.read_engine = build_engine(settings.read_db_url, read_only=True)
        app.state.write_engine = build_engine(settings.write_db_url)

        # Start fresh bucket per app lifecycle (deterministic tests, clean boot).
        rate_limiter.reset()
        app.state.api_key_hashes = allowed_hashes
        app.state.require_auth = require_auth

        # Start Postgres NOTIFY cycle_complete listener task (no-op on sqlite).
        stop_event = asyncio.Event()
        listener_task = asyncio.create_task(
            start_notify_listener(settings.read_db_url, app.state.read_engine, stop_event)
        )

        yield

        stop_event.set()
        listener_task.cancel()
        app.state.read_engine.dispose()
        app.state.write_engine.dispose()

    app = FastAPI(
        title="Pakhi API",
        version=VERSION,
        description="Fast-read layer over the WS-2 store — see docs/WS3_API_CONTRACT.md",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["X-Pakhi-Key", "X-Pakhi-Version", "Content-Type", "X-Request-ID"],
            allow_credentials=False,
            max_age=600,
        )

    # Middleware execution order (last added = outermost):
    #   AuthAndRateLimitMiddleware -> RequestContextMiddleware -> CORS -> app
    # Auth runs first so unknown keys / over-limit requests never reach the app,
    # but preflight OPTIONS are passed straight through (never rejected).
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        AuthAndRateLimitMiddleware,
        allowed_keys=allowed_hashes,
        require_auth=require_auth,
    )

    app.add_exception_handler(RequestValidationError, errors.request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, errors.http_exception_handler)
    app.add_exception_handler(Exception, errors.unhandled_exception_handler)

    app.include_router(meta_router)
    app.include_router(read_router)
    app.include_router(backtest_router)
    app.include_router(stream_router)

    app.state.settings = settings
    app.state.api_version = API_VERSION
    return app


app = create_app()
