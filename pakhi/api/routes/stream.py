"""WS-3 T4: WebSocket live stream route handler.

WS /v1/stream/signals — the ONLY async def endpoint in the API as locked in
contract §3/§4.  Pushes a ``signals.batch`` message to connected subscribers
whenever a new WS-2 forecast cycle completes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pakhi.api.auth import hash_key
from pakhi.api.broadcast import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["stream"])


@router.websocket("/stream/signals")
async def stream_signals(websocket: WebSocket):
    """Live WebSocket stream for signal batches."""
    # HTTP middleware does not wrap WebSocket routes, so the same key policy as
    # AuthAndRateLimitMiddleware is enforced here (presence + valid hash).
    require_auth = getattr(websocket.app.state, "require_auth", False)
    allowed_hashes = getattr(websocket.app.state, "api_key_hashes", set()) or set()
    key_header = websocket.headers.get("X-Pakhi-Key") or websocket.query_params.get("key")
    if require_auth and (not key_header or hash_key(key_header) not in allowed_hashes):
        await websocket.close(code=1008, reason="unauthorized: invalid or missing X-Pakhi-Key")
        return

    # WS-6 T1: feed metering — a durable connect/disconnect audit record for the
    # feed_hour billable unit. Best-effort: a missing row surfaces as
    # reconciliation drift (S1), never as a broken stream.
    from pakhi.ws6 import feed_events

    engine = getattr(websocket.app.state, "write_engine", None)
    tenant_id = None
    session_id = feed_events.new_session_id()
    try:
        tenant_id = await asyncio.to_thread(
            feed_events.resolve_tenant_id, engine, hash_key(key_header) if key_header else None
        )
    except Exception:
        tenant_id = None
    if tenant_id:
        websocket.scope[feed_events.SID_SCOPE_KEY] = session_id
        websocket.scope["ws6_feed_tenant"] = tenant_id
        with contextlib.suppress(Exception):
            await asyncio.to_thread(
                feed_events.record_connect, engine, tenant_id, session_id, session_id
            )

    await broadcaster.connect(websocket)
    from pakhi.ws5 import metrics as ws5_metrics

    ws5_metrics.ws_connected()
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except (TimeoutError, asyncio.TimeoutError):
                # Send server ping frame to maintain connection without terminating loop
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception as exc:
        logger.warning("WebSocket handler exception: %s", exc)
        broadcaster.disconnect(websocket)
    finally:
        ws5_metrics.ws_disconnected()
        tenant_id = websocket.scope.get("ws6_feed_tenant")
        if tenant_id:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    feed_events.record_disconnect, engine, tenant_id, session_id, session_id
                )
