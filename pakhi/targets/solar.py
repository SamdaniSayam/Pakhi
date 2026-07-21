"""Solar radiation and photovoltaic target variables for weather quant trading.

Implements solar position (Spencer 1971), Ineichen-Perez clear-sky model,
cloud-cover GHI estimation, and PV output calculation.

References:
    - Spencer, J. W. (1971). "A Comparison of Methods for Estimating Hourly
      Diffuse Solar Radiation from Global Solar Radiation." Solar Energy 15,
      353–362.
    - Ineichen, P. & Perez, R. (2002). "A New Airmass Independent Formulation
      for the Linke Turbidity Coefficient." Solar Energy 73, 151–157.
    - American Society of Heating, Refrigerating and Air-Conditioning Engineers
      (ASHRAE), "ASHRAE Handbook — Fundamentals", Chapter 14.
"""

from __future__ import annotations

import math
from datetime import datetime

__all__ = [
    "clear_sky_radiation",
    "ghi_from_cloud_cover",
    "photovoltaic_output",
    "solar_position",
]

# Physical constants
SOLAR_CONSTANT = 1361.0  # W/m² (TSI, Kopp & Lean 2011)
ZENITH_DEG_TO_RAD = math.pi / 180.0


def solar_position(
    latitude: float,
    longitude: float,
    datetime_utc: datetime,
) -> dict[str, float]:
    """Compute the solar zenith, azimuth, and elevation angles.

    Uses the Spencer (1971) method based on the fractional year and hour
    angle, which provides ≈ 0.01° accuracy.

    Parameters
    ----------
    latitude : float
        Observer latitude in degrees (positive north).
    longitude : float
        Observer longitude in degrees (positive east).
    datetime_utc : datetime
        UTC datetime of the observation.

    Returns
    -------
    dict
        ``{"zenith": float, "azimuth": float, "elevation": float}`` in degrees.
        Elevation is the complement of zenith (elevation = 90° − zenith).

    References
    ----------
    .. [1] Spencer, J. W. (1971). "Fourier series representation of the
           position of the Sun." Search 2(5), 172.
    .. [2] Iqbal, M. (1983). "An Introduction to Solar Radiation."
           Academic Press, Ch. 3.
    """
    lat = math.radians(latitude)

    # Fractional year (radians)
    n = datetime_utc.timetuple().tm_yday
    year_frac = 2.0 * math.pi * (n - 1) / 365.0

    # Equation of time (minutes) — Spencer 1971
    B = year_frac
    EoT = 229.18 * (
        0.000075
        + 0.001868 * math.cos(B)
        - 0.032077 * math.sin(B)
        - 0.014615 * math.cos(2 * B)
        - 0.04089 * math.sin(2 * B)
    )

    # Solar declination (radians) — Spencer 1971
    decl = (
        0.006918
        - 0.399912 * math.cos(B)
        + 0.070257 * math.sin(B)
        - 0.006758 * math.cos(2 * B)
        + 0.000907 * math.sin(2 * B)
        - 0.002697 * math.cos(3 * B)
        + 0.00148 * math.sin(3 * B)
    )

    # True solar time
    hour = datetime_utc.hour + datetime_utc.minute / 60.0 + datetime_utc.second / 3600.0
    LSTM = 15.0 * round(longitude / 15.0)  # Local Standard Time Meridian from longitude
    TC = 4.0 * (longitude - LSTM) + EoT  # time correction (minutes)
    LST = hour + TC / 60.0  # local solar time (hours)
    HRA = math.radians(15.0 * (LST - 12.0))  # hour angle (radians)

    # Solar zenith angle
    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(HRA)
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.degrees(math.acos(cos_zenith))

    # Elevation
    elevation = 90.0 - zenith

    # Azimuth angle (measured from north, clockwise)
    sin_az = -math.cos(decl) * math.sin(HRA) / math.cos(lat) if abs(cos_zenith) > 1e-6 else 0.0
    cos_az = (math.sin(decl) - math.sin(lat) * cos_zenith) / (
        math.cos(lat) * math.sin(math.radians(zenith)) + 1e-10
    )
    sin_az = max(-1.0, min(1.0, sin_az))
    cos_az = max(-1.0, min(1.0, cos_az))
    azimuth = math.degrees(math.atan2(sin_az, cos_az))
    azimuth = (azimuth + 360.0) % 360.0

    return {"zenith": zenith, "azimuth": azimuth, "elevation": elevation}


def clear_sky_radiation(
    solar_zenith: float,
    altitude_m: float,
    aerosol_optical_depth: float,
) -> float:
    """Estimate clear-sky global horizontal irradiance (GHI) using the Ineichen-Perez model.

    The model parameterises the Linke turbidity from AOD and altitude, then
    applies a broadband transmittance model.

    .. math::
        GHI = G_0 \\cdot e^{-0.09 \\cdot (TL - 1) \\cdot m^{0.88}}

    where *m* is the relative air mass, *TL* the Linke turbidity, and *G₀*
    the extraterrestrial horizontal irradiance.

    Parameters
    ----------
    solar_zenith : float
        Solar zenith angle in degrees.
    altitude_m : float
        Site altitude in metres above sea level.
    aerosol_optical_depth : float
        Aerosol optical depth at 550 nm (unitless, typical range 0.02–1.5).

    Returns
    -------
    float
        Clear-sky GHI in W/m².

    References
    ----------
    .. [1] Ineichen, P. & Perez, R. (2002). "A New Airmass Independent
           Formulation for the Linke Turbidity Coefficient." Solar Energy 73,
           151–157.
    .. [2] Kasten, F. (1996). "The Linke Turbidity Factor Based on Improved
           Values of the Integral Rayleigh Optical Thickness." Solar Energy
           56, 239–244.
    """
    zen_rad = math.radians(solar_zenith)

    # Extraterrestrial irradiance on horizontal surface
    G0 = SOLAR_CONSTANT * math.cos(zen_rad)
    if G0 <= 0:
        return 0.0

    # Relative air mass (Kasten & Young 1989) — clamp zenith to avoid complex numbers
    zenith_clamped = min(solar_zenith, 90.0)
    cos_z = math.cos(math.radians(zenith_clamped))
    m = 1.0 / (cos_z + 0.50572 * (96.07995 - zenith_clamped) ** (-1.6364))

    # Linke turbidity from AOD and altitude (Ineichen & Perez 2002)
    # TL = 1 + AOD / (0.01 * exp(-altitude/8500) * m + 0.00196 * 1.0)
    b0 = 0.01 * math.exp(-altitude_m / 8500.0) + 0.00196 * 1.0
    TL = 1.0 + aerosol_optical_depth / b0

    # Clear-sky GHI (Ineichen-Perez)
    ghi = G0 * math.exp(-0.09 * (TL - 1.0) * m**0.88)
    return max(ghi, 0.0)


def ghi_from_cloud_cover(
    cloud_cover_fraction: float,
    solar_zenith: float,
) -> float:
    """Estimate GHI from cloud cover using the BRL model simplification.

    Uses the Bird & Hulstrom (1981) clear-sky estimate combined with a
    cloud transmittance parameterisation.

    Parameters
    ----------
    cloud_cover_fraction : float
        Cloud cover fraction (0.0 = clear, 1.0 = overcast).
    solar_zenith : float
        Solar zenith angle in degrees.

    Returns
    -------
    float
        Estimated GHI in W/m².

    References
    ----------
    .. [1] Bird, R. E. & Hulstrom, R. L. (1981). "A Simplified Clear Sky
           Model for the Solar Spectral and Total Irradiance." Solar Energy
           27, 331–335.
    .. [2] Hollands, K. G. T. et al. (2016). "On the accurate characterization
           of solar irradiance." Solar Energy 135, 291–303.
    """
    zen_rad = math.radians(solar_zenith)
    cos_z = math.cos(zen_rad)
    if cos_z <= 0:
        return 0.0

    # Extraterrestrial irradiance
    G0 = SOLAR_CONSTANT * cos_z

    # Simple clear-sky transmittance (atmospheric, sea-level)
    # tau_clear ≈ 0.7^(m^0.678), m = sec(zenith), BRL approximation
    zenith_clamped = min(solar_zenith, 90.0)
    cos_z_clamped = math.cos(math.radians(zenith_clamped))
    m = 1.0 / (cos_z_clamped + 0.50572 * (96.07995 - zenith_clamped) ** (-1.6364))
    tau_clear = 0.7 ** (m**0.678)

    # Cloud transmittance (BRL)
    # For overcast sky, transmittance ≈ 0.2; clear → tau_clear
    tau_cloud = tau_clear * (1.0 - cloud_cover_fraction) + 0.20 * cloud_cover_fraction

    ghi = G0 * tau_cloud
    return max(ghi, 0.0)


def photovoltaic_output(
    ghi: float,
    panel_efficiency: float,
    area_m2: float,
    temperature_celsius: float,
    derating: float = 0.85,
) -> float:
    """Estimate photovoltaic electrical output from GHI.

    Applies the panel temperature derating factor per the NOCT model:

    .. math::
        T_{cell} = T_{amb} + \\frac{NOCT - 20}{800} \\cdot GHI

    and the temperature coefficient for crystalline silicon:

    .. math::
        P = GHI \\cdot A \\cdot \\eta \\cdot \\left(1 + \\beta (T_{cell} - 25)\\right) \\cdot D

    where β ≈ −0.004 /°C for c-Si.

    Parameters
    ----------
    ghi : float
        Global horizontal irradiance in W/m².
    panel_efficiency : float
        Nominal efficiency at STC (25 °C, 1000 W/m²) as a fraction (e.g. 0.20).
    area_m2 : float
        Total active panel area in m².
    temperature_celsius : float
        Ambient air temperature in °C.
    derating : float
        System-level derating for inverter, wiring, soiling, etc. (0–1).

    Returns
    -------
    float
        Electrical output in kW.

    References
    ----------
    .. [1] Marion, B. et al. (2005). "A Method for Modeling the Performance
           of Photovoltaic Systems." NREL/CP-620-37974.
    .. [2] King, D. L. et al. (2004). "Photovoltaic Array Performance Model."
           Sandia National Laboratories, SAND2004-3561.
    """
    if ghi <= 0 or panel_efficiency <= 0 or area_m2 <= 0:
        return 0.0

    # Cell temperature estimate (NOCT model)
    noct = 45.0  # typical NOCT in °C
    t_cell = temperature_celsius + (noct - 20.0) / 800.0 * ghi

    # Temperature coefficient for crystalline silicon
    beta = -0.004  # per °C

    # Power output
    p_stc = ghi * area_m2 * panel_efficiency / 1000.0  # kW at STC-like conditions
    p_adjusted = p_stc * (1.0 + beta * (t_cell - 25.0)) * derating
    return max(p_adjusted, 0.0)
