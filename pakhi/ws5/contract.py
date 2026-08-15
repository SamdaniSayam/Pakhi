"""WS-5 reliability contract — single source of truth accessor.

The machine twin ``data/ws5/reliability_contract.json`` is the one place
thresholds live (SLO targets, error budget, alert burn fraction, cache TTL,
``AUDIT_APPEND_LOCK_ID``, fail-closed HTTP code). Alert rules, the status page,
and the error-budget accounting are reconciled against this accessor — a
threshold that appears more than once in the codebase is a contract violation.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = _ROOT / "docs" / "WS5_RELIABILITY_CONTRACT.md"
CONTRACT_JSON = _ROOT / "data" / "ws5" / "reliability_contract.json"


@lru_cache(maxsize=1)
def reliability_contract() -> dict:
    """Load the machine twin (cached; the twin is hash-pinned and immutable)."""
    return json.loads(CONTRACT_JSON.read_text())


def contract_consistent() -> bool:
    """The twin's ``payload_sha256`` matches its canonical body (self-hash)."""
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    return record["payload_sha256"] == hashlib.sha256(body).hexdigest()


def api_availability_target() -> float:
    return reliability_contract()["slo"]["api_availability_target"]


def error_budget_minutes() -> float:
    return reliability_contract()["slo"]["error_budget_minutes_per_window"]


def burn_alert_fraction() -> float:
    return reliability_contract()["slo"]["burn_alert_fraction"]


def signal_latency_seconds() -> int:
    return reliability_contract()["slo"]["signal_latency_seconds"]


def cycle_period_seconds() -> int:
    return reliability_contract()["slo"]["cycle_period_seconds"]


def freshness_max_cycles_stale() -> int:
    return reliability_contract()["slo"]["freshness_max_cycles_stale"]


def audit_append_lock_id() -> int:
    """The advisory-lock key for multi-worker audit chain appends (T1)."""
    return reliability_contract()["audit_chain"]["append_lock_id"]


def redis_fail_closed_http() -> int:
    return reliability_contract()["redis"]["fail_closed_http"]


def status_cache_ttl_seconds() -> int:
    return reliability_contract()["status"]["cache_ttl_seconds"]


def rpo_cycles() -> int:
    return reliability_contract()["dr"]["rpo_cycles"]


def rto_hours() -> int:
    return reliability_contract()["dr"]["rto_hours"]
