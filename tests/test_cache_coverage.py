from pakhi.pipeline.cache import WeatherCache


def test_cache_load_index_corrupt(tmp_path):
    index_file = tmp_path / ".index.json"
    index_file.write_text("invalid json")

    # Should catch JSONDecodeError and return empty OrderedDict
    cache = WeatherCache(cache_dir=tmp_path)
    assert len(cache._lru) == 0
