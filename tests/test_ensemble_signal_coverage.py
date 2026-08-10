from pakhi.signals.base import Action
from pakhi.signals.ensemble_signal import EnsembleSignal


def test_ensemble_signal_direction_flat():
    val = EnsembleSignal._direction_value(Action.FLAT)
    assert val == 0.0
