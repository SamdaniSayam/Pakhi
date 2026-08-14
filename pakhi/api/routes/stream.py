"""WS-3 T4: WebSocket live stream route handler.

WS /v1/stream/signals — the ONLY async def endpoint in the API as locked in
contract §3/§4.  Pushes a ``signals.batch`` message to connected subscribers
whenever a new WS-2 forecast cycle completes.
"""

from __future__ import annotations

import asyncio
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

    await broadcaster.connect(websocket)
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
