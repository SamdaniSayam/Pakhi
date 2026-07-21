"""Tests for pipeline cache in pakhi.pipeline."""

from __future__ import annotations

import time

from pakhi.pipeline.cache import WeatherCache


class TestWeatherCache:
    def test_set_and_get(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        key = "test_key_123"
        data = b"hello weather data"
        cache.set(key, data)
        result = cache.get(key)
        assert result == data

    def test_get_missing_key(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        result = cache.get("nonexistent_key")
        assert result is None

    def test_is_stale(self):
        # timestamp from 10 hours ago
        old_time = time.time() - 10 * 3600
        assert WeatherCache.is_stale(old_time, max_age_hours=6) is True

    def test_not_stale(self):
        current_time = time.time()
        assert WeatherCache.is_stale(current_time, max_age_hours=6) is False

    def test_is_stale_boundary(self):
        current_time = time.time()
        assert WeatherCache.is_stale(current_time, max_age_hours=0.001) is False

    def test_get_json_set_json(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        key = "json_test"
        obj = {"temp": 25.0, "city": "Chicago"}
        cache.set_json(key, obj)
        result = cache.get_json(key)
        assert result["temp"] == 25.0
        assert result["city"] == "Chicago"

    def test_string_set_get(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        key = "string_test"
        cache.set(key, "string data")
        result = cache.get(key)
        assert result == b"string data"

    def test_invalidate(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        key = "inv_test"
        cache.set(key, b"data")
        assert cache.invalidate(key) is True
        assert cache.get(key) is None

    def test_invalidate_nonexistent(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        assert cache.invalidate("no_such_key") is False

    def test_clear(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        cache.set("a", b"data_a")
        cache.set("b", b"data_b")
        count = cache.clear()
        assert count == 2
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_entry_count(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        assert cache.entry_count == 0
        cache.set("a", b"data")
        assert cache.entry_count == 1
        cache.set("b", b"data")
        assert cache.entry_count == 2

    def test_hash_key_deterministic(self):
        key1 = WeatherCache.hash_key("https://api.example.com", {"lat": 40.0})
        key2 = WeatherCache.hash_key("https://api.example.com", {"lat": 40.0})
        assert key1 == key2

    def test_hash_key_params_sorted(self):
        key1 = WeatherCache.hash_key("url", {"a": 1, "b": 2})
        key2 = WeatherCache.hash_key("url", {"b": 2, "a": 1})
        assert key1 == key2

    def test_hash_key_different_url(self):
        key1 = WeatherCache.hash_key("https://a.com")
        key2 = WeatherCache.hash_key("https://b.com")
        assert key1 != key2

    def test_stale_entry_returns_none(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path)
        key = "stale_test"
        cache.set(key, b"data")
        # Artificially make it stale by writing an old mtime
        import os

        file_path = tmp_path / f"{key}.dat"
        old_time = time.time() - 100 * 3600
        os.utime(file_path, (old_time, old_time))
        result = cache.get(key, ttl_hours=1.0)
        assert result is None

    def test_ttl_override(self, tmp_path):
        cache = WeatherCache(cache_dir=tmp_path, default_ttl_hours=1.0)
        key = "ttl_test"
        cache.set(key, b"data")
        # Fresh entry should be returned
        result = cache.get(key)
        assert result == b"data"
        # Custom long TTL
        result = cache.get(key, ttl_hours=100.0)
        assert result == b"data"
