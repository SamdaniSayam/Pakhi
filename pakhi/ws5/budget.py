"""WS-5 SLO-1 error-budget accounting (T4).

SLO-1 is 99.9% availability at the edge over a rolling 30-day window (43.2 min
budget, contract ``slo.error_budget_minutes_per_window``). While the offer
accrues (T6) the accounting is an honest, documented proxy:

- **Remaining fraction** is rate-based, the classic error-budget math that also
  reconciles with the burn alert ``PakhiApiErrorRateBreach`` (5xx rate vs
  ``1 - slo.api_availability_target``)::

      remaining = 1 - min(1, observed_5xx_rate / (1 - api_availability_target))

- **Ledger** records every edge 5xx (timestamp, endpoint template, status) with
  its owner/repayment structure (contract §3) for the audit trail. Planned
  fail-closed 503s (Redis down in multi-worker mode, T1) are recorded but
  **never** consume budget — they are the documented fail-closed behavior, and
  are reported separately so they are not hidden.

In-process only: single worker sees its own edge; multi-worker deployments get
an honest per-worker view until a shared ledger lands. This is stated on the
status page rather than silently aggregated.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from pakhi.ws5.contract import api_availability_target


class ErrorBudget:
    """In-process SLO-1 error-budget accounting (singleton, thread-safe)."""

    def __init__(self, max_ledger: int = 200) -> None:
        # RLock: snapshot() calls remaining_fraction() while holding the lock.
        self._lock = threading.RLock()
        self._total = 0
        self._errors = 0
        self._fail_closed = 0
        self._ledger: deque[dict[str, Any]] = deque(maxlen=max_ledger)

    def record_response(self, status: int, *, endpoint: str, fail_closed: bool = False) -> None:
        """Feed one edge response. Only 5xx events are ledgered (4xx/429 are
        client faults, never downtime — contract §2)."""
        with self._lock:
            self._total += 1
            if status < 500:
                return
            if fail_closed:
                self._fail_closed += 1
            else:
                self._errors += 1
            self._ledger.appendleft(
                {
                    "ts": time.time(),
                    "status": status,
                    "endpoint": endpoint,
                    "fail_closed": fail_closed,
                }
            )

    def remaining_fraction(self) -> float:
        with self._lock:
            if self._total == 0:
                return 1.0
            allowed = 1 - api_availability_target()
            rate = self._errors / self._total
            return max(0.0, 1.0 - (rate / allowed))

    def reset(self) -> None:
        """Clear the ledger + counters (fresh accounting per app lifecycle —
        mirrors the per-app limiter reset for deterministic tests/clean boot)."""
        with self._lock:
            self._total = 0
            self._errors = 0
            self._fail_closed = 0
            self._ledger.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "remaining_fraction": self.remaining_fraction(),
                "observed_requests": self._total,
                "real_5xx": self._errors,
                "fail_closed_503": self._fail_closed,
                "ledger": list(self._ledger),
            }


# Module-level singleton: one accounting view per process.
budget = ErrorBudget()
