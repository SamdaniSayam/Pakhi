"""Instrument definitions for weather-linked futures and derivatives.

Each instrument specifies its exchange, tick size, contract size,
margin requirement, and per-contract commission.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

__all__ = [
    "CAT_BONDS",
    "CL_FUTURES",
    "ERCOT_FUTURES",
    "HE_FUTURES",
    "LE_FUTURES",
    "NG_FUTURES",
    "OJ_FUTURES",
    "PJM_FUTURES",
    "ZC_FUTURES",
    "ZS_FUTURES",
    "ZW_FUTURES",
    "Instrument",
    "get_instrument",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Instrument:
    """Specification of a tradeable instrument.

    Attributes
    ----------
    name : str
        Human-readable name (e.g. ``"Orange Juice Futures"``).
    exchange : str
        Exchange or market identifier (e.g. ``"ICE"``, ``"NYMEX"``).
    tick_size : float
        Minimum price increment.
    contract_size : float
        Units of underlying per one contract.
    margin_requirement : float
        Initial margin as a fraction of notional (e.g. ``0.08`` = 8%).
    commission_per_contract : float
        Flat commission in USD per contract per side.
    """

    name: str
    exchange: str
    tick_size: float
    contract_size: float
    margin_requirement: float
    commission_per_contract: float


# ---------------------------------------------------------------------------
# Instrument catalogue
# ---------------------------------------------------------------------------

OJ_FUTURES = Instrument(
    name="Orange Juice Futures",
    exchange="ICE",
    tick_size=0.05,
    contract_size=15_000,  # pounds
    margin_requirement=0.10,
    commission_per_contract=2.50,
)

NG_FUTURES = Instrument(
    name="Natural Gas Futures",
    exchange="NYMEX",
    tick_size=0.001,
    contract_size=10_000,  # MMBtu
    margin_requirement=0.08,
    commission_per_contract=1.25,
)

CL_FUTURES = Instrument(
    name="Crude Oil WTI Futures",
    exchange="NYMEX",
    tick_size=0.01,
    contract_size=1_000,  # barrels
    margin_requirement=0.07,
    commission_per_contract=1.50,
)

ZC_FUTURES = Instrument(
    name="Corn Futures",
    exchange="CBOT",
    tick_size=0.25,
    contract_size=5_000,  # bushels
    margin_requirement=0.06,
    commission_per_contract=1.25,
)

ZS_FUTURES = Instrument(
    name="Soybean Futures",
    exchange="CBOT",
    tick_size=0.25,
    contract_size=5_000,  # bushels
    margin_requirement=0.07,
    commission_per_contract=1.25,
)

ZW_FUTURES = Instrument(
    name="Wheat Futures",
    exchange="CBOT",
    tick_size=0.25,
    contract_size=5_000,  # bushels
    margin_requirement=0.06,
    commission_per_contract=1.25,
)

HE_FUTURES = Instrument(
    name="Lean Hogs Futures",
    exchange="CME",
    tick_size=0.025,
    contract_size=40_000,  # pounds
    margin_requirement=0.08,
    commission_per_contract=1.75,
)

LE_FUTURES = Instrument(
    name="Live Cattle Futures",
    exchange="CME",
    tick_size=0.025,
    contract_size=40_000,  # pounds
    margin_requirement=0.07,
    commission_per_contract=1.75,
)

ERCOT_FUTURES = Instrument(
    name="ERCOT Power Futures",
    exchange="ERCOT",
    tick_size=0.01,
    contract_size=1_000,  # MWh
    margin_requirement=0.10,
    commission_per_contract=3.00,
)

PJM_FUTURES = Instrument(
    name="PJM Power Futures",
    exchange="PJM",
    tick_size=0.01,
    contract_size=1_000,  # MWh
    margin_requirement=0.10,
    commission_per_contract=3.00,
)

CAT_BONDS = Instrument(
    name="Catastrophe Bond Index",
    exchange="OTC",
    tick_size=0.001,
    contract_size=100_000,  # notional USD
    margin_requirement=0.15,
    commission_per_contract=10.00,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_INSTRUMENTS: dict[str, Instrument] = {
    "OJ_FUTURES": OJ_FUTURES,
    "NG_FUTURES": NG_FUTURES,
    "CL_FUTURES": CL_FUTURES,
    "ZC_FUTURES": ZC_FUTURES,
    "ZS_FUTURES": ZS_FUTURES,
    "ZW_FUTURES": ZW_FUTURES,
    "HE_FUTURES": HE_FUTURES,
    "LE_FUTURES": LE_FUTURES,
    "ERCOT_FUTURES": ERCOT_FUTURES,
    "PJM_FUTURES": PJM_FUTURES,
    "CAT_BONDS": CAT_BONDS,
}


def get_instrument(name: str) -> Instrument:
    """Look up an instrument by its ticker key.

    Parameters
    ----------
    name : str
        Instrument key, e.g. ``"OJ_FUTURES"``.

    Returns
    -------
    Instrument

    Raises
    ------
    KeyError
        If the instrument key is not found.
    """
    key = name.upper().replace(" ", "_").replace("-", "_")
    if key not in _INSTRUMENTS:
        available = ", ".join(sorted(_INSTRUMENTS.keys()))
        raise KeyError(f"Unknown instrument '{name}'. Available: {available}")
    return _INSTRUMENTS[key]
