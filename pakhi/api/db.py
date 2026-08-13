"""WS-3 two-engine DB layer.

Every ``GET /v1/*`` reads through ``read_engine`` (the ``postgres_readonly``
role in Postgres deployments) and the only API mutations — ``backtest_jobs``
enqueue + key/rate-limit bookkeeping — go through ``write_engine`` (the app
role).  The roles are the enforcement mechanism; on top of that, the read
engine opens every Postgres connection in ``default_transaction_read_only``
mode so even a coding mistake cannot issue a write on a read connection.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def build_engine(url: str, *, read_only: bool = False) -> Engine:
    """Create an engine; ``read_only=True`` hardens Postgres connections to
    server-enforced read-only transactions (defense in depth over the role)."""
    kwargs: dict = {"pool_pre_ping": True}
    if read_only and url.startswith("postgresql"):
        kwargs["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    return create_engine(url, **kwargs)
