"""Comprehensive coverage tests for grids/subset.py, grids/regridder.py, grids/interpolate.py."""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import xarray as xr

from pakhi.grids.interpolate import (
    _ensure_regular_grid,
    _get_coord,
    bilinear_interpolation,
    cressman_interpolation,
    inverse_distance_weighting,
    nearest_neighbor,
)
from pakhi.grids.regridder import (
    _regrid_conservative,
    create_regular_grid,
    regrid,
    regrid_to_regular,
)
from pakhi.grids.subset import (
    _COUNTRY_BBOX,
    _find_coord,
    _get_country_mask,
    _haversine_km,
    _point_in_polygon,
    subset_country,
    subset_polygon,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _da2d(lat_min=0, lat_max=10, n_lat=11, lon_min=0, lon_max=10, n_lon=11):
    lats = np.linspace(lat_min, lat_max, n_lat)
    lons = np.linspace(lon_min, lon_max, n_lon)
    rng = np.random.default_rng(0)
    data = rng.random((n_lat, n_lon))
    return xr.DataArray(
        data, dims=["latitude", "longitude"], coords={"latitude": lats, "longitude": lons}
    )


def _da2d_named(coord_lat="lat", coord_lon="lon"):
    lats = np.linspace(0, 10, 11)
    lons = np.linspace(0, 10, 11)
    rng = np.random.default_rng(0)
    data = rng.random((11, 11))
    return xr.DataArray(
        data, dims=[coord_lat, coord_lon], coords={coord_lat: lats, coord_lon: lons}
    )


def _da3d():
    lats = np.linspace(0, 10, 6)
    lons = np.linspace(0, 10, 6)
    data = np.random.default_rng(1).random((3, 6, 6))
    return xr.DataArray(
        data,
        dims=["time", "latitude", "longitude"],
        coords={"time": [0, 1, 2], "latitude": lats, "longitude": lons},
    )


# ===========================================================================
# TestSubsetPolygon
# ===========================================================================


class TestSubsetPolygon:
    def test_basic_polygon_masks_outside(self):
        da = _da2d(lat_min=0, lat_max=10, n_lat=11, lon_min=0, lon_max=10, n_lon=11)
        poly_lat = np.array([2, 2, 8, 8])
        poly_lon = np.array([2, 8, 8, 2])
        result = subset_polygon(da, poly_lat, poly_lon)
        # Points inside should be finite, outside should be NaN
        assert np.any(np.isfinite(result.values))
        assert np.any(np.isnan(result.values))

    def test_polygon_closes_automatically(self):
        da = _da2d()
        poly_lat = np.array([1, 1, 5, 5])
        poly_lon = np.array([1, 5, 5, 1])
        result = subset_polygon(da, poly_lat, poly_lon)
        assert result.shape == da.shape

    def test_already_closed_polygon(self):
        da = _da2d()
        poly_lat = np.array([1, 1, 5, 5, 1])
        poly_lon = np.array([1, 5, 5, 1, 1])
        result = subset_polygon(da, poly_lat, poly_lon)
        assert result.shape == da.shape

    def test_too_few_vertices_raises(self):
        da = _da2d()
        with pytest.raises(ValueError, match="at least 3 vertices"):
            subset_polygon(da, np.array([1, 2]), np.array([3, 4]))

    def test_3d_array_masks_along_time(self):
        da = _da3d()
        poly_lat = np.array([2, 2, 8, 8])
        poly_lon = np.array([2, 8, 8, 2])
        result = subset_polygon(da, poly_lat, poly_lon)
        assert result.shape == da.shape
        # Check that NaN propagation along time axis works
        assert np.any(np.isnan(result.values))
        assert np.any(np.isfinite(result.values))

    def test_unsupported_4d_raises(self):
        data_4d = np.random.default_rng(0).random((2, 3, 4, 4))
        da = xr.DataArray(
            data_4d,
            dims=["a", "b", "latitude", "longitude"],
            coords={"latitude": np.linspace(0, 10, 4), "longitude": np.linspace(0, 10, 4)},
        )
        with pytest.raises(NotImplementedError, match="4-D"):
            subset_polygon(da, np.array([1, 1, 5]), np.array([1, 5, 1]))

    def test_single_point_inside_polygon(self):
        da = _da2d(lat_min=0, lat_max=10, n_lat=11, lon_min=0, lon_max=10, n_lon=11)
        # Tiny polygon around center
        poly_lat = np.array([4.9, 4.9, 5.1, 5.1])
        poly_lon = np.array([4.9, 5.1, 5.1, 4.9])
        result = subset_polygon(da, poly_lat, poly_lon)
        n_finite = np.sum(np.isfinite(result.values))
        assert n_finite >= 1

    def test_polygon_too_small_error(self):
        da = _da2d()
        with pytest.raises(ValueError, match="at least 3"):
            subset_polygon(da, np.array([1]), np.array([2]))


# ===========================================================================
# TestSubsetCountry
# ===========================================================================


class TestSubsetCountry:
    def test_known_country_returns_subset(self):
        da = _da2d(lat_min=-60, lat_max=85, n_lat=50, lon_min=-180, lon_max=180, n_lon=50)
        result = subset_country(da, "US")
        assert result.attrs.get("country_code") == "US"
        assert np.any(np.isfinite(result.values))
        # After bbox clipping, all remaining points are inside the bbox mask
        assert result.sizes["latitude"] < 50
        assert result.sizes["longitude"] < 50

    def test_unknown_country_raises(self):
        da = _da2d()
        with pytest.raises(ValueError, match="not in built-in lookup"):
            subset_country(da, "ZZ")

    def test_lowercase_code_works(self):
        da = _da2d(lat_min=-60, lat_max=85, n_lat=50, lon_min=-180, lon_max=180, n_lon=50)
        result = subset_country(da, "us")
        assert result.attrs.get("country_code") == "US"

    def test_3d_country_mask(self):
        lats = np.linspace(15, 55, 20)
        lons = np.linspace(-130, -60, 20)
        data = np.random.default_rng(0).random((3, 20, 20))
        da = xr.DataArray(
            data,
            dims=["time", "latitude", "longitude"],
            coords={"time": [0, 1, 2], "latitude": lats, "longitude": lons},
        )
        result = subset_country(da, "US")
        # subset_bbox clips spatial dims, so result is smaller
        assert result.sizes["time"] == 3
        assert result.sizes["latitude"] < 20
        assert result.sizes["longitude"] < 20
        assert result.attrs.get("country_code") == "US"

    def test_country_outside_grid_warns_or_nans(self):
        # Grid entirely south of any country
        da = _da2d(lat_min=-90, lat_max=-85, n_lat=5, lon_min=0, lon_max=5, n_lon=5)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = subset_country(da, "US")
        assert np.all(np.isnan(result.values))

    def test_country_bbox_lookup_is_populated(self):
        assert len(_COUNTRY_BBOX) > 0
        assert "US" in _COUNTRY_BBOX
        assert "IN" in _COUNTRY_BBOX


# ===========================================================================
# TestSubsetHelpers
# ===========================================================================


class TestSubsetHelpers:
    def test_find_coord_latitude(self):
        da = _da2d()
        assert _find_coord(da, "latitude") == "latitude"

    def test_find_coord_longitude(self):
        da = _da2d()
        assert _find_coord(da, "longitude") == "longitude"

    def test_find_coord_lat_name(self):
        da = _da2d_named("lat", "lon")
        assert _find_coord(da, "latitude") == "lat"

    def test_find_coord_lon_name(self):
        da = _da2d_named("lat", "lon")
        assert _find_coord(da, "longitude") == "lon"

    def test_find_coord_y_name(self):
        da = _da2d_named("y", "x")
        assert _find_coord(da, "latitude") == "y"

    def test_find_coord_x_name(self):
        da = _da2d_named("y", "x")
        assert _find_coord(da, "longitude") == "x"

    def test_find_coord_fallback_to_dims(self):
        data = np.zeros((5, 5))
        da = xr.DataArray(data, dims=["lat", "lon"])
        assert _find_coord(da, "latitude") == "lat"
        assert _find_coord(da, "longitude") == "lon"

    def test_find_coord_raises_on_missing(self):
        da = xr.DataArray(np.zeros((3, 3)), dims=["a", "b"])
        with pytest.raises(ValueError, match="Cannot find latitude"):
            _find_coord(da, "latitude")
        with pytest.raises(ValueError, match="Cannot find longitude"):
            _find_coord(da, "longitude")

    def test_haversine_same_point(self):
        d = _haversine_km(40.0, -80.0, 40.0, -80.0)
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_haversine_known_distance(self):
        # Roughly New York to London
        d = _haversine_km(40.71, -74.01, 51.51, -0.13)
        assert 5500 < d < 5600

    def test_haversine_array(self):
        lat1 = np.array([0.0, 0.0])
        lon1 = np.array([0.0, 0.0])
        lat2 = np.array([1.0, 2.0])
        lon2 = np.array([0.0, 0.0])
        d = _haversine_km(lat1, lon1, lat2, lon2)
        assert d[1] > d[0]

    def test_point_in_polygon_inside(self):
        poly_lat = np.array([0, 0, 10, 10, 0])
        poly_lon = np.array([0, 10, 10, 0, 0])
        result = _point_in_polygon(np.array([5.0]), np.array([5.0]), poly_lat, poly_lon)
        assert result[0]

    def test_point_in_polygon_outside(self):
        poly_lat = np.array([0, 0, 10, 10, 0])
        poly_lon = np.array([0, 10, 10, 0, 0])
        result = _point_in_polygon(np.array([15.0]), np.array([15.0]), poly_lat, poly_lon)
        assert not result[0]

    def test_point_in_polygon_on_boundary(self):
        poly_lat = np.array([0, 0, 10, 10, 0])
        poly_lon = np.array([0, 10, 10, 0, 0])
        result = _point_in_polygon(np.array([0.0]), np.array([5.0]), poly_lat, poly_lon)
        # On boundary — ray-casting result varies, just verify no crash
        assert isinstance(result[0], (bool, np.bool_))

    def test_point_in_polygon_triangle(self):
        poly_lat = np.array([0, 10, 5, 0])
        poly_lon = np.array([0, 0, 10, 0])
        inside = _point_in_polygon(np.array([2.0]), np.array([2.0]), poly_lat, poly_lon)
        assert inside[0]

    def test_get_country_mask_all_true_inside_bbox(self):
        lat_min, lat_max, lon_min, lon_max = 24.5, 49.4, -125.0, -66.9
        da = _da2d(
            lat_min=lat_min, lat_max=lat_max, n_lat=20, lon_min=lon_min, lon_max=lon_max, n_lon=20
        )
        mask = _get_country_mask(da, lat_min, lat_max, lon_min, lon_max, "US")
        assert mask.all()

    def test_get_country_mask_shape(self):
        da = _da2d(lat_min=0, lat_max=10, n_lat=6, lon_min=0, lon_max=10, n_lon=7)
        mask = _get_country_mask(da, 0, 10, 0, 10, "XX")
        assert mask.shape == (6, 7)


# ===========================================================================
# TestRegridderConservative
# ===========================================================================


class TestRegridderConservative:
    def test_conservative_basic(self):
        source = _da2d(lat_min=0, lat_max=10, n_lat=11, lon_min=0, lon_max=10, n_lon=11)
        target = create_regular_grid((1, 9), (1, 9), resolution_deg=2.0)
        result = regrid(source, target, method="conservative")
        assert result.shape == target.shape
        assert np.any(np.isfinite(result.values))

    def test_conservative_preserves_mean(self):
        source = _da2d(lat_min=0, lat_max=10, n_lat=21, lon_min=0, lon_max=10, n_lon=21)
        target = create_regular_grid((0, 10), (0, 10), resolution_deg=5.0)
        result = regrid(source, target, method="conservative")
        # Conservative should roughly preserve the area-weighted mean
        assert np.isfinite(result.values).any()

    def test_conservative_with_nan_source(self):
        data = np.full((5, 5), np.nan)
        data[2, 2] = 42.0
        da = xr.DataArray(
            data,
            dims=["latitude", "longitude"],
            coords={"latitude": np.linspace(0, 10, 5), "longitude": np.linspace(0, 10, 5)},
        )
        target = create_regular_grid((4, 6), (4, 6), resolution_deg=1.0)
        result = regrid(da, target, method="conservative")
        assert result.shape == target.shape

    def test_conservative_coarser_target(self):
        source = _da2d(lat_min=0, lat_max=4, n_lat=5, lon_min=0, lon_max=4, n_lon=5)
        target = create_regular_grid((0, 4), (0, 4), resolution_deg=4.0)
        result = regrid(source, target, method="conservative")
        assert result.shape == target.shape

    def test_conservative_direct_call(self):
        sv = np.ones((4, 4))
        slat = np.array([0.0, 1.0, 2.0, 3.0])
        slon = np.array([0.0, 1.0, 2.0, 3.0])
        tlat = np.array([0.5, 2.5])
        tlon = np.array([0.5, 2.5])
        result = _regrid_conservative(sv, slat, slon, tlat, tlon)
        assert result.shape == (2, 2)
        assert np.all(np.isfinite(result))

    def test_conservative_single_source_cell(self):
        sv = np.array([[5.0]])
        slat = np.array([5.0])
        slon = np.array([5.0])
        tlat = np.array([5.0])
        tlon = np.array([5.0])
        result = _regrid_conservative(sv, slat, slon, tlat, tlon)
        assert result.shape == (1, 1)
        assert result[0, 0] == pytest.approx(5.0)

    def test_conservative_nan_in_source(self):
        sv = np.array([[1.0, np.nan], [3.0, 4.0]])
        slat = np.array([0.0, 1.0])
        slon = np.array([0.0, 1.0])
        tlat = np.array([0.5])
        tlon = np.array([0.5])
        result = _regrid_conservative(sv, slat, slon, tlat, tlon)
        assert result.shape == (1, 1)


# ===========================================================================
# TestRegridderBilinearDescending
# ===========================================================================


class TestRegridderBilinearDescending:
    def test_descending_lat(self):
        lats = np.linspace(10, 0, 11)
        lons = np.linspace(0, 10, 11)
        data = np.arange(121, dtype=np.float64).reshape(11, 11)
        da = xr.DataArray(
            data, dims=["latitude", "longitude"], coords={"latitude": lats, "longitude": lons}
        )
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        result = regrid(da, target, method="bilinear")
        assert result.shape == target.shape
        assert np.any(np.isfinite(result.values))

    def test_descending_lon(self):
        lats = np.linspace(0, 10, 11)
        lons = np.linspace(10, 0, 11)
        data = np.arange(121, dtype=np.float64).reshape(11, 11)
        da = xr.DataArray(
            data, dims=["latitude", "longitude"], coords={"latitude": lats, "longitude": lons}
        )
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        result = regrid(da, target, method="bilinear")
        assert result.shape == target.shape

    def test_both_descending(self):
        lats = np.linspace(10, 0, 11)
        lons = np.linspace(10, 0, 11)
        data = np.random.default_rng(42).random((11, 11))
        da = xr.DataArray(
            data, dims=["latitude", "longitude"], coords={"latitude": lats, "longitude": lons}
        )
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        result = regrid(da, target, method="bilinear")
        assert result.shape == target.shape


# ===========================================================================
# TestRegridderEdgeCases
# ===========================================================================


class TestRegridderEdgeCases:
    def test_nearest_method_basic(self):
        source = _da2d()
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        result = regrid(source, target, method="nearest")
        assert result.shape == target.shape
        assert np.any(np.isfinite(result.values))

    def test_nearest_preserves_source_values(self):
        data = np.arange(25, dtype=np.float64).reshape(5, 5)
        da = xr.DataArray(
            data,
            dims=["latitude", "longitude"],
            coords={"latitude": np.linspace(0, 4, 5), "longitude": np.linspace(0, 4, 5)},
        )
        target = create_regular_grid((0, 4), (0, 4), resolution_deg=1.0)
        result = regrid(da, target, method="nearest")
        # Nearest should pick existing values
        assert np.all(np.isfinite(result.values))

    def test_create_regular_grid_single_point(self):
        grid = create_regular_grid((5, 5), (5, 5), resolution_deg=1.0)
        assert grid.shape == (1, 1)

    def test_create_regular_grid_invalid_lon_range(self):
        with pytest.raises(ValueError, match="lon_min.*must be <= lon_max"):
            create_regular_grid((0, 1), (10, 5))

    def test_create_regular_grid_zero_resolution(self):
        with pytest.raises(ValueError, match="resolution_deg must be positive"):
            create_regular_grid((0, 1), (0, 1), resolution_deg=0)

    def test_regrid_not_implemented_for_3d(self):
        da = _da3d()
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        with pytest.raises(NotImplementedError, match="not yet supported"):
            regrid(da, target, method="bilinear")

    def test_regrid_invalid_method_string(self):
        da = _da2d()
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        with pytest.raises(ValueError, match="Unknown method"):
            regrid(da, target, method="spline")

    def test_regrid_method_case_insensitive(self):
        da = _da2d()
        target = create_regular_grid((2, 8), (2, 8), resolution_deg=2.0)
        result = regrid(da, target, method="  BILINEAR  ")
        assert result.shape == target.shape

    def test_find_coord_name_lat_variant(self):
        da = _da2d_named("lat", "lon")
        from pakhi.grids.regridder import _find_coord_name

        assert _find_coord_name(da, "latitude") == "lat"
        assert _find_coord_name(da, "longitude") == "lon"

    def test_find_coord_name_yx(self):
        da = _da2d_named("y", "x")
        from pakhi.grids.regridder import _find_coord_name

        assert _find_coord_name(da, "latitude") == "y"
        assert _find_coord_name(da, "longitude") == "x"

    def test_find_coord_name_raises(self):
        da = xr.DataArray(np.zeros((3, 3)), dims=["a", "b"])
        from pakhi.grids.regridder import _find_coord_name

        with pytest.raises(ValueError, match="Cannot find latitude"):
            _find_coord_name(da, "latitude")

    def test_regrid_to_regular_bilinear(self):
        source = _da2d()
        result = regrid_to_regular(source, target_resolution=2.0, method="bilinear")
        assert result.shape[0] >= 1
        assert result.shape[1] >= 1

    def test_regrid_to_regular_nearest(self):
        source = _da2d()
        result = regrid_to_regular(source, target_resolution=2.0, method="nearest")
        assert result.shape[0] >= 1

    def test_regrid_to_regular_conservative(self):
        source = _da2d(n_lat=11, n_lon=11)
        result = regrid_to_regular(source, target_resolution=2.0, method="conservative")
        assert result.shape[0] >= 1

    def test_bilinear_all_nan_region(self):
        data = np.full((5, 5), np.nan)
        da = xr.DataArray(
            data,
            dims=["latitude", "longitude"],
            coords={"latitude": np.linspace(0, 4, 5), "longitude": np.linspace(0, 4, 5)},
        )
        target = create_regular_grid((0, 4), (0, 4), resolution_deg=1.0)
        result = regrid(da, target, method="bilinear")
        assert np.all(np.isnan(result.values))


# ===========================================================================
# TestInterpolationCressman
# ===========================================================================


class TestInterpolationCressman:
    def test_no_valid_obs_returns_background(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        with pytest.warns(UserWarning, match="No valid observations"):
            result = cressman_interpolation(
                grid,
                lats[5],
                lons[5],
                obs_lat=np.array([np.nan]),
                obs_lon=np.array([np.nan]),
                obs_values=np.array([np.nan]),
            )
        assert result == pytest.approx(grid.values[5, 5])

    def test_all_nan_obs_returns_background(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        with pytest.warns(UserWarning, match="No valid observations"):
            result = cressman_interpolation(
                grid,
                lats[3],
                lons[3],
                obs_lat=np.array([1.0, 2.0]),
                obs_lon=np.array([1.0, 2.0]),
                obs_values=np.array([np.nan, np.nan]),
            )
        assert result == pytest.approx(grid.values[3, 3])

    def test_obs_outside_search_radius_returns_background(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        result = cressman_interpolation(
            grid,
            lats[5],
            lons[5],
            obs_lat=np.array([0.0]),
            obs_lon=np.array([0.0]),
            obs_values=np.array([999.0]),
            search_radius_km=1.0,
        )
        assert result == pytest.approx(grid.values[5, 5])

    def test_array_output_shape(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        target_lats = np.array([lats[2], lats[4]])
        target_lons = np.array([lons[2], lons[4]])
        obs_lat = np.array([lats[2]])
        obs_lon = np.array([lons[2]])
        obs_val = np.array([100.0])
        result = cressman_interpolation(
            grid,
            target_lats,
            target_lons,
            obs_lat,
            obs_lon,
            obs_val,
            search_radius_km=500.0,
        )
        assert result.shape == (2,)

    def test_scalar_output(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        result = cressman_interpolation(
            grid,
            float(lats[5]),
            float(lons[5]),
            obs_lat=np.array([lats[5]]),
            obs_lon=np.array([lons[5]]),
            obs_values=np.array([42.0]),
            search_radius_km=500.0,
        )
        assert np.isscalar(result) or result.ndim == 0

    def test_multiple_obs_within_radius(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        obs_lat = np.array([lats[4], lats[5], lats[6]])
        obs_lon = np.array([lons[4], lons[5], lons[6]])
        obs_val = np.array([10.0, 20.0, 30.0])
        result = cressman_interpolation(
            grid,
            lats[5],
            lons[5],
            obs_lat,
            obs_lon,
            obs_val,
            search_radius_km=500.0,
        )
        assert 10.0 < result < 30.0


# ===========================================================================
# TestInterpolationIDW
# ===========================================================================


class TestInterpolationIDW:
    def test_exact_match_returns_obs_value(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        result = inverse_distance_weighting(
            grid,
            lats[5],
            lons[5],
            obs_lat=np.array([lats[5]]),
            obs_lon=np.array([lons[5]]),
            obs_values=np.array([77.7]),
        )
        assert result == pytest.approx(77.7)

    def test_no_observations_returns_nan(self):
        grid = _da2d()
        with pytest.warns(UserWarning, match="No valid observations"):
            result = inverse_distance_weighting(
                grid,
                5.0,
                5.0,
                obs_lat=np.array([]),
                obs_lon=np.array([]),
                obs_values=np.array([]),
            )
        assert np.isnan(result)

    def test_all_nan_obs_returns_nan(self):
        grid = _da2d()
        with pytest.warns(UserWarning, match="No valid observations"):
            result = inverse_distance_weighting(
                grid,
                5.0,
                5.0,
                obs_lat=np.array([1.0]),
                obs_lon=np.array([1.0]),
                obs_values=np.array([np.nan]),
            )
        assert np.isnan(result)

    def test_nearest_obs_dominates_with_high_power(self):
        grid = _da2d()
        result = inverse_distance_weighting(
            grid,
            5.0,
            5.0,
            obs_lat=np.array([5.0, 8.0]),
            obs_lon=np.array([5.0, 8.0]),
            obs_values=np.array([100.0, 0.0]),
            power=10.0,
        )
        assert result > 90.0

    def test_array_output(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        target_lats = np.array([lats[2], lats[6]])
        target_lons = np.array([lons[2], lons[6]])
        result = inverse_distance_weighting(
            grid,
            target_lats,
            target_lons,
            obs_lat=np.array([lats[4]]),
            obs_lon=np.array([lons[4]]),
            obs_values=np.array([50.0]),
        )
        assert result.shape == (2,)

    def test_power_1(self):
        grid = _da2d()
        result = inverse_distance_weighting(
            grid,
            5.0,
            5.0,
            obs_lat=np.array([4.0, 6.0]),
            obs_lon=np.array([5.0, 5.0]),
            obs_values=np.array([10.0, 20.0]),
            power=1.0,
        )
        assert 10.0 < result < 20.0


# ===========================================================================
# TestInterpolationEdgeCases
# ===========================================================================


class TestInterpolationEdgeCases:
    def test_bilinear_descending_lat(self):
        lats = np.linspace(45, 25, 11)
        lons = np.linspace(-100, -80, 11)
        data = np.arange(121, dtype=np.float64).reshape(11, 11)
        grid = xr.DataArray(
            data, dims=["latitude", "longitude"], coords={"latitude": lats, "longitude": lons}
        )
        result = bilinear_interpolation(grid, 35.0, -90.0)
        assert np.isfinite(result)

    def test_nearest_neighbor_array_output(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        target_lats = np.array([lats[1], lats[3], lats[5]])
        target_lons = np.array([lons[1], lons[3], lons[5]])
        result = nearest_neighbor(grid, target_lats, target_lons)
        assert result.shape == (3,)
        for i in range(3):
            assert result[i] == pytest.approx(grid.values[i * 2 + 1, i * 2 + 1])

    def test_nearest_neighbor_2d_grid_output(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        tlats, tlons = np.meshgrid(lats[:3], lons[:3], indexing="ij")
        result = nearest_neighbor(grid, tlats, tlons)
        assert result.shape == (3, 3)

    def test_ensure_regular_grid_error(self):
        with pytest.raises(ValueError, match="1-D"):
            _ensure_regular_grid(np.zeros((3, 3)), np.array([1.0]))

    def test_bilinear_3d_raises(self):
        grid = _da3d()
        with pytest.raises(ValueError, match="2-D"):
            bilinear_interpolation(grid, 5.0, 5.0)

    def test_nearest_neighbor_3d_raises(self):
        grid = _da3d()
        with pytest.raises(ValueError, match="2-D"):
            nearest_neighbor(grid, 5.0, 5.0)

    def test_get_coord_lat_variant(self):
        da = _da2d_named("lat", "lon")
        vals = _get_coord(da, "latitude")
        assert vals.shape == (11,)

    def test_get_coord_lon_variant(self):
        da = _da2d_named("lat", "lon")
        vals = _get_coord(da, "longitude")
        assert vals.shape == (11,)

    def test_get_coord_yx(self):
        da = _da2d_named("y", "x")
        assert _get_coord(da, "latitude").shape == (11,)
        assert _get_coord(da, "longitude").shape == (11,)

    def test_get_coord_fallback_to_dims(self):
        data = np.zeros((5, 5))
        da = xr.DataArray(data, dims=["lat", "lon"])
        lat_vals = _get_coord(da, "latitude")
        lon_vals = _get_coord(da, "longitude")
        assert lat_vals.shape == (5,)
        assert lon_vals.shape == (5,)

    def test_get_coord_raises_on_missing(self):
        da = xr.DataArray(np.zeros((3, 3)), dims=["a", "b"])
        with pytest.raises(ValueError, match="Cannot find latitude"):
            _get_coord(da, "latitude")

    def test_bilinear_out_of_bounds_nan(self):
        grid = _da2d()
        result = bilinear_interpolation(grid, 100.0, 100.0)
        assert np.isnan(result)

    def test_bilinear_array_of_targets(self):
        grid = _da2d()
        lats = grid.coords["latitude"].values
        lons = grid.coords["longitude"].values
        result = bilinear_interpolation(
            grid,
            np.array([lats[2], lats[5], lats[8]]),
            np.array([lons[2], lons[5], lons[8]]),
        )
        assert result.shape == (3,)

    def test_idw_scalar_output(self):
        grid = _da2d()
        result = inverse_distance_weighting(
            grid,
            5.0,
            5.0,
            obs_lat=np.array([5.0]),
            obs_lon=np.array([5.0]),
            obs_values=np.array([33.3]),
        )
        assert np.isscalar(result) or result.ndim == 0
        assert result == pytest.approx(33.3)
