"""WS-3 T4: WebSocket signal broadcaster & notification manager.

Manages connected WebSocket clients for ``WS /v1/stream/signals`` and fans out
``signals.batch`` messages when new forecast cycles complete.

The end-to-end path (contract §notify): the orchestrator issues a post-commit
``NOTIFY cycle_complete`` on Postgres; ``NotifyListener`` (a background thread —
psycopg2, the driver the ``postgres`` extra ships) LISTENs on the channel, reads
the new cycle's signal rows from the read engine, and schedules the fan-out onto
the asyncio loop. sqlite (local dev / tests) has no NOTIFY, so the listener is a
no-op there and the broadcaster is driven directly in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import select as socket_select
import threading
import time
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select

from pakhi.ws2.db import Signal as DBSignal

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


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


def _signals_for_cycle(read_engine, cycle_id: str) -> list[dict[str, Any]]:
    """Read the stored signal rows for a completed cycle (runs in the listener thread)."""
    from sqlalchemy.orm import Session

    from pakhi.api.serialize import utc

    with Session(read_engine) as session:
        rows = session.scalars(
            select(DBSignal)
            .where(DBSignal.forecast_cycle_id == cycle_id)
            .order_by(DBSignal.timestamp)
        ).all()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "instrument": r.instrument,
                "action": r.action,
                "size": r.size,
                "confidence": r.confidence,
                "reasoning": r.reasoning,
                "timestamp": utc(r.timestamp).isoformat() if r.timestamp else None,
                "forecast_cycle_id": r.forecast_cycle_id,
                "publication_ts": utc(r.publication_ts).isoformat() if r.publication_ts else None,
                "archive_source": r.archive_source,
                "model_version": r.model_version,
            }
        )
    return out


class NotifyListener:
    """Postgres ``cycle_complete`` NOTIFY listener in a dedicated thread.

    psycopg2 is synchronous and its connection must be used from a single
    thread, so the listener runs in a daemon thread and only touches the asyncio
    loop through ``loop.call_soon_threadsafe``. Reconnects with capped backoff.
    """

    def __init__(self, db_url: str, read_engine, loop: asyncio.AbstractEventLoop) -> None:
        self._db_url = db_url
        self._read_engine = read_engine
        self._loop = loop
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pakhi-notify-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        if not self._db_url.startswith("postgresql"):
            logger.info("NOTIFY listener skipped: %s is not Postgres", self._db_url)
            return

        backoff = 1.0
        while not self._stop.is_set():
            conn = None
            try:
                import psycopg2

                conn = psycopg2.connect(self._db_url)
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute("LISTEN cycle_complete;")
                logger.info("LISTENing on Postgres channel 'cycle_complete'")
                backoff = 1.0

                while not self._stop.is_set():
                    if not socket_select.select([conn], [], [], 1.0)[0]:
                        continue
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        self._dispatch(notify.payload)
            except Exception as exc:
                logger.warning("NOTIFY listener reconnecting: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        conn.close()

    def _dispatch(self, raw_payload: str) -> None:
        try:
            data = json.loads(raw_payload)
            cycle_id = data.get("cycle_id", "")
            publication_ts = data.get("publication_ts", "")
            signals = _signals_for_cycle(self._read_engine, cycle_id)
            batch = make_signals_batch_payload(cycle_id, publication_ts, signals)
        except Exception as exc:
            logger.warning("NOTIFY listener failed to build batch: %s", exc)
            return
        with contextlib.suppress(RuntimeError):  # event loop shutting down
            self._loop.call_soon_threadsafe(self._schedule_broadcast, batch)

    @staticmethod
    def _schedule_broadcast(batch: dict[str, Any]) -> None:
        task = asyncio.create_task(broadcaster.broadcast(batch))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def start_notify_listener(db_url: str, read_engine, stop_event: asyncio.Event) -> None:
    """Run the NOTIFY listener until ``stop_event`` is set (used as a lifespan task)."""
    listener = NotifyListener(db_url, read_engine, asyncio.get_running_loop())
    listener.start()
    try:
        await stop_event.wait()
    finally:
        listener.stop()
