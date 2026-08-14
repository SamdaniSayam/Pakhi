"""WS-3 API settings — loaded from environment at app creation.

Kept dependency-free and side-effect-free at import time: ``Settings.from_env``
is called when an app is created (uvicorn entry or tests), so tests can inject
their own ``Settings`` without polluting ``os.environ``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_READ_DB_URL = "postgresql://postgres:postgres@localhost:5432/pakhi"
DEFAULT_WRITE_DB_URL = "postgresql://postgres:postgres@localhost:5432/pakhi"
API_VERSION = "1.1"
VERSION = "1.1.0"

# data/ws3/api_keys.json (gitignored) — optional file source of raw keys:
# {"keys": ["k1", "k2"]} or a bare list. Contract: keys come from
# PAKHI_API_KEYS env (comma-separated) or this file; stored hashed at rest.
_API_KEYS_FILE = Path(__file__).resolve().parents[2] / "data" / "ws3" / "api_keys.json"


def _load_api_keys(environ: dict) -> tuple[str, ...]:
    """Collect raw API keys from env + the gitignored keys file."""
    keys: list[str] = []
    for raw in environ.get("PAKHI_API_KEYS", "").split(","):
        if raw.strip():
            keys.append(raw.strip())
    if _API_KEYS_FILE.exists():
        try:
            payload = json.loads(_API_KEYS_FILE.read_text())
            raw_keys = payload["keys"] if isinstance(payload, dict) else payload
            for raw in raw_keys or []:
                if isinstance(raw, str) and raw.strip():
                    keys.append(raw.strip())
        except (ValueError, KeyError, TypeError):
            pass
    # Deduplicate while preserving order.
    return tuple(dict.fromkeys(keys))


@dataclass(frozen=True)
class Settings:
    read_db_url: str
    write_db_url: str
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"
    api_keys: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, environ: dict | None = None) -> Settings:
        """Build settings from ``PAKHI_*`` env vars (``PAKHI_DB_READ_URL``,
        ``PAKHI_DB_WRITE_URL``, ``PAKHI_CORS_ORIGINS``, ``PAKHI_LOG_LEVEL``,
        ``PAKHI_API_KEYS``) plus the gitignored ``data/ws3/api_keys.json``."""
        env = os.environ if environ is None else environ
        origins = tuple(
            o.strip() for o in env.get("PAKHI_CORS_ORIGINS", "").split(",") if o.strip()
        )
        return cls(
            read_db_url=env.get("PAKHI_DB_READ_URL", DEFAULT_READ_DB_URL),
            write_db_url=env.get("PAKHI_DB_WRITE_URL", DEFAULT_WRITE_DB_URL),
            cors_origins=origins,
            log_level=env.get("PAKHI_LOG_LEVEL", "INFO"),
            api_keys=_load_api_keys(env),
        )
