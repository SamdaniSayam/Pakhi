"""WS-2 T0/T2: Core Database Infrastructure.

T0 models (``forecast_cycles``, ``signals``, ``metrics``) extended by T2 with
the paper **event ledger** — one row per live paper trade in the locked
``data/ws1/t4_candidate_ledger.csv`` shape plus the provenance mandated by the
paper-trading protocol (§7): ``archive_source``, ``vintage_hash``,
``fetch_date`` on every row.

``upsert`` is the dialect-aware ON CONFLICT write (Postgres ``DO UPDATE``,
SQLite ``ON CONFLICT``) used to make the ingest→compute→ledger writes
idempotent: re-running a cycle never duplicates a row.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ForecastCycle(Base):
    __tablename__ = "forecast_cycles"

    id = Column(String, primary_key=True)  # e.g. 20231231_12z
    publication_ts = Column(DateTime(timezone=True), nullable=False)
    archive_source = Column(String, nullable=False)
    model_version = Column(String, nullable=False)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    instrument = Column(String, nullable=False)
    action = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(String)

    # Provenance Columns (Strictly Enforced NOT NULL)
    forecast_cycle_id = Column(String, unique=True, nullable=False)
    publication_ts = Column(DateTime(timezone=True), nullable=False)
    archive_source = Column(String, nullable=False)
    model_version = Column(String, nullable=False)


class PaperLedger(Base):
    __tablename__ = "paper_ledger"

    # Locked event-trade construction (WS-1 t4_candidate_ledger.csv shape).
    episode_id = Column(Integer, nullable=False)
    entry_cycle = Column(DateTime(timezone=True), nullable=False)
    entry_session = Column(DateTime(timezone=True), nullable=False)
    exit_session = Column(DateTime(timezone=True), nullable=False)
    gross = Column(Float, nullable=False)
    net = Column(Float, nullable=False)
    net_of_benchmark = Column(Float, nullable=False)
    fold = Column(String, nullable=False)
    in_oos = Column(Boolean, nullable=False)
    embargoed = Column(Boolean, nullable=False)
    entry_weekend = Column(Boolean, nullable=False)
    next_close_fill = Column(Boolean, nullable=False)
    fill_days_after_cycle = Column(Integer, nullable=False)
    entry_freeze_prob = Column(Float, nullable=False)
    entry_temperature_min = Column(Float, nullable=False)
    forecast_cycle_id = Column(String, primary_key=True)  # natural UPSERT key
    publication_ts = Column(DateTime(timezone=True), nullable=False)
    model_version = Column(String, nullable=False)
    contract_month = Column(String)
    adjustment_factor = Column(Float)
    scored = Column(Boolean, nullable=False)

    # Protocol §7 provenance on every row.
    archive_source = Column(String, nullable=False)
    vintage_hash = Column(String, nullable=False)
    fetch_date = Column(DateTime(timezone=True), nullable=False)


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    details = Column(JSON)


class BacktestJob(Base):
    __tablename__ = "backtest_jobs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="queued")  # queued | running | done | failed
    created_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    params = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)


def get_engine(url: str = "postgresql://postgres:postgres@localhost:5432/pakhi"):
    return create_engine(url)


def init_db(engine):
    Base.metadata.create_all(engine)


def upsert(engine, table, values: dict, conflict_cols: list[str]) -> None:
    """Dialect-aware ``INSERT ... ON CONFLICT (cols) DO UPDATE``.

    Postgres and SQLite share the ``ON CONFLICT`` grammar; the construct is
    selected from the engine dialect so the same worker code runs against the
    TimescaleDB service and the hermetic SQLite test database.
    """
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert

    stmt = insert(table).values(values)
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=conflict_cols,
        set_={c: getattr(excluded, c) for c in values if c not in conflict_cols},
    )
    with engine.begin() as conn:
        conn.execute(stmt)
