import numpy as np
import xarray as xr

from pakhi.src.satellite import GOESConnector


def test_satellite_open_netcdf_scale():
    goes = GOESConnector()
    # create dummy netcdf in memory
    bt = xr.DataArray(
        np.array([1, 2]),
        name="brightness_temperature",
        attrs={"scale_factor": 2.0, "add_offset": 5.0},
    )
    ds = xr.Dataset({"brightness_temperature": bt})

    import pathlib

    # mock xr.open_dataset
    import unittest.mock

    with unittest.mock.patch("xarray.open_dataset", return_value=ds):
        res = goes._open_netcdf(pathlib.Path("dummy.nc"))
        assert res["brightness_temperature"].values[0] == 7.0  # 1 * 2 + 5


def test_satellite_cloud_motion_squeeze_and_shape(monkeypatch):
    goes = GOESConnector(bands=["band_13"])

    images_loaded = 0

    def mock_download(*args, **kwargs):
        nonlocal images_loaded
        images_loaded += 1
        return "dummy.nc"

    def mock_open(*args, **kwargs):
        # We need two images.
        # First image is shape (32, 32)
        # Second image is shape (16, 16) - to trigger `continue` on line 369
        # But wait, line 295 is ndim > 2. So let's make the first one (1, 32, 32)
        if images_loaded == 1:
            arr = np.random.rand(1, 32, 32)
        else:
            arr = np.random.rand(16, 16)
        return xr.Dataset({"brightness_temperature": xr.DataArray(arr)})

    monkeypatch.setattr(goes, "_find_latest_file", lambda *a, **kw: "dummy.nc")
    monkeypatch.setattr(goes, "_download_s3_file", mock_download)
    monkeypatch.setattr(goes, "_open_netcdf", mock_open)

    ds = goes.cloud_motion(minutes=15)
    # The first image (prev) will be 32x32, target will be 16x16, hitting continue
    assert "u_cloud_motion" in ds
