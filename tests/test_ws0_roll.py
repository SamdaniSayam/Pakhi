"""Tests for pakhi.ws0.roll — continuous contracts, roll adjustment, assertions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pakhi.ws0.roll import back_adjust, front_month_map, roll_jump_assertion


@pytest.fixture
def calendar():
    return pd.DataFrame(
        {
            "month_name": ["Mar26", "May26", "Jul26"],
            "first_notice_day": ["2026-03-02", "2026-05-01", "2026-07-01"],
            "last_trading_day": ["2026-02-26", "2026-04-28", "2026-06-29"],
        }
    )


@pytest.fixture
def flat_series():
    idx = pd.date_range("2026-01-01", periods=130, freq="D")
    return pd.Series(100.0, index=idx)


def test_front_month_map_fnd(calendar):
    dates = pd.date_range("2026-02-20", periods=4, freq="D")
    m = front_month_map(dates, calendar, roll_rule="FND")
    assert m.iloc[0] == "Mar26"
    after_roll = pd.Timestamp("2026-03-02")
    assert front_month_map(pd.DatetimeIndex([after_roll]), calendar, "FND").iloc[0] == "May26"


def test_front_month_map_ltd(calendar):
    d = pd.Timestamp("2026-02-26")
    assert front_month_map(pd.DatetimeIndex([d]), calendar, "LTD").iloc[0] == "Mar26"
    next_day = pd.Timestamp("2026-02-27")
    assert front_month_map(pd.DatetimeIndex([next_day]), calendar, "LTD").iloc[0] == "May26"


def test_back_adjust_removes_roll_jump(calendar):
    idx = pd.date_range("2026-02-20", periods=20, freq="D")
    base = pd.Series(100.0, index=idx)
    roll_idx = pd.Timestamp("2026-03-02")
    pos = idx.get_loc(roll_idx)
    prices = base.copy()
    prices.iloc[pos:] = 120.0  # 20% phantom roll gap, no volatility
    out = back_adjust(prices, calendar, roll_rule="FND")
    assert np.allclose(out.prices.diff().dropna(), 0.0, atol=1e-9)
    assert out.provenance[0].factor == pytest.approx(1.2)
    assert out.provenance[0].flagged is False


def test_back_adjust_keeps_real_gap_flagged(calendar):
    idx = pd.date_range("2026-02-20", periods=20, freq="D")
    prices = pd.Series(100.0, index=idx)
    roll_idx = pd.Timestamp("2026-03-02")
    pos = idx.get_loc(roll_idx)
    prices.iloc[pos:] = 300.0  # 3x jump = real event, must not be adjusted away
    out = back_adjust(prices, calendar, roll_rule="FND")
    assert out.provenance[0].flagged is True
    assert out.prices.iloc[pos] == pytest.approx(300.0)


def test_roll_jump_assertion_flags_real_move_near_roll(calendar):
    idx = pd.date_range("2026-02-20", periods=20, freq="D")
    prices = pd.Series(100.0, index=idx)
    prices.iloc[8:] = 250.0  # sudden move 3 days before the Mar26 FND
    flags = roll_jump_assertion(
        prices,
        [pd.Timestamp("2026-03-02")],
        n_sigma=5.0,
        sigma_window=10,
        window_days=3,
    )
    assert len(flags) >= 1
    assert "near_roll" in flags.columns


def test_back_adjust_provenance_frame(calendar):
    idx = pd.date_range("2026-01-01", periods=150, freq="D")  # spans Mar/May FNDs
    prices = pd.Series(100.0, index=idx)
    out = back_adjust(prices, calendar, roll_rule="FND")
    frame = out.provenance_frame()
    assert set(frame.columns) >= {"roll_date", "adjustment_type", "factor", "flagged"}
    assert len(frame) == 2  # two roll dates inside the window


def test_back_adjust_ignores_roll_outside_window(calendar):
    idx = pd.date_range("2026-01-01", periods=10, freq="D")  # before Mar FND
    prices = pd.Series(100.0, index=idx)
    out = back_adjust(prices, calendar, roll_rule="FND")
    assert len(out.provenance) == 0
