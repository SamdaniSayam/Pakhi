"""Open-Meteo free weather API connector.

Provides forecast, historical, and air quality data from the Open-Meteo
API (https://api.open-meteo.com). No API key required.

Example:
    >>> from pakhi.src.openmeteo import OpenMeteoConnector
    >>> api = OpenMeteoConnector()
    >>> forecast = api.forecast(lat=41.88, lon=-87.63, days=7)
    >>> hist = api.historical(start="2023-01-01", end="2023-12-31", lat=41.88, lon=-87.63)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import xarray as xr

__all__ = ["OpenMeteoConnector"]

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1"

# Zero-cost dev mode: when PAKHI_MOCK_DATA is truthy, connectors serve static
# fixtures instead of hitting the live API (respect free-tier rate limits).
_MOCK_ENABLED = os.environ.get("PAKHI_MOCK_DATA", "").lower() in ("1", "true", "yes", "on")
_MOCK_DIR = Path(os.environ.get("PAKHI_MOCK_DATA_DIR", "data/sample/mock"))


def _mock_load_url(url: str) -> Any:
    """Load a static fixture for ``url`` (path portion -> ``<path>.json``)."""
    path_part = url.split("//", 1)[1].split("?", 1)[0].replace("/", "_")
    path = _MOCK_DIR / f"{path_part}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"PAKHI_MOCK_DATA enabled but missing fixture: {path}. "
            f"Download it once and place it under {_MOCK_DIR}."
        )
    return json.loads(path.read_text())

FORECAST_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "soil_temperature_0cm",
    "soil_moisture_0_to_7cm",
]

HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "snow_depth",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]

DAILY_VARIABLES = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "sunrise",
    "sunset",
    "daylight_duration",
    "sunshine_duration",
    "uv_index_max",
    "precipitation_sum",
    "precipitation_hours",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
]

AIR_QUALITY_VARIABLES = [
    "european_aqi",
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "dust",
    "uv_index",
]

WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class OpenMeteoConnector:
    """Connector for the Open-Meteo free weather API.

    Provides forecast, historical weather, and air quality data without
    requiring an API key. Suitable for quick data access and prototyping.

    Args:
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum retry attempts.
        temperature_unit: "celsius" or "fahrenheit".
        wind_speed_unit: "kmh", "ms", "mph", or "kn".
        precipitation_unit: "mm" or "inch".

    Example:
        >>> api = OpenMeteoConnector()
        >>> forecast = api.forecast(lat=41.88, lon=-87.63, days=7)
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        temperature_unit: str = "celsius",
        wind_speed_unit: str = "kmh",
        precipitation_unit: str = "mm",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature_unit = temperature_unit
        self.wind_speed_unit = wind_speed_unit
        self.precipitation_unit = precipitation_unit
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "pakhi-weather-quant/0.1"})

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make a GET request with retry logic."""
        if _MOCK_ENABLED:
            return _mock_load_url(url)
        params.update(
            {
                "temperature_unit": self.temperature_unit,
                "wind_speed_unit": self.wind_speed_unit,
                "precipitation_unit": self.precipitation_unit,
            }
        )
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Open-Meteo request failed (attempt %d): %s", attempt, exc)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
        raise ConnectionError(
            f"Open-Meteo API request failed after {self.max_retries} attempts"
        ) from last_exc

    def forecast(
        self,
        lat: float,
        lon: float,
        days: int = 7,
        hourly: list[str] | None = None,
        daily: list[str] | None = None,
        models: list[str] | None = None,
    ) -> xr.Dataset:
        """Fetch weather forecast for a location.

        Args:
            lat: Latitude in decimal degrees.
            lon: Longitude in decimal degrees.
            days: Number of forecast days (1-16).
            hourly: List of hourly variables from HOURLY_VARIABLES.
            daily: List of daily variables from DAILY_VARIABLES.
            models: Specific forecast models, e.g. ["gfs_seamless", "ecmwf_ifs025"].

        Returns:
            xarray.Dataset with forecast data.
        """
        if hourly is None:
            hourly = [
                "temperature_2m",
                "precipitation",
                "wind_speed_10m",
                "pressure_msl",
                "cloud_cover",
            ]
        if daily is None:
            daily = [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "forecast_days": min(days, 16),
            "hourly": ",".join(hourly),
            "daily": ",".join(daily),
        }
        if models:
            params["models"] = ",".join(models)

        data = self._get(f"{BASE_URL}/forecast", params)
        return self._parse_response(data)

    def historical(
        self,
        start: str,
        end: str,
        lat: float,
        lon: float,
        hourly: list[str] | None = None,
    ) -> xr.Dataset:
        """Fetch historical weather data.

        Args:
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".
            lat: Latitude.
            lon: Longitude.
            hourly: Hourly variables to fetch.

        Returns:
            xarray.Dataset with historical data.
        """
        if hourly is None:
            hourly = [
                "temperature_2m",
                "precipitation",
                "wind_speed_10m",
                "pressure_msl",
                "relative_humidity_2m",
            ]

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(hourly),
        }

        data = self._get(f"{BASE_URL}/archive", params)
        return self._parse_response(data)

    def air_quality(
        self,
        lat: float,
        lon: float,
        hourly: list[str] | None = None,
    ) -> xr.Dataset:
        """Fetch air quality forecast.

        Args:
            lat: Latitude.
            lon: Longitude.
            hourly: Air quality variables from AIR_QUALITY_VARIABLES.

        Returns:
            xarray.Dataset with air quality data.
        """
        if hourly is None:
            hourly = ["european_aqi", "pm10", "pm2_5", "ozone"]

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(hourly),
        }

        data = self._get(f"{AIR_QUALITY_URL}/air-quality", params)
        return self._parse_response(data)

    def multi_location(
        self,
        locations: list[dict[str, float]],
        variable: str = "temperature_2m",
        days: int = 7,
    ) -> xr.Dataset:
        """Fetch forecast for multiple locations in one request.

        Args:
            locations: List of {"lat": ..., "lon": ...} dicts.
            variable: Single variable to fetch.
            days: Forecast days.

        Returns:
            xarray.Dataset with a 'location' dimension.
        """
        lats = [loc["lat"] for loc in locations]
        lons = [loc["lon"] for loc in locations]
        params: dict[str, Any] = {
            "latitude": ",".join(str(lat_val) for lat_val in lats),
            "longitude": ",".join(str(lon_val) for lon_val in lons),
            "forecast_days": min(days, 16),
            "hourly": variable,
        }
        data = self._get(f"{BASE_URL}/forecast", params)
        if isinstance(data, list):
            datasets = [self._parse_response(d) for d in data]
            for i, ds in enumerate(datasets):
                ds = ds.expand_dims(dim={"location": [i]})
                datasets[i] = ds
            return xr.concat(datasets, dim="location")
        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> xr.Dataset:
        """Parse Open-Meteo JSON response into xarray.Dataset."""
        ds_dict: dict[str, Any] = {}
        coords: dict[str, Any] = {}

        # Parse hourly data
        if "hourly" in data:
            hourly = data["hourly"]
            if "time" in hourly:
                times = pd.to_datetime(hourly["time"])
                coords["time"] = times
                for key, values in hourly.items():
                    if key == "time":
                        continue
                    ds_dict[key] = (["time"], values)

        # Parse daily data
        if "daily" in data:
            daily = data["daily"]
            if "time" in daily:
                days = pd.to_datetime(daily["time"])
                for key, values in daily.items():
                    if key == "time":
                        continue
                    daily_key = f"daily_{key}"
                    ds_dict[daily_key] = (["day"], values)
                    coords["day"] = days

        # Add metadata
        attrs: dict[str, Any] = {}
        if "latitude" in data:
            attrs["latitude"] = data["latitude"]
        if "longitude" in data:
            attrs["longitude"] = data["longitude"]
        if "elevation" in data:
            attrs["elevation"] = data["elevation"]
        if "timezone" in data:
            attrs["timezone"] = data["timezone"]
        if "model" in data:
            attrs["model"] = data["model"]
        attrs["source"] = "open-meteo"

        if not ds_dict:
            raise RuntimeError("No data in Open-Meteo response")

        ds = xr.Dataset(ds_dict, coords=coords, attrs=attrs)
        return ds

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> OpenMeteoConnector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
