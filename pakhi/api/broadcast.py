"""WS-3 T4: WebSocket signal broadcaster & notification manager.

Manages connected WebSocket clients for ``WS /v1/stream/signals`` and fans out
``signals.batch`` messages when new forecast cycles complete.
"""

from __future__ import annotations

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
        """Fan out a JSON payload to all connected clients. Returns count of successful sends."""
        if not self._active_connections:
            return 0

        stale: list[WebSocket] = []
        sent_count = 0
        for connection in list(self._active_connections):
            try:
                await connection.send_json(payload)
                sent_count += 1
            except Exception:
                stale.append(connection)

        for connection in stale:
            self.disconnect(connection)

        return sent_count

    @property
    def active_count(self) -> int:
        return len(self._active_connections)


# Global broadcaster instance attached to app state or module
broadcaster = SignalBroadcaster()
