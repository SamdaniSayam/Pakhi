# Data Sources

Pakhi supports multiple weather and financial data sources. Here's how to
access each one, from free/open to registration-required.

## Free — No API Key Required

### Open-Meteo
**Best for**: Quick prototyping, historical weather, forecasts.
```python
from pakhi.src.openmeteo import OpenMeteoConnector

api = OpenMeteoConnector()
forecast = api.forecast(lat=28.5, lon=-81.5, days=7)
history = api.historical(start="2020-01-01", end="2023-12-31", lat=28.5, lon=-81.5)
```
- URL: https://open-meteo.com
- Rate limit: 10,000 requests/day
- No account needed

### NOAA GFS via NOMADS
**Best for**: Operational global forecast model data (0.25° grid, 16-day forecast).
```python
from pakhi.src.noaa import GFSConnector

gfs = GFSConnector(variable=["temperature_2m", "wind_10m"])
latest = gfs.latest()
```
- URL: https://nomads.ncep.noaa.gov
- Direct download, no account needed
- Updated every 6 hours (00Z, 06Z, 12Z, 18Z)
- GRIB2 format

### GOES Satellite via AWS S3
**Best for**: Real-time satellite imagery, convective monitoring.
```python
from pakhi.src.satellite import GOESConnector

goes = GOESConnector(product="ABI-L2-CMI")
data = goes.latest(domain="full_disk")
```
- AWS S3 bucket: `noaa-goes16`
- No AWS account needed for public buckets
- Use `s3fs` or direct HTTP: `https://noaa-goes16.s3.amazonaws.com/`

### Meteostat
**Best for**: Historical station observations.
```python
from pakhi.src.meteostat import MeteostatConnector

ms = MeteostatConnector()
observations = ms.daily(station_id="722030-12839", start="2020-01-01", end="2023-12-31")
```
- https://meteostat.net
- Free tier available

## Free — Requires Registration

### ERA5 (ECMWF Copernicus)
**Best for**: High-quality global reanalysis (1979–present, 0.25° grid).
```python
from pakhi.src.era5 import ERA5Connector

era5 = ERA5Connector()
data = era5.fetch(
    variables=["2m_temperature", "10m_wind"],
    area=[30, -85, 25, -80],  # [N, W, S, E]
    start="2023-01-01",
    end="2023-12-31",
)
```
1. Register at https://cds.climate.copernicus.eu
2. Install: `pip install cdsapi`
3. Create `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api/v2
   key: YOUR_UID:YOUR_API_KEY
   ```
4. Accept the ERA5 license agreement at the CDS portal

### CME Weather Derivatives
**Best for**: Weather derivative pricing, HDD/CDD index futures.
```python
from pakhi.src.cmes import CMEWeatherConnector

cme = CMEWeatherConnector()
hdd_index = cme.hdd_index(city="CHICAGO", month="2024-01")
```
- https://www.cmegroup.com
- Market data may require CME DataMine subscription for full history

## Financial Data

### Yahoo Finance
**Best for**: Commodity futures (OJ, nat gas, crude), equities.
```python
from pakhi.src.yahoo import YahooFuturesConnector

yahoo = YahooFuturesConnector()
oj_data = yahoo.download(symbol="OJ=F", start="2020-01-01", end="2024-01-01")
ng_data = yahoo.download(symbol="NG=F", start="2020-01-01", end="2024-01-01")
```
- Install: `pip install yfinance`
- Free, no API key
- Rate-limited; cache results locally

## Sample Data

The `data/sample/` directory contains pre-downloaded datasets for examples
and notebooks. See individual files for format documentation.

## Data Caching

Pakhi includes a local cache to avoid redundant downloads:

```python
from pakhi.pipeline.cache import WeatherCache

cache = WeatherCache(cache_dir="~/.pakhi/cache")
# All connectors can optionally use the cache:
api = OpenMeteoConnector()
# ... (cache integration via pipeline layer)
```

## Recommendations

| Use Case | Source | Cost |
|----------|--------|------|
| Prototyping | Open-Meteo | Free |
| Operational forecasting | GFS (NOMADS) | Free |
| Historical analysis | ERA5 | Free (registration) |
| Satellite nowcasting | GOES-16/18 (AWS) | Free |
| Commodity trading | Yahoo Finance | Free |
| Weather derivatives | CME | Subscription |
| Station observations | Meteostat | Free |
