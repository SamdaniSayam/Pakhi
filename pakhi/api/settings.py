"""WS-3 API settings — loaded from environment at app creation.

Kept dependency-free and side-effect-free at import time: ``Settings.from_env``
is called when an app is created (uvicorn entry or tests), so tests can inject
their own ``Settings`` without polluting ``os.environ``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_READ_DB_URL = "postgresql://postgres:postgres@localhost:5432/pakhi"
DEFAULT_WRITE_DB_URL = "postgresql://postgres:postgres@localhost:5432/pakhi"
API_VERSION = "1.1"
VERSION = "1.1.0"


@dataclass(frozen=True)
class Settings:
    read_db_url: str
    write_db_url: str
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: dict | None = None) -> Settings:
        """Build settings from ``PAKHI_*`` env vars (``PAKHI_DB_READ_URL``,
        ``PAKHI_DB_WRITE_URL``, ``PAKHI_CORS_ORIGINS``, ``PAKHI_LOG_LEVEL``)."""
        env = os.environ if environ is None else environ
        origins = tuple(
            o.strip() for o in env.get("PAKHI_CORS_ORIGINS", "").split(",") if o.strip()
        )
        return cls(
            read_db_url=env.get("PAKHI_DB_READ_URL", DEFAULT_READ_DB_URL),
            write_db_url=env.get("PAKHI_DB_WRITE_URL", DEFAULT_WRITE_DB_URL),
            cors_origins=origins,
            log_level=env.get("PAKHI_LOG_LEVEL", "INFO"),
        )
