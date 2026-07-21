"""Signal generation module — weather-driven trading signals.

Submodules
----------
base
    Signal dataclass, BaseSignal ABC, and Kelly criterion position sizing.
freeze
    Orange juice freeze event signals.
heat
    Power market heatwave demand signals.
hurricane
    Natural gas hurricane shut-in signals.
drought
    Grain and water futures drought signals.
wind_power
    Electricity market wind generation signals.
ensemble_signal
    Correlation-adjusted ensemble combiner for multiple signals.
"""

from __future__ import annotations

from pakhi.signals.base import Action, BaseSignal, Signal, position_size
from pakhi.signals.drought import DroughtSignal
from pakhi.signals.ensemble_signal import EnsembleSignal
from pakhi.signals.freeze import FreezeSignal
from pakhi.signals.heat import PowerSignal
from pakhi.signals.hurricane import HurricaneSignal
from pakhi.signals.wind_power import WindPowerSignal

__all__ = [
    "Action",
    "BaseSignal",
    "DroughtSignal",
    "EnsembleSignal",
    "FreezeSignal",
    "HurricaneSignal",
    "PowerSignal",
    "Signal",
    "WindPowerSignal",
    "position_size",
]
