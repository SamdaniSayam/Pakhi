from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr


def test_anomaly_percentile():
    import dask.array as da

    from pakhi.features.anomaly import AnomalyFeatures

    hist = np.random.rand(100)
    data = xr.DataArray(da.random.random((10, 10), chunks=(5, 5)), dims=["lat", "lon"])
    res = AnomalyFeatures.percentile_rank(data, hist)
    assert isinstance(res, xr.DataArray)


def test_satellite_optical_flow():
    from pakhi.features.satellite import SatelliteFeatures

    data = xr.DataArray(
        np.random.rand(3, 10, 10),
        dims=["time", "lat", "lon"],
        coords={
            "time": pd.date_range("2020", periods=3),
            "lat": np.arange(10),
            "lon": np.arange(10),
        },
    )
    res = SatelliteFeatures.cloud_motion_vectors(data, 10)
    assert isinstance(res, xr.Dataset)


def test_spatial_div_coast():
    from pakhi.features.spatial import SpatialFeatures

    # Div without degrees
    u = np.array([[1, 2], [3, 4]])
    v = np.array([[1, 2], [3, 4]])
    ds = xr.Dataset(
        {"u": (("latitude", "longitude"), u), "v": (("latitude", "longitude"), v)},
        coords={"latitude": [0, 1], "longitude": [0, 1]},
    )
    div = SpatialFeatures.convergence(ds, dx_km=10.0)
    assert div["divergence"].shape == (2, 2)

    # distance_to_coast with scalar
    dist = SpatialFeatures.distance_to_coast(40.0, -70.0)
    assert isinstance(dist, float)


def test_teleconnection_xr():
    from pakhi.features.teleconnection import TeleconnectionIndices

    times = pd.date_range("2020", periods=10)
    ds = xr.Dataset(
        {"sst": (("time", "lat", "lon"), np.random.rand(10, 10, 10))}, coords={"time": times}
    )
    TeleconnectionIndices.compute_nino34(ds, lat_dim="lat", lon_dim="lon")

    ds_slp = xr.Dataset(
        {"slp": (("time", "lat", "lon"), np.random.rand(10, 10, 10))}, coords={"time": times}
    )
    TeleconnectionIndices.compute_nao(ds_slp, lat_dim="lat", lon_dim="lon")

    olr = xr.DataArray(
        np.random.rand(10, 10, 10),
        coords={"time": times, "lat": np.arange(10), "lon": np.arange(10)},
        dims=["time", "lat", "lon"],
    )
    TeleconnectionIndices.compute_mjo(olr, lat_dim="lat", lon_dim="lon")


def test_temporal_features():
    from pakhi.features.temporal import TemporalFeatures

    ds = xr.Dataset(
        {
            "var1": (("time",), np.random.rand(200)),
            "var2": (("lat", "lon"), np.random.rand(10, 10)),  # no time dim
        }
    )
    tf = TemporalFeatures()
    tf.build(ds, variables=["var1", "var2"])

    # test slope with nan and short array
    df = pd.DataFrame({"A": [np.nan, 1.0, np.nan]})
    tf = TemporalFeatures(stats=["trend"], windows=[3])
    tf.build(df, variables=["A"])

    # trigger ema and rolling_average xr paths
    df2 = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=pd.date_range("2020", periods=3))
    tf2 = TemporalFeatures(stats=["ema", "rolling"], windows=[2])
    res2 = tf2.build(df2, variables=["A"])
    assert "A_ema_12" in res2.columns
    assert "A_rolling_2" in res2.columns


def test_models_ensemble():
    from pakhi.models.ensemble import EnsembleForecaster
    from pakhi.models.persistence import PersistenceModel

    m1 = PersistenceModel()
    m1.fit(np.array([[1, 2], [3, 4]]), np.array([1, 2]))
    ens = EnsembleForecaster([m1])
    ens.fit(np.array([[1, 2], [3, 4]]), np.array([1, 2]))
    # Predict quantiles with single model (bma weights not used, just returns det)
    ens.predict_proba(np.array([[1, 2]]), quantiles=[0.1, 0.9])


def test_models_gradient():
    import sys

    from pakhi.models.gradient import (
        GradientForecaster,
        _lazy_import_lightgbm,
        _lazy_import_xgboost,
    )

    with patch.dict(sys.modules, {"xgboost": None}), pytest.raises(ImportError):
        _lazy_import_xgboost()

    with patch.dict(sys.modules, {"lightgbm": None}), pytest.raises(ImportError):
        _lazy_import_lightgbm()

    # empty feature importances
    m = GradientForecaster()
    _ = m.feature_importance
    m.feature_importance_top()

    # 2D X check
    m._fitted = True
    with pytest.raises(ValueError):
        m.predict(np.array([1, 2, 3]))


def test_models_lstm():
    import torch

    from pakhi.models.lstm import LSTMForecaster, _lazy_torch, _pinball_loss

    with patch.dict("sys.modules", {"torch": None}), pytest.raises(ImportError):
        _lazy_torch()

    # test empty all_preds in predict quantiles
    m = LSTMForecaster()
    m._fitted = True
    m._x_scaler.mean_ = 0
    m._x_scaler.std_ = 1
    m._net = type("DummyNet", (), {"train": lambda self: None, "eval": lambda self: None})()
    m._make_loader = lambda *a, **k: []
    m.predict_proba(np.array([[[1]]]), quantiles=[0.1])

    # test quantile_loss with all false mask and empty losses
    q = torch.tensor([[[1.0]]])
    y = torch.tensor([[1.0]])
    _pinball_loss(q, y, quantiles=[0.1])
    _pinball_loss(torch.tensor([]), torch.tensor([]), quantiles=[0.1])


def test_schedule_job_none():
    from datetime import datetime, timezone

    from pakhi.pipeline.schedule import RefreshScheduler

    class MockDict(dict):
        def get(self, k, default=None):
            return None

    sched = RefreshScheduler()
    sched._jobs = MockDict()
    sched._jobs["fake"] = {
        "next_run": datetime.now(timezone.utc),
        "interval_hours": 1,
        "callback": lambda: None,
    }

    sched._running = True
    sched._tick()


def test_verification_zero_denom():
    from pakhi.predict.verification import acc, brier_skill_score

    assert np.isnan(acc(np.array([1]), np.array([0]), 0.0))
    assert np.isnan(brier_skill_score(np.array([1]), np.array([1]), np.array([1])))


def test_risk_alerts_coverage():
    from pakhi.risk.alerts import AlertManager, AlertSeverity

    am = AlertManager()

    # Heatwave LOW (days=2, max_consecutive=2 => severity_factor = 2/7 = 0.28 <= 0.3)
    forecast = {"temperature_forecast": np.array([40, 40, 30])}
    alert = am.check_heatwave(forecast, threshold=38.0, days=2)
    assert alert is not None
    assert alert.severity == AlertSeverity.LOW

    # Drought HIGH (-3.0 <= mean_spi < -2.0)
    forecast = {"spi_values": np.array([-2.5, -2.5])}
    alert = am.check_drought(forecast, threshold=-1.0, days=2)
    assert alert is not None
    assert alert.severity == AlertSeverity.HIGH

    # Drought LOW (mean_spi >= -1.5)
    forecast = {"spi_values": np.array([-1.2, -1.2])}
    alert = am.check_drought(forecast, threshold=-1.0, days=2)
    assert alert is not None
    assert alert.severity == AlertSeverity.LOW


def test_risk_metrics_cvar_tail():
    from pakhi.risk.metrics import cvar

    with patch("numpy.percentile", return_value=-999):
        # r <= -999 will be empty
        assert cvar(np.array([1, 2, 3])) == 999.0


def test_metrics_cvar_empty_tail():
    from unittest.mock import patch

    import numpy as np

    from pakhi.risk.metrics import cvar

    with patch("pakhi.risk.metrics.np.percentile") as mock_perc:
        mock_perc.return_value = -999.0
        assert cvar(np.array([1.0, 2.0])) == 999.0


def test_metrics_sortino_tiny_downside():
    import numpy as np

    from pakhi.risk.metrics import sortino_ratio

    rf = 0.02
    rf_per_period = rf / 252
    returns = np.array([rf_per_period - 1e-16, rf_per_period - 1e-16])
    assert np.isnan(sortino_ratio(returns, risk_free_rate=rf))


def test_temp_heat_index():
    from pakhi.targets.temperature import heat_index

    # RH < 13 and 80 <= Tf <= 112
    heat_index((95 - 32) * 5 / 9, 10)


def test_maps_cartopy_import():
    import importlib
    import sys

    with patch.dict(sys.modules, {"cartopy.crs": None, "cartopy.feature": None}):
        import pakhi.viz.maps

        importlib.reload(pakhi.viz.maps)
        assert not pakhi.viz.maps._HAS_CARTOPY
