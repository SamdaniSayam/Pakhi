"""WS-1 evaluation instrument & signal-class registry — Contract V2 (DRAFT).

This module is the *code* twin of ``data/ws1/evaluation_contract_v2.json``. It
defines the multi-instrument expansion (S1) and the empirical-median threshold
mechanism **without hardcoding any threshold float**.

Each signal class declares a *mechanism* (e.g. ``theta = median of the
train-fold distribution``) that the harness resolves per fold at evaluation
time (Phases 1B-1D). Only fixed physical / geographic constants are literal
here — that is the entire point of the pre-registration discipline.

Status: DRAFT. Do not hash-lock until Phases 1A-1D are implemented and the
mechanism is verified clean of lookahead on historical folds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pakhi.trading.instruments import get_instrument

__all__ = [
    "SignalClass",
    "EvaluationInstrument",
    "SignalClassDef",
    "INSTRUMENTS",
    "SIGNAL_CLASSES",
    "YAHOO_TICKERS",
    "get_instrument_def",
    "get_signal_class",
    "price_source_for",
]

SignalClass = Literal["ColdGrip", "DroughtGrip", "StormGrip", "HeatGrip"]


@dataclass(frozen=True)
class EvaluationInstrument:
    """An instrument evaluated under Contract V2.

    ``price_source`` is where market data comes from (Yahoo for liquid
    futures; ERCOT requires a settlement feed). ``weather_source`` is where
    the weather feature comes from (always the as-published GFS archive).
    ``trading_key`` links to ``pakhi.trading.instruments`` for exchange / tick
    / margin specs so those are never duplicated here.
    """

    key: str
    ticker: str
    signal_class: SignalClass
    weather_var: str
    region: str
    price_source: str
    weather_source: str
    trading_key: str
    baseline: bool = False


@dataclass(frozen=True)
class SignalClassDef:
    """A Grip candidate signal class.

    ``theta_mechanism`` documents how each free parameter is resolved at
    evaluation time (per train fold, never from the test window). Only
    ``fixed_constants`` are literal — these are physical / geographic facts,
    not fitted values.
    """

    name: SignalClass
    fire_expr: str
    theta_mechanism: dict[str, str]
    fixed_constants: dict[str, float]


# ---------------------------------------------------------------------------
# Instrument registry (S1 multi-instrument expansion)
# ---------------------------------------------------------------------------

INSTRUMENTS: dict[str, EvaluationInstrument] = {
    "OJ": EvaluationInstrument(
        key="OJ",
        ticker="OJ=F",
        signal_class="ColdGrip",
        weather_var="freeze_prob",
        region="Florida citrus belt",
        price_source="yahoo",
        weather_source="noaa-gfs-bdp-pds",
        trading_key="OJ_FUTURES",
        baseline=True,
    ),
    "Corn": EvaluationInstrument(
        key="Corn",
        ticker="ZC=F",
        signal_class="DroughtGrip",
        weather_var="spi_30d",
        region="US Corn Belt [-104,36,-80,48]",
        price_source="yahoo",
        weather_source="noaa-gfs-bdp-pds",
        trading_key="ZC_FUTURES",
    ),
    "NatGas": EvaluationInstrument(
        key="NatGas",
        ticker="NG=F",
        signal_class="StormGrip",
        weather_var="hurricane_prob",
        region="Gulf of Mexico",
        price_source="yahoo",
        weather_source="noaa-gfs-bdp-pds",
        trading_key="NG_FUTURES",
    ),
    "Wheat": EvaluationInstrument(
        key="Wheat",
        ticker="ZW=F",
        signal_class="DroughtGrip",
        weather_var="spi_30d",
        region="Great Plains wheat [-104,32,-96,48]",
        price_source="yahoo",
        weather_source="noaa-gfs-bdp-pds",
        trading_key="ZW_FUTURES",
    ),
    "ERCOT": EvaluationInstrument(
        key="ERCOT",
        ticker="ERCOT_POWER",
        signal_class="HeatGrip",
        weather_var="cdd_3day",
        region="Texas (ERCOT)",
        price_source="ercot_settlement",
        weather_source="noaa-gfs-bdp-pds",
        trading_key="ERCOT_FUTURES",
    ),
}

# ---------------------------------------------------------------------------
# Signal-class (Grip candidate) registry
# ---------------------------------------------------------------------------

SIGNAL_CLASSES: dict[SignalClass, SignalClassDef] = {
    "ColdGrip": SignalClassDef(
        name="ColdGrip",
        fire_expr="freeze_prob >= theta_p AND temperature_min <= theta_t",
        theta_mechanism={
            "theta_p": "median freeze_prob over TRAIN-window freeze rows (per fold)",
            "theta_t": "fixed 0.0 C (physical freeze definition)",
        },
        fixed_constants={"theta_t": 0.0},
    ),
    "DroughtGrip": SignalClassDef(
        name="DroughtGrip",
        fire_expr="spi_30d <= theta_spi AND precip_anomaly <= theta_precip",
        theta_mechanism={
            "theta_spi": "median SPI over TRAIN-window drought rows (per fold)",
            "theta_precip": "fixed 0.0 (anomaly <= 0 means dry)",
        },
        fixed_constants={"theta_precip": 0.0},
    ),
    "StormGrip": SignalClassDef(
        name="StormGrip",
        fire_expr="hurricane_prob >= theta_h AND gulf_proximity_km <= 320",
        theta_mechanism={
            "theta_h": "median of TRAIN-fold hurricane_prob distribution (per fold)",
        },
        fixed_constants={"gulf_proximity_km": 320.0},
    ),
    "HeatGrip": SignalClassDef(
        name="HeatGrip",
        fire_expr="cdd_3day >= theta_cdd AND temperature_max_C >= 38",
        theta_mechanism={
            "theta_cdd": "median of TRAIN-fold cdd_3day distribution (per fold)",
        },
        fixed_constants={"temperature_max_C": 38.0},
    ),
}

# Yahoo-sourced instruments — the only ones the Phase 1A downloader can fetch.
YAHOO_TICKERS: dict[str, str] = {
    key: inst.ticker for key, inst in INSTRUMENTS.items() if inst.price_source == "yahoo"
}


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_instrument_def(key: str) -> EvaluationInstrument:
    """Return the evaluation instrument definition for ``key`` (e.g. ``"OJ"``)."""
    if key not in INSTRUMENTS:
        available = ", ".join(sorted(INSTRUMENTS.keys()))
        raise KeyError(f"Unknown evaluation instrument '{key}'. Available: {available}")
    return INSTRUMENTS[key]


def get_signal_class(name: SignalClass) -> SignalClassDef:
    """Return the signal-class definition for ``name`` (e.g. ``"DroughtGrip"``)."""
    if name not in SIGNAL_CLASSES:
        available = ", ".join(sorted(SIGNAL_CLASSES.keys()))
        raise KeyError(f"Unknown signal class '{name}'. Available: {available}")
    return SIGNAL_CLASSES[name]


def price_source_for(key: str) -> str:
    """Return the market-data price source for an evaluation instrument."""
    return get_instrument_def(key).price_source
