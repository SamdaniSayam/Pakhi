"""WS-2 T0: live paper-trading protocol — pre-registered, hash-pinned.

Mirror of the WS-1 evaluation-contract discipline
(``data/ws1/evaluation_contract.json``): **before any live event is recorded**,
the rules that will later decide the G1 re-run are locked in writing
(``docs/WS2_PAPER_TRADING_PROTOCOL.md``) and as a self-hash-pinned machine
artifact (``data/ws2/paper_trading_protocol.json``).

The critical lock is the **frozen live θ_p**: a single value derived from the
historical PIT frame as of the G1 date (2026-08-12).  Re-estimating θ_p from the
accumulating live dataset would be exactly the tuning-lookahead WS-1 banned —
re-estimation is only permitted at the N ≥ 8 G1 re-run and must itself freeze a
new value under a new protocol version (change control).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from pakhi.ws1.candidate import estimate_thresholds
from pakhi.ws1.pit import benchmark_2sess, load_pit
from pakhi.ws1.significance import N_MIN

__all__ = [
    "G1_DATE",
    "PROTOCOL_DOC",
    "PROTOCOL_JSON",
    "build_paper_trading_protocol",
    "frozen_theta_p",
    "payload_sha256",
    "protocol_consistent",
]

G1_DATE = pd.Timestamp("2026-08-12")  # G1 decision date (docs/WS1_G1_REPORT.md)
LOCKED_UTC = "2026-08-12T00:00:00+00:00"  # fixed lock time (stable payload hash)
PROTOCOL_DOC = "docs/WS2_PAPER_TRADING_PROTOCOL.md"
PROTOCOL_JSON = "data/ws2/paper_trading_protocol.json"

_HERE = Path(__file__).resolve().parent.parent.parent
G1_DECISION_JSON = _HERE / "data" / "ws1" / "g1_decision.json"


def payload_sha256(payload: dict) -> str:
    """Self-verifying hash over the canonical JSON payload (excluding itself)."""
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()


def frozen_theta_p(pit: pd.DataFrame, as_of_date=G1_DATE) -> dict:
    """Frozen live θ_p from historical PIT rows with ``date <= as_of_date``.

    Reuses the WS-1 estimator (``pakhi.ws1.candidate.estimate_thresholds``) so
    the live gate is byte-identical to the backtest gate: θ_p = median
    ``freeze_prob`` over rows with ``freeze_prob > 0``; θ_t = 0 °C fixed.
    """
    train = pit[pit["date"] <= pd.Timestamp(as_of_date)]
    return estimate_thresholds(train)


def _predecessor() -> dict:
    """G1 facts from the self-hash-pinned decision record (falls back to the
    locked report numbers if the artifact is absent, e.g. in a fresh clone)."""
    if G1_DECISION_JSON.exists():
        rec = json.loads(G1_DECISION_JSON.read_text())
        return {
            "g1_report": "docs/WS1_G1_REPORT.md",
            "g1_outcome": rec["outcome"],
            "g1_n_events": rec["headline_metric"]["n_events"],
            "g1_net_of_benchmark_event_sharpe": rec["headline_metric"]["net_of_benchmark_event_sharpe"],
            "g1_decision_json": str(G1_DECISION_JSON.relative_to(_HERE)),
        }
    return {
        "g1_report": "docs/WS1_G1_REPORT.md",
        "g1_outcome": "UNDER_POWERED",
        "g1_n_events": 7,
        "g1_net_of_benchmark_event_sharpe": -0.193,
        "g1_decision_json": None,
    }


def build_paper_trading_protocol(
    pit: pd.DataFrame | None = None,
    as_of_date=G1_DATE,
    locked_utc: str | None = None,
) -> dict:
    """Build the pre-registered live paper-trading protocol payload.

    The signal and trade rules are copied verbatim from the WS-1 contract; only
    the θ_p (frozen here) and the live-specific provenance/armor requirements
    are new.  The payload is self-hash-pinned like every WS-1 artifact.
    """
    if pit is None:
        pit = load_pit()
    theta = frozen_theta_p(pit, as_of_date)
    freeze_rows = int(
        ((pit["freeze_prob"] > 0) & (pit["date"] <= pd.Timestamp(as_of_date))).sum()
    )
    rbar = float(benchmark_2sess(pit))
    pred = _predecessor()

    payload = {
        "version": "1.0",
        "status": "LOCKED",
        "locked_utc": locked_utc or LOCKED_UTC,
        "gate": "G1 re-run feed (Phase 2 paper-trading); G2 = infrastructure proof only",
        "instrument": "OJ=F",
        "source_doc": PROTOCOL_DOC,
        "predecessor": pred,
        "mandate": (
            "60-day live OJ paper-trading harness to accumulate scored OOS "
            f"event-trades to N >= N_min ({N_MIN}) and re-run G1"
        ),
        "cycle": {
            "signal_cycle": "12Z",
            "publication_ts_est_utc": "~15:35Z",
            "decision_cutoff": "14:00 America/New_York of the fill session",
            "same_day_fill": "12Z publishes before the 14:00 NY close -> same-day fill on trading days",
            "non_signal_cycles": "00/06/18Z not ingested for the signal path (18Z publishes after the cutoff)",
        },
        "signal": {
            "name": "ColdGrip",
            "fire": "freeze_prob >= theta_p AND temperature_min <= theta_t",
            "theta_p": theta["theta_p"],
            "theta_p_estimator": (
                "median(freeze_prob) over historical PIT rows with freeze_prob>0 "
                f"and date <= G1 date ({G1_DATE.date()})"
            ),
            "theta_p_frozen_at": "G1 date, BEFORE any live event is recorded; single value, no live re-estimation",
            "theta_p_n_historical_freeze_rows": freeze_rows,
            "theta_t_c": theta["theta_t"],
            "theta_t_origin": "fixed physical freeze definition, not estimated",
            "re_estimation": (
                "only at the N >= N_min G1 re-run, under the same estimator, on the "
                "accumulated historical + live ledger; the new value is frozen in a "
                "new protocol version (change control)"
            ),
            "one_shot": True,
            "trades_per_episode_max": 1,
            "entry": "first firing row of each live episode",
        },
        "trade": {
            "entry": (
                "fill at the first trading-session close ON/AFTER the firing row's "
                "cycle date; same-day for trading days, next trading close for "
                "weekend/holiday cycles; NEVER prior close"
            ),
            "hold_sessions": 2,
            "gross_return": "close[fill+2]/close[fill]-1",
            "exit": "close of the 2nd trading session after the fill session",
            "costs_bps_round_trip": 30,
            "costs_breakdown": "5 bps commission + 10 bps slippage per position change x2",
            "episode": (
                "maximal run of live rows with freeze_prob>0 grouped by executable "
                "fill session; split iff fill sessions are >= 2 trading sessions apart"
            ),
        },
        "benchmark": {
            "definition": "always-long OJ over matched 2-session window",
            "rbar_2sess_oos_backtest": rbar,
            "live_rbar": (
                "recomputed at the N >= N_min G1 re-run on the accumulated window "
                "with the WS-1 formula (mean of matched always-long OJ 2-session returns)"
            ),
            "net_of_benchmark_return": "gross - 0.0030 - rbar",
        },
        "event_counting": {
            "scored": "live OOS event-trades (in the paper window, not embargoed)",
            "embargo_sessions": 5,
            "n_min": N_MIN,
            "decision_rules": {
                "PASS": "N>=N_min and net-of-benchmark event Sharpe>1.0 and bootstrap CI lower bound>0",
                "FAIL_PIVOT": "N>=N_min and (CI includes 0 or mean net<=0)",
                "UNDER_POWERED": "N<N_min OOS event-trades",
                "ZERO_TRADES": "no live trades -> documented (architecture success path)",
            },
        },
        "armor": {
            "timestamp": "publication_ts <= decision cutoff (14:00 America/New_York) of the fill session",
            "vintage": "fetched bytes hash must match the as-published noaa-gfs-bdp-pds archive",
            "roll_jump": "roll-date move > 5x daily sigma without a modeled freeze event => halt (RollJumpError)",
            "on_violation": (
                "cycle REJECTED: never persisted, never fills a paper trade; alert raised"
            ),
        },
        "data_integrity": {
            "never_empty_dataframe": True,
            "stored_vs_offline_equivalence": (
                "stored ColdGrip output must equal pakhi.ws1.candidate output on the "
                "same cycle, else the worker halts"
            ),
            "provenance_on_every_row": [
                "model_version",
                "forecast_cycle_id",
                "publication_ts",
                "archive_source",
                "vintage_hash",
                "fetch_date",
            ],
            "db": (
                "Postgres (TimescaleDB optional at Phase-3 scale); paper ledger columns "
                "identical to data/ws1/t4_candidate_ledger.csv so significance_report "
                "consumes it unmodified"
            ),
        },
        "g2_scope": (
            "infrastructure proof only (autonomous, no-lookahead, provenance-complete "
            "store feeding the paper ledger); does NOT clear G1"
        ),
        "deferred_until_g1_verdict": [
            "ensemble disagreement",
            "NG",
            "CME HDD/CDD",
            "WS-3 API build",
            "TimescaleDB at scale",
            "multi-tenancy",
        ],
        "anti_gaming": [
            "protocol locked in writing BEFORE any live event is recorded",
            "theta_p frozen; no live re-estimation from the accumulating dataset",
            "no metric feedback into tuning",
            "one-shot evaluation per locked version",
            "pre-registration committed to git",
        ],
        "change_control": (
            "any amendment requires a new version + re-lock; accumulated paper ledger "
            "void unless re-validated"
        ),
    }
    payload["payload_sha256"] = payload_sha256(payload)
    return payload


def protocol_consistent(record: dict) -> bool:
    """True iff the record's self-hash still pins the payload."""
    body = {k: v for k, v in record.items() if k != "payload_sha256"}
    return record.get("payload_sha256") == payload_sha256(body)
