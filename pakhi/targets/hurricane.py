"""Hurricane / tropical cyclone target variables for weather quant trading.

Implements Saffir–Simpson classification, Kaplan–DeMaria rapid intensification
probability, Holland wind profile, and hurricane rainfall accumulation.

References:
    - Saffir-Simpson: NHC, https://www.nhc.noaa.gov/aboutsshws.php
    - Kaplan, J. & DeMaria, M. (2003). "Large-Scale Characteristics of
      Rapidly Intensifying Tropical Cyclones in the Gulf of Mexico." Wea.
      Forecasting 18, 1093–1108.
    - Holland, G. J. (1980). "An Analytic Model of the Wind and Pressure
      Profiles in Hurricanes." Mon. Wea. Rev. 108, 1212–1218.
    - Rappaport, E. N. (2003). "Impact of Hurricane Forecasting on Emergency
      Management." Bull. Amer. Meteor. Soc. 84, 419–424.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "rainfall_accumulation",
    "rapid_intensification_probability",
    "saffir_simpson",
    "wind_radius_estimate",
]


def saffir_simpson(central_pressure_hpa: float, wind_speed_kmh: float) -> int:
    """Classify a tropical cyclone using the Saffir-Simpson Hurricane Wind Scale.

    Classification is based on the **maximum sustained 1-min wind speed** at
    10 m elevation.  Pressure is used as a tie-breaker for consistency with
    operational practice.

    Parameters
    ----------
    central_pressure_hpa : float
        Central sea-level pressure in hPa.
    wind_speed_kmh : float
        Maximum sustained wind speed in km/h.

    Returns
    -------
    int
        Category number (1–5).  Returns 0 for tropical depressions or storms
        that do not reach hurricane strength.

    References
    ----------
    .. [1] NHC, "Saffir-Simpson Hurricane Wind Scale"
           https://www.nhc.noaa.gov/aboutsshws.php
    """
    # Convert km/h to knots for standard thresholds
    wind_kt = wind_speed_kmh / 1.852

    if wind_kt < 64:
        return 0  # Tropical Depression / Tropical Storm

    # Hurricane categories (wind in knots)
    cats = [
        (64, 82, 980),
        (83, 95, 965),
        (96, 112, 945),
        (113, 136, 920),
        (137, 999, 0),
    ]
    for i, (_vmin, vmax, pmax) in enumerate(cats, start=1):
        if wind_kt <= vmax:
            if pmax > 0 and central_pressure_hpa > pmax:
                return max(i - 1, 1)
            return i
    return 5


def rapid_intensification_probability(
    pressure_drop_24h: float,
    sst: float,
    shear: float,
) -> float:
    """Estimate the probability of rapid intensification (RI).

    Uses the Kaplan–DeMaria (2003, 2005) logistic regression model.  RI is
    defined as an increase in maximum sustained wind of ≥ 30 kt in 24 h.

    The logistic function:

    .. math::
        P(\\text{RI}) = \\frac{1}{1 + e^{-z}}

    where:

    .. math::
        z = a + b_1 \\cdot \\Delta P_{24} + b_2 \\cdot SST + b_3 \\cdot V_{shear}

    Coefficients are empirical fits from Kaplan & DeMaria (2003).

    Parameters
    ----------
    pressure_drop_24h : float
        Observed central pressure drop in the last 24 hours (hPa, positive
        means pressure is falling).
    sst : float
        Sea surface temperature in °C beneath the storm.
    shear : float
        200–850 hPa vertical wind shear in m/s.

    Returns
    -------
    float
        Probability of RI in [0, 1].

    References
    ----------
    .. [1] Kaplan, J. & DeMaria, M. (2003). "Large-Scale Characteristics of
           Rapidly Intensifying Tropical Cyclones in the Gulf of Mexico." Wea.
           Forecasting 18, 1093–1108.
    .. [2] Kaplan, J., DeMaria, M. & Knaff, J. A. (2010). "A Revised
           Tropical Cyclone Rapid Intensification Index for the Atlantic and
           Eastern North Pacific Basins." Wea. Forecasting 25, 220–241.
    """
    # Logistic regression coefficients (Kaplan & DeMaria 2003, Table 3)
    a0 = -3.94  # intercept
    a1 = 0.14  # dP24 coefficient (hPa⁻¹)
    a2 = 0.13  # SST coefficient (°C⁻¹)
    a3 = -0.15  # shear coefficient ((m/s)⁻¹)

    z = a0 + a1 * pressure_drop_24h + a2 * sst + a3 * shear
    prob = 1.0 / (1.0 + math.exp(-z))
    return float(np.clip(prob, 0.0, 1.0))


def wind_radius_estimate(
    category: int,
    distance_from_center_km: float,
) -> float:
    """Estimate tangential wind speed at a given radius using the Holland (1980) profile.

    .. math::
        V(r) = \\sqrt{\\frac{B}{\\rho} \\left(\\frac{R_{max}}{r}\\right)^{2B}
        \\left(P_n - P_c\\right) \\exp\\left[-\\left(\\frac{R_{max}}{r}\\right)^{2B}\\right]
        + \\frac{r^2 f^2}{4} - \\frac{rf}{2}}

    Here we use a simplified parametric form that maps category to a
    representative maximum wind and radius of maximum wind, then applies
    the Holland radial profile.

    Parameters
    ----------
    category : int
        Saffir-Simpson category (1–5).
    distance_from_center_km : float
        Radial distance from the eye centre in km.

    Returns
    -------
    float
        Estimated tangential wind speed in m/s at *distance_from_center_km*.

    References
    ----------
    .. [1] Holland, G. J. (1980). "An Analytic Model of the Wind and Pressure
           Profiles in Hurricanes." Mon. Wea. Rev. 108, 1212–1218.
    .. [2] Emanuel, K. A. (2005). "Increasing destructiveness of tropical
           cyclones over the past 30 years." Nature 436, 686–688.
    """
    # Category → representative parameters
    cat_params: dict[int, tuple[float, float, float]] = {
        # (Vmax m/s, Rmax km, B parameter)
        1: (38.0, 60.0, 1.0),
        2: (48.0, 50.0, 1.2),
        3: (58.0, 40.0, 1.4),
        4: (68.0, 30.0, 1.6),
        5: (80.0, 25.0, 1.8),
    }

    _vmax, rmax, B = cat_params.get(category, cat_params[1])

    rho = 1.15  # air density in eye wall (kg/m³)
    P_n = 1013.25  # environmental pressure (hPa)
    P_c = P_n - category * 18.0  # approximate central pressure

    r = max(distance_from_center_km, 0.1)
    R = rmax

    # Holland profile
    x = (R / r) ** (2.0 * B)
    V_squared = (B / rho) * x * (P_n - P_c) * 100.0 * math.exp(-x)
    V = math.sqrt(max(V_squared, 0.0))

    return float(V)


def rainfall_accumulation(
    category: int,
    forward_speed_kmh: float,
    duration_hours: float,
) -> float:
    """Estimate total hurricane rainfall accumulation.

    Uses a simple kinematic model:

    .. math::
        R_{total} = r_{rate} \\cdot \\frac{D}{V_f}

    where *r_rate* is the peak rainfall rate (mm/h) parameterised by category,
    *D* is the storm diameter of significant rain, and *V_f* is the forward
    speed.

    Rainfall rate follows an empirical relationship from tropical cyclone
    climatology (Molinari et al. 2002).

    Parameters
    ----------
    category : int
        Saffir-Simpson category (1–5).
    forward_speed_kmh : float
        Translation speed of the storm in km/h.
    duration_hours : float
        Duration of influence at the location in hours.

    Returns
    -------
    float
        Estimated total rainfall in mm.

    References
    ----------
    .. [1] Molinari, J., Meneghini, D. M. & Franklin, J. L. (2002). "The
           Relationship of Rainfall Area and Rate in Tropical Cyclones." J.
           Appl. Meteor. 41, 952–962.
    .. [2] Rappaport, E. N. (2003). "Impact of Hurricane Forecasting on
           Emergency Management." Bull. Amer. Meteor. Soc. 84, 419–424.
    """
    # Peak rainfall rate (mm/h) by category (empirical climatological values)
    peak_rates: dict[int, float] = {
        1: 15.0,
        2: 25.0,
        3: 40.0,
        4: 60.0,
        5: 90.0,
    }
    rate = peak_rates.get(category, 15.0)

    # Diameter of significant rainfall (km) — roughly scales with storm size
    rain_diameter: dict[int, float] = {
        1: 300.0,
        2: 350.0,
        3: 400.0,
        4: 500.0,
        5: 600.0,
    }
    diameter = rain_diameter.get(category, 300.0)

    # Exposure time at a fixed location
    if forward_speed_kmh > 0:
        exposure_hours = min(diameter / forward_speed_kmh, duration_hours)
    else:
        exposure_hours = duration_hours

    # Total accumulation
    total = rate * exposure_hours
    return max(total, 0.0)
