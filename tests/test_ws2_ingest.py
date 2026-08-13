"""WS-2 T1: ingestion worker tests (mocked upstream, no network)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from pakhi.ws1.armor import LookaheadError
from pakhi.ws2 import ingest
from pakhi.ws2.ingest import (
    DataStalenessError,
    IngestError,
    RejectCycleError,
    UpstreamMissingError,
    check_staleness,
    ingest_cycle,
    latest_12z_cycle,
    validate_cycle,
)


def _fake_cycle_frame(cycle_date="2026-08-10", t2m_k=290.0) -> pd.DataFrame:
    run = pd.Timestamp(f"{cycle_date} 12:00:00", tz="UTC")
    lats = np.arange(31.0, 23.5, -0.5)
    lons = np.arange(275.0, 280.5, 0.5)
    frames = []
    for lead in (0, 12, 24, 48):
        rows = [
            {
                "latitude": lat,
                "longitude": lon,
                "time": run,
                "step": pd.Timedelta(hours=lead),
                "valid_time": run + pd.Timedelta(hours=lead),
                "t2m": t2m_k,
                "date": cycle_date.replace("-", ""),
                "cycle": "12",
                "lead": lead,
            }
            for lat in lats
            for lon in lons
        ]
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def fake_fetch(monkeypatch):
    def _install(frames=None, raises=None):
        def _fake(date, source, conn=None):
            if raises is not None:
                raise raises
            if frames is None:
                return [
                    (df, "aws") for df in [pd.concat([_fake_cycle_frame(date)], ignore_index=True)]
                ]
            return [(df, "aws") for df in frames]

        monkeypatch.setattr(ingest, "_fetch_leads", _fake)

    return _install


@pytest.fixture
def live_cycle():
    return "20260810"


def test_latest_12z_cycle_before_publish():
    assert latest_12z_cycle("2026-08-13 12:00:00") == "20260812"
    assert latest_12z_cycle("2026-08-13 16:00:00") == "20260813"
    assert latest_12z_cycle("2026-08-13") == "20260812"


def test_staleness_rejects_old_and_future_cycles():
    check_staleness("20260813", ref_time="2026-08-13 16:00:00")
    check_staleness("20260812", ref_time="2026-08-13 16:00:00")
    with pytest.raises(DataStalenessError):
        check_staleness("20260801", ref_time="2026-08-13 16:00:00")
    with pytest.raises(DataStalenessError):
        check_staleness("20260814", ref_time="2026-08-13 16:00:00")


def test_validate_cycle_ok(live_cycle):
    detail = validate_cycle(_fake_cycle_frame(live_cycle))
    assert detail["grid_cells"] == 660
    assert detail["leads"] == [0, 12, 24, 48]


def test_validate_empty_raises():
    with pytest.raises(UpstreamMissingError):
        validate_cycle(pd.DataFrame())


def test_validate_schema_and_spatial_failures(live_cycle):
    frame = _fake_cycle_frame(live_cycle).drop(columns=["t2m"])
    with pytest.raises(RejectCycleError, match="missing columns"):
        validate_cycle(frame)
    frame = _fake_cycle_frame(live_cycle)
    frame = frame[frame["lead"] != 12]
    with pytest.raises(RejectCycleError, match="missing leads"):
        validate_cycle(frame)
    frame = _fake_cycle_frame(live_cycle)
    frame = frame.drop(frame[(frame["lead"] == 0) & (frame["latitude"] == 31.0)].index)
    with pytest.raises(RejectCycleError, match="wedge cells"):
        validate_cycle(frame)


def test_upstream_missing_raises(fake_fetch, live_cycle, tmp_path, monkeypatch):
    from pakhi.src.noaa import GFSConnector

    def _conn_fail(*args, **kwargs):
        raise ConnectionError("upstream unreachable")

    monkeypatch.setattr(GFSConnector, "_fetch_forecast", _conn_fail)
    monkeypatch.setattr(GFSConnector, "_fetch_archive_cycle", _conn_fail)
    with pytest.raises(UpstreamMissingError, match="upstream unavailable"):
        ingest.download_cycle(live_cycle, gfs_dir=tmp_path / "gfs")
    fake_fetch(frames=[pd.DataFrame()])
    with pytest.raises(UpstreamMissingError):
        ingest_cycle(live_cycle, ref_time="2026-08-10 16:00:00", gfs_dir=tmp_path / "gfs")


def test_happy_path_ingest_writes_pinned_artifacts(fake_fetch, live_cycle, tmp_path):
    fake_fetch()
    gfs = tmp_path / "gfs"
    manifest = tmp_path / "vintage_manifest.json"
    ingested = tmp_path / "ingested"
    record = ingest_cycle(
        live_cycle,
        ref_time="2026-08-10 16:00:00",
        gfs_dir=gfs,
        manifest_path=manifest,
        ingested_dir=ingested,
    )
    assert record["ok"] is True
    assert record["forecast_cycle_id"] == "20260810_12z"
    assert record["features"]["freeze_prob"] == 0.0
    assert len(list(gfs.glob("gfs_20260810_*"))) == 4
    pin = record["vintage"]
    assert pin["n_files"] == 4 and len(pin["sha256"]) == 64
    assert pin == json.loads(manifest.read_text())["cycles"]["20260810"]
    assert record["oj_close"]["date"] == "2026-08-10"
    for key in (
        "model_version",
        "forecast_cycle_id",
        "publication_ts",
        "archive_source",
        "vintage",
        "fetch_date",
    ):
        assert key in record
    assert record["armor"]["pass"] is True
    assert (ingested / "20260810_12z" / "cycle.json").exists()


def test_dry_run_does_not_persist(fake_fetch, live_cycle, tmp_path):
    fake_fetch()
    gfs = tmp_path / "gfs"
    manifest = tmp_path / "vintage_manifest.json"
    record = ingest_cycle(
        live_cycle,
        ref_time="2026-08-10 16:00:00",
        gfs_dir=gfs,
        manifest_path=manifest,
        persist=False,
    )
    assert record["ok"] is True
    assert list(gfs.glob("gfs_*")) == []
    assert not manifest.exists()
    assert ingest.load_live_manifest(manifest)["cycles"] == {}


def test_armor_rejection_cleans_up_never_persisted(fake_fetch, live_cycle, tmp_path, monkeypatch):
    fake_fetch()
    gfs = tmp_path / "gfs"
    manifest = tmp_path / "vintage_manifest.json"

    def _ts_fail(*args, **kwargs):
        raise LookaheadError("timestamp armor: injected future publish")

    monkeypatch.setattr(ingest, "check_timestamp_armor", _ts_fail)
    with pytest.raises(RejectCycleError, match="timestamp"):
        ingest_cycle(
            live_cycle,
            ref_time="2026-08-10 16:00:00",
            gfs_dir=gfs,
            manifest_path=manifest,
        )
    assert list(gfs.glob("gfs_*")) == []
    assert "20260810" not in ingest.load_live_manifest(manifest)["cycles"]


def test_vintage_drift_detected(fake_fetch, live_cycle, tmp_path):
    fake_fetch()
    gfs = tmp_path / "gfs"
    manifest = tmp_path / "vintage_manifest.json"
    ingest_cycle(
        live_cycle,
        ref_time="2026-08-10 16:00:00",
        gfs_dir=gfs,
        manifest_path=manifest,
    )
    tamper = next(iter(gfs.glob("gfs_*")))
    tamper.write_bytes(b"tampered raw archive bytes")
    features = ingest.build_features(_fake_cycle_frame(live_cycle))
    with pytest.raises(RejectCycleError, match="drifted"):
        ingest.live_armor(
            features,
            live_cycle,
            ingest.sessions_from_market(),
            ingest.load_live_manifest(manifest),
            gfs,
        )


def test_oj_close_missing_or_stale_raises(fake_fetch, live_cycle, tmp_path):
    fake_fetch()
    market = tmp_path / "market"
    market.mkdir()
    stale = pd.DataFrame(
        {
            "Date": pd.date_range("2020-01-01", periods=5, freq="B"),
            "close_adj": np.linspace(100, 110, 5),
            "close_raw": np.linspace(100, 110, 5),
        }
    )
    stale.to_parquet(market / "oj_continuous.parquet", index=False)
    with pytest.raises(DataStalenessError, match="stale"):
        ingest_cycle(
            live_cycle, ref_time="2026-08-10 16:00:00", gfs_dir=tmp_path / "gfs", market_dir=market
        )
    (market / "oj_continuous.parquet").unlink()
    with pytest.raises(UpstreamMissingError, match="missing"):
        ingest_cycle(
            live_cycle, ref_time="2026-08-10 16:00:00", gfs_dir=tmp_path / "gfs", market_dir=market
        )
    assert list((tmp_path / "gfs").glob("gfs_*")) == []


def test_never_returns_empty_dataframe(fake_fetch, live_cycle, tmp_path):
    fake_fetch(frames=[pd.DataFrame()])
    with pytest.raises(IngestError):
        ingest_cycle(live_cycle, ref_time="2026-08-10 16:00:00", gfs_dir=tmp_path / "gfs")


def test_forecast_cycle_id_format(live_cycle):
    assert latest_12z_cycle("2026-08-13 16:00:00") == "20260813"
    assert f"{live_cycle}_12z" == "20260810_12z"
