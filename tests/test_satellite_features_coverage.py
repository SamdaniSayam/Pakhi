import pytest
import numpy as np
from pakhi.features.satellite import SatelliteFeatures

def test_cloud_motion_vectors_ndarray():
    # 86-90: np.ndarray input
    # 127: search_area smaller than patch
    ir_images = np.random.rand(2, 20, 20)
    # search_window=9 means patch is 19x19, search area is 39x39, but since image is 20x20
    # search area will be truncated and be smaller than expected, possibly smaller than patch1.
    res = SatelliteFeatures.cloud_motion_vectors(
        ir_images, time_delta_minutes=15, search_window=9
    )
    assert res is not None

def test_brightness_temp_ndarray():
    val = SatelliteFeatures.brightness_temperature(np.array([1000.0, 2000.0]), 2)
    assert val is not None

def test_cloud_fraction_ndarray():
    val = SatelliteFeatures.cloud_fraction(np.array([[250.0, 270.0]]), threshold_k=260.0)
    assert val == 0.5
