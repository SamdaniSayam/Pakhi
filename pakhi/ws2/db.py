"""WS-2 T0: Core Database Infrastructure."""

from sqlalchemy import (
    JSON,
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
    forecast_cycle_id = Column(String, nullable=False)
    publication_ts = Column(DateTime(timezone=True), nullable=False)
    archive_source = Column(String, nullable=False)
    model_version = Column(String, nullable=False)


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    details = Column(JSON)


def get_engine(url: str = "postgresql://postgres:postgres@localhost:5432/pakhi"):
    return create_engine(url)


def init_db(engine):
    Base.metadata.create_all(engine)
