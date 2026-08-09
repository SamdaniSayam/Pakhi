"""Meteostat historical weather data connector.

Provides station-based historical weather observations via the Meteostat
API or library. Useful for training data, validation, and quick tests.

Example:
    >>> from pakhi.src.meteostat import MeteostatConnector
    >>> ms = MeteostatConnector()
    >>> stations = ms.stations_near(lat=41.88, lon=-87.63, radius_km=50)
    >>> history = ms.history(station_id="725300-14819", start="2020-01-01", end="2023-12-31")
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests

__all__ = ["MeteostatConnector"]

logger = logging.getLogger(__name__)

METEOSTAT_API_BASE = "https://api.meteostat.net/v2"

STATION_VARIABLES = [
    "temperature",
    "dewpoint",
    "windspeed",
    "winddirection",
    "windgust",
    "pressure",
    "precipitations",
    "weather",
    "visibility",
    "cloudcover",
    "humidity",
]


class MeteostatConnector:
    """Connector for Meteostat historical weather data.

    Fetches station-based historical observations for point locations.
    Can operate via the Meteostat REST API (requires API key) or the
    meteostat Python library.

    Args:
        api_key: Meteostat API key (optional, free tier available).
                 Can also be set via METEOSTAT_API_KEY environment variable.
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum retry attempts.

    Example:
        >>> ms = MeteostatConnector()
        >>> stations = ms.stations_near(lat=41.88, lon=-87.63)
        >>> data = ms.history(station_id="725300-14819", start="2020-01-01", end="2023-12-31")
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        import os

        self.api_key = api_key or os.environ.get("METEOSTAT_API_KEY", "")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "pakhi-weather-quant/0.1",
            }
        )
        if self.api_key:
            self._session.headers["x-api-key"] = self.api_key

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the Meteostat API."""
        url = f"{METEOSTAT_API_BASE}/{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                if data.get("meta", {}).get("code") == 429:
                    logger.warning("Rate limited, backing off...")
                    time.sleep(5 * attempt)
                    continue
                return data
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Meteostat API request failed (attempt %d): %s", attempt, exc)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
        raise ConnectionError(
            f"Meteostat API request failed after {self.max_retries} attempts"
        ) from last_exc

    def stations_near(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50,
        limit: int = 10,
    ) -> pd.DataFrame:
        """Find nearby weather stations.

        Args:
            lat: Latitude in decimal degrees.
            lon: Longitude in decimal degrees.
            radius_km: Search radius in kilometers.
            limit: Maximum number of stations to return.

        Returns:
            DataFrame with station info: id, name, country, lat, lon,
            elevation, distance_km, start_date, end_date.
        """
        params: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "limit": limit,
        }
        try:
            data = self._get("stations/nearby", params)
        except (ConnectionError, Exception) as exc:
            logger.warning("Meteostat API unavailable, trying meteostat library: %s", exc)
            return self._stations_near_library(lat, lon, radius_km, limit)

        stations: list[dict[str, Any]] = []
        for s in data.get("data", []):
            stations.append(
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "country": s.get("country", ""),
                    "region": s.get("region", ""),
                    "lat": s.get("latitude", np.nan),
                    "lon": s.get("longitude", np.nan),
                    "elevation": s.get("elevation", np.nan),
                    "distance_km": s.get("distance", np.nan),
                    "start_date": s.get("first", ""),
                    "end_date": s.get("last", ""),
                    "hourly": s.get("hourly", False),
                    "daily": s.get("daily", False),
                }
            )

        if not stations:
            return pd.DataFrame()

        df = pd.DataFrame(stations)
        df = df[df["distance_km"] <= radius_km]
        return df.sort_values("distance_km").reset_index(drop=True)

    def _stations_near_library(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        limit: int,
    ) -> pd.DataFrame:
        """Fallback: use the meteostat Python library."""
        try:
            from meteostat import Stations
        except ImportError:
            raise ImportError(
                "meteostat library is required as fallback. Install with: pip install meteostat"
            )

        stations = Stations()
        nearby = stations.nearby(lat, lon, radius_km).fetch(limit)
        if nearby is None or (hasattr(nearby, "empty") and nearby.empty):
            return pd.DataFrame()

        records: list[dict[str, Any]] = []
        for idx, row in nearby.iterrows():
            records.append(
                {
                    "id": str(idx),
                    "name": row.get("name", ""),
                    "country": row.get("country", ""),
                    "region": "",
                    "lat": row.get("latitude", np.nan),
                    "lon": row.get("longitude", np.nan),
                    "elevation": row.get("elevation", np.nan),
                    "distance_km": row.get("distance", np.nan),
                    "start_date": "",
                    "end_date": "",
                    "hourly": True,
                    "daily": True,
                }
            )
        return pd.DataFrame(records)

    def history(
        self,
        station_id: str,
        start: str,
        end: str,
        variables: list[str] | None = None,
    ) -> pd.DataFrame:
        """Fetch historical weather observations for a station.

        Args:
            station_id: Meteostat station ID (e.g. "725300-14819").
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".
            variables: Variables to fetch. Defaults to all available.

        Returns:
            DataFrame indexed by datetime with observation columns.
        """
        if variables is None:
            variables = STATION_VARIABLES

        params: dict[str, Any] = {
            "station": station_id,
            "start": start.replace("-", ""),
            "end": end.replace("-", ""),
            "parameters": ",".join(variables),
        }

        try:
            data = self._get("data/daily", params)
        except (ConnectionError, Exception) as exc:
            logger.warning("Meteostat API failed, trying library: %s", exc)
            return self._history_library(station_id, start, end)

        records: list[dict[str, Any]] = []
        for obs in data.get("data", []):
            record: dict[str, Any] = {
                "date": obs.get("date", ""),
                "temperature_max": obs.get("tmax"),
                "temperature_min": obs.get("tmin"),
                "temperature_mean": obs.get("tavg"),
                "precipitation": obs.get("prcp"),
                "windspeed_max": obs.get("wspd"),
                "winddirection": obs.get("wdir"),
                "windgust_max": obs.get("wpgt"),
                "pressure_mean": obs.get("pres"),
                "humidity_mean": obs.get("rhum"),
                "cloudcover_mean": obs.get("coco"),
                "visibility_mean": obs.get("tsun"),
                "weather": obs.get("coco"),
            }
            records.append(record)

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df

    def _history_library(
        self,
        station_id: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Fallback: use the meteostat Python library for historical data."""
        try:
            from meteostat import Daily
        except ImportError:
            raise ImportError(
                "meteostat library is required as fallback. Install with: pip install meteostat"
            )

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        daily = Daily(station_id, start_dt, end_dt)
        df = daily.fetch()
        if df is None or (hasattr(df, "empty") and df.empty):
            return pd.DataFrame()
        return df

    def history_multi(
        self,
        station_ids: list[str],
        start: str,
        end: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical data for multiple stations.

        Args:
            station_ids: List of Meteostat station IDs.
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".

        Returns:
            Dict mapping station ID to DataFrame.
        """
        result: dict[str, pd.DataFrame] = {}
        for sid in station_ids:
            try:
                df = self.history(sid, start, end)
                if not df.empty:
                    result[sid] = df
            except Exception as exc:
                logger.warning("Failed to fetch history for station %s: %s", sid, exc)
                continue
        return result

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> MeteostatConnector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        auth_status = "authenticated" if self.api_key else "anonymous"
        return f"MeteostatConnector({auth_status})"
