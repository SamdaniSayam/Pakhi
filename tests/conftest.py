"""Shared pytest fixtures for the Pakhi test suite."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr


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
