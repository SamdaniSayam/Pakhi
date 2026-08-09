import pytest
from pakhi.signals.ensemble_signal import EnsembleSignal
from pakhi.signals.base import Action

def test_ensemble_signal_direction_flat():
    val = EnsembleSignal._direction_value(Action.FLAT)
    assert val == 0.0
