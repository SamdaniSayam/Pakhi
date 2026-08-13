"""WS-3 serializers — store rows -> contract dicts (provenance verbatim).

Shared by the REST routes and the T4 WebSocket fan-out so both always emit the
exact same signal shape (contract §3 ``GET /v1/signals/{instrument}`` +
§4 ``signals.batch``).
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc(dt):
    """Coerce a DB datetime to aware UTC (sqlite returns naive datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def bind_dt(engine, dt: datetime):
    """Normalize a datetime for comparison against the store.

    sqlite stores naive UTC datetimes (WS-2 writes ``to_pydatetime()`` values),
    Postgres stores timezone-aware. Comparisons must run in the dialect's native
    form, so aware values are normalized to naive UTC on sqlite.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if engine.dialect.name == "sqlite":
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def signal_to_dict(row) -> dict:
    """Full signal contract shape — provenance columns verbatim."""
    return {
        "instrument": row.instrument,
        "action": row.action,
        "size": row.size,
        "confidence": row.confidence,
        "reasoning": row.reasoning,
        "timestamp": utc(row.timestamp).isoformat() if row.timestamp is not None else None,
        "forecast_cycle_id": row.forecast_cycle_id,
        "publication_ts": utc(row.publication_ts).isoformat()
        if row.publication_ts is not None
        else None,
        "archive_source": row.archive_source,
        "model_version": row.model_version,
    }
