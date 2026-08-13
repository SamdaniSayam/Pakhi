"""WS-1: PIT loading, validation gate, and locked evaluation windows."""

from __future__ import annotations

import pandas as pd
import pytest

from pakhi.ws1.pit import (
    COST,
    EMBARGO_SESSIONS,
    FOLDS,
    OOS_END,
    OOS_START,
    TEST_FOLDS,
    benchmark_2sess,
    embargo_sessions,
    fold_label,
    load_oj,
    load_pit,
    oos_mask,
    oos_span_years,
    validate_pit_frame,
)


@pytest.fixture(scope="module")
def pit() -> pd.DataFrame:
    return load_pit()


class TestLoad:
    def test_normalised_dates_sorted(self, pit):
        assert pd.api.types.is_datetime64_any_dtype(pit["date"])
        assert pit["date"].is_monotonic_increasing
        assert pit["date"].min() == pd.Timestamp("2021-11-01")
        assert pit["date"].max() == pd.Timestamp("2026-03-31")

    def test_required_columns(self, pit):
        for col in [
            "date",
            "freeze_prob",
            "temperature_min",
            "ojd_close",
            "fwd_return",
            "ojd_next2_close",
            "fwd2_return",
        ]:
            assert col in pit.columns, col

    def test_two_session_outcomes_complete(self, pit):
        assert not pit["fwd2_return"].isna().any()


class TestValidateGate:
    def test_passes_on_real_frame(self, pit):
        ok, detail = validate_pit_frame(pit)
        assert ok
        assert "fwd2" in detail

    def test_fails_on_empty(self):
        ok, _ = validate_pit_frame(pd.DataFrame())
        assert not ok

    def test_fails_on_implausible_1sess(self, pit):
        bad = pit.copy()
        bad.loc[0, "fwd_return"] = 0.99
        ok, _ = validate_pit_frame(bad)
        assert not ok

    def test_fails_on_missing_fwd2(self, pit):
        bad = pit.drop(columns=["fwd2_return"])
        ok, _ = validate_pit_frame(bad)
        assert not ok

    def test_fails_on_nan_fwd2(self, pit):
        bad = pit.copy()
        bad.loc[0, "fwd2_return"] = float("nan")
        ok, _ = validate_pit_frame(bad)
        assert not ok

    def test_fails_on_implausible_2sess(self, pit):
        bad = pit.copy()
        bad.loc[0, "fwd2_return"] = 0.99
        ok, _ = validate_pit_frame(bad)
        assert not ok


class TestLockedWindows:
    def test_oos_row_count_is_1247(self, pit):
        assert oos_mask(pit).sum() == 1247

    def test_oos_bounds(self):
        assert pd.Timestamp("2022-11-01") == OOS_START
        assert pd.Timestamp("2026-03-31") == OOS_END

    def test_fold_spec(self):
        assert FOLDS[0][0] == "seed"
        assert [f[0] for f in TEST_FOLDS] == ["fold1", "fold2", "fold3", "fold4"]

    def test_fold_row_counts(self, pit):
        labels = fold_label(pit)
        counts = {
            name: int((labels == name).sum())
            for name in ["seed", "fold1", "fold2", "fold3", "fold4"]
        }
        assert counts == {"seed": 365, "fold1": 365, "fold2": 366, "fold3": 365, "fold4": 151}

    def test_oos_span_years_locked(self):
        assert oos_span_years() == pytest.approx(3.4114, abs=1e-4)

    def test_benchmark_reproduces_locked_value(self, pit):
        assert benchmark_2sess(pit) == pytest.approx(0.0024054917097990308, abs=1e-9)

    def test_embargo_purges_five_sessions_per_fold(self):
        sessions = load_oj().index
        emb = embargo_sessions(sessions)
        assert len(emb) == EMBARGO_SESSIONS * len(TEST_FOLDS)
        for _, start, _ in TEST_FOLDS:
            fold_sessions = sessions[(sessions >= pd.Timestamp(start))]
            head = set(fold_sessions[:EMBARGO_SESSIONS])
            assert head <= emb

    def test_cost_locked(self):
        assert pytest.approx(0.0030) == COST


class TestOJ:
    def test_sessions_are_unique_trading_days(self):
        oj = load_oj()
        assert oj.index.is_unique
        assert (oj["close_adj"] > 0).all()
        # Covers the whole PIT window plus 2-session lookahead for outcomes.
        assert oj.index.min() <= pd.Timestamp("2021-11-01")
        assert oj.index.max() > pd.Timestamp("2026-03-31")
