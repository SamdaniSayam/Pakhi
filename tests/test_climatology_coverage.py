import numpy as np

from pakhi.models.climatology import ClimatologyModel


def test_climatology_extract_doy():
    kwargs = {"day_of_year": [1, 2, 3]}
    X = np.zeros((3, 2))
    doy = ClimatologyModel._extract_doy(kwargs, X)
    assert np.array_equal(doy, [1, 2, 3])
    assert "day_of_year" not in kwargs


def test_climatology_extract_doy_default():
    kwargs = {}
    X = np.zeros((4, 2))
    doy = ClimatologyModel._extract_doy(kwargs, X)
    assert np.array_equal(doy, [1, 2, 3, 4])
