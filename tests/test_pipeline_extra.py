"""Tests for pakhi.pipeline — RefreshScheduler."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pakhi.pipeline.schedule import RefreshScheduler


class TestRefreshScheduler:
    def test_init(self):
        sched = RefreshScheduler()
        assert sched.check_interval_seconds == 300

    def test_schedule_refresh(self):
        sched = RefreshScheduler(check_interval_seconds=9999)
        cb = MagicMock()
        job_id = sched.schedule_refresh(cb, interval_hours=6)
        assert isinstance(job_id, str)
        assert sched.next_run_time(job_id) is not None
        sched.stop()

    def test_cancel(self):
        sched = RefreshScheduler(check_interval_seconds=9999)
        job_id = sched.schedule_refresh(lambda: None, interval_hours=6)
        assert sched.cancel(job_id) is True
        assert sched.cancel(job_id) is False
        sched.stop()

    def test_next_run_time(self):
        sched = RefreshScheduler(check_interval_seconds=9999)
        assert sched.next_run_time("nonexistent") is None
        sched.stop()

    def test_is_stale(self):
        now = time.time()
        assert RefreshScheduler.is_stale(now - 7200, 1.0) is True
        assert RefreshScheduler.is_stale(now - 100, 1.0) is False

    def test_stop(self):
        sched = RefreshScheduler(check_interval_seconds=9999)
        sched.schedule_refresh(lambda: None, interval_hours=6)
        sched.stop()

    def test_callback_fires(self):
        cb = MagicMock()
        sched = RefreshScheduler(check_interval_seconds=9999)
        sched.schedule_refresh(cb, interval_hours=0, next_run_time=datetime.now(timezone.utc))
        sched._tick()
        cb.assert_called()
        sched.stop()
