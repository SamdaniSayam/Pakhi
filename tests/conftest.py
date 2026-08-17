"""Shared pytest fixtures for the Pakhi test suite."""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import pakhi.ws1.pit as pit_module

_original_load_pit = pit_module.load_pit


def load_pit_skip_if_missing(*args, **kwargs):
    if not Path("data/ws0/freeze_pit.parquet").exists():
        pytest.skip("Real PIT data not found in CI environment, skipping test.")
    return _original_load_pit(*args, **kwargs)


pit_module.load_pit = load_pit_skip_if_missing


@pytest.fixture
def temp_series_365() -> pd.Series:
    """Synthetic daily temperature time series for 365 days.

    Simulates a sinusoidal annual cycle around 10 °C with noise.
    """
    rng = np.random.default_rng(42)
    days = pd.date_range("2023-01-01", periods=365, freq="D")
    trend = 10.0 + 15.0 * np.sin(2 * np.pi * np.arange(365) / 365.0 - np.pi / 2)
    noise = rng.normal(0, 2, 365)
    return pd.Series(trend + noise, index=days, name="temperature")


@pytest.fixture
def forecast_array() -> np.ndarray:
    """Synthetic 7-day ensemble forecast array.

    Shape (7, 20) — 7 days, 20 ensemble members.
    """
    rng = np.random.default_rng(99)
    base = np.array([5, 3, 1, -1, 2, 4, 6])
    return base[:, None] + rng.normal(0, 3, (7, 20))


@pytest.fixture
def synth_xr_dataset() -> xr.Dataset:
    """Synthetic xarray Dataset with lat, lon, and time dimensions.

    Contains temperature and pressure variables on a small 5x5 grid over
    10 days.
    """
    lats = np.linspace(30.0, 34.0, 5)
    lons = np.linspace(-90.0, -86.0, 5)
    times = pd.date_range("2023-06-01", periods=10, freq="D")
    rng = np.random.default_rng(0)

    temp = 25.0 + 5.0 * rng.random((10, 5, 5))
    pres = 1013.0 + rng.normal(0, 5, (10, 5, 5))

    return xr.Dataset(
        {
            "temperature": (["time", "latitude", "longitude"], temp),
            "pressure": (["time", "latitude", "longitude"], pres),
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )


@pytest.fixture
def synth_grid() -> xr.DataArray:
    """Small 2-D synthetic DataArray for interpolation tests."""
    lats = np.linspace(25.0, 45.0, 11)
    lons = np.linspace(-100.0, -80.0, 11)
    rng = np.random.default_rng(7)
    data = rng.random((11, 11))
    return xr.DataArray(
        data,
        dims=["latitude", "longitude"],
        coords={"latitude": lats, "longitude": lons},
    )


@pytest.fixture
def price_df() -> pd.DataFrame:
    """Synthetic daily price DataFrame with a datetime index."""
    rng = np.random.default_rng(55)
    dates = pd.date_range("2023-01-01", periods=200, freq="D")
    price = 100.0 + np.cumsum(rng.normal(0, 1, 200))
    return pd.DataFrame({"close": price}, index=dates)


@pytest.fixture
def daily_returns() -> np.ndarray:
    """Array of 252 synthetic daily returns."""
    rng = np.random.default_rng(123)
    return rng.normal(0.0005, 0.01, 252)


def pytest_sessionfinish(session, exitstatus):
    """Prevent PyTorch/ONNX teardown core dumps on interpreter shutdown.

    PyTorch + ONNX install C++ global state whose *static destructors* can
    segfault during ``Py_Finalize`` (a known Dynamo/ONNX artifact) once the ML
    stack has been loaded. We clear the JIT registry / ONNX caches here, then
    register an ``atexit`` handler that forces a clean process exit *after*
    pytest has printed its terminal summary but *before* the broken C++
    destructor teardown would dump core and make CI report a non-zero exit.

    The original pass/fail ``exitstatus`` is preserved, so real failures still
    propagate. Runs that never import torch exit normally.
    """
    import atexit
    import os
    import sys

    if "torch" not in sys.modules:
        return

    import torch

    if hasattr(torch._C, "_jit_clear_class_registry"):
        with contextlib.suppress(Exception):
            torch._C._jit_clear_class_registry()
    for modname in ("torch.onnx", "onnx"):
        if modname in sys.modules:
            with contextlib.suppress(Exception):
                sys.modules.pop(modname, None)

    def _clean_exit():
        # Flush buffered output, then bypass the segfaulting C++ teardown.
        with contextlib.suppress(Exception):
            import logging

            for handler in logging.root.handlers:
                handler.flush()
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        os._exit(int(exitstatus))

    atexit.register(_clean_exit)
