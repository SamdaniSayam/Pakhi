"""WS-2 T4: G1 re-run & G2 handoff — decision record from the live paper ledger.

Contract (``docs/WS2_EXECUTION_BLUEPRINT.md`` §4-T4, §8 and the paper-trading
protocol §5):

- **Exact re-run:** the live scored paper events feed the *same*
  :func:`~pakhi.ws1.significance.significance_report` (same N gate, Sharpe > 1,
  bootstrap CI lower bound, Newey-West) as the WS-1 G1 — no new machinery, no
  re-tuning.
- **WS-1 ledger shape:** the DB ledger is read back in the locked
  ``t4_candidate_ledger.csv`` column shape so nothing downstream changes.
- **Honest verdicts:** if N < 8 after the 60-day window the decision is the
  same UNDER_POWERED (events arrive only at the rate of real freezes — a data
  fact, not a defect); the report never stretches a claim.
- **G2 = infrastructure gate only:** an autonomous, no-lookahead,
  provenance-complete signal store feeding the paper ledger.  It does **not**
  clear G1.  WS-3 (API) is gated on the G1 re-run verdict.
- **Self-hash-pinned** machine twin, mirroring ``pakhi.ws1.g1``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pakhi.ws1.pit import benchmark_2sess, load_pit
from pakhi.ws1.significance import N_MIN, significance_report
from pakhi.ws2.protocol import G1_DATE

__all__ = [
    "G2_DECISION_JSON",
    "G2_REPORT",
    "OUTCOME_LABEL",
    "build_g2_decision",
    "g2_decision_consistent",
    "load_live_ledger",
    "produce_g2_report",
    "recomputed_rbar",
    "record_sha256",
    "scored_events",
]

G2_REPORT = "docs/WS2_G2_REPORT.md"
G2_DECISION_JSON = "data/ws2/g2_decision.json"

OUTCOME_LABEL = {
    "ZERO_TRADES": "architecture success: live harness running, no scored events yet",
    "UNDER_POWERED": "no conclusion; N < N_min after the live window (data fact, not a defect)",
    "PASS": "G1 re-run PASS on the live paper ledger; WS-3 build authorized",
    "FAIL_PIVOT": "edge refuted on the live paper ledger; documented pivot",
}

_LEDGER_COLUMNS = [
    "episode_id",
    "entry_cycle",
    "entry_session",
    "exit_session",
    "gross",
    "net",
    "net_of_benchmark",
    "fold",
    "in_oos",
    "embargoed",
    "entry_weekend",
    "next_close_fill",
    "fill_days_after_cycle",
    "entry_freeze_prob",
    "entry_temperature_min",
    "forecast_cycle_id",
    "publication_ts",
    "model_version",
    "contract_month",
    "adjustment_factor",
    "scored",
]


def record_sha256(payload: dict) -> str:
    """Self-verifying hash over the canonical JSON payload (excluding itself)."""
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()


def load_live_ledger(engine) -> pd.DataFrame:
    """Paper ledger from the DB in the locked ``t4_candidate_ledger.csv`` shape.

    Reads every row (scored and unscored) so the report carries full
    provenance; the G1 re-run itself only uses the scored events.
    """
    df = pd.read_sql_table("paper_ledger", engine)
    for c in ("entry_cycle", "entry_session", "exit_session"):
        df[c] = pd.to_datetime(df[c])
    df["fold"] = df["fold"].fillna("live")
    return df[_LEDGER_COLUMNS].sort_values("entry_session").reset_index(drop=True)


def scored_events(ledger: pd.DataFrame) -> pd.DataFrame:
    """The live scored paper events the G1 re-run is judged on."""
    if ledger.empty:
        return ledger
    return ledger[ledger["scored"].astype(bool)].sort_values("entry_session").reset_index(drop=True)


def recomputed_rbar() -> tuple[float, str]:
    """Live always-long benchmark (2-session OJ return) over the live window.

    Protocol §4 recomputes rbar at re-run on the *accumulated live window*.
    The WS-1 PIT frame ends at the WS-1 OOS boundary (before the live window
    starts), so the live benchmark is derived from the OJ close series over
    ``[G1_DATE, now]``.  When the live window has fewer than 3 realized
    sessions (e.g. immediately after the G1 decision) no live benchmark
    exists yet and the function falls back to the locked WS-1 OOS benchmark
    so the G1 re-run stays well-defined.

    Returns
    -------
    (rbar, source) : tuple
        ``source`` is ``"live_window"`` or ``"locked_ws1_oos_fallback"`` and
        is recorded in the G2 report so the label never over-claims.
    """
    from pakhi.ws2.ingest import load_oj

    sessions = load_oj().index
    live = sessions[sessions >= pd.Timestamp(G1_DATE)]
    if len(live) >= 3:
        close = load_oj()["close_adj"]
        fwd2 = close.loc[live[2:]].to_numpy() / close.loc[live[:-2]].to_numpy() - 1.0
        rbar = float(np.nanmean(fwd2))
        if np.isfinite(rbar):
            return rbar, "live_window"
    return float(benchmark_2sess(load_pit())), "locked_ws1_oos_fallback"


def _span_years(live_start) -> float:
    now = pd.Timestamp.now("UTC").tz_localize(None)
    start = pd.Timestamp(live_start).tz_localize(None)
    days = max(1.0, (now - start).days)
    return days / 365.25


def build_g2_decision(
    sig: dict,
    *,
    n_scored_events: int,
    n_ledger_rows: int,
    rbar: float,
    span_years: float,
    live_start: str,
    g1_predecessor: dict | None = None,
    rbar_source: str = "locked_ws1_oos_fallback",
) -> dict:
    """G2 decision record derived (never hand-typed) from the exact re-run."""
    decision = sig["decision"]
    outcome = decision["outcome"]
    hm = sig
    record: dict[str, Any] = {
        "gate": "G2",
        "instrument": "ColdGrip (OJ)",
        "decision_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "outcome": outcome,
        "outcome_statement": OUTCOME_LABEL[outcome],
        "decision_reason": decision["reason"],
        "headline_metric": {
            "net_of_benchmark_event_sharpe": hm.get("net_of_benchmark_sharpe", 0.0),
            "ci_95_lower": hm["ci_95_net_of_benchmark_sharpe"][0],
            "ci_95_upper": hm["ci_95_net_of_benchmark_sharpe"][1],
            "bootstrap_pvalue_edge_gt_zero": hm["bootstrap_pvalue_edge_gt_zero"],
            "n_events": hm["n_events"],
            "power_class": hm["power_class"],
            "mean_net_of_benchmark": hm.get("mean_net_of_benchmark", 0.0),
            "classic_t": hm["classic_t"],
            "newey_west_t": hm["newey_west_t"],
            "newey_west_lag": hm["newey_west_lag"],
        },
        "metrics_crosscheck": {
            "n_events": hm["n_events"],
            "net_of_benchmark_sharpe": hm.get("net_of_benchmark_sharpe", 0.0),
        },
        "live_ledger": {
            "n_scored_events": n_scored_events,
            "n_ledger_rows": n_ledger_rows,
            "window_start": str(live_start),
            "span_years": float(span_years),
            "rbar_recomputed": float(rbar),
            "rbar_source": rbar_source,
            "n_min": N_MIN,
        },
        "g1_predecessor": {
            "outcome": g1_predecessor.get("outcome") if g1_predecessor else None,
            "n_events": g1_predecessor.get("headline_metric", {}).get("n_events")
            if g1_predecessor
            else None,
            "decision_json": "data/ws1/g1_decision.json",
        },
        "evidence_chain": {
            "paper_trading_protocol": "docs/WS2_PAPER_TRADING_PROTOCOL.md",
            "protocol_json": "data/ws2/paper_trading_protocol.json",
            "execution_blueprint": "docs/WS2_EXECUTION_BLUEPRINT.md",
            "decision_report": G2_REPORT,
        },
        "phase_3": {
            "gated_on": "G1 re-run verdict (or explicit infra-first user decision)",
            "api_scope": "deferred until PASS; an API serving an unproven edge is premature",
        },
        "note": (
            "G2 is an infrastructure gate only: autonomous, no-lookahead, "
            "provenance-complete store feeding the paper ledger. It does not "
            "clear G1; verdicts follow the exact WS-1 significance rules on the "
            "live ledger."
        ),
    }
    record["payload_sha256"] = record_sha256(record)
    return record


def g2_decision_consistent(record: dict) -> bool:
    """True iff the record's self-hash and metric cross-checks still hold."""
    if record.get("payload_sha256") != record_sha256(
        {k: v for k, v in record.items() if k != "payload_sha256"}
    ):
        return False
    hm = record["headline_metric"]
    mc = record["metrics_crosscheck"]
    return (
        hm["n_events"] == mc["n_events"]
        and abs(hm["net_of_benchmark_event_sharpe"] - mc["net_of_benchmark_sharpe"]) < 1e-9
    )


def produce_g2_report(
    engine,
    *,
    out_json: Path | str = G2_DECISION_JSON,
    out_md: Path | str = G2_REPORT,
    g1_predecessor: dict | None = None,
) -> dict:
    """Run the exact G1 re-run on the live ledger and write the pinned records."""
    if g1_predecessor is None:
        path = Path(__file__).resolve().parent.parent.parent / "data" / "ws1" / "g1_decision.json"
        g1_predecessor = json.loads(path.read_text()) if path.exists() else None

    ledger = load_live_ledger(engine)
    scored = scored_events(ledger)
    rbar, rbar_source = recomputed_rbar()
    span = _span_years(G1_DATE)
    sig = significance_report(scored, benchmark_mean=rbar, span_years=span, hold_sessions=2)

    record = build_g2_decision(
        sig,
        n_scored_events=len(scored),
        n_ledger_rows=len(ledger),
        rbar=rbar,
        span_years=span,
        live_start=str(G1_DATE),
        g1_predecessor=g1_predecessor,
        rbar_source=rbar_source,
    )
    assert g2_decision_consistent(record), "G2 record self-hash/cross-check broken"

    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(record, indent=2, default=str) + "\n")

    _write_markdown(record, scored, ledger, out_md)
    return record


def _write_markdown(
    record: dict, scored: pd.DataFrame, ledger: pd.DataFrame, path: Path | str
) -> None:
    hm = record["headline_metric"]
    ll = record["live_ledger"]
    lines = [
        "# WS-2 T4 — G2 Handoff: G1 Re-run on the Live Paper Ledger",
        "",
        "Status: generated from the live paper ledger by the exact WS-1 significance",
        "engine (no new machinery, no re-tuning). Machine twin: "
        "`data/ws2/g2_decision.json` (payload sha256 `" + record["payload_sha256"][:12] + "`).",
        "",
        "## Decision",
        "",
        f"- **Outcome:** {record['outcome']}",
        f"- **Statement:** {record['outcome_statement']}",
        f"- **Reason:** {record['decision_reason']}",
        "",
        "## Headline (net-of-benchmark event-trade Sharpe, live scored events)",
        "",
        f"- **N scored events:** {hm['n_events']} (N_min = 8)",
        f"- **Power class:** {hm['power_class']}",
        f"- **Mean net-of-benchmark:** {hm['mean_net_of_benchmark'] * 100:+.4f}%",
        f"- **Event Sharpe:** {hm['net_of_benchmark_event_sharpe']:.3f} "
        f"(95% CI {hm['ci_95_lower']:.3f}, {hm['ci_95_upper']:.3f})",
        f"- **Classic t / Newey-West t:** {hm['classic_t']:.3f} / {hm['newey_west_t']:.3f} "
        f"(lag {hm['newey_west_lag']})",
        f"- **Bootstrap p (edge > 0):** {hm['bootstrap_pvalue_edge_gt_zero']:.3f}",
        "",
        "## Live ledger state",
        "",
        f"- **Scored events:** {ll['n_scored_events']}",
        f"- **Total ledger rows:** {ll['n_ledger_rows']}",
        f"- **Window:** {ll['window_start']} → now (span {ll['span_years']:.2f} y)",
        f"- **rbar recomputed at re-run:** {ll['rbar_recomputed'] * 100:+.4f}% "
        f"(source: {ll['rbar_source']})",
        "",
        "## G1 predecessor",
        "",
        f"- **G1 outcome:** {record['g1_predecessor']['outcome']} "
        f"(N = {record['g1_predecessor']['n_events']}) — ",
        "  `data/ws1/g1_decision.json`",
        "",
        "## G2 scope (infrastructure gate only)",
        "",
        "- **G2 proves:** an autonomous, no-lookahead, provenance-complete signal store",
        "  feeding the paper ledger — **not** a cleared G1.",
        "- **WS-3 API build is gated** on the G1 re-run verdict (or an explicit,",
        "  user-made infra-first decision).",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")
