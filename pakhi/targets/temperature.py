"""Temperature-derived target variables for weather quant trading.

Implements heat index (NWS), wind chill (Environment Canada), freeze probability,
growing degree days, and diurnal temperature range.

References:
    - NWS Heat Index: https://www.weather.gov/ama/heatindex
    - Environment Canada Wind Chill: https://www.canada.ca/en/environment-climate-services/services/weather-forecasts/cold-weather/wind-chill.html
    - Growing Degree Days: https://en.wikipedia.org/wiki/Growing_degree-day
"""

from __future__ import annotations

from typing import Literal, Sequence

import numpy as np

__all__ = [
    "diurnal_temperature_range",
    "freeze_probability",
    "growing_degree_days",
    "heat_index",
    "wind_chill",
]

Method = Literal["ensemble_mean", "quantile_10", "worst_case"]


def freeze_probability(
    temperature_forecast: Sequence[float] | np.ndarray,
    threshold_celsius: float = 0.0,
    window_days: int = 7,
    method: Method = "ensemble_mean",
) -> float:
    """Estimate the probability of temperature dropping below a freezing threshold.

    Treats an ensemble of temperature forecasts (e.g. from GEFS, ECMWF EPS)
    as equiprobable samples and computes the fraction that fall at or below
    the threshold.

    Parameters
    ----------
    temperature_forecast : array-like
        Ensemble member forecasts in degrees Celsius.  Length should equal the
        number of ensemble members multiplied by the number of forecast lead
        days within *window_days*.  Alternatively, pass the full ensemble
        spread for a single lead time and the function normalises accordingly.
    threshold_celsius : float
        Temperature threshold in °C (default 0.0).
    window_days : int
        Number of forecast lead days to consider (default 7).
    method : {"ensemble_mean", "quantile_10", "worst_case"}
        Aggregation strategy:
        * ``"ensemble_mean"`` – fraction of members below threshold, then
          averaged over the window.
        * ``"quantile_10"`` – 10th-percentile temperature across members for
          each day; fraction of days where that percentile is below threshold.
        * ``"worst_case"`` – maximum daily fraction below threshold across the
          window (most conservative).

    Returns
    -------
    float
        Probability in [0, 1].
    """
    arr = np.asarray(temperature_forecast, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    if arr.ndim == 1:
        n_members = max(1, len(arr) // max(window_days, 1))
        n_days = max(1, len(arr) // n_members)
        arr = arr[: n_days * n_members]
        arr = arr.reshape(n_days, n_members)
    # arr shape: (n_days, n_members)
    daily_frac = np.mean(arr <= threshold_celsius, axis=1)

    if method == "ensemble_mean":
        return float(np.clip(np.mean(daily_frac), 0.0, 1.0))
    elif method == "quantile_10":
        daily_p10 = np.percentile(arr, 10, axis=1)
        return float(np.clip(np.mean(daily_p10 <= threshold_celsius), 0.0, 1.0))
    elif method == "worst_case":
        return float(np.clip(np.max(daily_frac), 0.0, 1.0))
    else:
        raise ValueError(f"Unknown method {method!r}")


def heat_index(temperature_celsius: float, relative_humidity: float) -> float:
    """Compute the NWS heat index (feels-like temperature).

    Uses the Rothfusz regression equation from the NWS, which is valid for
    temperatures above 27 °C and relative humidity above 40 %.  For lower
    values the simple Steadman formula is returned.

    Parameters
    ----------
    temperature_celsius : float
        Ambient air temperature in °C.
    relative_humidity : float
        Relative humidity as a percentage (0–100).

    Returns
    -------
    float
        Heat index in degrees Celsius.

    References
    ----------
    .. [1] NWS, "Heat Index Equation"
           https://www.weather.gov/ama/heatindex
    .. [2] Steadman, R. G. (1979). "The Assessment of Sultriness."
           J. Appl. Meteor. 18, 861–873.
    """
    T = temperature_celsius
    RH = relative_humidity

    # Steadman simple formula (constants are in degrees Fahrenheit).
    Tf = T * 9.0 / 5.0 + 32.0
    HI_simple_F = 0.5 * (Tf + 61.0 + (Tf - 68.0) * 1.2 + RH * 0.094)
    HI_simple = (HI_simple_F - 32.0) * 5.0 / 9.0

    if T < 27.0 or RH < 40.0:
        return float(HI_simple)

    # Rothfusz regression (T in °F, RH in %)
    c1 = -42.379
    c2 = 2.04901523
    c3 = 10.14333127
    c4 = -0.22475541
    c5 = -0.00683783
    c6 = -0.05481717
    c7 = 0.00122874
    c8 = 0.00085282
    c9 = -0.00000199

    HI_F = (
        c1
        + c2 * Tf
        + c3 * RH
        + c4 * Tf * RH
        + c5 * Tf * Tf
        + c6 * RH * RH
        + c7 * Tf * Tf * RH
        + c8 * Tf * RH * RH
        + c9 * Tf * Tf * RH * RH
    )

    # Adjustments
    if RH > 85.0 and 80.0 <= Tf <= 87.0:
        adjustment = ((RH - 85.0) / 10.0) * ((87.0 - Tf) / 5.0)
        HI_F += adjustment

    return float((HI_F - 32.0) * 5.0 / 9.0)


def wind_chill(temperature_celsius: float, wind_speed_kmh: float) -> float:
    """Compute wind chill using the Environment Canada / NWS formula.

    Valid for temperatures at or below 10 °C and wind speeds above 4.8 km/h.
    Outside this range the ambient temperature is returned unchanged.

    Parameters
    ----------
    temperature_celsius : float
        Air temperature in °C.
    wind_speed_kmh : float
        Wind speed in km/h at 10 m height.

    Returns
    -------
    float
        Wind chill temperature in °C.

    References
    ----------
    .. [1] Environment Canada, "Wind Chill Index"
           https://www.canada.ca/en/environment-climate-services/services/weather-forecasts/cold-weather/wind-chill.html
    .. [2] Osczevski, R. J. & Bluestein, M. A. (2005). "The New Wind Chill
           Equivalent Temperature Chart." Bull. Amer. Meteor. Soc. 86, 1453–1458.
    """
    if temperature_celsius > 10.0 or wind_speed_kmh < 4.8:
        return float(temperature_celsius)

    V = wind_speed_kmh
    T = temperature_celsius

    WC = 13.12 + 0.6215 * T - 11.37 * V**0.16 + 0.3965 * T * V**0.16

    return float(WC)


def growing_degree_days(
    temperature: Sequence[float] | np.ndarray,
    base: float = 10.0,
    max_celsius: float = 30.0,
) -> float:
    """Accumulate growing degree days (GDD) using the standard formula.

    GDD for a single day is ``max(0, min(T_max, max_celsius) - base)`` where
    T_max is the daily maximum temperature.  If an array of daily temperatures
    is provided each element is treated as a daily max.

    Parameters
    ----------
    temperature : array-like
        Daily maximum temperatures in °C.
    base : float
        Base temperature below which no growth accumulation occurs (default 10 °C).
    max_celsius : float
        Upper cap; temperatures above this are clamped to avoid unrealistically
        large accumulation (default 30 °C).

    Returns
    -------
    float
        Total accumulated GDD in °C·days.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Growing_degree-day
    .. [2] McMaster, G. S. & Wilhelm, W. W. (1997). "Growing degree-days:
           one equation, two interpretations." Agric. For. Meteorol. 87, 291–300.
    """
    arr = np.asarray(temperature, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    gdd = np.maximum(0.0, np.minimum(arr, max_celsius) - base)
    return float(np.sum(gdd))


def diurnal_temperature_range(
    temperature_max: Sequence[float] | np.ndarray,
    temperature_min: Sequence[float] | np.ndarray,
) -> float:
    """Compute the mean diurnal temperature range (DTR).

    DTR = mean(T_max − T_min).  A larger DTR is associated with clearer skies
    and drier air.

    Parameters
    ----------
    temperature_max : array-like
        Daily maximum temperatures in °C.
    temperature_min : array-like
        Daily minimum temperatures in °C.

    Returns
    -------
    float
        Mean diurnal range in °C.

    References
    ----------
    .. [1] Vose, R. S. et al. (2011). "Does global warming affect diurnal
           temperature range?" J. Climate 24, 2667–2679.
    """
    tmax = np.asarray(temperature_max, dtype=np.float64)
    tmin = np.asarray(temperature_min, dtype=np.float64)
    if tmax.size == 0 or tmin.size == 0:
        return 0.0
    if tmax.shape != tmin.shape:
        raise ValueError("temperature_max and temperature_min must have the same shape")
    return float(np.mean(tmax - tmin))
