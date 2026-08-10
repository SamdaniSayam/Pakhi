import numpy as np

from pakhi.predict.verification import _sanitize


def test_verification_sanitize_single_array():
    a = np.array([1, 2, np.nan, 4])
    res = _sanitize(a)
    assert len(res) == 3
    assert 4 in res
