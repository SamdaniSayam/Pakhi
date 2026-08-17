"""Wind-derived target variables for weather quant trading.

Implements wind power curves (multi-turbine), farm-level power forecast,
Beaufort scale, and wind vector decomposition.

References:
    - IEC 61400-12-1: Wind turbine power performance testing.
    - Holland (1980): "An Analytic Model of the Wind and Pressure Profiles
      in Hurricanes." Mon. Wea. Rev. 108, 1212–1218.
    - Beaufort Scale: https://en.wikipedia.org/wiki/Beaufort_scale
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

__all__ = [
    "beaufort_scale",
    "power_curve",
    "wind_direction_components",
    "wind_power_forecast",
]

TurbineType = Literal["vestas_v110", "vestas_v90", "siemens_swift", "generic_2mw"]

# Turbine specifications: (rated_power_MW, cut_in_ms, rated_speed_ms, cut_out_ms, rotor_diameter_m)
_TURBINE_DB: dict[str, tuple[float, float, float, float, float]] = {
    "vestas_v110": (2.0, 3.0, 12.0, 25.0, 110.0),
    "vestas_v90": (2.0, 4.0, 12.0, 25.0, 90.0),
    "siemens_swift": (3.0, 3.5, 13.0, 25.0, 101.0),
    "generic_2mw": (2.0, 3.0, 12.0, 25.0, 80.0),
}


def power_curve(
    wind_speed: float | np.ndarray,
    turbine: TurbineType = "vestas_v110",
    hub_height_m: float = 80.0,
) -> float | np.ndarray:
    """Compute electrical power output from a wind turbine power curve.

    Uses the standard cubic relationship between wind speed and available
    power in the rated region, with linear interpolation between cut-in and
    rated speeds.

    Parameters
    ----------
    wind_speed : float or array-like
        Wind speed in m/s at the given hub height.
    turbine : str
        Turbine model identifier.
    hub_height_m : float
        Hub height in metres.  If different from the turbine's design hub
        height the wind speed is extrapolated via the log wind profile
        (roughness length 0.03 m assumed for open terrain).

    Returns
    -------
    float or np.ndarray
        Power output in MW.

    References
    ----------
    .. [1] Manwell, J. F., McGowan, J. G. & Rogers, A. L. (2009).
           "Wind Energy Explained: Theory, Design and Application."
           2nd ed., Wiley, Ch. 3.
    """
    spec = _TURBINE_DB.get(turbine)
    if spec is None:
        raise ValueError(f"Unknown turbine {turbine!r}. Choose from {list(_TURBINE_DB)}")
    rated_mw, v_cutin, v_rated, v_cutout, _rotor_d = spec

    # Height extrapolation (log profile, z0 = 0.03 m)
    z0 = 0.03
    design_hub = 80.0  # reference height for the specs above
    ws = np.asarray(wind_speed, dtype=np.float64)
    if hub_height_m != design_hub and hub_height_m > 0:
        ratio = math.log(hub_height_m / z0) / math.log(design_hub / z0)
        ws = ws / ratio

    # Vectorised power curve
    power = np.zeros_like(ws, dtype=np.float64)

    # Ramp region
    ramp = (ws >= v_cutin) & (ws < v_rated)
    # Rated region
    rated = (ws >= v_rated) & (ws <= v_cutout)

    power[ramp] = rated_mw * ((ws[ramp] - v_cutin) / (v_rated - v_cutin)) ** 3
    power[rated] = rated_mw
    # above and below remain 0

    # Return scalar if scalar input
    if np.ndim(wind_speed) == 0:
        return float(power.item())
    return power


def wind_power_forecast(
    power_per_turbine: float | np.ndarray,
    farm_capacity_mw: float,
    n_turbines: int,
) -> float:
    """Aggregate individual turbine power to farm-level output.

    Applies a wake-loss derating factor (roughly 70–85 % for a well-spaced
    onshore farm) and clips to the installed capacity.

    Parameters
    ----------
    power_per_turbine : float or array-like
        Power per turbine in MW (may be a single turbine's forecast or an
        array of per-turbine values).
    farm_capacity_mw : float
        Installed farm capacity in MW.
    n_turbines : int
        Number of turbines in the farm.

    Returns
    -------
    float
        Aggregate farm output in MW, capped at *farm_capacity_mw*.
    """
    p = np.asarray(power_per_turbine, dtype=np.float64)
    total = float(np.sum(p)) if p.ndim > 0 else float(p * n_turbines)
    # Wake loss factor (Frandsen et al. 2006 approximation)
    wake_factor = 0.78
    total *= wake_factor
    return min(total, farm_capacity_mw)


def beaufort_scale(wind_speed_ms: float) -> int:
    """Convert wind speed to the Beaufort number (0–12).

    Parameters
    ----------
    wind_speed_ms : float
        Wind speed in m/s.

    Returns
    -------
    int
        Beaufort scale number.
    """
    # Beaufort thresholds (lower bound of each class in m/s)
    thresholds: list[tuple[float, int]] = [
        (0.0, 0),
        (0.5, 1),
        (1.6, 2),
        (3.4, 3),
        (5.5, 4),
        (8.0, 5),
        (10.8, 6),
        (13.9, 7),
        (17.2, 8),
        (20.8, 9),
        (24.5, 10),
        (28.5, 11),
        (32.7, 12),
    ]
    result = 0
    for lower, bf in thresholds:
        if wind_speed_ms >= lower:
            result = bf
        else:
            break
    return result


def wind_direction_components(
    wind_speed: float | np.ndarray,
    wind_direction_deg: float | np.ndarray,
) -> tuple:
    """Decompose wind speed into zonal (u) and meridional (v) components.

    Convention: meteorological – direction *from* which the wind blows,
    0° = from North, 90° = from East.

    .. math::
        u = -V \\sin(\\theta), \\quad v = -V \\cos(\\theta)

    Parameters
    ----------
    wind_speed : float or array-like
        Wind speed in m/s.
    wind_direction_deg : float or array-like
        Wind direction in degrees (meteorological convention).

    Returns
    -------
    tuple
        (u, v) components in m/s.  Positive u is eastward; positive v is
        northward.
    """
    ws = np.asarray(wind_speed, dtype=np.float64)
    wd = np.asarray(wind_direction_deg, dtype=np.float64)
    rad = np.deg2rad(wd)
    u = -ws * np.sin(rad)
    v = -ws * np.cos(rad)
    if np.ndim(wind_speed) == 0 and np.ndim(wind_direction_deg) == 0:
        return (float(u.item()), float(v.item()))
    return (u, v)
