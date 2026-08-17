"""WS-5 T3 — Prometheus + Grafana + alerting, reconciled against the contract twin.

Exit criteria (blueprint §3.7):
- docker-compose gains prometheus (scrape config generated from the reliability
  contract JSON) and grafana (dashboards + alert rules provisioned from the repo).
- Configs parse; every alert threshold equals the contract twin value;
  regenerating the configs is byte-identical (single source of truth).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from pakhi.ws5.contract import (
    api_availability_target,
    backup_age_alert_threshold_hours,
    burn_alert_fraction,
    cycle_period_seconds,
    freshness_max_cycles_stale,
    redis_fail_closed_http,
    reliability_contract,
    signal_latency_seconds,
    stripe_sync_staleness_alert_threshold_seconds,
)

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "deploy" / "observability"
GEN = ROOT / "scripts" / "ws5_gen_observability.py"

RULES_FILE = OBS / "alert-rules.yml"
PROM_FILE = OBS / "prometheus.yml"
DASH_FILE = OBS / "grafana" / "dashboards" / "api.json"
COMPOSE_FILE = ROOT / "docker-compose.yml"

CONTRACT_FAMILIES = {
    name for group in reliability_contract()["metrics"]["families"].values() for name in group
}

EXPECTED_ALERTS = {
    "PakhiApiErrorRateBreach",
    "PakhiErrorBudgetBurn",
    "PakhiSignalLatencyBreach",
    "PakhiStalePipeline",
    "PakhiCycleFailed",
    "PakhiNoOkCycle",
    "PakhiRedisFailClosed",
    "PakhiAuditChainBroken",
    "PakhiSkillDrift",
    "PakhiBackupStale",
    "PakhiStripeSyncStale",
}

# deploy/observability/* (prometheus.yml, alert-rules.yml, grafana dashboards)
# is private — it lives in Pakhi-private and is gitignored in the public tree.
# These reconciliation tests can only run where the committed configs exist.
_requires_obs = pytest.mark.skipif(
    not (ROOT / "deploy" / "observability").exists(),
    reason="deploy/observability is private (Pakhi-private)",
)


def _parse_rules() -> list[dict]:
    groups = yaml.safe_load(RULES_FILE.read_text())["groups"]
    return [r for group in groups for r in group["rules"]]


def _metric_names_in_expr(expr: str) -> list[str]:
    import re

    # Histograms expose derived _bucket/_sum/_count series; they belong to the
    # same contract family (pakhi_http_request_duration_seconds).
    names = []
    for name in re.findall(r"\bpakhi_[a-z0-9_]+", expr):
        for suffix in ("_bucket", "_sum", "_count"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        names.append(name)
    return names


@_requires_obs
def test_generated_configs_regenerate_byte_identical(tmp_path: Path) -> None:
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(GEN), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    for rel in ("prometheus.yml", "alert-rules.yml"):
        assert (out / rel).read_bytes() == (OBS / rel).read_bytes(), (
            f"{rel} drifted from the generator output — edit "
            f"scripts/ws5_gen_observability.py, not the committed file"
        )


@_requires_obs
def test_alert_rules_thresholds_equal_contract_twin() -> None:
    rules = {r["alert"]: r for r in _parse_rules()}
    assert set(rules) == EXPECTED_ALERTS

    # SLO-1: 5xx rate above 1 - api_availability_target (0.001).
    expr = rules["PakhiApiErrorRateBreach"]["expr"]
    assert f"> {1 - api_availability_target():g}" in expr

    # Burn alert: budget remaining below 1 - burn_alert_fraction (0.5).
    expr = rules["PakhiErrorBudgetBurn"]["expr"]
    assert f"< {1 - burn_alert_fraction():g}" in expr

    # SLO-2: ingestion lag above signal_latency_seconds (60).
    expr = rules["PakhiSignalLatencyBreach"]["expr"]
    assert f"> {signal_latency_seconds()}" in expr

    # SLO-3: freshness above cycle_period * freshness_max_cycles_stale (86400).
    expr = rules["PakhiStalePipeline"]["expr"]
    assert f"> {cycle_period_seconds() * freshness_max_cycles_stale()}" in expr

    # No-OK-cycle window = one cycle period.
    expr = rules["PakhiNoOkCycle"]["expr"]
    assert f"> {cycle_period_seconds()}" in expr

    # Redis fail-closed alert keys on the fail_closed_http status code.
    expr = rules["PakhiRedisFailClosed"]["expr"]
    assert f'status="{redis_fail_closed_http()}"' in expr

    # Backup age: threshold in seconds = hours * 3600.
    expr = rules["PakhiBackupStale"]["expr"]
    assert f"> {backup_age_alert_threshold_hours() * 3600}" in expr

    # Stripe sync staleness: threshold in seconds.
    expr = rules["PakhiStripeSyncStale"]["expr"]
    assert f"> {stripe_sync_staleness_alert_threshold_seconds()}" in expr

    for _, rule in rules.items():
        # Every threshold is annotated with its twin path + rendered value.
        assert rule["annotations"]["contract_path"]
        assert rule["annotations"]["summary"]
        assert rule["labels"]["severity"] in {"warning", "critical"}


@_requires_obs
def test_every_alert_consumes_a_contract_family() -> None:
    for rule in _parse_rules():
        used = set(_metric_names_in_expr(rule["expr"]))
        assert used, f"{rule['alert']} references no pakhi metric"
        assert used <= CONTRACT_FAMILIES, (
            f"{rule['alert']} references metrics not in the contract twin: "
            f"{used - CONTRACT_FAMILIES}"
        )


@_requires_obs
def test_prometheus_config_scrapes_api_and_loads_rules() -> None:
    cfg = yaml.safe_load(PROM_FILE.read_text())
    assert "alert-rules.yml" in cfg["rule_files"]
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    api = jobs["pakhi-api"]
    assert api["metrics_path"] == "/metrics"
    assert api["static_configs"][0]["targets"] == ["api:8000"]
    assert cfg["global"]["scrape_interval"]
    assert cfg["global"]["evaluation_interval"]


@_requires_obs
def test_dashboard_references_only_contract_families() -> None:
    import json

    dash = json.loads(DASH_FILE.read_text())
    used = set()
    exprs = []
    for panel in dash["panels"]:
        for target in panel.get("targets", []):
            exprs.append(target["expr"])
            used.update(_metric_names_in_expr(target["expr"]))
    assert used, "dashboard panels reference no pakhi metrics"
    assert used <= CONTRACT_FAMILIES, (
        f"dashboard leaks non-contract metrics: {used - CONTRACT_FAMILIES}"
    )
    # The SLO-1 error-budget panel consumes the T4 accounting gauge.
    assert any("pakhi_error_budget_remaining_fraction" in e for e in exprs)


@_requires_obs
def test_docker_compose_provisions_observability() -> None:
    # The observability stack (deploy/observability/*) is private (Pakhi-private);
    # the volume mounts are only validated there. The compose *service* shape is
    # still public and checked below.
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose["services"]
    assert "prometheus" in services and "grafana" in services
    prom = services["prometheus"]
    assert "./deploy/observability/prometheus.yml" in prom["volumes"][0]
    assert "./deploy/observability/alert-rules.yml" in prom["volumes"][1]
    graf = services["grafana"]
    assert any("provisioning" in v and ":ro" in v for v in graf["volumes"])
    assert any("dashboards" in v and ":ro" in v for v in graf["volumes"])


def test_docker_compose_config_valid_if_docker_available() -> None:
    # `docker compose` (v2 plugin) or the v1 `docker-compose` binary — whichever
    # the environment ships (GH Actions runners have the v2 plugin).
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if probe.returncode == 0:
        cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "-q"]
    else:
        alt = subprocess.run(["docker-compose", "version"], capture_output=True, text=True)
        if alt.returncode == 127:
            return  # no compose tooling in this environment
        cmd = ["docker-compose", "-f", str(COMPOSE_FILE), "config", "-q"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
