"""Pressure-derived target variables for weather quant trading.

Implements Saffir–Simpson categorisation, storm surge estimation, pressure
tendency classification, and pressure gradient force.

References:
    - Saffir-Simpson Hurricane Wind Scale: https://www.nhc.noaa.gov/aboutsshws.php
    - Jelesnianski, C. P. (1990). "SPLOSH: Sea, Lake, and Overland Surges
      from Hurricanes." NOAA Technical Report NWS 44.
    - Holton, J. R. & Hakim, G. J. (2012). "An Introduction to Dynamic
      Meteorology." 5th ed., Academic Press, Ch. 3.
"""

from __future__ import annotations

import math

__all__ = [
    "central_pressure_to_category",
    "pressure_gradient_force",
    "pressure_tendency",
    "storm_surge_estimate",
]


def central_pressure_to_category(pressure_hpa: float) -> str:
    """Map tropical cyclone central pressure and wind to Saffir-Simpson category.

    This function uses **pressure** as the primary classifier following the
    operational Saffir-Simpson scale breakpoints.  For a combined wind+pressure
    classification, use *saffir_simpson* from ``pakhi.targets.hurricane``.

    Parameters
    ----------
    pressure_hpa : float
        Central sea-level pressure in hPa (mbar).

    Returns
    -------
    str
        Category string: ``"TD"``, ``"TS"``, ``"Cat1"`` – ``"Cat5"``.

    References
    ----------
    .. [1] NHC, "Saffir-Simpson Hurricane Wind Scale"
           https://www.nhc.noaa.gov/aboutsshws.php
    """
    # Pressure breakpoints (approximate operational thresholds)
    if pressure_hpa > 1009.0:
        return "TD"  # Tropical Depression (weak)
    elif pressure_hpa > 1000.0:
        return "TD"
    elif pressure_hpa > 985.0:
        return "TS"
    elif pressure_hpa > 970.0:
        return "Cat1"
    elif pressure_hpa > 955.0:
        return "Cat2"
    elif pressure_hpa > 940.0:
        return "Cat3"
    elif pressure_hpa > 920.0:
        return "Cat4"
    else:
        return "Cat5"


def storm_surge_estimate(
    central_pressure: float,
    forward_speed_kmh: float,
    coastline_slope: float,
) -> float:
    """Estimate storm surge from a tropical cyclone using a simple inverted-barometer model.

    The total surge is the sum of the *pressure surge* (inverted barometer
    effect) and a *wind-driven* component parameterised by the forward speed.

    .. math::
        \\Delta \\eta = \\frac{P_n - P_c}{\\rho g} + \\alpha \\, V_f

    where:
        - *P_n* = environmental pressure (1013.25 hPa)
        - *P_c* = central pressure (hPa)
        - *ρ* = seawater density (1025 kg/m³)
        - *g* = 9.81 m/s²
        - *α* = empirical coefficient (~0.04 m per km/h forward speed, after Jelesnianski)
        - *V_f* = forward speed of the storm

    The *coastline_slope* parameter (m/km) modulates the wind-driven component:
    shallower slopes amplify surge.

    Parameters
    ----------
    central_pressure : float
        Central pressure of the cyclone in hPa.
    forward_speed_kmh : float
        Translation speed of the storm in km/h.
    coastline_slope : float
        Bathymetric slope of the near-shore seabed in m/km (e.g. 0.05 for
        gentle shelves).

    Returns
    -------
    float
        Estimated storm surge in metres above normal tide.

    References
    ----------
    .. [1] Jelesnianski, C. P. (1990). SPLOSH, NOAA Tech. Rep. NWS 44.
    .. [2] National Hurricane Center. "Storm Surge Overview"
           https://www.nhc.noaa.gov/surge/
    """
    P_n = 1013.25  # environmental pressure (hPa)
    rho = 1025.0  # seawater density (kg/m³)
    g = 9.81  # gravitational acceleration (m/s²)
    alpha = 0.04  # empirical surge coefficient (m / (km/h))

    pressure_surge = (P_n - central_pressure) * 100.0 / (rho * g)  # Pa conversion
    slope_factor = 1.0 / max(coastline_slope, 0.01)  # gentler slope → more surge
    wind_surge = alpha * forward_speed_kmh * math.tanh(slope_factor)

    return float(pressure_surge + wind_surge)


def pressure_tendency(
    pressure_3h_ago: float,
    pressure_now: float,
) -> str:
    """Classify 3-hour pressure tendency for synoptic weather reporting.

    Follows WMO conventions for pressure change descriptions.

    Parameters
    ----------
    pressure_3h_ago : float
        Sea-level pressure 3 hours ago in hPa.
    pressure_now : float
        Current sea-level pressure in hPa.

    Returns
    -------
    str
        One of ``"rising"``, ``"falling"``, ``"steady"``.

    References
    ----------
    .. [1] WMO Manual on Codes, Vol. I.1, Code FA.
    """
    dp = pressure_now - pressure_3h_ago
    if dp > 1.0:
        return "rising"
    elif dp < -1.0:
        return "falling"
    else:
        return "steady"


def pressure_gradient_force(
    dpressure_dx: float,
    dpressure_dy: float,
    latitude: float,
) -> tuple[float, float]:
    """Compute the horizontal pressure gradient force per unit mass.

    The PGF is the primary driver of wind in the geostrophic approximation:

    .. math::
        \\text{PGF} = -\\frac{1}{\\rho} \\nabla P, \\quad
        f = 2 \\Omega \\sin \\phi

    Parameters
    ----------
    dpressure_dx : float
        Pressure gradient in the x (eastward) direction in Pa/m.
    dpressure_dy : float
        Pressure gradient in the y (northward) direction in Pa/m.
    latitude : float
        Latitude in degrees (used to compute the Coriolis parameter).

    Returns
    -------
    tuple[float, float]
        (magnitude in m/s², direction in degrees from north).

    References
    ----------
    .. [1] Holton, J. R. & Hakim, G. J. (2012). "An Introduction to Dynamic
           Meteorology." 5th ed., Academic Press.
    """
    rho = 1.225  # sea-level air density (kg/m³)
    omega = 7.2921e-5  # Earth's angular velocity (rad/s)
    lat_rad = math.radians(latitude)
    f = 2.0 * omega * math.sin(lat_rad)

    if abs(f) < 1e-10:
        # At the equator geostrophic balance breaks down
        magnitude = math.sqrt(dpressure_dx**2 + dpressure_dy**2) / rho
        direction = math.degrees(math.atan2(-dpressure_dx, -dpressure_dy)) % 360.0
        return (magnitude, direction)

    # Geostrophic wind components
    u_g = -(1.0 / (rho * f)) * dpressure_dy
    v_g = (1.0 / (rho * f)) * dpressure_dx

    magnitude = math.sqrt(u_g**2 + v_g**2)
    direction = math.degrees(math.atan2(u_g, v_g)) % 360.0

    return (magnitude, direction)
