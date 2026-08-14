"""WS-2 T3: orchestration & failover — the daily ingest→compute→store loop.

Contract (``docs/WS2_EXECUTION_BLUEPRINT.md`` §3, §4-T3, §5 and the paper-
trading protocol §7):

- **Single chain, no DAG:** for each pending cycle run ingest → compute →
  persist, then record structured logs to **one sink**
  (``data/ws2/logs/orchestrate.jsonl``) and raise an alert on every failure.
- **Never a silent drop:** ``DataStalenessError`` / ``UpstreamMissingError`` /
  ``RejectCycleError`` (ingest) and ``ComputeError`` (compute) each produce a
  loud alert + a terminal run record.  Armor rejection / staleness / missing
  OJ close are the *designed* loud-skip path; anything else is a worker
  failure.
- **Replay mode (48 h autonomy milestone):** ``replay_cycles`` drives the
  *identical* ingest→compute→store code over cached GFS parquets
  (``offline=True``) with each cycle's own ``ref_time``, into a **separate**
  replay database so the live paper ledger (which decides G1) is never
  polluted by backfilled infrastructure runs.
- **Idempotent:** the DB UPSERTs and the ``vintage_manifest`` pins make a
  re-run of any cycle a no-op that still passes the equivalence + armor gates.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from pakhi.ws2.alerts import Notifier, default_notifiers, send_alert
from pakhi.ws2.compute import compute_cycle
from pakhi.ws2.db import get_engine, init_db
from pakhi.ws2.ingest import (
    GFS_DIR,
    INGESTED_DIR,
    LIVE_MANIFEST,
    MARKET,
    IngestError,
    ingest_cycle,
)

logger = logging.getLogger("ws2.orchestrate")

HERE = Path(__file__).resolve().parent.parent.parent
LOG_DIR = HERE / "data" / "ws2" / "logs"
DEFAULT_REPLAY_DB = "sqlite:///data/ws2/replay.db"

__all__ = [
    "LOG_DIR",
    "CycleOutcome",
    "next_episode_id",
    "orchestrate_cycle",
    "replay_cycles",
    "run_orchestration",
    "structured_log",
]


class CycleOutcome:
    """Terminal statuses of a single orchestrated cycle."""

    OK = "ok"
    REJECTED = "rejected"  # designed loud skip: armor / staleness / missing close
    FAILED = "failed"  # unexpected worker failure


def next_episode_id(engine) -> int:
    """Next monotone paper-ledger episode id (max + 1), 1 when empty."""
    from sqlalchemy import func, select

    from pakhi.ws2.db import PaperLedger

    with engine.connect() as conn:
        mx = conn.execute(select(func.max(PaperLedger.episode_id))).scalar()
    return int(mx) + 1 if mx is not None else 1


def _episode_id_for(engine, forecast_cycle_id: str, episode_id: int | None = None) -> int | None:
    """Stable episode id: reuse an existing row's id, else allocate the next.

    Keeps idempotent re-runs (UPSERT recovery) from drifting the episode id.
    """
    if episode_id is not None:
        return episode_id
    from sqlalchemy import select

    from pakhi.ws2.db import PaperLedger

    with engine.connect() as conn:
        existing = conn.execute(
            select(PaperLedger.episode_id).where(PaperLedger.forecast_cycle_id == forecast_cycle_id)
        ).scalar()
    if existing is not None:
        return int(existing)
    return next_episode_id(engine)


def structured_log(record: dict, sink: Path | str | None = None) -> Path:
    """Append one JSON-line run record to the single structured-log sink."""
    path = Path(sink) if sink is not None else LOG_DIR / "orchestrate.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return path


def _alert(
    severity: str,
    summary: str,
    cycle_id: str | None,
    details: dict[str, Any],
    notifiers: list[Notifier],
) -> None:
    send_alert(summary, severity=severity, cycle_id=cycle_id, details=details, notifiers=notifiers)


def orchestrate_cycle(
    cycle_date: str,
    *,
    engine=None,
    ref_time=None,
    offline: bool = False,
    persist: bool = True,
    notifiers: list[Notifier] | None = None,
    log_sink: Path | str | None = None,
    episode_id: int | None = None,
    gfs_dir: Path | str = GFS_DIR,
    market_dir: Path | str = MARKET,
    ingested_dir: Path | str = INGESTED_DIR,
    manifest_path: Path | str = LIVE_MANIFEST,
) -> dict:
    """Ingest → compute → persist one cycle; alert on any failure, never drop.

    Returns a terminal run record with ``status`` in {ok, rejected, failed}.
    """
    notifiers = notifiers if notifiers is not None else default_notifiers()
    record: dict[str, Any] = {
        "cycle_date": str(cycle_date),
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "offline-replay" if offline else "live",
        "status": CycleOutcome.FAILED,
    }
    try:
        ingested = ingest_cycle(
            cycle_date,
            ref_time=ref_time,
            gfs_dir=gfs_dir,
            market_dir=market_dir,
            ingested_dir=ingested_dir,
            manifest_path=manifest_path,
            persist=persist,
            offline=offline,
        )
    except IngestError as exc:
        record["status"] = CycleOutcome.REJECTED
        record["reject"] = {"type": type(exc).__name__, "error": str(exc)}
        _alert(
            "ERROR",
            f"cycle {cycle_date} rejected: {type(exc).__name__}",
            cycle_date,
            record["reject"],
            notifiers,
        )
        structured_log(record, log_sink)
        return record

    record["ingest"] = {
        "forecast_cycle_id": ingested["forecast_cycle_id"],
        "freeze_prob": ingested["features"]["freeze_prob"],
        "temperature_min": ingested["features"]["temperature_min"],
        "armor": ingested["armor"]["pass"],
        "vintage_sha": ingested["vintage"]["sha256"][:16],
    }
    record["ok"] = True

    if engine is not None and persist:
        try:
            result = compute_cycle(
                ingested,
                engine=engine,
                episode_id=_episode_id_for(engine, ingested["forecast_cycle_id"], episode_id),
            )
        except Exception as exc:
            record["status"] = CycleOutcome.FAILED
            record["failure"] = {"type": type(exc).__name__, "error": str(exc)}
            _alert(
                "CRITICAL",
                f"compute crash on cycle {cycle_date}: {type(exc).__name__}",
                cycle_date,
                record["failure"],
                notifiers,
            )
            structured_log(record, log_sink)
            return record
        record["decision"] = result["decision"]
        record["ledger_row"] = result["ledger_row"]

        # Issue Postgres NOTIFY cycle_complete after compute & ledger write commit
        if engine is not None and getattr(engine.dialect, "name", "") == "postgresql":
            from sqlalchemy import text

            try:
                payload = json.dumps(
                    {
                        "cycle_id": ingested["forecast_cycle_id"],
                        "publication_ts": ingested.get("publication_ts")
                        or datetime.now(timezone.utc).isoformat(),
                    }
                )
                # NOTIFY takes a string literal (no bind params); escape quotes.
                escaped = payload.replace("'", "''")
                with engine.begin() as conn:
                    conn.execute(text(f"NOTIFY cycle_complete, '{escaped}'"))
            except Exception as exc:
                logger.warning("NOTIFY cycle_complete failed: %s", exc)

    record["status"] = CycleOutcome.OK
    structured_log(record, log_sink)
    return record


def replay_cycles(
    dates: Iterable[str],
    *,
    engine=None,
    notifiers: list[Notifier] | None = None,
    log_sink: Path | str | None = None,
    gfs_dir: Path | str = GFS_DIR,
    market_dir: Path | str = MARKET,
    ingested_dir: Path | str = INGESTED_DIR,
    manifest_path: Path | str = LIVE_MANIFEST,
) -> dict:
    """Replay cached cycles through the full pipeline (48 h autonomy harness).

    Each cycle is ingested with its own ``ref_time`` (the day the cycle would
    have been processed live) so the staleness gate is exercised honestly, and
    written to the supplied (separate) replay database.
    """
    summary: dict[str, Any] = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "offline-replay",
        "cycles": {},
        "counts": {CycleOutcome.OK: 0, CycleOutcome.REJECTED: 0, CycleOutcome.FAILED: 0},
        "fired": 0,
        "ledger_rows": 0,
    }
    for d in dates:
        cyc = pd.Timestamp(d)
        ref_time = cyc + pd.Timedelta(hours=12 + 3.5 + 2)  # publish + margin
        rec = orchestrate_cycle(
            str(cyc.date()),
            engine=engine,
            ref_time=ref_time,
            offline=True,
            persist=engine is not None,
            notifiers=notifiers,
            log_sink=log_sink,
            gfs_dir=gfs_dir,
            market_dir=market_dir,
            ingested_dir=ingested_dir,
            manifest_path=manifest_path,
        )
        summary["cycles"][str(cyc.date())] = {
            "status": rec["status"],
            "reject": rec.get("reject"),
            "failure": rec.get("failure"),
            "decision": rec.get("decision"),
            "ledger_row": rec.get("ledger_row"),
        }
        summary["counts"][rec["status"]] += 1
        if rec.get("decision", {}).get("fires"):
            summary["fired"] += 1
        if rec.get("ledger_row"):
            summary["ledger_rows"] += 1
    summary["log_sink"] = str(structured_log(summary, log_sink))
    return summary


def run_orchestration(
    *,
    engine=None,
    notifiers: list[Notifier] | None = None,
    log_sink: Path | str | None = None,
    replay_db: str = DEFAULT_REPLAY_DB,
    ref_time=None,
    persist: bool = True,
) -> dict:
    """Daily entry point: ingest+compute the latest completed 12Z cycle.

    Mirrors what the systemd timer / GitHub Actions runner invokes.  Returns
    the terminal run record (never raises a silent path out).
    """
    from pakhi.ws2.ingest import latest_12z_cycle

    cycle_date = latest_12z_cycle(ref_time)
    return orchestrate_cycle(
        cycle_date,
        engine=engine,
        ref_time=ref_time,
        offline=False,
        persist=persist,
        notifiers=notifiers,
        log_sink=log_sink,
    )


def make_replay_engine(url: str = DEFAULT_REPLAY_DB):
    """Engine for the replay/autonomy database (kept separate from the live ledger)."""
    engine = get_engine(url)
    init_db(engine)
    return engine
