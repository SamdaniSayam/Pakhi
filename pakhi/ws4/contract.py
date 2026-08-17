"""WS-4 security & tenancy contract — single source of truth accessor.

Mirrors ``pakhi.ws5.contract``. The machine twin
``data/ws4/security_tenancy_contract.json`` is the one place the locked
security/tenancy values live (token TTL, JWT algorithm, default tenant id,
per-tier rate limits). ``contract_consistent()`` verifies its self-hash; the
accessors expose the locked values so code reads them from one place and a
threshold that appears in two spots is a contract violation.

Previously this twin was orphaned (no accessor, values hardcoded in
``tokens.py``/``tenant.py``/``service.py``). This module restores the same
discipline WS-5/WS-6 have: a single hash-pinned source of truth.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_JSON = _ROOT / "data" / "ws4" / "security_tenancy_contract.json"


@lru_cache(maxsize=1)
def security_tenancy_contract() -> dict:
    """Load the machine twin (cached; the twin is hash-pinned and immutable)."""
    return json.loads(CONTRACT_JSON.read_text())


def contract_consistent() -> bool:
    """The twin's ``payload_sha256`` matches its canonical body (self-hash)."""
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    return record["payload_sha256"] == hashlib.sha256(body).hexdigest()


def access_token_ttl_minutes() -> int:
    return security_tenancy_contract()["identity"]["human"]["access_token_lifetime_minutes"]


def access_algorithm() -> str:
    return security_tenancy_contract()["identity"]["human"]["algorithm"]


def default_tenant_id() -> str:
    return security_tenancy_contract()["tenancy"]["default_tenant"]


def tier_limit_per_min(tier: str) -> int:
    return security_tenancy_contract()["tiers"][tier]["limit_per_min"]
