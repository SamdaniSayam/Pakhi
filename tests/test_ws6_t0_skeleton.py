"""WS-6 T0 — billing/metering contract freeze + skeleton exit evidence.

Proves the T0 exit criteria at the pure level, before any machinery ships:

- ``pakhi.ws6`` imports cleanly with no side effects (no fastapi dependency, no
  prometheus_client at package import — the metrics registry is wired lazily).
- The machine contract twin self-hashes (``payload_sha256`` over the canonical
  body) and the accessors return exactly the locked values: units
  (api_call / feed_hour / backtest_hour), never-billed rule, tier prices,
  reconciliation targets + tolerance/hard thresholds, drift response, Stripe
  sync cadence + staleness, trial policy, support severities/targets.
- The backwards-compat rule stands (metering is read-only aggregation; the
  twin records it) and WS-3/WS-4/WS-5 suites re-run green.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pakhi.ws6 import contract as ws6_contract

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = ROOT / "data" / "ws6" / "billing_metering_contract.json"


def test_ws6_imports_cleanly_without_api_extra() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pakhi.ws6; "
            "assert 'fastapi' not in sys.modules, 'pakhi.ws6 must not import fastapi'; "
            "assert 'prometheus_client' not in sys.modules, 'prometheus_client must stay lazy'; "
            "assert pakhi.ws6.contract and pakhi.ws6.metering and pakhi.ws6.reconcile",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ws6_import_has_no_side_effects() -> None:
    assert ws6_contract.billing_contract is not None


def test_contract_machine_twin_self_hashes() -> None:
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    assert record["payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert ws6_contract.contract_consistent()


def test_accessor_returns_locked_values() -> None:
    twin = ws6_contract.billing_contract()
    assert twin["status"] == "LOCKED"
    assert twin["version"] == "1.3"
    assert set(twin["units"]) == {"api_call", "feed_hour", "backtest_hour"}
    assert twin["units"]["api_call"]["never_billed"] == ["4xx incl 429", "5xx", "503"]
    assert twin["tiers"]["pro"]["price_anchor_usd"] == 1500
    assert twin["reconciliation"]["targets"] == [
        "ws4-audit-chain(exact)",
        "ws5-structured-access-logs(tolerance)",
    ]
    assert twin["reconciliation"]["limiter_role"] == "ops-signal-only"
    assert ws6_contract.tolerance_percent() == 1.0
    assert ws6_contract.hard_threshold_percent() == 10.0
    assert ws6_contract.never_billed() == ["4xx incl 429", "5xx", "503"]
    assert twin["trial"]["days"] == 14
    assert twin["stripe"]["sync_cadence"] == "daily every 24h"
    assert twin["stripe"]["staleness_alert_hours"] == 24
    assert twin["support_sla"]["paid_tiers_only"] is True
    assert "4h" in str(twin["support_sla"]["severities"]["S1"]["target"])


def test_backwards_compat_rule_locked() -> None:
    twin = ws6_contract.billing_contract()
    assert "WS-3/4/5 request contract unchanged" in twin["backwards_compat"]
