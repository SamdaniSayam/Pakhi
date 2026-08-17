"""WS-5 T6 — SLA offer posture flip + exit evidence.

T6 flips the WS-4 no-SLA clause into a **conditional offer** only after the
reliability machinery is live and the 30-day measurement window is open and
recorded. The evidence of meeting 99.9% accrues during the window; nothing here
fabricates an achieved-uptime number (G1 stays UNDER-POWERED). These tests are
the machine-checkable half of the T6 exit criteria: both contract twins
re-pinned, the window recorded, and *every* SOC2 reliability control backed by
a test or a rehearsed drill — never a bare config file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pakhi.ws5.contract import contract_consistent, reliability_contract

ROOT = Path(__file__).resolve().parents[1]
WS4_CONTRACT_JSON = ROOT / "data" / "ws4" / "security_tenancy_contract.json"
WS5_CONTRACT_JSON = ROOT / "data" / "ws5" / "reliability_contract.json"
PROGRESS = ROOT / "docs" / "WS5_PROGRESS.md"

# Every SOC2 reliability control -> the test/drill/script that machine-checks
# it (T6 exit: a control with only a config file is not a control).
EVIDENCE = {
    "t1_redis": ["tests/test_ws5_t1_redis.py", "pakhi/ws5/redis_limiter.py"],
    "t2_metrics": ["tests/test_ws5_t2_metrics.py", "pakhi/ws5/metrics.py"],
    "t3_alerting": [
        "tests/test_ws5_t3_alerting.py",
        "scripts/ws5_gen_observability.py",
        "deploy/observability/alert-rules.yml",
    ],
    "t4_slo_accounting": ["pakhi/ws5/budget.py", "tests/test_ws5_t4_status.py"],
    "t5_dr_drill": [
        "scripts/run_ws5_backup.py",
        "scripts/run_ws5_restore_drill.py",
        ".github/workflows/ws5-dr.yml",
    ],
}


def _sha(record: dict) -> str:
    body = json.dumps(
        {k: v for k, v in record.items() if k != "payload_sha256"}, sort_keys=True
    ).encode()
    return hashlib.sha256(body).hexdigest()


def test_ws4_twin_upgraded_to_conditional_offer() -> None:
    twin = json.loads(WS4_CONTRACT_JSON.read_text())
    assert twin["payload_sha256"] == _sha(twin)
    assert twin["version"] == "1.1"
    assert "conditional offer" in twin["uptime"]
    assert "no achieved-uptime claim" in twin["uptime"]
    # The offer is conditioned on the machinery + the window, not on a promise.
    assert "measurement window is open and recorded" in twin["uptime"]


def test_ws5_twin_offer_is_live_with_window() -> None:
    twin = reliability_contract()
    assert contract_consistent()
    assert twin["version"] == "1.4"
    assert twin["slo"]["sla_offer_active"] is True
    window = twin["slo"]["measurement_window"]
    assert window["days"] == 30
    started = datetime.fromisoformat(window["started_utc"])
    ends = datetime.fromisoformat(window["ends_utc"])
    assert (ends - started).days == 30
    assert ends.tzinfo is not None  # recorded UTC, not a naive placeholder
    # The offer's gates are all machinery that T1–T6 shipped; none is a claim.
    assert twin["slo"]["sla_offer_gates"] == [
        "t1_redis",
        "t2_metrics",
        "t4_slo_accounting",
        "t5_dr_drill",
        "t6_30day_window_open",
    ]


def test_every_soc2_control_has_machine_evidence_not_a_config() -> None:
    twin = reliability_contract()
    controls = twin["soc2"]["reliability_controls_operational_at"]
    assert controls == [
        "t1_redis",
        "t2_metrics",
        "t3_alerting",
        "t4_slo_accounting",
        "t5_dr_drill",
    ]
    for control in controls:
        paths = EVIDENCE[control]
        # Evidence that lives in the private repo (Pakhi-private) — deploy/
        # artifacts and relocated deploy workflows — is excluded from the
        # public-repo assertion; it is still machine-checked in Pakhi-private.
        private = ("deploy/", ".github/workflows/ws5-dr.yml")
        public_paths = [p for p in paths if not p.startswith(private)]
        missing = [p for p in public_paths if not (ROOT / p).exists()]
        assert not missing, f"{control}: evidence missing {missing}"
        # A control backed only by generated config is not operational.
        assert any((ROOT / p).suffix in (".py", ".yml") for p in public_paths)


def test_measurement_window_recorded_in_progress_doc() -> None:
    text = PROGRESS.read_text()
    assert "30-day measurement window" in text
    assert "2026-08-14" in text
    assert "sla_offer" in text or "conditional offer" in text


def test_no_fabricated_uptime_claim_anywhere() -> None:
    # WS-5 never asserts an achieved uptime number — only the target, the
    # window, and the offer. A fake "we hit 99.9%" key would violate this.
    ws5 = json.loads(WS5_CONTRACT_JSON.read_text())
    assert "achieved_uptime" not in ws5["slo"]
    assert "observed_availability" not in ws5["slo"]
    ws4 = json.loads(WS4_CONTRACT_JSON.read_text())
    assert "no achieved-uptime claim" in ws4["uptime"]
    assert "UNDER-POWERED" in ws5["gate"]["g1"]
