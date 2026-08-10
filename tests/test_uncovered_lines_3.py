import numpy as np

import pakhi.targets.precipitation as precip
from pakhi.targets.hurricane import saffir_simpson
from pakhi.targets.solar import clear_sky_radiation
from pakhi.targets.temperature import heat_index


def test_saffir_simpson_extreme():
    # 75: wind_kt > 136 (252 km/h), pmax=0 -> returns 5
    assert saffir_simpson(900, 300) == 5


def test_precipitation_spi():
    # 145: return 0.0 when len(cumul) < 2
    # So array length = window_days (30)
    assert precip.drought_index(np.ones(30), window_days=30) == 0.0

    # 168-169: p < 0.5
    # Make the last element very small so cumul[-1] is small
    arr = np.ones(100)
    arr[-30:] = 0.0001
    res = precip.drought_index(arr, window_days=30)
    assert res < 0


def test_solar_clear_sky():
    # 164: G0 <= 0 (zenith >= 90)
    assert clear_sky_radiation(95.0, 0, 0.1) == 0.0


def test_heat_index_low_rh():
    # 149-150: RH < 13.0 and 80 <= Tf <= 112
    # Tf = 95F = 35C, RH = 10.0
    res = heat_index(35.0, 10.0)
    assert res is not None
