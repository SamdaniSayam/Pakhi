"""Tests for pakhi.ws0.features — freeze feature extraction from GFS frames."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.ws0.features import freeze_features, publish_time

T0C = 273.15


def _frame(t2m_values, valid_times):
    n = len(t2m_values)
    return pd.DataFrame(
        {
            "latitude": np.linspace(25, 30, n),
            "longitude": np.full(n, 276.0),
            "time": [pd.Timestamp("2022-01-15 12:00")] * n,
            "valid_time": valid_times,
            "t2m": t2m_values,
        }
    )


def test_freeze_features_all_warm():
    frame = _frame([280.0] * 10, pd.date_range("2022-01-15 18:00", periods=10, freq="6h"))
    feats = freeze_features(frame)
    assert feats["freeze_prob"] == 0.0
    assert feats["temperature_min"] == pytest.approx(280.0 - T0C)
    assert feats["current_time"] == publish_time(pd.Timestamp("2022-01-15"))


def test_freeze_features_half_cold():
    vals = [280.0] * 5 + [271.0] * 5
    times = pd.date_range("2022-01-15 16:00", periods=10, freq="4h")  # last 04:00 +1d < 48h
    feats = freeze_features(_frame(vals, times))
    assert feats["freeze_prob"] == pytest.approx(0.5)
    assert feats["temperature_min"] == pytest.approx(271.0 - T0C)
    assert feats["event_peak_time"] == times[5].tz_localize("UTC").to_pydatetime()


def test_freeze_features_horizon_excludes_late_cells():
    vals = [271.0] * 4 + [280.0] * 6  # cold cells all within ~24h
    times = pd.date_range("2022-01-15 18:00", periods=10, freq="12h")  # 0-108h
    feats = freeze_features(_frame(vals, times), horizon_hours=48)
    # within 48h: cells at 18:00, 06:00(+1d), 18:00(+1d), 06:00(+2d) -> 4 cold
    assert feats["freeze_prob"] == pytest.approx(1.0)
    assert feats["horizon_cells"] == 4


def test_freeze_features_empty_frame():
    feats = freeze_features(pd.DataFrame())
    assert feats["freeze_prob"] == 0.0
    assert np.isnan(feats["temperature_min"])


def test_publish_time():
    t = publish_time(pd.Timestamp("2022-01-15"))
    assert t.hour == 15
    assert t.minute == 30
    assert t.tzinfo is not None


def test_freeze_features_edge_zero():
    # exactly 0C is NOT a freeze cell
    frame = _frame([273.15] * 3, pd.date_range("2022-01-15 18:00", periods=3, freq="6h"))
    assert freeze_features(frame)["freeze_prob"] == 0.0
