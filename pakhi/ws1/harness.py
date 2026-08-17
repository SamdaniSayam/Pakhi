"""WS-1 harness: PIT frame -> locked event trades -> BacktestEngine -> report.

One entry point, ``run_harness``, wires the WS-0 PIT frame into the engine and
reports every locked Evaluation Contract number plus the context equity curves.

Pipeline (T1 "wire the PIT frames into the engine"):

1. load + validate the PIT frame (shared gate with ``rebuild_dataset.py``);
2. segment freeze episodes (locked §2) and reproduce the locked counts 16/13;
3. build the 2-session hold schedule on the real OJ trading-session grid;
4. construct the event-trade ledger from the PIT outcomes (``fwd2_return``,
   net −30 bps, net-of-benchmark) with fold + embargo + weekend flags;
5. run ``BacktestEngine`` over the OJ path (full OOS window + per-fold
   walk-forward) and cross-validate every engine trade return against the PIT
   event gross return.

The demo generator fires at **every** episode start (parameter-free) purely to
exercise the machinery at maximal load — it is *not* a registered T4 candidate
and no G1 inference is drawn here (that gate is T6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from pakhi.risk.backtest import BacktestEngine
from pakhi.ws1.armor import run_armor
from pakhi.ws1.candidate import (
    CANDIDATE_NAME,
    TEMP_GATE_C,
    build_candidate_schedule,
    candidate_entries,
)
from pakhi.ws1.episodes import freeze_episodes
from pakhi.ws1.metrics import event_metrics
from pakhi.ws1.pit import (
    COST,
    OOS_END,
    OOS_START,
    TEST_FOLDS,
    benchmark_2sess,
    embargo_sessions,
    fold_label,
    load_oj,
    load_pit,
    oos_mask,
    oos_span_years,
    validate_pit_frame,
)
from pakhi.ws1.provenance import ARCHIVE, MODEL_VERSION, build_provenance_map
from pakhi.ws1.signal import build_hold_schedule, fill_session_of, make_episode_hold_generator
from pakhi.ws1.significance import significance_report

__all__ = ["run_harness"]

DEMO_INSTRUMENT = "OJ_FUTURES"
MAX_GROSS_ERROR = 1e-9  # engine trade return vs PIT fwd2_return


def _engine_on(
    oj: pd.DataFrame,
    schedule: pd.Series,
    start: str,
    end: str,
    provenance_map: dict | None = None,
) -> Any:
    data = oj.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    gen = make_episode_hold_generator(
        schedule, instrument=DEMO_INSTRUMENT, provenance_map=provenance_map
    )
    return BacktestEngine(price_column="close_adj").run(
        gen,
        data,
        initial_capital=1_000_000.0,
        commission_bps=5.0,
        slippage_bps=10.0,
        instrument=DEMO_INSTRUMENT,
        lookahead_armor=True,  # T3: any leaked/future provenance aborts the run
    )


def _summarize_provenance(trades: list[dict]) -> dict:
    """T2 summary of the engine trade log: provenance coverage + cost check."""
    costs_bps = [float(t["costs_bps"]) for t in trades] if trades else []
    return {
        "n_trades": len(trades),
        "n_with_provenance": int(sum(1 for t in trades if t.get("provenance"))),
        "forecast_cycle_ids": [
            t["provenance"]["forecast_cycle_id"] for t in trades if t.get("provenance")
        ],
        "costs_bps_range": [min(costs_bps), max(costs_bps)] if costs_bps else [],
        "costs_match_30bps": bool(costs_bps) and all(abs(c - 30.0) < 1e-6 for c in costs_bps),
    }


def _event_row(
    row: pd.Series,
    sessions: pd.DatetimeIndex,
    benchmark: float,
    prov_map: dict,
    fold: str,
) -> dict:
    """One locked event-trade row from an entry row (shared demo/candidate)."""
    entry_cycle = pd.Timestamp(row["date"])
    base = fill_session_of(entry_cycle, sessions)
    if base is None:
        return {}
    loc = sessions.get_loc(base)
    exit_session = sessions[loc + 2] if loc + 2 < len(sessions) else None
    gross = float(row["fwd2_return"])
    prov = prov_map.get(base, {})
    roll = prov.get("roll_state", {})
    return {
        "episode_id": int(row["episode_id"]),
        "entry_cycle": entry_cycle,
        "entry_session": base,
        "exit_session": exit_session,
        "gross": gross,
        "net": gross - COST,
        "net_of_benchmark": gross - COST - benchmark,
        "fold": fold,
        "in_oos": bool(OOS_START <= entry_cycle <= OOS_END),
        "embargoed": base in embargo_sessions(sessions),
        "entry_weekend": entry_cycle.dayofweek >= 5,
        "next_close_fill": base > entry_cycle,
        "fill_days_after_cycle": (base - entry_cycle).days,
        "entry_freeze_prob": float(row["freeze_prob"]),
        "entry_temperature_min": float(row["temperature_min"]),
        "forecast_cycle_id": prov.get("forecast_cycle_id", ""),
        "publication_ts": prov.get("publication_ts", ""),
        "model_version": prov.get("model_version", ""),
        "contract_month": roll.get("contract_month", ""),
        "adjustment_factor": roll.get("adjustment_factor", float("nan")),
    }


def _build_ledger(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    benchmark: float,
    provenance_map: dict | None = None,
) -> pd.DataFrame:
    """One row per episode: locked event-trade construction + scoring flags."""
    ep = freeze_episodes(pit, sessions)
    starts = ep[ep["episode_start"]]
    folds = fold_label(ep)
    prov_map = provenance_map or {}

    rows: list[dict] = []
    for _, row in starts.iterrows():
        rec = _event_row(row, sessions, benchmark, prov_map, folds.loc[row.name])
        if rec:
            rows.append(rec)
    ledger = pd.DataFrame(rows)
    if not ledger.empty:
        ledger["scored"] = ledger["in_oos"] & ~ledger["embargoed"]
    return ledger


def _build_candidate_ledger(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    benchmark: float,
    provenance_map: dict | None = None,
) -> pd.DataFrame:
    """One row per redefined-signal trade (first firing row per episode)."""
    entries = candidate_entries(pit, sessions)
    prov_map = provenance_map or {}
    rows: list[dict] = []
    for _, row in entries.iterrows():
        row = row.copy()
        row["date"] = row["entry_cycle"]
        rec = _event_row(row, sessions, benchmark, prov_map, str(row["fold"]))
        if rec:
            rows.append(rec)
    ledger = pd.DataFrame(rows)
    if not ledger.empty:
        ledger["scored"] = ledger["in_oos"] & ~ledger["embargoed"]
    return ledger


def _cross_validate_engine(
    engine_trades: list[dict],
    ledger: pd.DataFrame,
    oj: pd.DataFrame,
) -> dict:
    """Match engine trades to events by entry session; verify fills + returns.

    The engine's trade ``return`` must equal the PIT ``fwd2_return`` (both are
    ``close[exit]/close[entry] - 1``), and the fill prices must equal the PIT
    closes.  Returns the mismatch bounds and match count.
    """
    by_session = {pd.Timestamp(t["entry_time"]): t for t in engine_trades}
    n_match = 0
    max_ret_err = 0.0
    price_mismatches = 0
    unmatched: list[str] = []
    for _, ev in ledger.iterrows():
        if not ev["in_oos"]:
            continue
        if pd.isna(ev["exit_session"]):
            # Episode too close to the end of the session grid to have a
            # locked 2-session hold; nothing to cross-validate against.
            continue
        t = by_session.get(pd.Timestamp(ev["entry_session"]))
        if t is None:
            unmatched.append(str(ev["entry_cycle"].date()))
            continue
        n_match += 1
        max_ret_err = max(max_ret_err, abs(float(t["return"]) - ev["gross"]))
        entry_close = float(oj.loc[pd.Timestamp(ev["entry_session"]), "close_adj"])
        exit_close = float(oj.loc[pd.Timestamp(ev["exit_session"]), "close_adj"])
        if t["entry_price"] != entry_close or t["exit_price"] != exit_close:
            price_mismatches += 1
    return {
        "matched_trades": n_match,
        "n_oos_events": int(sum(1 for _, ev in ledger.iterrows() if ev["in_oos"])),
        "unmatched_events": unmatched,
        "max_return_abs_error": float(max_ret_err),
        "price_mismatches": int(price_mismatches),
    }


def run_harness(
    pit: pd.DataFrame | None = None,
    oj: pd.DataFrame | None = None,
    ledger_path: Path | str | None = None,
    report_path: Path | str | None = None,
    trades_path: Path | str | None = None,
    armor: bool = True,
    vintage_manifest: dict | None = None,
    candidate: bool = False,
    calendar: pd.DataFrame | None = None,
) -> dict:
    """Run the full T1 harness and return the report dictionary.

    Parameters
    ----------
    pit, oj : optional preloaded frames (tests inject them); defaults read the
        real ``data/ws0/freeze_pit.parquet`` and ``data/market/oj_continuous.parquet``.
    ledger_path, report_path, trades_path : optional output files
        (event ledger CSV / report JSON / engine trade log CSV).
    armor : bool, default True
        T3/T4 armor (timestamp + vintage + roll-jump layers).  Any violation
        raises :class:`pakhi.ws1.armor.LookaheadError` / ``RollJumpError`` —
        the run is INVALID (§9).
    vintage_manifest : optional prebuilt manifest dict (bypasses the on-disk
        ``data/ws0/gfs_vintage_manifest.json``).
    candidate : bool, default False
        If True, the engine runs the pre-registered T4 "ColdGrip" redefined
        signal (``pakhi.ws1.candidate``) instead of the parameter-free demo
        generator.  The demo fires at every episode start purely to exercise
        the machinery at maximal load; ``candidate=True`` is the one-shot T4
        evaluation (thresholds re-estimated inside walk-forward folds).
    calendar : optional ICE roll calendar (injected by tests; defaults to
        ``data/market/oj_contract_calendar.csv``).

    Returns
    -------
    dict
        Locked-number validations, episode counts, event ledger summary,
        metric table, engine context (full-OOS + per-fold), cross-validation,
        the T2 provenance trail for every engine trade, the T3/T4 armor pass,
        and (in candidate mode) the registered signal + per-fold thresholds.
    """
    if pit is None:
        pit = load_pit()
    if oj is None:
        oj = load_oj()

    ok, detail = validate_pit_frame(pit)
    report: dict[str, Any] = {"valid": ok, "validation": detail}
    if not ok:
        return report

    sessions = oj.index

    if armor:
        # Enforce the vintage hash-drift layer on the real pipeline (T1/T4/T6):
        # when PAKHI_GFS_DIR is set (or data/gfs exists) recompute per-cycle
        # archive hashes and compare to the pinned manifest. Without this the
        # dedicated run_t3_armor.py path was the only one enforcing drift.
        gfs_dir = os.environ.get("PAKHI_GFS_DIR")
        if gfs_dir is None:
            from pakhi.ws1.armor import GFS

            gfs_dir = str(GFS) if GFS.exists() else None
        report["armor"] = run_armor(
            pit,
            sessions,
            manifest=vintage_manifest,
            oj=oj,
            calendar=calendar,
            gfs_dir=gfs_dir,
        )

    benchmark = benchmark_2sess(pit)
    span_years = oos_span_years()
    provenance_map = build_provenance_map(pit, sessions)

    ep = freeze_episodes(pit, sessions)
    n_episodes = int(ep["episode_id"].nunique() - (1 if (ep["episode_id"] == 0).any() else 0))
    n_oos_episodes = int(ep.loc[ep["episode_start"] & oos_mask(ep), "episode_id"].nunique())

    if candidate:
        schedule, fold_thresholds = build_candidate_schedule(pit, sessions)
        ledger = _build_candidate_ledger(pit, sessions, benchmark, provenance_map)
        signal = {
            "name": CANDIDATE_NAME,
            "kind": "T4 registered redefined signal",
            "registration": "docs/T4_CANDIDATE_REGISTRATION.md",
            "params": {
                "theta_p_estimator": "median(freeze_prob) over fold train freeze rows",
                "theta_t_c": TEMP_GATE_C,
                "free_parameters": 1,
                "hold_sessions": 2,
            },
            "fold_thresholds": fold_thresholds,
            "n_trades": len(ledger),
        }
    else:
        schedule = build_hold_schedule(pit, sessions)
        ledger = _build_ledger(pit, sessions, benchmark, provenance_map)
        signal = {
            "name": "DemoEveryEpisode",
            "kind": "parameter-free demo generator (max-load plumbing exercise)",
            "params": {},
            "fold_thresholds": [],
            "n_trades": len(ledger),
        }
    scored = ledger[ledger["scored"]] if not ledger.empty else ledger
    metrics = event_metrics(scored, benchmark, span_years)
    significance = significance_report(scored, benchmark, span_years)

    engine_full = _engine_on(
        oj, schedule, str(OOS_START.date()), str(OOS_END.date()), provenance_map
    )
    xval = _cross_validate_engine(engine_full.trades, ledger, oj)
    n_scored_events = int((ledger["scored"] if not ledger.empty else []).sum())
    holds_merged = len(engine_full.trades) != n_scored_events

    trade_log = pd.DataFrame(engine_full.trades)
    provenance_summary = _summarize_provenance(engine_full.trades)

    fold_runs = []
    for name, start, end in TEST_FOLDS:
        res = _engine_on(oj, schedule, start, end, provenance_map)
        fold_runs.append(
            {
                "fold": name,
                "start": start,
                "end": end,
                "total_return": float(res.total_return),
                "daily_equity_sharpe": float(res.sharpe),
                "n_trades": len(res.trades),
                "max_drawdown": float(res.max_drawdown),
            }
        )

    report.update(
        {
            "locked": {
                "pit_rows": len(pit),
                "oos_rows": int(oos_mask(pit).sum()),
                "span_years": float(span_years),
                "benchmark_2sess_pct": float(benchmark * 100),
                "cost_round_trip_bps": COST * 10_000,
                "n_episodes_total": n_episodes,
                "n_episodes_oos": n_oos_episodes,
            },
            "engine_context": {
                "full_oos_total_return": float(engine_full.total_return),
                "full_oos_daily_equity_sharpe": float(engine_full.sharpe),
                "full_oos_trades": len(engine_full.trades),
                "cross_validation": xval,
                "per_fold": fold_runs,
            },
            "provenance": {
                "model_version": MODEL_VERSION,
                "archive": ARCHIVE,
                "n_trades": provenance_summary["n_trades"],
                "n_trades_with_provenance": provenance_summary["n_with_provenance"],
                "forecast_cycle_ids": provenance_summary["forecast_cycle_ids"],
                "costs_bps_range": provenance_summary["costs_bps_range"],
                "costs_match_locked_round_trip": provenance_summary["costs_match_30bps"],
            },
            "signal": signal,
            "metrics": metrics,
            "significance": significance,
            "events": {
                "n_all_episodes": len(ledger),
                "n_oos_events": int((ledger["in_oos"] if not ledger.empty else []).sum()),
                "n_scored": n_scored_events,
                "holds_merged_in_engine": bool(holds_merged),
                "n_embargoed": int((ledger["embargoed"] if not ledger.empty else []).sum()),
                "n_weekend_entries_oos": int(
                    ((ledger["in_oos"] & ledger["entry_weekend"]).sum()) if not ledger.empty else 0
                ),
                "n_next_close_entries_oos": int(
                    ((ledger["in_oos"] & ledger["next_close_fill"]).sum())
                    if not ledger.empty
                    else 0
                ),
            },
            "note": (
                "T1 plumbing demonstration + T2 provenance + T3/T4 armor. "
                + (
                    "T4 registered candidate 'ColdGrip': freeze_prob >= theta_p (median over "
                    "fold train freeze rows) AND temperature_min <= 0C, first firing row per "
                    "episode = entry, <= 1 trade/episode, 2-session hold (locked). Thresholds "
                    "re-estimated inside walk-forward folds; no ojd_*/fwd* read during "
                    "definition; one-shot (registered before scoring)."
                    if candidate
                    else "Signal = parameter-free demo generator fires at every episode start "
                    "(max-load exercise). NOT a registered T4 candidate; no G1 decision drawn (T6)."
                )
                + " v1.1: episode gaps are measured in trading sessions between executable fill "
                "sessions; non-trading-day cycles fill at the NEXT trading close (no prior-close "
                "lookahead). Every engine trade logs forecast_cycle_id / publication_ts / "
                "model_version / archive / roll_state / costs_incurred (T2). Armor is armed: "
                "timestamp layer (features precede the 14:00 NY decision cutoff, 48h feature "
                "window, feature/outcome separation), vintage layer (as-published "
                "noaa-gfs-bdp-pds + pinned cycle hashes) and roll-jump layer (X=5x daily_sigma "
                "at a roll date, WS-0 machinery) — a leak INVALIDATES the run."
            ),
        }
    )

    if ledger_path is not None:
        out = pd.DataFrame(ledger)
        out.to_csv(ledger_path, index=False)
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, default=str, indent=2))
    if trades_path is not None and not trade_log.empty:
        pd.DataFrame(trade_log).to_csv(trades_path, index=False)
    return report
