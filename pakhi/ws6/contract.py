"""WS-6 billing/metering contract — single source of truth accessor.

The machine twin ``data/ws6/billing_metering_contract.json`` is the one place
billing numbers live (billable units + their definitions, tier prices, never-
billed rules, reconciliation targets + tolerances, drift response, Stripe sync
cadence, trial policy, support SLA). Metering code, reconciliation, suspension,
and the trial lifecycle reconcile against this accessor — a billing number that
appears more than once in the codebase is a contract violation.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = _ROOT / "docs" / "WS6_BILLING_METERING_CONTRACT.md"
CONTRACT_JSON = _ROOT / "data" / "ws6" / "billing_metering_contract.json"


@lru_cache(maxsize=1)
def billing_contract() -> dict:
    """Load the machine twin (cached; the twin is hash-pinned and immutable)."""
    return json.loads(CONTRACT_JSON.read_text())


def contract_consistent() -> bool:
    """The twin's ``payload_sha256`` matches its canonical body (self-hash)."""
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    return record["payload_sha256"] == hashlib.sha256(body).hexdigest()


def billable_units() -> dict:
    return billing_contract()["units"]


def never_billed() -> list[str]:
    return billing_contract()["units"]["api_call"]["never_billed"]


def reconciliation() -> dict:
    return billing_contract()["reconciliation"]


def tolerance_percent() -> float:
    return float(reconciliation()["tolerance_percent"])


def hard_threshold_percent() -> float:
    return float(reconciliation()["hard_threshold_percent"])


def drift_response() -> dict:
    return reconciliation()["drift_response"]


def stripe() -> dict:
    return billing_contract()["stripe"]


def trial_days() -> int:
    return int(billing_contract()["trial"]["days"])


def support_sla() -> dict:
    return billing_contract()["support_sla"]
