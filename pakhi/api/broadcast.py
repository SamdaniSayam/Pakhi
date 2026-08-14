"""WS-3 T4: WebSocket signal broadcaster & notification manager.

Manages connected WebSocket clients for ``WS /v1/stream/signals`` and fans out
``signals.batch`` messages when new forecast cycles complete.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SignalBroadcaster:
    """Pub-sub broadcaster for streaming signal batches to connected WebSocket clients."""

    def __init__(self) -> None:
        self._active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept connection and register client."""
        await websocket.accept()
        self._active_connections.add(websocket)
        logger.info("WebSocket client connected. Active clients: %d", len(self._active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove client on disconnect."""
        self._active_connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected. Active clients: %d", len(self._active_connections)
        )

    async def broadcast(self, payload: dict[str, Any]) -> int:
        """Fan out a JSON payload to all connected clients in parallel (no head-of-line blocking)."""
        connections = list(self._active_connections)
        if not connections:
            return 0

        async def _send(ws: WebSocket) -> bool:
            try:
                await ws.send_json(payload)
                return True
            except Exception:
                self.disconnect(ws)
                return False

        results = await asyncio.gather(*[_send(ws) for ws in connections], return_exceptions=True)
        return sum(1 for r in results if r is True)

    @property
    def active_count(self) -> int:
        return len(self._active_connections)


# Global broadcaster instance attached to app state
broadcaster = SignalBroadcaster()


def make_signals_batch_payload(
    cycle_id: str,
    publication_ts: str,
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format payload according to locked signals.batch schema (Contract §4)."""
    return {
        "type": "signals.batch",
        "version": "1",
        "cycle_id": cycle_id,
        "publication_ts": publication_ts,
        "signals": signals,
    }


async def start_notify_listener(db_url: str, stop_event: asyncio.Event) -> None:
    """Background task listening for Postgres NOTIFY cycle_complete events or local events."""
    if not db_url.startswith("postgresql"):
        # SQLite / in-memory store in local dev & tests
        while not stop_event.is_set():
            await asyncio.sleep(1.0)
        return

    # Postgres listener loop
    while not stop_event.is_set():
        try:
            import psycopg

            conn = await psycopg.AsyncConnection.connect(db_url, autocommit=True)
            async with conn:
                await conn.execute("LISTEN cycle_complete;")
                gen = conn.notifies()
                while not stop_event.is_set():
                    try:
                        notify = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
                        data = json.loads(notify.payload)
                        payload = make_signals_batch_payload(
                            cycle_id=data.get("cycle_id", ""),
                            publication_ts=data.get("publication_ts", ""),
                            signals=data.get("signals", []),
                        )
                        await broadcaster.broadcast(payload)
                    except (TimeoutError, asyncio.TimeoutError):
                        continue
        except Exception as exc:
            logger.warning("Postgres NOTIFY listener reconnecting: %s", exc)
            await asyncio.sleep(2.0)
