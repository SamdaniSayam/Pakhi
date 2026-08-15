"""WS-5 T0 — reliability contract freeze + skeleton exit evidence.

Proves the T0 exit criteria at the pure level, before any machinery ships:

- ``pakhi.ws5`` imports cleanly with no side effects (no fastapi dependency, no
  prometheus_client, no DB/env reads at package import).
- The machine contract twin self-hashes (``payload_sha256`` over the canonical
  body), and the accessor returns exactly the locked values.
- The locked constants the rest of WS-5 depends on are contract values, not
  code literals: ``AUDIT_APPEND_LOCK_ID = 4815162342``, 99.9% SLO target,
  43.2-min error budget, 50% burn alert, 10 s status cache TTL, Redis
  fail-closed 503.
- The backwards-compat rule stands: the twin records that the unset-Redis
  single-worker path is byte-identical, and WS-3/WS-4 suites re-run green.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pakhi.ws5 import contract as ws5_contract
from pakhi.ws5 import metrics as ws5_metrics

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = ROOT / "data" / "ws5" / "reliability_contract.json"


# ---------------------------------------------------------------------------
# Import-clean / no-side-effects skeleton
# ---------------------------------------------------------------------------


def test_ws5_imports_cleanly_without_api_extra() -> None:
    # Fresh interpreter: importing pakhi.ws5 pulls neither the API nor
    # prometheus_client (T2 wires the registry lazily behind initialize()).
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pakhi.ws5; "
            "assert 'fastapi' not in sys.modules, 'pakhi.ws5 must not import fastapi'; "
            "assert 'prometheus_client' not in sys.modules, 'prometheus_client must stay lazy'; "
            "assert pakhi.ws5.contract and pakhi.ws5.metrics",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ws5_import_has_no_side_effects() -> None:
    import pakhi.ws5

    assert pakhi.ws5.contract is not None and pakhi.ws5.metrics is not None
    # The laziness guarantee is proven in a fresh interpreter above; in-process
    # the API app (create_app) legitimately imports prometheus_client, so the
    # sys.modules check would be a false alarm after any app has been created.


# ---------------------------------------------------------------------------
# Contract twin self-hash + accessor fidelity
# ---------------------------------------------------------------------------


def test_contract_machine_twin_self_hashes() -> None:
    record = json.loads(CONTRACT_JSON.read_text())
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    assert record["payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert ws5_contract.contract_consistent()


def test_accessor_returns_locked_values() -> None:
    twin = ws5_contract.reliability_contract()
    assert ws5_contract.api_availability_target() == 0.999
    assert ws5_contract.error_budget_minutes() == 43.2
    assert ws5_contract.burn_alert_fraction() == 0.5
    assert ws5_contract.signal_latency_seconds() == 60
    assert ws5_contract.cycle_period_seconds() == 86400
    assert ws5_contract.freshness_max_cycles_stale() == 1
    assert ws5_contract.redis_fail_closed_http() == 503
    assert ws5_contract.status_cache_ttl_seconds() == 10
    assert twin["slo"]["never_downtime"] == ["4xx", "429", "401", "403"]
    assert ws5_contract.rpo_cycles() == 1
    assert ws5_contract.rto_hours() == 4
    assert twin["dr"]["drill_runs_in_ci"] is True
    assert "run_ws5_restore_drill.py" in twin["dr"]["drill_script"]


def test_audit_append_lock_id_is_contract_value() -> None:
    # The advisory lock key is a named constant, not an accident: it lives in
    # the contract twin and in the source constant, and must never drift.
    assert ws5_contract.audit_append_lock_id() == 4815162342
    import pakhi.ws5.contract as c

    assert c.audit_append_lock_id() == c.reliability_contract()["audit_chain"]["append_lock_id"]


def test_metrics_families_match_contract() -> None:
    families = ws5_metrics.metric_families()
    for family in ("api", "pipeline", "store", "skill", "slo"):
        assert families[family], f"metric family {family} empty"
    names = [n for lst in families.values() for n in lst]
    assert "pakhi_http_requests_total" in names
    assert "pakhi_cycle_freshness_seconds" in names
    assert "pakhi_audit_chain_ok" in names
    assert ws5_metrics.multiprocess_env() == "PROMETHEUS_MULTIPROC_DIR"


def test_backwards_compat_rule_locked() -> None:
    twin = ws5_contract.reliability_contract()
    assert "PAKHI_REDIS_URL" in twin["backwards_compat"]["rule"]
    assert "byte-identical" in twin["backwards_compat"]["rule"]
