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
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pakhi.api import errors
from pakhi.api.auth import AuthAndRateLimitMiddleware, hash_key, rate_limiter
from pakhi.api.broadcast import start_notify_listener
from pakhi.api.db import build_engine
from pakhi.api.logcfg import RequestContextMiddleware, setup_logging
from pakhi.api.routes.admin import router as admin_router
from pakhi.api.routes.backtest import router as backtest_router
from pakhi.api.routes.billing import router as billing_router
from pakhi.api.routes.meta import router as meta_router
from pakhi.api.routes.read import router as read_router
from pakhi.api.routes.stream import router as stream_router
from pakhi.api.settings import API_VERSION, VERSION, Settings
from pakhi.api.ws4_auth import Ws4AuthMiddleware
from pakhi.ws4.db import init_db, migrate
from pakhi.ws4.service import (
    DEFAULT_TENANT_ID,
    TIER_LIMIT_PER_MIN,
    lookup_key,
    upsert_tenant,
)
from pakhi.ws4.tenant import PermissionDeniedError

logger = logging.getLogger("pakhi.api.main")


async def _permission_denied_handler(request: Request, exc: PermissionDeniedError) -> JSONResponse:
    """Map ``PermissionDeniedError`` to the locked 403 envelope (WS-4 role gate)."""
    return JSONResponse(
        status_code=403,
        content=errors.error_body("forbidden", "permission denied"),
    )


def _db_key_valid(request: Request, key_hash: str) -> bool:
    """WS-4 T2: is this hash a live DB per-tenant API key? Fail-closed: DB down
    or unknown -> False, so DB keys die with the DB while bootstrap keys
    (validated against env/file hashes) keep working."""
    engine = getattr(request.app.state, "write_engine", None)
    if engine is None:
        return False
    try:
        return lookup_key(engine, key_hash) is not None
    except Exception:
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    setup_logging(settings.log_level)

    allowed_hashes = {hash_key(k) for k in settings.api_keys}
    require_auth = bool(allowed_hashes)

    # WS-4 T2: one bucket per tier (free/pro/labs -> contract limits), resolved
    # from the tenant tier. WS-5 T1: Redis-backed buckets when PAKHI_REDIS_URL
    # is set (multi-worker shared state, fail-closed 503 when Redis is down);
    # unset -> in-memory single-worker limiters, byte-identical to WS-3/WS-4.
    from pakhi.ws5.redis_limiter import build_tier_limiters

    tier_limiters, redis_client = build_tier_limiters(
        TIER_LIMIT_PER_MIN, redis_url=settings.redis_url, workers=settings.workers
    )

    # WS-5 T2: Prometheus registry (multiprocess-mandatory above one worker —
    # misconfiguration is a boot error, never a silent per-worker registry).
    from pakhi.ws5 import metrics as ws5_metrics

    ws5_metrics.initialize(settings.workers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.read_engine = build_engine(settings.read_db_url, read_only=True)
        app.state.write_engine = build_engine(settings.write_db_url)

        # Start fresh buckets per app lifecycle (deterministic tests, clean boot).
        rate_limiter.reset()
        for limiter in tier_limiters.values():
            limiter.reset()
        from pakhi.ws5.budget import budget

        budget.reset()
        app.state.api_key_hashes = allowed_hashes
        app.state.require_auth = require_auth
        app.state.jwt_secret = settings.jwt_secret
        app.state.jwt_issuer = settings.jwt_issuer
        app.state.tier_limiters = tier_limiters
        app.state.redis_url = settings.redis_url
        app.state.redis_client = redis_client
        app.state.workers = settings.workers

        # WS-5 T2: wire the scrape-time collector so /metrics reflects the live
        # store/state (audit chain, latest cycle, DB pool, error budget) instead
        # of only whatever /v1/status last wrote — the Prometheus source of
        # truth. Re-evaluated on every scrape (never cached/stale).
        def _ws5_scrape_provider() -> dict:
            result: dict = {}
            write_engine = app.state.write_engine
            read_engine = app.state.read_engine
            if write_engine is not None:
                try:
                    from pakhi.ws4.audit_events import verify_chain_in_store

                    ok, _ = verify_chain_in_store(write_engine)
                    result["audit_chain_ok"] = 1.0 if ok else 0.0
                except Exception:
                    result["audit_chain_ok"] = 0.0
            if read_engine is not None:
                import datetime as _dt

                try:
                    from sqlalchemy import desc, select

                    from pakhi.ws2.db import ForecastCycle
                    from pakhi.ws5.contract import cycle_period_seconds

                    with read_engine.connect() as conn:
                        row = conn.execute(
                            select(ForecastCycle.publication_ts)
                            .order_by(desc(ForecastCycle.publication_ts))
                            .limit(1)
                        ).first()
                    if row is not None:
                        pub = row[0]
                        if pub.tzinfo is None:
                            pub = pub.replace(tzinfo=_dt.timezone.utc)
                        now = _dt.datetime.now(_dt.timezone.utc)
                        fresh = (now - pub).total_seconds()
                        result["cycle_freshness_seconds"] = float(fresh)
                        result["cycle_status"] = (
                            1.0 if fresh <= cycle_period_seconds() else 0.0
                        )
                        result["cycle_last_ok_timestamp_seconds"] = float(pub.timestamp())
                except Exception:
                    pass
                try:
                    pool = read_engine.pool
                    result["db_pool_in_use"] = float(pool.checkedout())
                    result["db_pool_max"] = float(pool.size())
                except Exception:
                    pass
            return result

        ws5_metrics.set_scrape_provider(_ws5_scrape_provider)

        # Create WS-2 + WS-4 tables on the write engine (idempotent; sqlite in
        # tests, TimescaleDB in deployment), then run one-shot additive
        # migrations for pre-WS-4 stores. Non-fatal: the locked WS-3 503
        # contract requires the app to stay bootable with a down DB and serve
        # db_unavailable at request time. The T3 fail-fast gate is for secrets.
        try:
            init_db(app.state.write_engine)
            migrate(app.state.write_engine)
            # Seed the default tenant so WS-3 client_id semantics and token
            # issuance for "pakhi-internal" always have a row (idempotent).
            upsert_tenant(
                app.state.write_engine,
                tenant_id=DEFAULT_TENANT_ID,
                name="Pakhi (default internal)",
                tier="free",
                created_by="bootstrap",
            )
        except Exception:
            logger.warning("WS-4 table init skipped: DB unreachable at startup", exc_info=True)

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
    #   Ws5Metrics -> Ws4Auth -> Ws4Audit -> AuthAndRateLimit -> RequestContext -> CORS -> app
    # Ws4Auth runs outermost so handlers always see a resolved ws4_scope;
    # Ws4Audit appends read rows post-response (scope already resolved, and it
    # sees 401/429 results from the inner Auth middleware); key validity + rate
    # limiting stay with the WS-3 middleware. Ws5Metrics is outermost of all so
    # it records the *edge* status (401/429/503 included) and full latency.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        AuthAndRateLimitMiddleware,
        allowed_keys=allowed_hashes,
        require_auth=require_auth,
        tier_limiters=tier_limiters,
        db_key_validator=_db_key_valid,
    )
    if settings.jwt_secret:
        from pakhi.api.ws4_audit import Ws4AuditMiddleware

        app.add_middleware(Ws4AuditMiddleware)
        app.add_middleware(
            Ws4AuthMiddleware, jwt_secret=settings.jwt_secret, issuer=settings.jwt_issuer
        )
        app.state.ws4_enabled = True

    # Outermost: WS-5 request metrics (edge latency + status, route-template
    # labels, no PII). Added last so it wraps the whole stack.
    from pakhi.ws5.api import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)

    app.add_exception_handler(RequestValidationError, errors.request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, errors.http_exception_handler)
    app.add_exception_handler(Exception, errors.unhandled_exception_handler)
    app.add_exception_handler(
        PermissionDeniedError,
        _permission_denied_handler,
    )

    app.include_router(meta_router)
    app.include_router(read_router)
    app.include_router(backtest_router)
    app.include_router(stream_router)
    app.include_router(admin_router)
    app.include_router(billing_router)
    from pakhi.ws5.api import router as ws5_router

    app.include_router(ws5_router)

    app.state.settings = settings
    app.state.api_version = API_VERSION
    # WS-5 T4: per-app in-memory TTL cache for /v1/status (contract §6 — the
    # deep page's computed body is cached, DB liveness is always re-checked).
    app.state.status_cache = {"ts": 0.0, "data": None}
    return app


app = create_app()
