"""Refresh scheduling for weather data pipelines.

Provides staleness checking and callback-based scheduling to keep
cached weather data up to date.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = ["RefreshScheduler"]

logger = logging.getLogger(__name__)


class RefreshScheduler:
    """Callback scheduler that triggers data refreshes when cache is stale.

    Parameters
    ----------
    check_interval_seconds : int, optional
        How often the background thread polls for stale entries.
        Default 300 (5 minutes).

    Examples
    --------
    >>> scheduler = RefreshScheduler()
    >>> scheduler.schedule_refresh(
    ...     callback=lambda: print("Refreshing..."),
    ...     interval_hours=6,
    ... )
    """

    __all__ = [
        "RefreshScheduler",
        "schedule_refresh",
        "cancel",
        "is_stale",
        "next_run_time",
    ]

    def __init__(self, check_interval_seconds: int = 300) -> None:
        self.check_interval_seconds = check_interval_seconds
        self._jobs: dict[str, dict[str, Any]] = {}
        self._timer: threading.Timer | None = None
        self._running = False
        self._lock = threading.Lock()

    def schedule_refresh(
        self,
        callback: Callable[[], Any],
        interval_hours: float,
        next_run_time: datetime | None = None,
        job_id: str | None = None,
    ) -> str:
        """Register a recurring refresh callback.

        Parameters
        ----------
        callback : callable
            Function to invoke at each scheduled time.
        interval_hours : float
            Hours between refreshes.
        next_run_time : datetime, optional
            When to first run. Defaults to now (immediate).
        job_id : str, optional
            Unique identifier for this job. Auto-generated if omitted.

        Returns
        -------
        str
            The job identifier.
        """
        if job_id is None:
            job_id = f"job_{len(self._jobs)}_{int(time.time())}"

        if next_run_time is None:
            next_run_time = datetime.now(timezone.utc)

        if next_run_time.tzinfo is None:
            next_run_time = next_run_time.replace(tzinfo=timezone.utc)

        with self._lock:
            self._jobs[job_id] = {
                "callback": callback,
                "interval_hours": interval_hours,
                "next_run": next_run_time,
            }

        logger.info(
            "Scheduled refresh %s every %.1fh (next: %s)",
            job_id,
            interval_hours,
            next_run_time.isoformat(),
        )

        self._ensure_running()
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job.

        Returns ``True`` if the job existed and was removed.
        """
        with self._lock:
            removed = self._jobs.pop(job_id, None)
        if removed is not None:
            logger.info("Cancelled refresh job %s", job_id)
        return removed is not None

    def next_run_time(self, job_id: str) -> datetime | None:
        """Return the next scheduled run time for a job."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return job["next_run"]

    @staticmethod
    def is_stale(cache_timestamp: float, max_age_hours: float) -> bool:
        """Check whether cached data has exceeded its maximum age.

        Parameters
        ----------
        cache_timestamp : float
            Unix timestamp of the cache entry.
        max_age_hours : float
            Maximum allowed age in hours.

        Returns
        -------
        bool
            ``True`` if the entry is older than *max_age_hours*.
        """
        age_hours = (time.time() - cache_timestamp) / 3600.0
        return age_hours > max_age_hours

    def _ensure_running(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def _tick(self) -> None:
        if not self._running:
            return

        now = datetime.now(timezone.utc)
        fired_jobs: list[str] = []

        with self._lock:
            for job_id, job in self._jobs.items():
                if now >= job["next_run"]:
                    fired_jobs.append(job_id)

        for job_id in fired_jobs:
            job = self._jobs.get(job_id)
            if job is None:
                continue

            def _run_job(jid: str = job_id, cb=job["callback"], hrs=job["interval_hours"]) -> None:
                try:
                    cb()
                except Exception:
                    logger.exception("Refresh callback failed for job %s", jid)
                with self._lock:
                    if jid in self._jobs:
                        self._jobs[jid]["next_run"] = datetime.now(timezone.utc) + timedelta(hours=hrs)

            t = threading.Thread(target=_run_job, name=f"RefreshJob-{job_id}", daemon=True)
            t.start()

        self._timer = threading.Timer(self.check_interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
