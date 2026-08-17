"""Coordinate conversion and validation utilities.

Provides Haversine distance, lat/lon offsets, pressure–altitude conversions,
geopotential-to-height calculations, and coordinate validation.
"""

from __future__ import annotations

import math
import warnings

import numpy as np

__all__ = [
    "altitude_to_pressure",
    "geopotential_to_height",
    "km_to_latlon",
    "latlon_to_km",
    "pressure_to_altitude",
    "validate_latlon",
]

_EARTH_RADIUS_KM = 6371.0
StandardGravity = 9.80665
MOLAR_MASS_AIR = 0.0289644
GAS_CONSTANT = 8.31447
LAPSE_RATE = 0.0065
SEA_LEVEL_PRESSURE = 1013.25
SEA_LEVEL_TEMP = 288.15
G0 = 9.80665
R_EARTH = 6356752.0


def latlon_to_km(
    lat1: float | np.ndarray,
    lon1: float | np.ndarray,
    lat2: float | np.ndarray,
    lon2: float | np.ndarray,
) -> float | np.ndarray:
    """Great-circle distance using the Haversine formula.

    Parameters
    ----------
    lat1, lon1 : float or array-like
        First point(s) in degrees.
    lat2, lon2 : float or array-like
        Second point(s) in degrees.

    Returns
    -------
    float or ndarray
        Distance(s) in kilometres.
    """
    lat1 = np.asarray(lat1, dtype=np.float64)
    lon1 = np.asarray(lon1, dtype=np.float64)
    lat2 = np.asarray(lat2, dtype=np.float64)
    lon2 = np.asarray(lon2, dtype=np.float64)

    lat1_r, lat2_r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))

    return _EARTH_RADIUS_KM * c


def km_to_latlon(
    lat: float | np.ndarray,
    lon: float | np.ndarray,
    dk_lat_km: float,
    dk_lon_km: float,
) -> tuple[float | np.ndarray, float | np.ndarray]:
    """Compute new lat/lon by offsetting a point by a distance in km.

    Parameters
    ----------
    lat, lon : float or array-like
        Starting position(s) in degrees.
    dk_lat_km : float
        Northward displacement (positive = north, negative = south).
    dk_lon_km : float
        Eastward displacement (positive = east, negative = west).

    Returns
    -------
    (new_lat, new_lon)
        New position(s) in degrees.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)

    new_lat = lat + (dk_lat_km / _EARTH_RADIUS_KM) * (180.0 / math.pi)
    cos_lat = np.maximum(np.cos(np.radians(lat)), 1e-10)
    new_lon = lon + (dk_lon_km / (_EARTH_RADIUS_KM * cos_lat)) * (180.0 / math.pi)

    return float(new_lat) if new_lat.ndim == 0 else new_lat, float(
        new_lon
    ) if new_lon.ndim == 0 else new_lon


def pressure_to_altitude(pressure_hpa: float | np.ndarray) -> float | np.ndarray:
    """Convert pressure to altitude using the international standard atmosphere.

    Uses the barometric formula assuming a constant lapse rate in the
    troposphere.  Valid for 0–11 km altitude (≈ 1013.25–226.3 hPa).
    Values below sea level return negative altitudes.

    Parameters
    ----------
    pressure_hpa : float or array-like
        Pressure in hPa (mb).

    Returns
    -------
    float or ndarray
        Altitude in metres above sea level.
    """
    pressure_hpa = np.asarray(pressure_hpa, dtype=np.float64)

    if np.any(pressure_hpa <= 0):
        raise ValueError("Pressure must be positive.")

    altitude_m = (SEA_LEVEL_TEMP / LAPSE_RATE) * (
        1.0
        - (pressure_hpa / SEA_LEVEL_PRESSURE)
        ** (GAS_CONSTANT * LAPSE_RATE / (StandardGravity * MOLAR_MASS_AIR))
    )

    return float(altitude_m) if altitude_m.ndim == 0 else altitude_m


def altitude_to_pressure(altitude_m: float | np.ndarray) -> float | np.ndarray:
    """Convert altitude to pressure using the international standard atmosphere.

    Parameters
    ----------
    altitude_m : float or array-like
        Altitude(s) in metres above sea level.

    Returns
    -------
    float or ndarray
        Pressure in hPa (mb).
    """
    altitude_m = np.asarray(altitude_m, dtype=np.float64)

    exponent = (StandardGravity * MOLAR_MASS_AIR) / (GAS_CONSTANT * LAPSE_RATE)
    pressure = SEA_LEVEL_PRESSURE * (1.0 - (LAPSE_RATE * altitude_m / SEA_LEVEL_TEMP)) ** exponent

    pressure = np.clip(pressure, 0.0, None)

    return float(pressure) if pressure.ndim == 0 else pressure


def geopotential_to_height(
    geopotential: float | np.ndarray,
    latitude: float = 45.0,
) -> float | np.ndarray:
    """Convert geopotential (m² s⁻²) to geopotential height (gpm).

    The relationship is:

        Z = Φ / g(φ)

    where g(φ) is the local gravitational acceleration approximated by:

        g(φ) = 9.7803253359 × (1 + 0.001931853 sin²φ) / √(1 − 0.00669438 sin²φ)

    Parameters
    ----------
    geopotential : float or array-like
        Geopotential in m² s⁻² (= J kg⁻¹).
    latitude : float
        Latitude in degrees (default 45°).

    Returns
    -------
    float or ndarray
        Geopotential height in geopotential metres (gpm).
    """
    geopotential = np.asarray(geopotential, dtype=np.float64)

    lat_rad = math.radians(latitude)
    sin_lat = math.sin(lat_rad)
    sin2 = sin_lat**2

    g = 9.7803253359 * (1 + 0.001931853 * sin2) / math.sqrt(1 - 0.00669438 * sin2)

    height = geopotential / g

    return float(height) if height.ndim == 0 else height


def validate_latlon(
    lat: float | np.ndarray,
    lon: float | np.ndarray,
) -> tuple[bool, list[str]]:
    """Validate latitude and longitude values.

    Parameters
    ----------
    lat, lon : float or array-like
        Coordinates to validate.

    Returns
    -------
    (is_valid, errors)
        *is_valid* is True if all checks pass.  *errors* is a list of
        human-readable problem descriptions (empty when valid).
    """
    lat = np.asarray(lat, dtype=np.float64).ravel()
    lon = np.asarray(lon, dtype=np.float64).ravel()

    errors: list[str] = []

    if lat.size == 0:
        errors.append("latitude array is empty.")
        return False, errors
    if lon.size == 0:
        errors.append("longitude array is empty.")
        return False, errors
    if lat.size != lon.size:
        errors.append(
            f"latitude and longitude must have the same length (got {lat.size} and {lon.size})."
        )

    nan_lat = np.isnan(lat)
    nan_lon = np.isnan(lon)
    if np.any(nan_lat):
        count = int(np.sum(nan_lat))
        errors.append(f"latitude contains {count} NaN value(s).")
    if np.any(nan_lon):
        count = int(np.sum(nan_lon))
        errors.append(f"longitude contains {count} NaN value(s).")

    finite_lat = lat[~nan_lat]
    finite_lon = lon[~nan_lon]

    oob_lat = finite_lat[(finite_lat < -90) | (finite_lat > 90)]
    if oob_lat.size > 0:
        examples = oob_lat[:5].tolist()
        errors.append(
            f"latitude has {oob_lat.size} out-of-range value(s) outside [-90, 90]. "
            f"Examples: {examples}"
        )

    oob_lon = finite_lon[(finite_lon < -180) | (finite_lon > 360)]
    if oob_lon.size > 0:
        examples = oob_lon[:5].tolist()
        warnings.warn(
            f"longitude has {oob_lon.size} value(s) outside [-180, 360]. "
            f"Examples: {examples}. Values outside this range are unusual "
            "but may be valid for some conventions.",
            stacklevel=2,
        )

    is_valid = len(errors) == 0
    return is_valid, errors
