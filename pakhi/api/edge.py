"""X-Pakhi-Edge-Status computation — contract §2.

States (computed live from the paper ledger, never hardcoded):

- ``underpowered_n<N>`` — N scored events < N_MIN (harness still accumulating)
- ``unproven_n<N>`` — N >= N_MIN but no recorded G1 re-run PASS verdict
- ``proven_n<N>`` — a recorded G1 re-run verdict = PASS

The G1 re-run verdict is read from ``data/ws3/g1_rerun_verdict.json`` when it
exists; its absence means "not proven", which is the honest default.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from pakhi.api.contract import N_MIN
from pakhi.ws2.db import PaperLedger

HERE = Path(__file__).resolve().parent.parent.parent
G1_RERUN_VERDICT = HERE / "data" / "ws3" / "g1_rerun_verdict.json"


def _g1_rerun_passed() -> bool:
    """True only when a committed G1 re-run verdict explicitly says PASS."""
    try:
        rec = json.loads(G1_RERUN_VERDICT.read_text())
    except (OSError, ValueError):
        return False
    return rec.get("outcome") == "PASS"


def scored_event_count(engine) -> int:
    with engine.connect() as conn:
        n = conn.execute(
            select(func.count()).select_from(PaperLedger).where(PaperLedger.scored.is_(True))
        ).scalar()
    return int(n or 0)


def edge_status(engine) -> dict:
    """Live edge status: ``{status, n_scored_events, header}``."""
    n = scored_event_count(engine)
    if n < N_MIN:
        state = "underpowered"
    elif _g1_rerun_passed():
        state = "proven"
    else:
        state = "unproven"
    return {"status": state, "n_scored_events": n, "header": f"{state}_n{n}"}
