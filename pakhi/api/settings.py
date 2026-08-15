"""WS-3 API settings — loaded from environment at app creation.

Kept dependency-free and side-effect-free at import time: ``Settings.from_env``
is called when an app is created (uvicorn entry or tests), so tests can inject
their own ``Settings`` without polluting ``os.environ``.

WS-4 T3 fail-fast secret gate: a *weak* ``jwt_secret`` (short or an obvious
default) is a construction error on every path — the API never silently runs on
a guessable signing key. A *missing* secret is a boot error only when WS-4 is
enabled (``PAKHI_WS4_ENABLED=1``, the production posture); the WS-3 dev posture
(key-only, no WS-4) keeps booting and the admin surface answers 503.
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

# T3: signing keys below this length (or equal to an obvious default) are a
# boot error — never a served response. Tests use 32-char obvious ``test_``
# values which pass the length floor; the denylist catches hand-typed defaults.
_MIN_JWT_SECRET_LEN = 32
_WEAK_JWT_SECRETS = frozenset(
    {
        "changeme",
        "change-me",
        "changeme123",
        "secret",
        "password",
        "hunter2",
        "supersecret",
        "my-secret",
        "pakhi",
        "pakhi-jwt-secret",
        "changemechangemechangemechangeme",
        "abcdefghijklmnopqrstuvwxyz0123456789",
        "01234567890123456789012345678901",
    }
)

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


def _validate_jwt_secret(secret: str | None, ws4_enabled: bool) -> None:
    """T3 fail-fast gate: weak secret is always an error; missing secret is an
    error when WS-4 is enabled (never a silently-defaulted signing key)."""
    if secret is None:
        if ws4_enabled:
            raise ValueError(
                "PAKHI_JWT_SECRET is required when PAKHI_WS4_ENABLED=1 — refusing to boot"
            )
        return
    if len(secret) < _MIN_JWT_SECRET_LEN:
        raise ValueError(
            f"PAKHI_JWT_SECRET is weak: must be >= {_MIN_JWT_SECRET_LEN} chars, got {len(secret)}"
        )
    if secret.lower() in _WEAK_JWT_SECRETS:
        raise ValueError("PAKHI_JWT_SECRET is an obvious default — refusing to boot")


@dataclass(frozen=True)
class Settings:
    read_db_url: str
    write_db_url: str
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"
    api_keys: tuple[str, ...] = field(default_factory=tuple)
    jwt_secret: str | None = None
    jwt_issuer: str = "pakhi"
    ws4_enabled: bool = False
    redis_url: str | None = None
    workers: int = 1

    def __post_init__(self) -> None:
        _validate_jwt_secret(self.jwt_secret, self.ws4_enabled)
        # WS-5 T1: multi-worker is a contract-gated posture — horizontal workers
        # share rate-limit state and audit appends only via Redis + advisory
        # locking; silently running N workers on in-memory buckets would multiply
        # quota, so refuse to boot instead.
        if self.workers > 1 and not self.redis_url:
            raise ValueError(
                "PAKHI_WORKERS > 1 requires PAKHI_REDIS_URL "
                "(shared rate-limit state; see docs/WS5_RELIABILITY_CONTRACT.md §4)"
            )

    @classmethod
    def from_env(cls, environ: dict | None = None) -> Settings:
        """Build settings from ``PAKHI_*`` env vars (``PAKHI_DB_READ_URL``,
        ``PAKHI_DB_WRITE_URL``, ``PAKHI_CORS_ORIGINS``, ``PAKHI_LOG_LEVEL``,
        ``PAKHI_API_KEYS``, ``PAKHI_JWT_SECRET``, ``PAKHI_JWT_ISSUER``,
        ``PAKHI_WS4_ENABLED``) plus the gitignored ``data/ws3/api_keys.json``.
        ``PAKHI_WS4_ENABLED`` defaults off so the WS-3 key-only posture keeps
        booting; production WS-4 sets it to 1 and then a missing/weak
        ``PAKHI_JWT_SECRET`` refuses startup."""
        env = os.environ if environ is None else environ
        origins = tuple(
            o.strip() for o in env.get("PAKHI_CORS_ORIGINS", "").split(",") if o.strip()
        )
        ws4 = env.get("PAKHI_WS4_ENABLED", "").lower() in {"1", "true", "yes", "on"}
        workers_raw = env.get("PAKHI_WORKERS", "1").strip()
        try:
            workers = max(1, int(workers_raw))
        except ValueError:
            raise ValueError(f"PAKHI_WORKERS must be an integer, got {workers_raw!r}")
        return cls(
            read_db_url=env.get("PAKHI_DB_READ_URL", DEFAULT_READ_DB_URL),
            write_db_url=env.get("PAKHI_DB_WRITE_URL", DEFAULT_WRITE_DB_URL),
            cors_origins=origins,
            log_level=env.get("PAKHI_LOG_LEVEL", "INFO"),
            api_keys=_load_api_keys(env),
            jwt_secret=env.get("PAKHI_JWT_SECRET") or None,
            jwt_issuer=env.get("PAKHI_JWT_ISSUER", "pakhi"),
            ws4_enabled=ws4,
            redis_url=env.get("PAKHI_REDIS_URL") or None,
            workers=workers,
        )
