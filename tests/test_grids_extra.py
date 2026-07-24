"""Tests for pakhi.grids — coordinate, regridder, subset."""
from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from pakhi.grids.coordinate import (
    altitude_to_pressure,
    geopotential_to_height,
    km_to_latlon,
    latlon_to_km,
    pressure_to_altitude,
    validate_latlon,
)
from pakhi.grids.regridder import create_regular_grid, regrid, regrid_to_regular
from pakhi.grids.subset import subset_bbox, subset_point


def _make_da_2d(n_lat=10, n_lon=10):
    lats = np.linspace(30, 35, n_lat)
    lons = np.linspace(-90, -85, n_lon)
    data = np.random.randn(n_lat, n_lon)
    return xr.DataArray(data, dims=["latitude", "longitude"],
                        coords={"latitude": lats, "longitude": lons})


class TestCoordinate:
    def test_latlon_to_km(self):
        d = latlon_to_km(32.0, -88.0, 33.0, -87.0)
        assert d > 0

    def test_latlon_to_km_same(self):
        d = latlon_to_km(32.0, -88.0, 32.0, -88.0)
        assert d == pytest.approx(0.0)

    def test_km_to_latlon(self):
        lat, lon = km_to_latlon(32.0, -88.0, 100.0, 100.0)
        assert lat > 32.0
        assert lon > -88.0

    def test_pressure_to_altitude(self):
        alt = pressure_to_altitude(1013.25)
        assert alt == pytest.approx(0.0, abs=1.0)

    def test_pressure_to_altitude_high(self):
        alt = pressure_to_altitude(500.0)
        assert alt > 5000

    def test_pressure_to_altitude_negative(self):
        with pytest.raises(ValueError):
            pressure_to_altitude(-1.0)

    def test_altitude_to_pressure(self):
        p = altitude_to_pressure(0.0)
        assert p == pytest.approx(1013.25, rel=0.01)

    def test_altitude_to_pressure_high(self):
        p = altitude_to_pressure(10000.0)
        assert p < 300

    def test_pressure_roundtrip(self):
        p = altitude_to_pressure(5000.0)
        alt = pressure_to_altitude(p)
        assert alt == pytest.approx(5000.0, rel=0.05)

    def test_geopotential_to_height(self):
        h = geopotential_to_height(9806.65, latitude=45.0)
        assert h == pytest.approx(1000.0, rel=0.01)

    def test_validate_latlon(self):
        valid, errors = validate_latlon(32.0, -88.0)
        assert valid
        assert errors == []

    def test_validate_latlon_invalid(self):
        valid, errors = validate_latlon(100.0, -88.0)
        assert not valid

    def test_validate_latlon_empty(self):
        valid, errors = validate_latlon(np.array([]), np.array([]))
        assert not valid


class TestRegridder:
    def test_create_regular_grid(self):
        grid = create_regular_grid((30, 32), (-90, -88), resolution_deg=0.5)
        assert grid.shape[0] > 0
        assert grid.shape[1] > 0

    def test_create_regular_grid_invalid(self):
        with pytest.raises(ValueError):
            create_regular_grid((32, 30), (-90, -88))

    def test_regrid_bilinear(self):
        source = _make_da_2d()
        target = create_regular_grid((31, 34), (-89, -86), resolution_deg=1.0)
        result = regrid(source, target, method="bilinear")
        assert result is not None

    def test_regrid_nearest(self):
        source = _make_da_2d()
        target = create_regular_grid((31, 34), (-89, -86), resolution_deg=1.0)
        result = regrid(source, target, method="nearest")
        assert result is not None

    def test_regrid_invalid_method(self):
        source = _make_da_2d()
        target = create_regular_grid((31, 34), (-89, -86), resolution_deg=1.0)
        with pytest.raises(ValueError):
            regrid(source, target, method="bad")

    def test_regrid_to_regular(self):
        source = _make_da_2d()
        result = regrid_to_regular(source, target_resolution=1.0)
        assert result is not None


class TestSubset:
    def test_subset_bbox(self):
        da = _make_da_2d()
        result = subset_bbox(da, lat_min=31, lat_max=33, lon_min=-89, lon_max=-87)
        assert result is not None

    def test_subset_point(self):
        da = _make_da_2d()
        result = subset_point(da, lat=32.5, lon=-87.5, radius_km=100)
        assert result is not None
