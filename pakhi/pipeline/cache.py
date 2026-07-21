"""LRU cache with TTL for weather API responses.

Stores fetched data on disk under ``~/.pakhi/cache/`` with deterministic
hash keys and configurable time-to-live for different data categories.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

__all__ = ["WeatherCache"]

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".pakhi" / "cache"
DEFAULT_TTL_FORECAST_HOURS = 6
DEFAULT_TTL_REANALYSIS_DAYS = 30
MAX_CACHE_SIZE_MB = 2048


class WeatherCache:
    """Disk-backed LRU cache with TTL-based expiration.

    Parameters
    ----------
    cache_dir : Path or str, optional
        Root directory for cached files. Defaults to ``~/.pakhi/cache/``.
    max_size_mb : int, optional
        Maximum cache size in megabytes before LRU eviction.
        Default 2048.
    default_ttl_hours : float, optional
        Default time-to-live in hours. Default 6.

    Examples
    --------
    >>> cache = WeatherCache()
    >>> cache.hash_key("https://api.example.com/forecast", {"lat": 40.7})
    'a1b2c3d4e5f6...'
    """

    __all__ = [
        "WeatherCache",
        "hash_key",
        "get",
        "set",
        "is_stale",
        "invalidate",
        "clear",
    ]

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        max_size_mb: int = MAX_CACHE_SIZE_MB,
        default_ttl_hours: float = DEFAULT_TTL_FORECAST_HOURS,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_mb = max_size_mb
        self.default_ttl_hours = default_ttl_hours
        self._index_path = self.cache_dir / ".index.json"
        self._lru: OrderedDict[str, float] = self._load_index()

    @staticmethod
    def hash_key(url: str, params: dict[str, Any] | None = None) -> str:
        """Compute a deterministic SHA-256 cache key.

        Parameters
        ----------
        url : str
            The request URL.
        params : dict, optional
            Query parameters. Keys are sorted for determinism.

        Returns
        -------
        str
            64-character hex digest.
        """
        payload = url
        if params:
            payload += "?" + json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(
        self,
        key: str,
        ttl_hours: float | None = None,
    ) -> bytes | None:
        """Retrieve cached data if it exists and is not stale.

        Parameters
        ----------
        key : str
            Cache key (from :meth:`hash_key`).
        ttl_hours : float, optional
            TTL override. Uses ``default_ttl_hours`` if ``None``.

        Returns
        -------
        bytes or None
            Cached content, or ``None`` if missing / expired.
        """
        file_path = self.cache_dir / f"{key}.dat"
        if not file_path.exists():
            self._touch_lru(key)
            return None

        ttl = ttl_hours if ttl_hours is not None else self.default_ttl_hours
        if self.is_stale(file_path.stat().st_mtime, ttl):
            logger.debug("Cache stale for key %s", key[:12])
            self._remove(file_path, key)
            return None

        self._touch_lru(key)
        return file_path.read_bytes()

    def get_json(
        self,
        key: str,
        ttl_hours: float | None = None,
    ) -> Any:
        """Retrieve and deserialise JSON from cache.

        Returns ``None`` on miss or stale entry.
        """
        raw = self.get(key, ttl_hours)
        if raw is None:
            return None
        return json.loads(raw)

    def set(
        self,
        key: str,
        data: bytes | str,
        ttl_hours: float | None = None,
    ) -> Path:
        """Store data in the cache.

        Parameters
        ----------
        key : str
            Cache key.
        data : bytes or str
            Content to store.
        ttl_hours : float, optional
            TTL (informational only — not enforced on write).

        Returns
        -------
        Path
            Path to the written cache file.
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        file_path = self.cache_dir / f"{key}.dat"
        file_path.write_bytes(data)
        self._touch_lru(key)
        self._evict_if_needed()
        return file_path

    def set_json(self, key: str, obj: Any, **dump_kwargs: Any) -> Path:
        """Serialise *obj* as JSON and store in cache."""
        default_kwargs = {"indent": 2, "default": str}
        default_kwargs.update(dump_kwargs)
        return self.set(key, json.dumps(obj, **default_kwargs))

    @staticmethod
    def is_stale(cache_timestamp: float, max_age_hours: float) -> bool:
        """Check whether a cache entry has exceeded its maximum age.

        Parameters
        ----------
        cache_timestamp : float
            Unix timestamp (e.g. ``os.path.getmtime``).
        max_age_hours : float
            Maximum allowed age in hours.

        Returns
        -------
        bool
            ``True`` if the entry is older than *max_age_hours*.
        """
        age_hours = (time.time() - cache_timestamp) / 3600.0
        return age_hours > max_age_hours

    def invalidate(self, key: str) -> bool:
        """Remove a specific cache entry.

        Returns ``True`` if the entry existed and was removed.
        """
        file_path = self.cache_dir / f"{key}.dat"
        if file_path.exists():
            self._remove(file_path, key)
            return True
        return False

    def clear(self) -> int:
        """Delete all cached files.

        Returns
        -------
        int
            Number of files removed.
        """
        count = 0
        for f in self.cache_dir.glob("*.dat"):
            f.unlink(missing_ok=True)
            count += 1
        self._lru.clear()
        self._save_index()
        return count

    @property
    def size_mb(self) -> float:
        """Total size of the cache in megabytes."""
        total = sum(f.stat().st_size for f in self.cache_dir.glob("*.dat"))
        return total / (1024 * 1024)

    @property
    def entry_count(self) -> int:
        """Number of cached entries."""
        return sum(1 for _ in self.cache_dir.glob("*.dat"))

    def _touch_lru(self, key: str) -> None:
        self._lru.pop(key, None)
        self._lru[key] = time.time()
        self._save_index()

    def _remove(self, file_path: Path, key: str) -> None:
        file_path.unlink(missing_ok=True)
        self._lru.pop(key, None)
        self._save_index()

    def _evict_if_needed(self) -> None:
        while self.size_mb > self.max_size_mb and self._lru:
            oldest_key, _ = self._lru.popitem(last=False)
            oldest_path = self.cache_dir / f"{oldest_key}.dat"
            oldest_path.unlink(missing_ok=True)
            logger.debug("Evicted cache entry %s", oldest_key[:12])
        self._save_index()

    def _load_index(self) -> OrderedDict[str, float]:
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text())
                return OrderedDict(data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupt cache index, resetting")
        return OrderedDict()

    def _save_index(self) -> None:
        try:
            self._index_path.write_text(json.dumps(dict(self._lru)))
        except OSError:
            logger.debug("Failed to save cache index", exc_info=True)
