"""Tests for grid operations in pakhi.grids."""

from __future__ import annotations

import numpy as np
import pytest

from pakhi.grids.coordinate import (
    altitude_to_pressure,
    km_to_latlon,
    latlon_to_km,
    pressure_to_altitude,
)
from pakhi.grids.interpolate import (
    bilinear_interpolation,
    cressman_interpolation,
    nearest_neighbor,
)
from pakhi.grids.regridder import create_regular_grid
from pakhi.grids.subset import subset_bbox

# ---------------------------------------------------------------------------
# bilinear_interpolation
# ---------------------------------------------------------------------------


class TestBilinearInterpolation:
    def test_exact_grid_point(self, synth_grid):
        lat = float(synth_grid.coords["latitude"].values[2])
        lon = float(synth_grid.coords["longitude"].values[3])
        result = bilinear_interpolation(synth_grid, lat, lon)
        expected = float(synth_grid.values[2, 3])
        assert result == pytest.approx(expected, rel=1e-6)

    def test_midpoint_interpolation(self, synth_grid):
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        mid_lat = float((lats[0] + lats[1]) / 2)
        mid_lon = float((lons[0] + lons[1]) / 2)
        result = bilinear_interpolation(synth_grid, mid_lat, mid_lon)
        expected = np.mean(synth_grid.values[:2, :2])
        assert result == pytest.approx(expected, rel=1e-3)

    def test_array_input(self, synth_grid):
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        target_lats = np.array([lats[1], lats[3]])
        target_lons = np.array([lons[1], lons[3]])
        result = bilinear_interpolation(synth_grid, target_lats, target_lons)
        assert result.shape == (2,)
        assert result[0] == pytest.approx(synth_grid.values[1, 1], rel=1e-6)
        assert result[1] == pytest.approx(synth_grid.values[3, 3], rel=1e-6)

    def test_out_of_bounds_returns_nan(self, synth_grid):
        result = bilinear_interpolation(synth_grid, 90.0, 90.0)
        assert np.isnan(result)

    def test_rejects_3d_input(self, synth_grid):
        arr_3d = synth_grid.expand_dims("time")
        with pytest.raises(ValueError, match="2-D"):
            bilinear_interpolation(arr_3d, 32.0, -88.0)


# ---------------------------------------------------------------------------
# nearest_neighbor
# ---------------------------------------------------------------------------


class TestNearestNeighbor:
    def test_exact_grid_point(self, synth_grid):
        lat = float(synth_grid.coords["latitude"].values[0])
        lon = float(synth_grid.coords["longitude"].values[0])
        result = nearest_neighbor(synth_grid, lat, lon)
        assert result == pytest.approx(synth_grid.values[0, 0])

    def test_nearest_to_correct_point(self, synth_grid):
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        # Slightly closer to index [2,2] than [2,3]
        result = nearest_neighbor(
            synth_grid,
            lats[2] + 0.01,
            lons[2] + 0.01,
        )
        assert result == pytest.approx(synth_grid.values[2, 2])

    def test_array_input(self, synth_grid):
        lats = synth_grid.coords["latitude"].values[:3]
        lons = synth_grid.coords["longitude"].values[:3]
        result = nearest_neighbor(synth_grid, lats, lons)
        assert result.shape == (3,)

    def test_rejects_3d_input(self, synth_grid):
        arr_3d = synth_grid.expand_dims("time")
        with pytest.raises(ValueError, match="2-D"):
            nearest_neighbor(arr_3d, 32.0, -88.0)


# ---------------------------------------------------------------------------
# cressman_interpolation
# ---------------------------------------------------------------------------


class TestCressmanInterpolation:
    def test_with_matching_obs(self, synth_grid):
        """Observations at grid points should pull analysis toward obs."""
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        obs_lat = np.array([lats[2]])
        obs_lon = np.array([lons[2]])
        obs_val = np.array([999.0])

        result = cressman_interpolation(
            synth_grid,
            lats[2],
            lons[2],
            obs_lat,
            obs_lon,
            obs_val,
            search_radius_km=500.0,
        )
        # Should be close to the observation
        assert abs(result - 999.0) < 50.0

    def test_no_observations_returns_background(self, synth_grid):
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        with pytest.warns(UserWarning, match="No valid observations"):
            result = cressman_interpolation(
                synth_grid,
                lats[2],
                lons[2],
                np.array([]),
                np.array([]),
                np.array([]),
            )
        assert result == pytest.approx(synth_grid.values[2, 2])

    def test_nan_observations_excluded(self, synth_grid):
        lats = synth_grid.coords["latitude"].values
        lons = synth_grid.coords["longitude"].values
        obs_lat = np.array([lats[2]])
        obs_lon = np.array([lons[2]])
        obs_val = np.array([np.nan])
        with pytest.warns(UserWarning):
            result = cressman_interpolation(
                synth_grid,
                lats[2],
                lons[2],
                obs_lat,
                obs_lon,
                obs_val,
            )
        assert result == pytest.approx(synth_grid.values[2, 2])


# ---------------------------------------------------------------------------
# latlon_to_km / km_to_latlon roundtrip
# ---------------------------------------------------------------------------


class TestCoordinateRoundtrip:
    def test_known_distance(self):
        # New York to Los Angeles ≈ 3944 km
        d = latlon_to_km(40.71, -74.01, 34.05, -118.24)
        assert 3900 < d < 4000

    def test_zero_distance(self):
        d = latlon_to_km(41.88, -87.63, 41.88, -87.63)
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_roundtrip_near_equator(self):
        lat, lon = 0.0, 0.0
        new_lat, new_lon = km_to_latlon(lat, lon, 100.0, 100.0)
        d = latlon_to_km(lat, lon, new_lat, new_lon)
        assert d == pytest.approx(141.4, rel=0.05)  # sqrt(100^2+100^2) approx

    def test_km_to_latlon_northward(self):
        new_lat, new_lon = km_to_latlon(40.0, -80.0, 100.0, 0.0)
        assert new_lat > 40.0
        assert new_lon == pytest.approx(-80.0, abs=1e-6)


# ---------------------------------------------------------------------------
# pressure_to_altitude / altitude_to_pressure roundtrip
# ---------------------------------------------------------------------------


class TestPressureAltitudeRoundtrip:
    def test_sea_level_pressure(self):
        alt = pressure_to_altitude(1013.25)
        assert alt == pytest.approx(0.0, abs=1.0)

    def test_500hpa_altitude(self):
        alt = pressure_to_altitude(500.0)
        assert 5000 < alt < 6000

    def test_roundtrip(self):
        alt = 3000.0
        p = altitude_to_pressure(alt)
        alt_back = pressure_to_altitude(p)
        assert alt_back == pytest.approx(alt, rel=0.01)

    def test_array_roundtrip(self):
        alts = np.array([0.0, 1000.0, 5000.0, 10000.0])
        pressures = altitude_to_pressure(alts)
        alts_back = pressure_to_altitude(pressures)
        np.testing.assert_allclose(alts_back, alts, rtol=0.01)

    def test_negative_pressure_raises(self):
        with pytest.raises(ValueError, match="Pressure must be positive"):
            pressure_to_altitude(-100.0)


# ---------------------------------------------------------------------------
# subset_bbox
# ---------------------------------------------------------------------------


class TestSubsetBbox:
    def test_full_subset(self, synth_xr_dataset):
        sub = subset_bbox(
            synth_xr_dataset["temperature"],
            lat_min=30.0,
            lat_max=34.0,
            lon_min=-90.0,
            lon_max=-86.0,
        )
        assert sub.shape == (10, 5, 5)

    def test_partial_subset(self, synth_xr_dataset):
        sub = subset_bbox(
            synth_xr_dataset["temperature"],
            lat_min=31.0,
            lat_max=33.0,
            lon_min=-89.0,
            lon_max=-87.0,
        )
        assert sub.sizes["latitude"] < 5
        assert sub.sizes["longitude"] < 5

    def test_no_overlap_warns(self, synth_xr_dataset):
        with pytest.warns(UserWarning, match="No latitude"):
            subset_bbox(
                synth_xr_dataset["temperature"],
                lat_min=0.0,
                lat_max=1.0,
                lon_min=0.0,
                lon_max=1.0,
            )


# ---------------------------------------------------------------------------
# create_regular_grid
# ---------------------------------------------------------------------------


class TestCreateRegularGrid:
    def test_basic(self):
        grid = create_regular_grid((0.0, 2.0), (0.0, 2.0), resolution_deg=1.0)
        assert grid.shape == (3, 3)
        assert grid.dims == ("latitude", "longitude")

    def test_025_resolution(self):
        grid = create_regular_grid((30.0, 31.0), (-90.0, -89.0), resolution_deg=0.25)
        assert grid.shape[0] >= 4
        assert grid.shape[1] >= 4

    def test_nan_fill(self):
        grid = create_regular_grid((0.0, 1.0), (0.0, 1.0), resolution_deg=1.0)
        assert np.all(np.isnan(grid.values))

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="lat_min.*must be <= lat_max"):
            create_regular_grid((5.0, 0.0), (0.0, 1.0))

    def test_negative_resolution_raises(self):
        with pytest.raises(ValueError, match="resolution_deg must be positive"):
            create_regular_grid((0.0, 1.0), (0.0, 1.0), resolution_deg=-0.5)

    def test_attrs(self):
        grid = create_regular_grid((0.0, 1.0), (0.0, 1.0), resolution_deg=0.5)
        assert grid.attrs["grid_type"] == "regular_lonlat"
        assert grid.attrs["resolution_deg"] == 0.5
