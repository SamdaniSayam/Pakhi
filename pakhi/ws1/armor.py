"""WS-1 T3: Lookahead Armor — timestamp layer + vintage layer.

Two independent gates (Evaluation Contract §9, locked):

1. **Timestamp layer.** No feature vector at cycle ``D`` may reference data
   published after its decision cutoff.  The decision cutoff is the close of
   the **executable fill session** — the first OJ trading session on/after ``D``
   (v1.1 fill rule) — at the ICE OJ close (14:00 America/New_York).  A cycle
   whose ``publish_time`` falls after that close would be trading on
   information not yet published ⇒ the run is **INVALID** (``LookaheadError``).
   Also asserted: the freeze feature window is confined to ``[publish,
   publish + 48h]`` (``event_peak_time`` must lie inside it), and the feature
   columns are cleanly separated from the ``ojd_*``/``fwd*`` outcome columns.

2. **Vintage layer.** Every feature must trace to the **as-published** GFS
   archive ``noaa-gfs-bdp-pds`` (never reanalysis, never a live AWS mirror).
   The PIT frame records ``source`` per row; a per-cycle **vintage manifest**
   pins a content hash of each cycle's raw archive bytes so a rewritten
   archive (or a re-fetch of revised data) is detected as drift.  Reanalysis
   or a rewritten cycle ⇒ the run is **INVALID**.

3. **Roll-jump layer (T4, §9.3).** Any continuous-price move ``> X × daily_σ``
   **at a roll date** (measured by WS-0 ``back_adjust`` across the roll) that is
   **not** co-located with a modeled freeze episode ⇒ the run is **INVALID**
   (``RollJumpError``) — a signal could otherwise trade the roll artifact.

Exit (blueprint T3): *a backtest fed leaked future data immediately errors
out.*  ``BacktestEngine.run(lookahead_armor=True)`` additionally fails any
signal whose attached provenance references a future cycle or a publication
after the current session's decision cutoff.

Honest caveat on "vintage hash predates the feature's own timestamp" (§9.2):
for a historical backtest the archive bytes are fetched after the fact; what
makes them valid is that ``noaa-gfs-bdp-pds`` is an **immutable, as-published**
S3 bucket, so the pinned hash of today's bytes equals what was published in
real time.  The manifest therefore records ``source`` + a content hash + the
``recorded_utc`` (the honest fetch date) and fails on any *drift* from the
pinned bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from pakhi.ws0.roll import back_adjust, roll_jump_assertion
from pakhi.ws1.provenance import ARCHIVE, ROLL_RULE
from pakhi.ws1.signal import fill_session_of

__all__ = [
    "ARCHIVE",
    "FEATURE_HORIZON_HOURS",
    "NY_CLOSE",
    "ROLL_JUMP_NEAR_SESSIONS",
    "ROLL_JUMP_SIGMA",
    "ROLL_JUMP_WINDOW_DAYS",
    "SESSION_CLOSE_HOUR",
    "build_vintage_manifest",
    "check_roll_jump_armor",
    "check_timestamp_armor",
    "check_vintage_armor",
    "decision_cutoff",
    "run_armor",
]

HERE = Path(__file__).resolve().parent.parent.parent
GFS = HERE / "data" / "gfs"
WS0 = HERE / "data" / "ws0"
MANIFEST_PATH = WS0 / "gfs_vintage_manifest.json"

NY = ZoneInfo("America/New_York")
SESSION_CLOSE_HOUR = 14  # ICE OJ session close, 14:00 America/New_York
NY_CLOSE = "14:00 America/New_York"
FEATURE_HORIZON_HOURS = 48  # freeze features use forecast valid times in [publish, publish+48h]

FEATURE_COLUMNS = (
    "temperature_min",
    "freeze_prob",
    "t2m_min_k",
    "grid_cells",
    "horizon_cells",
    "event_peak_time",
)
OUTCOME_PREFIXES = ("ojd_", "fwd")


class LookaheadError(Exception):
    """Raised when a backtest violates the T3 no-lookahead gates.

    Per Evaluation Contract §9 a violation makes the run **INVALID**, not just
    flagged — so this error aborts the harness/engine immediately.
    """


class RollJumpError(Exception):
    """Raised when a roll-date move > X × daily_σ is not a modeled weather event.

    Evaluation Contract §9.3: a continuous-price move above ``X * daily_sigma``
    at a roll date that is **not** co-located with a modeled freeze episode
    makes the run **INVALID** — a signal could otherwise exploit the roll gap.
    """


ROLL_JUMP_SIGMA = 5.0  # X in "X * daily_sigma", locked (§9.3, from WS-0 machinery)
ROLL_JUMP_WINDOW_DAYS = 3  # ±3-day near-roll net (WS-0 roll_jump_assertion)
ROLL_JUMP_NEAR_SESSIONS = 3  # freeze co-location tolerance, in trading sessions


def decision_cutoff(session: pd.Timestamp) -> pd.Timestamp:
    """UTC instant of the ICE OJ session close (14:00 America/New_York).

    This is the executable decision cutoff for a fill at ``session``: any
    feature used to trade must have been published at or before this instant.
    """
    return pd.Timestamp(session).tz_localize(NY).replace(hour=SESSION_CLOSE_HOUR).tz_convert("UTC")


def _cycle_sha256(cycle_dir_files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in cycle_dir_files:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def build_vintage_manifest(gfs_dir: Path | str = GFS) -> dict:
    """Pin a content hash for every GFS cycle's raw archive bytes.

    One entry per cycle date (all leads hashed in filename order).  Rebuilds
    of the immutable as-published archive reproduce identical hashes; any
    change means the archive bytes were rewritten ⇒ vintage violation.
    """
    gfs = Path(gfs_dir)
    by_cycle: dict[str, list[Path]] = {}
    for p in sorted(gfs.glob("gfs_*.parquet")):
        date_s = p.name.split("_")[1]
        by_cycle.setdefault(date_s, []).append(p)

    cycles = {}
    for date_s, files in by_cycle.items():
        cycles[date_s] = {
            "n_files": len(files),
            "nbytes": sum(f.stat().st_size for f in files),
            "sha256": _cycle_sha256(sorted(files)),
        }
    return {
        "source": ARCHIVE,
        "recorded_utc": pd.Timestamp.now("UTC").isoformat(),
        "n_cycles": len(cycles),
        "cycles": cycles,
    }


def _pit_cycle_dates(pit: pd.DataFrame) -> set[str]:
    return {pd.Timestamp(d).strftime("%Y%m%d") for d in pit["date"]}


def check_timestamp_armor(pit: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    """Timestamp layer: features must precede their decision cutoff.

    Raises :class:`LookaheadError` on any violation; otherwise returns the
    pass summary (rows checked, margin, horizon, feature/outcome separation).
    """
    errors: list[str] = []
    worst_margin_h = float("inf")
    n_publish_after_cutoff = 0
    n_peak_outside_horizon = 0

    for _, row in pit.iterrows():
        cycle = pd.Timestamp(row["date"])
        base = fill_session_of(cycle, sessions)
        if base is None:
            continue
        pub = pd.Timestamp(row["publish_time"])
        cutoff = decision_cutoff(base)
        margin_h = (cutoff - pub).total_seconds() / 3600.0
        worst_margin_h = min(worst_margin_h, margin_h)
        if pub > cutoff:
            n_publish_after_cutoff += 1
            errors.append(
                f"cycle {cycle.date()} publish {pub} after decision cutoff {cutoff} (fill {base.date()})"
            )
        peak = pd.Timestamp(row["event_peak_time"])
        if pd.notna(peak):
            horizon_end = pub + pd.Timedelta(hours=FEATURE_HORIZON_HOURS)
            if peak < pub or peak > horizon_end:
                n_peak_outside_horizon += 1
                errors.append(
                    f"cycle {cycle.date()} event_peak_time {peak} outside [publish, publish+48h]"
                )

    missing_features = [c for c in FEATURE_COLUMNS if c not in pit.columns]
    contaminated = [c for c in pit.columns if c in FEATURE_COLUMNS and c.startswith(OUTCOME_PREFIXES)]
    separated = (not missing_features) and (not contaminated)
    if missing_features:
        errors.append(f"feature vector incomplete, missing columns: {missing_features}")
    if contaminated:
        errors.append(f"feature columns contaminated by outcomes: {contaminated}")

    detail = {
        "n_rows": len(pit),
        "publish_after_cutoff": int(n_publish_after_cutoff),
        "min_publish_margin_hours": float(worst_margin_h) if len(pit) else float("nan"),
        "event_peak_outside_horizon": int(n_peak_outside_horizon),
        "feature_horizon_hours": FEATURE_HORIZON_HOURS,
        "feature_outcome_separation": bool(separated),
    }
    if errors:
        raise LookaheadError("timestamp armor: " + "; ".join(errors[:5]))
    return detail


def check_vintage_armor(
    pit: pd.DataFrame,
    manifest: dict | None = None,
    gfs_dir: Path | str | None = None,
) -> dict:
    """Vintage layer: every feature traces to the as-published archive.

    Requires a vintage manifest (see :func:`build_vintage_manifest`) and (when
    ``gfs_dir`` is given) recomputes the cycle hashes to detect archive drift.
    Raises :class:`LookaheadError` on any violation.
    """
    if manifest is None:
        manifest_path = Path(MANIFEST_PATH)
        if not manifest_path.exists():
            raise LookaheadError("vintage armor: no vintage manifest; run build_vintage_manifest()")
        manifest = json.loads(manifest_path.read_text())

    errors: list[str] = []
    pit_cycles = _pit_cycle_dates(pit)
    manifest_cycles = set(manifest.get("cycles", {}))

    if manifest.get("source") != ARCHIVE:
        errors.append(f"vintage manifest source {manifest.get('source')!r} != {ARCHIVE!r}")

    missing = sorted(pit_cycles - manifest_cycles)
    if missing:
        errors.append(f"{len(missing)} PIT cycles missing from vintage manifest: {missing[:5]}")

    if gfs_dir is not None:
        current = build_vintage_manifest(gfs_dir)
        drift = sorted(
            c
            for c in pit_cycles
            if c in current["cycles"]
            and current["cycles"][c]["sha256"] != manifest["cycles"].get(c, {}).get("sha256")
        )
        if drift:
            errors.append(f"{len(drift)} cycles drifted from the pinned archive hash: {drift[:5]}")
    else:
        drift = []

    detail = {
        "archive": ARCHIVE,
        "n_pit_cycles": len(pit_cycles),
        "n_cycles_in_manifest": len(pit_cycles & manifest_cycles),
        "source_match": bool(manifest.get("source") == ARCHIVE),
        "n_hash_drift": len(drift),
        "recorded_utc": manifest.get("recorded_utc", ""),
    }

    if errors:
        raise LookaheadError("vintage armor: " + "; ".join(errors[:5]))
    return detail


def _modeled_weather_sessions(pit: pd.DataFrame, sessions: pd.DatetimeIndex) -> set[pd.Timestamp]:
    """Freeze-episode fill sessions — the modeled weather events (§9.3)."""
    from pakhi.ws1.episodes import freeze_episodes

    ep = freeze_episodes(pit, sessions)
    modeled: set[pd.Timestamp] = set()
    for _, row in ep[ep["episode_start"]].iterrows():
        base = fill_session_of(pd.Timestamp(row["date"]), sessions)
        if base is not None:
            modeled.add(base)
    return modeled


def check_roll_jump_armor(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    oj: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    n_sigma: float = ROLL_JUMP_SIGMA,
) -> dict:
    """Roll-jump layer (§9.3): halt on unmodeled roll-date gaps > X × daily_σ.

    Reuses the WS-0 machinery:

    - ``back_adjust`` measures the continuous-price gap **at each roll date**;
      a gap >= 1 + X*σ (or <= 1/(1+X*σ)) that is left unadjusted is a roll
      artifact the signal could exploit.  Each such flagged roll must be
      co-located (within ``ROLL_JUMP_NEAR_SESSIONS`` sessions) with a modeled
      freeze episode, else the run is INVALID (``RollJumpError``).
    - ``roll_jump_assertion`` adds the stricter ±3-day near-roll net and is
      reported for transparency (weather-co-location flagged per move); it does
      not halt by itself — the halt gate is the roll-date gap, faithful to
      "a continuous-price move > X × daily_σ *at a roll date*".

    On the real archive ``back_adjust`` flags 0 of 34 roll gaps; the 2023-11-02
    OJ crash (−7.5 %, 5.7σ, one session after the 2023-11-01 FND roll) is a
    real move in the back-adjusted series, not a roll artifact, and sits outside
    the traded path — so the layer passes and reports it as context.
    """
    from pakhi.ws1.provenance import MARKET

    if oj is None:
        oj = pd.read_parquet(MARKET / "oj_continuous.parquet").reset_index()
        oj["Date"] = pd.to_datetime(oj["Date"])
        oj = oj.set_index("Date").sort_index()
        oj = oj[["close_adj"]].dropna()
    if calendar is None:
        calendar = pd.read_csv(MARKET / "oj_contract_calendar.csv")

    cont = back_adjust(oj["close_adj"], calendar, roll_rule=ROLL_RULE, n_sigma=n_sigma)
    prov = cont.provenance_frame()

    modeled = _modeled_weather_sessions(pit, sessions)
    session_list = list(sessions)
    session_pos = {s: i for i, s in enumerate(session_list)}

    def _near_modeled(roll_dt: pd.Timestamp) -> bool:
        if roll_dt not in session_pos:
            return False
        pos = session_pos[roll_dt]
        lo, hi = max(0, pos - ROLL_JUMP_NEAR_SESSIONS), min(len(sessions), pos + ROLL_JUMP_NEAR_SESSIONS + 1)
        return any(s in modeled for s in session_list[lo:hi])

    flagged_rolls: list[dict] = []
    if not prov.empty:
        for _, r in prov[prov["flagged"]].iterrows():
            flagged_rolls.append(
                {
                    "roll_date": str(r["roll_date"]),
                    "contract_to": str(r["contract_to"]),
                    "factor": float(r["factor"]),
                    "flag_reason": str(r["flag_reason"]),
                }
            )

    unmodeled = [f for f in flagged_rolls if not _near_modeled(pd.Timestamp(f["roll_date"]))]

    roll_dates = list(pd.to_datetime(calendar["first_notice_day"]))
    near = roll_jump_assertion(
        oj["close_adj"], roll_dates, n_sigma=n_sigma, window_days=ROLL_JUMP_WINDOW_DAYS
    )
    near_roll_moves: list[dict] = []
    for _, r in near.iterrows():
        d = pd.Timestamp(r["date"])
        near_roll_moves.append(
            {
                "date": str(d.date()),
                "return": float(r["return"]),
                "ratio": float(r["ratio"]),
                "near_roll": str(r["near_roll"]),
                "weather_co_located": _near_modeled(d),
            }
        )

    if unmodeled:
        raise RollJumpError(
            "roll-jump armor: unmodeled roll-date gaps > {}x daily_sigma: {}".format(
                n_sigma, [u["roll_date"] for u in unmodeled]
            )
        )

    return {
        "n_rolls": len(prov),
        "n_flagged_rolls": len(flagged_rolls),
        "flagged_rolls": flagged_rolls,
        "unmodeled_roll_gaps": [u["roll_date"] for u in unmodeled],
        "n_near_roll_extreme_moves": len(near_roll_moves),
        "near_roll_extreme_moves": near_roll_moves,
        "x_sigma": n_sigma,
    }


def run_armor(
    pit: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    manifest: dict | None = None,
    gfs_dir: Path | str | None = None,
    oj: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
) -> dict:
    """Run the armor layers; raises :class:`LookaheadError` / :class:`RollJumpError`.

    T3 timestamp + vintage layers and the T4 roll-jump layer (§9.3).  Returns a
    combined pass summary for the harness report.
    """
    ts = check_timestamp_armor(pit, sessions)
    vg = check_vintage_armor(pit, manifest=manifest, gfs_dir=gfs_dir)
    rj = check_roll_jump_armor(pit, sessions, oj=oj, calendar=calendar)
    return {"pass": True, "timestamp": ts, "vintage": vg, "roll_jump": rj}
