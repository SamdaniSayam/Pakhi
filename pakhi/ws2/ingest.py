"""WS-2 T1: live ingestion worker — locked 12Z GFS cycle + OJ daily close.

Contract (``docs/WS2_PAPER_TRADING_PROTOCOL.md`` §3, §6, §7 and the execution
blueprint T1):

- Pull the locked 12Z cycle with NOMADS primary and the as-published AWS
  ``noaa-gfs-bdp-pds`` archive as fallback, plus the latest realized OJ daily
  close.
- Validate schema, spatial completeness (wedge 0p50 grid coverage) and
  staleness; pin a content hash over the cycle's raw parquet bytes (vintage
  pin) into ``data/ws2/vintage_manifest.json``.
- Run the three live armor gates (timestamp / vintage / roll-jump); any
  violation raises :class:`RejectCycleError` — the cycle is never persisted
  and never fills a paper trade.
- Never return an empty DataFrame: failures raise ``DataStalenessError`` /
  ``UpstreamMissingError`` / ``RejectCycleError`` — never a silent drop.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd

from pakhi.src.noaa import GFSConnector
from pakhi.ws0.features import freeze_features
from pakhi.ws1.armor import (
    LookaheadError,
    RollJumpError,
    check_roll_jump_armor,
    check_timestamp_armor,
    check_vintage_armor,
)
from pakhi.ws1.provenance import ARCHIVE, MARKET, MODEL_VERSION

__all__ = [
    "BBOX_TAG",
    "CYCLE_HOUR",
    "GFS_DIR",
    "LEADS",
    "LIVE_MANIFEST",
    "DataStalenessError",
    "IngestError",
    "RejectCycleError",
    "UpstreamMissingError",
    "append_cycle_pin",
    "build_features",
    "check_staleness",
    "download_cycle",
    "fetch_oj_close",
    "ingest_cycle",
    "latest_12z_cycle",
    "live_armor",
    "load_calendar",
    "load_oj",
    "pin_vintage_sha",
    "sessions_from_market",
    "validate_cycle",
]

CYCLE_HOUR = 12
LEADS = (0, 12, 24, 48)
WEDGE_BBOX = [-85.0, 24.0, -80.0, 31.0]
RESOLUTION = "0p50"
VARIABLES = ["temperature_2m"]
BBOX_TAG = "W24S-85E31N-80"
PUBLISH_LATENCY_HOURS = 3.5
STALE_CYCLE_TOLERANCE_DAYS = 1
OJ_STALENESS_MAX_DAYS = 7
EXPECTED_CELLS_PER_LEAD = 15 * 11
REQUIRED_COLUMNS = ("latitude", "longitude", "time", "valid_time", "t2m")

HERE = Path(__file__).resolve().parent.parent.parent
GFS_DIR = HERE / "data" / "gfs"
MARKET_DIR = MARKET
INGESTED_DIR = HERE / "data" / "ws2" / "ingested"
LIVE_MANIFEST = HERE / "data" / "ws2" / "vintage_manifest.json"


class IngestError(Exception):
    """Base class for live-ingestion failures (never a silent drop)."""


class DataStalenessError(IngestError):
    """Cycle or OJ close too old / not yet published for the live path."""


class UpstreamMissingError(IngestError):
    """Upstream data (GFS cycle, OJ close) unavailable or empty."""


class RejectCycleError(IngestError):
    """A live armor gate failed; the cycle is rejected and never persisted."""


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t


def _as_date_str(x) -> str:
    return pd.Timestamp(x).strftime("%Y%m%d")


def latest_12z_cycle(ref_time=None) -> str:
    """Most recent completed 12Z cycle date at ``ref_time`` (12Z + latency)."""
    now = _utc(ref_time) if ref_time is not None else pd.Timestamp(datetime.now(timezone.utc))
    for days_back in range(8):
        run = now.normalize() - pd.Timedelta(days=days_back)
        published = run + pd.Timedelta(hours=CYCLE_HOUR + PUBLISH_LATENCY_HOURS)
        if published <= now:
            return run.strftime("%Y%m%d")
    raise UpstreamMissingError(f"no completed {CYCLE_HOUR}Z GFS cycle near {now}")


def check_staleness(cycle_date, ref_time=None) -> None:
    """Reject a cycle that is not the current or immediately-previous 12Z run."""
    cyc = _utc(cycle_date).normalize()
    latest = _utc(latest_12z_cycle(ref_time)).normalize()
    if cyc > latest:
        raise DataStalenessError(
            f"cycle {cyc.date()} not yet published; latest completed {CYCLE_HOUR}Z is {latest.date()}"
        )
    if (latest - cyc).days > STALE_CYCLE_TOLERANCE_DAYS:
        raise DataStalenessError(
            f"cycle {cyc.date()} is stale: latest completed {CYCLE_HOUR}Z is {latest.date()} "
            f"(tolerance {STALE_CYCLE_TOLERANCE_DAYS} cycle)"
        )


def _fetch_leads(
    date: str, source: str, conn: GFSConnector | None
) -> list[tuple[pd.DataFrame, str]]:
    """Download each locked lead (NOMADS primary, AWS ``noaa-gfs-bdp-pds`` fallback)."""
    conn = conn or GFSConnector(variables=VARIABLES, bbox=WEDGE_BBOX, resolution=RESOLUTION)
    fetched: list[tuple[pd.DataFrame, str]] = []
    for lead in LEADS:
        used = source if source in ("nomads", "aws") else "auto"
        try:
            if source == "aws":
                ds = conn._fetch_archive_cycle(date, f"{CYCLE_HOUR:02d}", lead)
            else:
                try:
                    ds = conn._fetch_forecast(date, f"{CYCLE_HOUR:02d}", lead)
                    used = "nomads"
                except Exception:
                    if source == "nomads":
                        raise
                    ds = conn._fetch_archive_cycle(date, f"{CYCLE_HOUR:02d}", lead)
                    used = "aws"
        except IngestError:
            raise
        except Exception as exc:
            raise UpstreamMissingError(
                f"cycle {date} {CYCLE_HOUR}Z f{lead:03d} upstream unavailable: {exc}"
            ) from exc
        ds = conn._subset_bbox(ds)
        df = ds.to_dataframe().reset_index()
        if df.empty:
            raise UpstreamMissingError(
                f"cycle {date} {CYCLE_HOUR}Z f{lead:03d}: empty frame after subset"
            )
        df["date"] = date
        df["cycle"] = f"{CYCLE_HOUR:02d}"
        df["lead"] = int(lead)
        fetched.append((df, used))
    if not fetched:
        raise UpstreamMissingError(f"cycle {date} {CYCLE_HOUR}Z: no leads downloaded")
    return fetched


def _cycle_files(gfs_dir: Path, cycle_date: str) -> list[Path]:
    return sorted(Path(gfs_dir).glob(f"gfs_{cycle_date}_*_{BBOX_TAG}.parquet"))


def download_cycle(
    date: str,
    source: str = "auto",
    gfs_dir: Path | str = GFS_DIR,
    cache_dir: Path | str | None = None,
    conn: GFSConnector | None = None,
    offline: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Fetch the cycle, persist one raw parquet per lead, return (frame, source).

    With ``offline=True`` (T3 replay mode) the cycle is read from the cached
    ``gfs_dir`` parquets instead of the network — the exact bytes the live path
    would have pinned, so the vintage armor and feature recipe are unchanged.
    """
    gfs_dir = Path(gfs_dir)
    if offline:
        files = _cycle_files(gfs_dir, date)
        if not files:
            raise UpstreamMissingError(
                f"cycle {date} {CYCLE_HOUR}Z: no cached parquets in {gfs_dir} (offline replay)"
            )
        frame = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
        if frame.empty:
            raise UpstreamMissingError(f"cycle {date} {CYCLE_HOUR}Z: empty offline frame")
        return frame, "offline-replay"

    gfs_dir.mkdir(parents=True, exist_ok=True)
    fetched = _fetch_leads(date, source, conn=conn)
    frame = pd.concat([df for df, _ in fetched], ignore_index=True)
    if frame.empty:
        raise UpstreamMissingError(f"cycle {date} {CYCLE_HOUR}Z: empty frame")
    for lead in LEADS:
        sub = frame[frame["lead"] == int(lead)]
        path = gfs_dir / f"gfs_{date}_12z_f{lead:03d}_{BBOX_TAG}.parquet"
        sub.to_parquet(path, index=False)
    return frame, fetched[0][1]


def validate_cycle(frame: pd.DataFrame) -> dict:
    """Schema + spatial-completeness gates; raises, never returns an empty frame."""
    if frame.empty:
        raise UpstreamMissingError("empty cycle frame — refusing to persist")
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise RejectCycleError(f"schema: missing columns {missing}")
    if "lead" not in frame.columns:
        raise RejectCycleError("schema: no lead column")
    present = sorted({int(x) for x in frame["lead"]})
    missing_leads = [lead for lead in LEADS if lead not in present]
    if missing_leads:
        raise RejectCycleError(f"spatial completeness: missing leads {missing_leads}")
    per_lead = frame.groupby("lead").size().to_dict()
    bad = [int(lead) for lead, n in per_lead.items() if n != EXPECTED_CELLS_PER_LEAD]
    if bad:
        raise RejectCycleError(
            f"spatial completeness: wedge cells {per_lead}; expected {EXPECTED_CELLS_PER_LEAD} per lead"
        )
    if frame["t2m"].isna().all():
        raise RejectCycleError("schema: t2m all-NaN")
    return {
        "grid_cells": len(frame),
        "per_lead": {int(k): int(v) for k, v in per_lead.items()},
        "leads": present,
        "ok": True,
    }


def fetch_oj_close(cycle_date, market_dir: Path | str = MARKET_DIR) -> dict:
    """Latest realized OJ close on/before the cycle date; fails loud on gaps."""
    p = Path(market_dir) / "oj_continuous.parquet"
    if not p.exists():
        raise UpstreamMissingError(f"OJ market file missing: {p}")
    oj = pd.read_parquet(p).reset_index()
    if oj.empty:
        raise UpstreamMissingError(f"OJ market file empty: {p}")
    oj["Date"] = pd.to_datetime(oj["Date"])
    oj = oj.set_index("Date").sort_index()
    cyc = _utc(cycle_date).tz_localize(None).normalize()
    realized = oj[oj.index <= cyc]
    if realized.empty:
        raise UpstreamMissingError(f"no realized OJ close on/before {cyc.date()}")
    row = realized.iloc[-1]
    close_date = realized.index[-1]
    stale_days = int((cyc - close_date).days)
    if stale_days > OJ_STALENESS_MAX_DAYS:
        raise DataStalenessError(
            f"OJ close {close_date.date()} is {stale_days}d stale "
            f"(max {OJ_STALENESS_MAX_DAYS}d) relative to cycle {cyc.date()}"
        )
    rec = {
        "date": str(close_date.date()),
        "close_adj": float(row["close_adj"]),
        "close_raw": float(row["close_raw"]) if "close_raw" in oj.columns else None,
        "stale_days": stale_days,
    }
    rec["sha256"] = hashlib.sha256(
        json.dumps(
            {"date": rec["date"], "close_adj": rec["close_adj"], "close_raw": rec["close_raw"]},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return rec


def build_features(frame: pd.DataFrame) -> dict:
    """Freeze features from the cycle frame (identical to the WS-0/WS-1 recipe)."""
    return freeze_features(frame, publish_latency_hours=PUBLISH_LATENCY_HOURS)


def pin_vintage_sha(gfs_dir: Path | str, cycle_date: str) -> dict:
    """Content hash over the cycle's raw parquet bytes (byte order = filename order)."""
    files = _cycle_files(Path(gfs_dir), cycle_date)
    if not files:
        raise UpstreamMissingError(f"no raw cycle parquets for {cycle_date} in {gfs_dir}")
    h = hashlib.sha256()
    nbytes = 0
    for p in files:
        nbytes += p.stat().st_size
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return {"n_files": len(files), "nbytes": int(nbytes), "sha256": h.hexdigest()}


def load_live_manifest(path: Path | str = LIVE_MANIFEST) -> dict:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    return {"source": ARCHIVE, "recorded_utc": None, "n_cycles": 0, "cycles": {}}


@contextmanager
def _manifest_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock for read-modify-write on the manifest JSON.

    Concurrent workers (cron + manual, Actions runner + local) otherwise
    race: two read-modify-write cycles can silently drop each other's pin.
    """
    try:
        import fcntl
    except ImportError:  # non-POSIX: no advisory locks; best-effort
        yield
        return
    lock_path = Path(str(path) + ".lock")
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def append_cycle_pin(cycle_date: str, pin: dict, manifest_path: Path | str = LIVE_MANIFEST) -> None:
    p = Path(manifest_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _manifest_lock(p):
        manifest = load_live_manifest(p)
        manifest["cycles"][cycle_date] = pin
        manifest["recorded_utc"] = pd.Timestamp.now("UTC").isoformat()
        manifest["n_cycles"] = len(manifest["cycles"])
        p.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _revert_pin(cycle_date: str, manifest_path: Path | str = LIVE_MANIFEST) -> None:
    p = Path(manifest_path)
    if not p.exists():
        return
    with _manifest_lock(p):
        manifest = json.loads(p.read_text())
        if cycle_date in manifest.get("cycles", {}):
            manifest["cycles"].pop(cycle_date)
            manifest["n_cycles"] = len(manifest["cycles"])
            if manifest["cycles"]:
                p.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            else:
                p.unlink()


def _remove_raw_cycle(gfs_dir: Path | str, cycle_date: str) -> None:
    from contextlib import suppress

    for f in _cycle_files(Path(gfs_dir), cycle_date):
        with suppress(OSError):
            f.unlink()


def load_oj(market_dir: Path | str = MARKET_DIR) -> pd.DataFrame:
    oj = pd.read_parquet(Path(market_dir) / "oj_continuous.parquet").reset_index()
    oj["Date"] = pd.to_datetime(oj["Date"])
    return oj.set_index("Date").sort_index()[["close_adj"]].dropna()


def sessions_from_market(market_dir: Path | str = MARKET_DIR) -> pd.DatetimeIndex:
    return load_oj(market_dir).index


def load_calendar(market_dir: Path | str = MARKET_DIR) -> pd.DataFrame:
    return pd.read_csv(Path(market_dir) / "oj_contract_calendar.csv")


def _armor_pit_row(features: dict, cycle_date) -> pd.DataFrame:
    row = {
        "date": _utc(cycle_date).tz_localize(None),
        "publish_time": _utc(features["current_time"]),
        "event_peak_time": (
            _utc(features["event_peak_time"])
            if features.get("event_peak_time") is not None
            else pd.NaT
        ),
        "temperature_min": features["temperature_min"],
        "freeze_prob": features["freeze_prob"],
        "t2m_min_k": features.get("t2m_min_k"),
        "grid_cells": features.get("grid_cells"),
        "horizon_cells": features.get("horizon_cells"),
    }
    return pd.DataFrame([row])


def live_armor(
    features: dict,
    cycle_date,
    sessions: pd.DatetimeIndex,
    manifest: dict,
    gfs_dir: Path | str,
    oj: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
) -> dict:
    """Run the three live armor gates; a violation raises :class:`RejectCycleError`."""
    pit = _armor_pit_row(features, cycle_date)
    try:
        ts = check_timestamp_armor(pit, sessions)
        vg = check_vintage_armor(pit, manifest=manifest, gfs_dir=str(gfs_dir))
        rj = check_roll_jump_armor(pit, sessions, oj=oj, calendar=calendar)
    except (LookaheadError, RollJumpError) as exc:
        raise RejectCycleError(str(exc)) from exc
    return {"pass": True, "timestamp": ts, "vintage": vg, "roll_jump": rj}


def ingest_cycle(
    date,
    ref_time=None,
    source: str = "auto",
    gfs_dir: Path | str = GFS_DIR,
    market_dir: Path | str = MARKET_DIR,
    ingested_dir: Path | str = INGESTED_DIR,
    manifest_path: Path | str = LIVE_MANIFEST,
    cache_dir: Path | str | None = None,
    conn: GFSConnector | None = None,
    persist: bool = True,
    offline: bool = False,
) -> dict:
    """Ingest, validate, gate and persist one live 12Z cycle + OJ close.

    Never returns an empty frame: on any failure the cycle's raw files and
    vintage pin are removed (it is never persisted) and an explicit
    :class:`IngestError` subclass is raised.  With ``offline=True`` (T3 replay)
    the raw cached parquets are read rather than downloaded and are **not**
    deleted on failure (they are shared infrastructure, not worker scratch).
    """
    cycle_date = _as_date_str(date)
    gfs_dir = Path(gfs_dir)
    try:
        check_staleness(cycle_date, ref_time=ref_time)
        frame, src = download_cycle(
            cycle_date,
            source=source,
            gfs_dir=gfs_dir,
            cache_dir=cache_dir,
            conn=conn,
            offline=offline,
        )
        validation = validate_cycle(frame)
        features = build_features(frame)
        oj_close = fetch_oj_close(cycle_date, market_dir=market_dir)
        pin = pin_vintage_sha(gfs_dir, cycle_date)
        append_cycle_pin(cycle_date, pin, manifest_path)
        sessions = sessions_from_market(market_dir)
        armor = live_armor(
            features,
            cycle_date,
            sessions,
            load_live_manifest(manifest_path),
            gfs_dir,
            oj=load_oj(market_dir),
            calendar=load_calendar(market_dir),
        )
    except IngestError:
        _revert_pin(cycle_date, manifest_path)
        if not offline:
            _remove_raw_cycle(gfs_dir, cycle_date)
        raise

    record = {
        "forecast_cycle_id": f"{cycle_date}_{CYCLE_HOUR:02d}z",
        "cycle_date": str(_utc(cycle_date).date()),
        "cycle_hour": CYCLE_HOUR,
        "publication_ts": _utc(features["current_time"]).isoformat(),
        "model_version": MODEL_VERSION,
        "archive_source": ARCHIVE,
        "upstream": src,
        "fetch_date": pd.Timestamp.now("UTC").isoformat(),
        "leads": list(LEADS),
        "validation": validation,
        "features": {
            k: features[k]
            for k in ("freeze_prob", "temperature_min", "t2m_min_k", "grid_cells", "horizon_cells")
        },
        "event_peak_time": (
            _utc(features["event_peak_time"]).isoformat()
            if features.get("event_peak_time") is not None
            else None
        ),
        "vintage": pin,
        "oj_close": oj_close,
        "armor": armor,
        "raw_files": [
            str(p.relative_to(HERE)) if HERE in p.parents else str(p)
            for p in _cycle_files(gfs_dir, cycle_date)
        ],
        "ok": True,
    }
    if persist:
        out_dir = Path(ingested_dir) / f"{cycle_date}_{CYCLE_HOUR:02d}z"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cycle.json").write_text(
            json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
        )
    else:
        _revert_pin(cycle_date, manifest_path)
        if not offline:
            _remove_raw_cycle(gfs_dir, cycle_date)
    return record
