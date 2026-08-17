"""CME Weather Derivatives settlement data connector.

Parses CME weather derivative settlement data including HDD/CDD indices
and Weather Services International (WSI) products. Fetches settlement
prices and historical records for weather derivative analysis.

Example:
    >>> from pakhi.src.cmes import CMEWeatherConnector
    >>> cmes = CMEWeatherConnector(products=["HDD_CME", "CDD_CME"])
    >>> settlements = cmes.latest_settlements()
    >>> hist = cmes.history()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
import requests

__all__ = ["CMEWeatherConnector"]

logger = logging.getLogger(__name__)

CME_PRODUCT_TYPES = Literal["HDD_CME", "CDD_CME", "WSI", "GAS_DD"]

CME_PRODUCTS: dict[str, dict[str, Any]] = {
    "HDD_CME": {
        "name": "Heating Degree Day Futures",
        "description": "NYMEX HDD index based on population-weighted temperature",
        "exchange": "NYMEX",
        "base_temp_f": 65,
        "unit": "index points",
        "tick_value": 20,
        "settlement_url": "https://www.cmegroup.com/CmeWS/mvc/Weather/301/settlements",
    },
    "CDD_CME": {
        "name": "Cooling Degree Day Futures",
        "description": "NYMEX CDD index based on population-weighted temperature",
        "exchange": "NYMEX",
        "base_temp_f": 65,
        "unit": "index points",
        "tick_value": 20,
        "settlement_url": "https://www.cmegroup.com/CmeWS/mvc/Weather/302/settlements",
    },
    "WSI": {
        "name": "Weather Services International Index",
        "description": "WSI regional temperature index futures",
        "exchange": "NYMEX",
        "base_temp_f": 65,
        "unit": "index points",
        "tick_value": 20,
    },
    "GAS_DD": {
        "name": "Natural Gas Degree Day Futures",
        "description": "Gas-weighted heating degree day futures",
        "exchange": "NYMEX",
        "base_temp_f": 65,
        "unit": "index points",
        "tick_value": 50,
    },
}

# Regional definitions for CME weather derivatives
CME_REGIONS: dict[str, dict[str, Any]] = {
    "CHICAGO": {"name": "Chicago", "lat": 41.88, "lon": -87.63},
    "NEW_YORK": {"name": "New York City", "lat": 40.71, "lon": -74.01},
    "LOS_ANGELES": {"name": "Los Angeles", "lat": 34.05, "lon": -118.24},
    "DALLAS": {"name": "Dallas", "lat": 32.78, "lon": -96.80},
    "ATLANTA": {"name": "Atlanta", "lat": 33.75, "lon": -84.39},
    "DENVER": {"name": "Denver", "lat": 39.74, "lon": -104.99},
    "MINNEAPOLIS": {"name": "Minneapolis", "lat": 44.98, "lon": -93.27},
    "PHOENIX": {"name": "Phoenix", "lat": 33.45, "lon": -112.07},
    "SEATTLE": {"name": "Seattle", "lat": 47.61, "lon": -122.33},
    "MIAMI": {"name": "Miami", "lat": 25.76, "lon": -80.19},
    "US_NATIONAL": {"name": "US National", "lat": None, "lon": None},
}


class CMEWeatherConnector:
    """Connector for CME weather derivative settlement data.

    Fetches and parses settlement prices for CME weather futures including
    HDD (Heating Degree Day), CDD (Cooling Degree Day), and WSI products.

    Args:
        products: List of CME product codes — "HDD_CME", "CDD_CME", "WSI", "GAS_DD".
        regions: List of region codes from CME_REGIONS.
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum retry attempts.

    Example:
        >>> cmes = CMEWeatherConnector(
        ...     products=["HDD_CME", "CDD_CME"],
        ...     regions=["CHICAGO", "NEW_YORK"],
        ... )
        >>> settlements = cmes.latest_settlements()
    """

    def __init__(
        self,
        products: list[str] | None = None,
        regions: list[str] | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        if products is None:
            products = ["HDD_CME", "CDD_CME"]
        for p in products:
            if p not in CME_PRODUCTS:
                raise ValueError(f"Unknown product '{p}'. Available: {sorted(CME_PRODUCTS.keys())}")
        if regions is None:
            regions = ["US_NATIONAL"]
        for r in regions:
            if r not in CME_REGIONS:
                raise ValueError(f"Unknown region '{r}'. Available: {sorted(CME_REGIONS.keys())}")

        self.products = products
        self.regions = regions
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "pakhi-weather-quant/0.1",
                "Accept": "application/json",
            }
        )

    def _fetch_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Fetch JSON from a URL with retry logic."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Request failed (attempt %d): %s", attempt, exc)
                if attempt < self.max_retries:
                    import time

                    time.sleep(2**attempt)
        raise ConnectionError(
            f"Failed to fetch CME data after {self.max_retries} attempts"
        ) from last_exc

    def _parse_cme_settlements(self, raw_data: Any, product: str) -> pd.DataFrame:
        """Parse raw CME settlement response into a DataFrame."""
        records: list[dict[str, Any]] = []
        product_info = CME_PRODUCTS[product]

        if isinstance(raw_data, dict):
            settlements = raw_data.get("settlements", raw_data.get("data", []))
        elif isinstance(raw_data, list):
            settlements = raw_data
        else:
            return pd.DataFrame()

        for item in settlements:
            if isinstance(item, dict):
                record: dict[str, Any] = {
                    "product": product,
                    "product_name": product_info["name"],
                    "exchange": product_info["exchange"],
                    "settlement_date": item.get("settlementDate", item.get("date", "")),
                    "month": item.get("month", item.get("contractMonth", "")),
                    "settlement_price": item.get("settlementPrice", item.get("last", None)),
                    "change": item.get("change", item.get("netChange", None)),
                    "volume": item.get("volume", item.get("totalVolume", 0)),
                    "open_interest": item.get("openInterest", 0),
                    "region": item.get("region", "US_NATIONAL"),
                }
                try:
                    if record["settlement_price"] is not None:
                        record["settlement_price"] = float(record["settlement_price"])
                except (ValueError, TypeError):
                    record["settlement_price"] = None
                records.append(record)

        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)

    def _fetch_settlements_from_api(self, product: str) -> pd.DataFrame:
        """Try fetching settlements from CME API endpoints."""
        product_info = CME_PRODUCTS[product]
        url = product_info.get("settlement_url")
        if not url:
            return self._generate_synthetic_settlements(product)

        try:
            data = self._fetch_json(url)
            return self._parse_cme_settlements(data, product)
        except Exception as exc:
            logger.warning("CME API fetch failed for %s: %s", product, exc)
            return self._generate_synthetic_settlements(product)

    def _generate_synthetic_settlements(self, product: str) -> pd.DataFrame:
        """Generate placeholder settlements when API is unavailable.

        Returns a DataFrame with the correct schema but null values,
        so downstream code doesn't break on missing data.
        """
        logger.info("Generating placeholder settlements for %s (CME API unavailable)", product)
        product_info = CME_PRODUCTS[product]
        today = datetime.now(timezone.utc)
        months = []
        for i in range(1, 13):
            m = today.month + i
            y = today.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            months.append(f"{y}-{m:02d}")

        records = [
            {
                "product": product,
                "product_name": product_info["name"],
                "exchange": product_info["exchange"],
                "settlement_date": today.strftime("%Y-%m-%d"),
                "month": month,
                "settlement_price": None,
                "change": None,
                "volume": 0,
                "open_interest": 0,
                "region": "US_NATIONAL",
            }
            for month in months
        ]
        return pd.DataFrame(records)

    def latest_settlements(self) -> pd.DataFrame:
        """Fetch the most recent settlement data for all products.

        Returns:
            DataFrame with settlement prices, volumes, and open interest.
        """
        frames: list[pd.DataFrame] = []
        for product in self.products:
            df = self._fetch_settlements_from_api(product)
            if not df.empty:
                frames.append(df)

        if not frames:
            raise RuntimeError("No settlement data could be fetched")
        return pd.concat(frames, ignore_index=True)

    def history(
        self,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical settlement data.

        Attempts to pull historical settlements from the CME website.
        Falls back to synthetic data structure if the API is unavailable.

        Args:
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".

        Returns:
            DataFrame with historical settlement records.
        """
        all_records: list[pd.DataFrame] = []
        for product in self.products:
            try:
                df = self._fetch_settlements_from_api(product)
                if not df.empty:
                    if start:
                        df = df[df["settlement_date"] >= start]
                    if end:
                        df = df[df["settlement_date"] <= end]
                    all_records.append(df)
            except Exception as exc:
                logger.warning("History fetch failed for %s: %s", product, exc)
                continue

        if not all_records:
            return self._generate_synthetic_settlements(self.products[0])
        return pd.concat(all_records, ignore_index=True)

    def compute_hdd(
        self,
        temperature_series: pd.Series,
        base_temp_f: float = 65.0,
    ) -> pd.Series:
        """Compute Heating Degree Days from a temperature time series.

        Args:
            temperature_series: Daily mean temperature in Fahrenheit.
            base_temp_f: Base temperature for HDD calculation.

        Returns:
            Series of daily HDD values.
        """
        temp_f = temperature_series.copy()
        # Auto-detect Celsius. Celsius daily means for HDD contexts rarely
        # exceed 40 C; a Fahrenheit winter series can legitimately max < 50 F
        # (e.g. ~10 C), so we only convert when the maximum is below 40.
        if temp_f.max() < 40:  # Likely Celsius
            temp_f = temp_f * 9.0 / 5.0 + 32.0
        hdd = (base_temp_f - temp_f).clip(lower=0)
        hdd.name = "HDD"
        return hdd

    def compute_cdd(
        self,
        temperature_series: pd.Series,
        base_temp_f: float = 65.0,
    ) -> pd.Series:
        """Compute Cooling Degree Days from a temperature time series.

        Args:
            temperature_series: Daily mean temperature in Fahrenheit.
            base_temp_f: Base temperature for CDD calculation.

        Returns:
            Series of daily CDD values.
        """
        temp_f = temperature_series.copy()
        # Auto-detect Celsius. Celsius daily means for CDD contexts rarely
        # exceed 40 C; a Fahrenheit series can legitimately max < 50 F, so we
        # only convert when the maximum is below 40.
        if temp_f.max() < 40:  # Likely Celsius
            temp_f = temp_f * 9.0 / 5.0 + 32.0
        cdd = (temp_f - base_temp_f).clip(lower=0)
        cdd.name = "CDD"
        return cdd

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> CMEWeatherConnector:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"CMEWeatherConnector(products={self.products}, regions={self.regions})"
