"""Precipitation-derived target variables for weather quant trading.

Implements precipitation accumulation, snow probability, drought index (SPI-like),
and rain-days probability.

References:
    - WMO Standard Precipitation Index: https://link.springer.com/chapter/10.1007/978-94-015-9171-3_6
    - McKee et al. (1993): https://doi.org/10.1175/1520-0477(1993)074<1417:TDPSPI>2.3.CO;2
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import stats as sp_stats

__all__ = [
    "drought_index",
    "precipitation_accumulation",
    "rain_days_probability",
    "snow_probability",
]


def precipitation_accumulation(
    precipitation_rate: Sequence[float] | np.ndarray,
    window_hours: int,
) -> float:
    """Accumulate precipitation from a rate time series.

    Parameters
    ----------
    precipitation_rate : array-like
        Precipitation rate in mm/h at each time step.  Time steps are assumed
        to be evenly spaced.
    window_hours : int
        Accumulation window in hours.

    Returns
    -------
    float
        Total accumulated precipitation in mm.
    """
    rates = np.asarray(precipitation_rate, dtype=np.float64)
    if rates.ndim != 1:
        raise ValueError("precipitation_rate must be 1-D")
    n_steps = len(rates)
    if n_steps <= 1:
        return 0.0
    dt_hours = window_hours / (n_steps - 1)
    total = float(np.sum(rates) * dt_hours)
    return max(total, 0.0)


def snow_probability(
    temperature_forecast: Sequence[float] | np.ndarray,
    precipitation_forecast: Sequence[float] | np.ndarray,
    threshold_celsius: float = 0.0,
) -> float:
    """Estimate the probability that precipitation falls as snow.

    Uses a simple physically motivated model: precipitation events with a
    temperature below *threshold_celsius* are classified as snow events.  The
    returned probability is the fraction of precipitating time steps where the
    temperature is at or below the threshold.

    For mixed-phase transitions a linear ramp from 0 to 1 is used in the
    band [threshold, threshold + 2 °C].

    Parameters
    ----------
    temperature_forecast : array-like
        Forecast temperatures in °C.
    precipitation_forecast : array-like
        Forecast precipitation rates in mm/h (same length as temperature).
    threshold_celsius : float
        Temperature below which all precipitation is snow (default 0 °C).

    Returns
    -------
    float
        Snow probability in [0, 1].  Returns 0.0 when no precipitation is
        forecast.
    """
    temp = np.asarray(temperature_forecast, dtype=np.float64)
    precip = np.asarray(precipitation_forecast, dtype=np.float64)
    if temp.shape != precip.shape:
        raise ValueError("temperature_forecast and precipitation_forecast must match")

    precip_mask = precip > 0.0
    if not np.any(precip_mask):
        return 0.0

    precipitating_temps = temp[precip_mask]
    # Snow fraction: full below threshold, linear ramp to 0 over 2 °C band
    snow_frac = np.clip((threshold_celsius + 2.0 - precipitating_temps) / 2.0, 0.0, 1.0)
    return float(np.mean(snow_frac))


def drought_index(
    precipitation_history: Sequence[float] | np.ndarray,
    window_days: int = 90,
) -> float:
    """Compute a Standardised Precipitation Index (SPI) analogue.

    The SPI normalises cumulative precipitation over a window against its
    long-term climatological distribution.  Here we fit a gamma distribution
    to the input series and compute the standardised anomaly.

    A positive SPI indicates wet conditions; negative indicates drought.

    Parameters
    ----------
    precipitation_history : array-like
        Daily precipitation totals in mm for a long period (ideally ≥ 30 years
        for robust statistics, but works with shorter records).
    window_days : int
        Accumulation window in days (default 90 for seasonal drought).

    Returns
    -------
    float
        SPI-like index (dimensionless). Values < −2 indicate extreme drought;
        values > +2 indicate extremely wet.

    References
    ----------
    .. [1] McKee, T. B., Doesken, N. J. & Kleist, J. (1993). "The
           Relationship of Drought Frequency and Duration to Time Scales."
           Proc. 8th Conf. Applied Climatology, AMS, 179–184.
    .. [2] Lloyd-Hughes, B. & Saunders, M. A. (2002). "A drought climatology
           for Europe." Int. J. Climatol. 22, 1571–1592.
    """
    arr = np.asarray(precipitation_history, dtype=np.float64)
    if arr.ndim != 1 or len(arr) < window_days:
        raise ValueError("precipitation_history must be 1-D with length >= window_days")

    # Rolling accumulation
    kernel = np.ones(window_days, dtype=np.float64)
    cumul = np.convolve(arr, kernel, mode="valid")

    if len(cumul) < 2:
        return 0.0

    # Fit gamma distribution (SPI convention: shift zero-precipitation differently)
    # Use L-moment approximation for gamma parameters when possible.
    mean = np.mean(cumul)
    var = np.var(cumul, ddof=1)
    if mean <= 0 or np.isnan(var) or var <= 0:
        return 0.0

    # Method of moments for gamma
    alpha = (mean**2) / var  # shape
    beta = var / mean  # scale

    # Log-normal transform for SPI calculation
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    p = sp_stats.gamma.cdf(cumul[-1], a=alpha, scale=beta)
    # Clamp to avoid infinities at tails
    p = np.clip(p, 1e-6, 1.0 - 1e-6)

    # Abramowitz & Stegun approximation for inverse normal
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
        spi = -(t - (c0 + c1 * t + c2 * t**2) / (1.0 + d1 * t + d2 * t**2 + d3 * t**3))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        spi = t - (c0 + c1 * t + c2 * t**2) / (1.0 + d1 * t + d2 * t**2 + d3 * t**3)

    return float(spi)


def rain_days_probability(
    precipitation_forecast: Sequence[float] | np.ndarray,
    threshold_mm: float = 1.0,
) -> float:
    """Estimate the probability of measurable rain over a forecast window.

    Counts the fraction of forecast time steps with precipitation above the
    threshold.

    Parameters
    ----------
    precipitation_forecast : array-like
        Forecast precipitation rates or totals in mm per time step.
    threshold_mm : float
        Minimum precipitation to count as a "rain day" (default 1.0 mm).

    Returns
    -------
    float
        Probability in [0, 1].
    """
    arr = np.asarray(precipitation_forecast, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.clip(np.mean(arr >= threshold_mm), 0.0, 1.0))
