import numpy as np
import pytest

import pakhi.viz.maps as maps
from pakhi.viz.maps import plot_forecast_map, plot_track


def test_maps_has_cartopy(monkeypatch):
    monkeypatch.setattr(maps, "_HAS_CARTOPY", True)

    # We also need to mock cartopy if it's not installed
    import sys
    from unittest.mock import MagicMock

    with pytest.MonkeyPatch.context() as m:
        # Mock cartopy.crs and cartopy.feature
        m.setitem(sys.modules, "cartopy", MagicMock())
        m.setitem(sys.modules, "cartopy.crs", MagicMock())
        m.setitem(sys.modules, "cartopy.feature", MagicMock())

        # We have to also patch ccrs and cfeature inside maps
        monkeypatch.setattr(maps, "ccrs", sys.modules["cartopy.crs"], raising=False)
        monkeypatch.setattr(maps, "cfeature", sys.modules["cartopy.feature"], raising=False)

        # Mock Figure to avoid matplotlib trying to interpret the mock projection
        mock_fig = MagicMock()
        mock_ax = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        monkeypatch.setattr(maps, "Figure", lambda **kwargs: mock_fig)

        data = np.random.rand(10, 10)
        plot_forecast_map(data)

        cone_lats = np.array([1, 2, 3])
        cone_lons = np.array([1, 2, 3])
        track_lats = np.array([1, 2])
        track_lons = np.array([1, 2])
        plot_track(cone_lats, cone_lons, track_lats, track_lons)
