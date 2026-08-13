"""Shared WS-3 test store seeding (cycles / signals / ledger).

sqlite is seeded with naive UTC datetimes, matching how WS-2 writes
``to_pydatetime()`` values in sqlite; the API's ``serialize.utc`` normalizes on
read.  Both engines point at the same file in tests — Postgres role separation
is covered by the T1 CI permission test, not here.

Note: ``Signal.forecast_cycle_id`` is unique, so seeded signals must use
distinct cycle ids.  ``PaperLedger`` columns are all NOT NULL, so the seeder
fills defaults for any field a test row omits.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine

from pakhi.ws2.db import ForecastCycle, PaperLedger, Signal, init_db

_LEDGER_DEFAULTS = {
    "entry_cycle": datetime(2026, 8, 10),
    "entry_session": datetime(2026, 8, 10, 15),
    "exit_session": datetime(2026, 8, 12, 15),
    "gross": 0.0,
    "net": 0.0,
    "net_of_benchmark": 0.0,
    "fold": "fold_1",
    "in_oos": True,
    "embargoed": False,
    "entry_weekend": False,
    "next_close_fill": True,
    "fill_days_after_cycle": 0,
    "entry_freeze_prob": 0.5,
    "entry_temperature_min": 20.0,
    "contract_month": None,
    "adjustment_factor": None,
    "vintage_hash": "0" * 64,
    "fetch_date": datetime.now(),
}


def _ledger_row(row: dict) -> dict:
    merged = {**_LEDGER_DEFAULTS, **row}
    if merged.get("publication_ts") is None:
        merged["publication_ts"] = datetime.now() - timedelta(days=1)
    return merged


def seed_store(db_url: str, *, cycles=(), signals=(), ledger=()) -> None:
    engine = create_engine(db_url)
    init_db(engine)
    with engine.begin() as conn:
        for c in cycles:
            conn.execute(ForecastCycle.__table__.insert().values(**c))
        for s in signals:
            conn.execute(Signal.__table__.insert().values(**s))
        for row in ledger:
            conn.execute(PaperLedger.__table__.insert().values(**_ledger_row(row)))
    engine.dispose()
