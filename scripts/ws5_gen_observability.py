#!/usr/bin/env python3
"""Generate Prometheus + Grafana configs from the WS-5 contract twin.

Single source of truth: every numeric threshold in the generated alert rules
comes from ``data/ws5/reliability_contract.json`` (via pakhi.ws5.contract).
A threshold that would appear twice in the codebase is a contract violation;
this script is the *only* place the Prometheus/Grafana numbers are rendered.

Usage:
    python scripts/ws5_gen_observability.py [--out DIR]   # default deploy/observability

Deterministic: regenerating yields byte-identical files (CI asserts this).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pakhi.ws5.contract import (
    api_availability_target,
    burn_alert_fraction,
    cycle_period_seconds,
    freshness_max_cycles_stale,
    redis_fail_closed_http,
    signal_latency_seconds,
)

RULES_ANNOTATION = (
    "Single source of truth: thresholds are rendered from "
    "data/ws5/reliability_contract.json by scripts/ws5_gen_observability.py."
)

PROMETHEUS_YML = """\
global:
  scrape_interval: 15s
  evaluation_interval: 30s

rule_files:
  - alert-rules.yml

scrape_configs:
  - job_name: pakhi-api
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
"""


def _fmt_float(value: float) -> str:
    return f"{value:g}"


def _rules_body() -> str:
    target = api_availability_target()
    error_rate_threshold = 1 - target
    burn = burn_alert_fraction()
    remaining_threshold = 1 - burn
    cycle = cycle_period_seconds()
    stale = freshness_max_cycles_stale()
    stale_threshold = cycle * stale
    latency = signal_latency_seconds()
    fail_closed = redis_fail_closed_http()

    rules = [
        {
            "alert": "PakhiApiErrorRateBreach",
            "expr": (
                f"sum(rate(pakhi_http_5xx_total[5m])) "
                f"/ sum(rate(pakhi_http_requests_total[5m])) "
                f"> {_fmt_float(error_rate_threshold)}"
            ),
            "for": "10m",
            "path": "slo.api_availability_target",
            "value": f"1 - {_fmt_float(target)}",
            "severity": "critical",
            "summary": "API error rate above the SLO-1 budget burn (5xx only).",
        },
        {
            "alert": "PakhiErrorBudgetBurn",
            "expr": (f"pakhi_error_budget_remaining_fraction < {_fmt_float(remaining_threshold)}"),
            "for": "1m",
            "path": "slo.burn_alert_fraction",
            "value": f"1 - {_fmt_float(burn)}",
            "severity": "critical",
            "summary": (
                ">=50% of the 30-day error budget consumed; status page shows "
                "error_budget_remaining."
            ),
        },
        {
            "alert": "PakhiSignalLatencyBreach",
            "expr": f"pakhi_cycle_ingestion_lag_seconds > {latency}",
            "for": "5m",
            "path": "slo.signal_latency_seconds",
            "value": str(latency),
            "severity": "warning",
            "summary": "Published signal not served within the SLO-2 latency.",
        },
        {
            "alert": "PakhiStalePipeline",
            "expr": f"pakhi_cycle_freshness_seconds > {stale_threshold}",
            "for": "5m",
            "path": "slo.cycle_period_seconds * slo.freshness_max_cycles_stale",
            "value": f"{cycle} * {stale}",
            "severity": "warning",
            "summary": "Pipeline stale past SLO-3 (freshness >= 1 cycle).",
        },
        {
            "alert": "PakhiCycleFailed",
            "expr": "pakhi_cycle_status == 0",
            "for": "5m",
            "path": "metrics.families.pipeline (pakhi_cycle_status, 0 = failed)",
            "value": "0",
            "severity": "warning",
            "summary": "Latest published cycle status is failed.",
        },
        {
            "alert": "PakhiNoOkCycle",
            "expr": (f"time() - pakhi_cycle_last_ok_timestamp_seconds > {cycle}"),
            "for": "15m",
            "path": "slo.cycle_period_seconds",
            "value": str(cycle),
            "severity": "warning",
            "summary": "No OK cycle for a full cycle period.",
        },
        {
            "alert": "PakhiRedisFailClosed",
            "expr": (f'sum(increase(pakhi_http_requests_total{{status="{fail_closed}"}}[5m])) > 0'),
            "for": "5m",
            "path": "redis.fail_closed_http",
            "value": str(fail_closed),
            "severity": "warning",
            "summary": (
                "Multi-worker Redis down: requests failing closed with "
                "fail_closed_http (planned 503s, recorded in the budget ledger)."
            ),
        },
        {
            "alert": "PakhiAuditChainBroken",
            "expr": "pakhi_audit_chain_ok == 0",
            "for": "5m",
            "path": "metrics.families.store (pakhi_audit_chain_ok, 1 = ok)",
            "value": "0",
            "severity": "critical",
            "summary": "Audit chain verification is failing.",
        },
        {
            "alert": "PakhiSkillDrift",
            "expr": "pakhi_live_bss_vs_baseline < 0",
            "for": "1h",
            "path": "metrics.families.skill (pakhi_live_bss_vs_baseline, 0 = at baseline)",
            "value": "0",
            "severity": "warning",
            "summary": "Sustained skill regression below the WS-2 baseline.",
        },
    ]

    lines = ["groups:", "  - name: pakhi-reliability.rules"]
    lines.append(f"    # {RULES_ANNOTATION}")
    lines.append("    rules:")
    for r in rules:
        lines.append(f"      - alert: {r['alert']}")
        lines.append(f"        expr: {r['expr']}")
        lines.append(f"        for: {r['for']}")
        lines.append("        labels:")
        lines.append(f"          severity: {r['severity']}")
        lines.append("        annotations:")
        lines.append(f'          summary: "{r["summary"]}"')
        lines.append(f'          contract_path: "{r["path"]}"  # rendered value: {r["value"]}')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="deploy/observability", type=Path)
    args = parser.parse_args()

    out = Path(args.out)
    grafana = out / "grafana" / "dashboards"
    grafana.mkdir(parents=True, exist_ok=True)

    (out / "prometheus.yml").write_text(PROMETHEUS_YML)
    (out / "alert-rules.yml").write_text(_rules_body())
    (out / "README.md").write_text(
        "Generated by scripts/ws5_gen_observability.py from the WS-5 contract "
        "twin (data/ws5/reliability_contract.json). Do not edit by hand: "
        "`python scripts/ws5_gen_observability.py` regenerates byte-identical "
        "files, and tests/test_ws5_t3_alerting.py asserts the committed files "
        "match the generator output.\n"
    )
    print(f"wrote {out}/prometheus.yml, alert-rules.yml, README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
