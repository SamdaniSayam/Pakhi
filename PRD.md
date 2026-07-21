# Pakhi — Product Requirements Document

**Version:** 1.0.0-draft
**Date:** July 2026
**Author:** Megh Megha (Megh Megha) — TripleS Studio
**Status:** Draft

---

## 1. Executive Summary

### What is Pakhi?

Pakhi (Bengali: পাখি, meaning "bird") is an open-source weather intelligence
and quantitative trading platform. Birds are living barometers and acoustic
sensors — they detect approaching storms, pressure changes, and atmospheric
disturbances long before human instruments register them. Pakhi does the
same: it ingests raw meteorological data from satellites, reanalysis, and
forecast models, then transforms it into tradeable signals for commodities,
power grids, and climate risk derivatives.

### Why "Pakhi"?

> *"A flock of birds changes direction 48 hours before a storm hits.
> We built software that does the same thing — but for markets."*

Birds are the original weather forecasters. They sense barometric pressure,
humidity, and infrasound from distant weather systems. Pakhi is the digital
equivalent: an early-warning system for weather-driven financial risk.

### The Problem

- Climate change has increased weather volatility by 40% since 2000
- A single hurricane costs $100B+ in damages; a freeze destroys $1B in crops
- Energy traders lose millions from 24-hour forecast errors
- Existing tools (DTN, CelsiusPro, Tomorrow.io) are closed, expensive, or
  consumer-focused
- No open-source platform connects raw weather data → ML forecasts →
  tradeable signals in a single pipeline

### The Solution

Pakhi provides:
1. **Data ingestion** — Ingest NOAA GFS, ECMWF ERA5, GOES satellite, and
   commercial feeds in streaming pipelines
2. **ML forecasting** — Ensemble of statistical and deep learning models
   (LSTM, XGBoost, Gaussian Process) trained on historical reanalysis
3. **Signal generation** — Convert forecasts into tradeable signals for
   futures (OJ, nat gas, heating oil), power markets (PJM, ERCOT), and
   insurance (catastrophe bonds)
4. **Risk quantification** — Uncertainty quantification via ensemble spread
   and Bayesian confidence intervals

### Target Users

| Persona | What They Need | Pakhi Delivers |
|---------|---------------|----------------|
| **Energy Trader** | 48-hour wind/solar/power price forecast | Grid-level wind/solar irradiance + power price signal |
| **Commodity Hedge Fund** | 7-day freeze/drought probability | Freeze probability → OJ/nat gas futures signal |
| **Reinsurance Analyst** | Hurricane track + intensity probability | 5-day tropical cyclone risk assessment |
| **Agricultural Trader** | Growing degree days, precipitation, frost | Crop yield impact model → grain futures signal |
| **Power Grid Operator** | 15-minute load forecast, heatwave alert | Grid stress indicator + demand response signal |
| **Insurance Quant** | Extreme event frequency, catastrophe probability | Cat bond pricing model + tail risk metric |

---

## 2. Architecture

### 2.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Pakhi Platform                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │  pakhi.src  │  │ pakhi.grids │  │ pakhi.feeds │                │
│  │  Data Source │  │  Grid Ops   │  │  Real-Time  │                │
│  │  Connectors │  │  Interpolate│  │  Streams    │                │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                │
│         │                 │                 │                        │
│         └────────────┬────┴────────┬────────┘                        │
│                      ▼             ▼                                  │
│              ┌──────────────────────────────┐                       │
│              │     pakhi.pipeline            │                       │
│              │  Streaming Data Pipeline      │                       │
│              │  (SigPipeline from sigfast)   │                       │
│              └──────────────┬───────────────┘                       │
│                             │                                        │
│                ┌────────────┴────────────┐                          │
│                ▼                         ▼                           │
│    ┌───────────────────┐   ┌───────────────────┐                   │
│    │  pakhi.features   │   │  pakhi.targets    │                   │
│    │  Feature Engine   │   │  Target Variables │                   │
│    │  (rolling, lag,   │   │  (temp, precip,   │                   │
│    │   anomaly, HDA)   │   │   wind, pressure) │                   │
│    └────────┬──────────┘   └────────┬──────────┘                   │
│             │                       │                                │
│             └───────────┬───────────┘                                │
│                         ▼                                            │
│           ┌─────────────────────────────┐                           │
│           │      pakhi.models           │                           │
│           │  ML Forecasting Engine      │                           │
│           │  ┌────────┐ ┌────────────┐ │                           │
│           │  │ LSTM   │ │ XGBoost    │ │                           │
│           │  ├────────┤ ├────────────┤ │                           │
│           │  │ GP     │ │ Ensemble   │ │                           │
│           │  └────────┘ └────────────┘ │                           │
│           └─────────────┬───────────────┘                           │
│                         │                                            │
│           ┌─────────────┴───────────────┐                           │
│           │      pakhi.predict          │                           │
│           │  Forecast Generation        │                           │
│           │  + Uncertainty Quantification│                           │
│           └─────────────┬───────────────┘                           │
│                         │                                            │
│           ┌─────────────┴───────────────┐                           │
│           │      pakhi.signals          │                           │
│           │  Trade Signal Engine        │                           │
│           │  (probability → position)   │                           │
│           └─────────────┬───────────────┘                           │
│                         │                                            │
│           ┌─────────────┴───────────────┐                           │
│           │      pakhi.risk             │                           │
│           │  Risk Metrics & Alerts      │                           │
│           │  (VaR, CVaR, Brier Score)   │                           │
│           └─────────────────────────────┘                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                     │
         ▼                    ▼                     ▼
  ┌──────────┐       ┌──────────┐         ┌──────────────┐
  │ NOAA GFS │       │ ERA5     │         │ CME Weather  │
  │ HRRR/NAM │       │ ECMWF    │         │ Yahoo Finance│
  │ GOES-16  │       │ Meteostat│         │ PJM/ERCOT    │
  └──────────┘       └──────────┘         └──────────────┘
```

### 2.2 Directory Structure

```
pakhi/
├── pyproject.toml
├── PRD.md
├── README.md
├── LICENSE
├── CHANGELOG.md
│
├── pakhi/
│   ├── __init__.py
│   ├── __version__.py
│   │
│   ├── src/                    # Data source connectors
│   │   ├── __init__.py
│   │   ├── noaa.py             # GFS, HRRR, NAM, NDFD
│   │   ├── ecmwf.py            # ECMWF IFS operational
│   │   ├── era5.py             # ERA5 reanalysis (CDS API)
│   │   ├── satellite.py        # GOES-16/17, Meteosat
│   │   ├── meteostat.py        # Meteostat historical
│   │   ├── openmeteo.py        # Open-Meteo API (free forecasts)
│   │   ├── cmes.py             # CME weather derivative settlements
│   │   └── yahoo.py            # Yahoo Finance commodity futures
│   │
│   ├── grids/                  # Grid operations & interpolation
│   │   ├── __init__.py
│   │   ├── interpolate.py      # Bilinear, nearest, kriging
│   │   ├── regridder.py        # Resolution conversion (0.25° → 3km)
│   │   ├── subset.py           # Spatial subsetting (bbox, polygon)
│   │   └── coordinate.py       # Lat/lon, CRS transforms
│   │
│   ├── pipeline/               # Data streaming engine
│   │   ├── __init__.py
│   │   ├── stream.py           # Out-of-core streaming (from sigfast)
│   │   ├── chunk.py            # Chunked processing for GRIB/NetCDF
│   │   ├── cache.py            # LRU/Disk caching for API calls
│   │   └── schedule.py         # Cron-like refresh scheduling
│   │
│   ├── features/               # Feature engineering
│   │   ├── __init__.py
│   │   ├── temporal.py         # Lag features, rolling stats, EMA
│   │   ├── spatial.py          # Distance-weighted averages, gradient
│   │   ├── climate.py          # HDD, CDD, growing degree days
│   │   ├── anomaly.py          # Z-score, percentile, departure from norm
│   │   ├── teleconnection.py   # ENSO, NAO, PDO indices
│   │   └── satellite.py        # Brightness temp, cloud motion vectors
│   │
│   ├── targets/                # Target variable computation
│   │   ├── __init__.py
│   │   ├── temperature.py      # Freeze probability, heat index, HDD/CDD
│   │   ├── precipitation.py    # Rain/snow accumulation, probability
│   │   ├── wind.py             # Wind speed, gust, power curve mapping
│   │   ├── pressure.py         # Central pressure, storm surge
│   │   ├── solar.py            # GHI, DNI, cloud cover
│   │   └── hurricane.py        # Track, intensity, rapid intensification
│   │
│   ├── models/                 # ML forecasting models
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract model interface
│   │   ├── lstm.py             # LSTM / BiLSTM
│   │   ├── transformer.py      # Temporal Fusion Transformer
│   │   ├── gradient.py         # XGBoost / LightGBM
│   │   ├── gaussian.py         # Gaussian Process regression
│   │   ├── ensemble.py         # Model stacking, blending, weighting
│   │   ├── persistence.py      # Naive persistence baseline
│   │   └── climatology.py      # Climatological baseline (30-year mean)
│   │
│   ├── predict/                # Forecast generation
│   │   ├── __init__.py
│   │   ├── deterministic.py    # Single best forecast
│   │   ├── probabilistic.py    # Ensemble, quantile, MC dropout
│   │   ├── multi_step.py       # Autoregressive 1→7 day rollout
│   │   └── verification.py     # RMSE, ACC, Brier skill score, CRPS
│   │
│   ├── signals/                # Trading signal generation
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract signal interface
│   │   ├── freeze.py           # Freeze → OJ/nat gas/ethanol signal
│   │   ├── heat.py             # Heatwave → power, cooling demand signal
│   │   ├── hurricane.py        # Hurricane → nat gas, power, insurance signal
│   │   ├── drought.py          # Drought → grain, water signal
│   │   ├── wind.py             # Wind forecast → power generation signal
│   │   └── ensemble.py         # Multi-instrument signal combination
│   │
│   ├── risk/                   # Risk metrics & alerts
│   │   ├── __init__.py
│   │   ├── metrics.py          # VaR, CVaR, Brier score, reliability
│   │   ├── uncertainty.py      # Ensemble spread, calibration
│   │   ├── alerts.py           # Freeze/heat/hurricane alert system
│   │   └── backtest.py         # Historical signal backtesting engine
│   │
│   ├── trading/                # Trading infrastructure
│   │   ├── __init__.py
│   │   ├── portfolio.py        # Position sizing, Kelly criterion
│   │   ├── instruments.py      # Instrument definitions (OJ, nat gas, etc.)
│   │   ├── execution.py        # Broker API hooks (IB, Alpaca)
│   │   └── pnl.py             # Profit/loss tracking, Sharpe, max DD
│   │
│   └── viz/                    # Visualization
│       ├── __init__.py
│       ├── maps.py             # Geographic forecast maps
│       ├── timeseries.py       # Forecast vs obs time series
│       ├── ensemble.py         # Ensemble plume diagrams
│       └── dashboard.py        # Terminal dashboard (plotext)
│
├── tests/
│   ├── test_src/
│   ├── test_grids/
│   ├── test_features/
│   ├── test_models/
│   ├── test_signals/
│   └── test_risk/
│
├── examples/
│   ├── 01_freeze_detection.py
│   ├── 02_power_forecast.py
│   ├── 03_hurricane_risk.py
│   ├── 04_historical_backtest.py
│   └── 05_full_pipeline.py
│
├── notebooks/
│   ├── 01_quickstart.ipynb
│   ├── 02_feature_engineering.ipynb
│   ├── 03_model_training.ipynb
│   ├── 04_signal_backtest.ipynb
│   └── 05_trading_simulation.ipynb
│
├── data/
│   ├── README.md              # Instructions for obtaining data
│   ├── sample/                # Sample GRIB/CSV for testing
│   └── cache/                 # Cached API responses (.gitignore)
│
└── docs/
    ├── architecture.md
    ├── data_sources.md
    ├── models.md
    ├── signals.md
    └── deployment.md
```

---

## 3. Module Specifications

### 3.1 pakhi.src — Data Source Connectors

#### 3.1.1 NOAA GFS Connector

```
Purpose:  Ingest Global Forecast System (GFS) operational model output
Format:   GRIB2 (0.25° resolution, 16-day forecast)
Source:   NOAA NOMADS (nomads.ncep.noaa.gov) — free, real-time
Variables:
  - Temperature (2m, 850hPa, 500hPa)
  - Wind (10m u/v, 250hPa jet stream)
  - Precipitation (total, convective)
  - Geopotential height (500hPa — steering flow)
  - Relative humidity (multiple levels)
  - Mean sea level pressure
Refresh:  Every 6 hours (00Z, 06Z, 12Z, 18Z)
Lag:      3-4 hours from initialization

API Design:
  from pakhi.src.noaa import GFSConnector

  gfs = GFSConnector(
      variable=["temperature_2m", "wind_10m", "precipitation"],
      bbox=[-125, 24, -66, 50],      # CONUS
      resolution="0.25",
  )

  # Latest forecast as xarray.Dataset
  forecast = gfs.latest()

  # Historical forecasts for training
  archive = gfs.archive(start="2020-01-01", end="2025-12-31")
```

#### 3.1.2 ERA5 Reanalysis Connector

```
Purpose:  Ingest ERA5 reanalysis (1940-present) for training ML models
Format:   NetCDF / Zarr
Source:   Copernicus Climate Data Store (CDS API) — free, requires account
Variables: Full atmospheric state (137 pressure levels, surface)
Resolution: 0.25° hourly (or 0.1° with climate reanalysis)
Lag:      5-10 days (near-real-time)
License:  Copernicus License (free for research/commercial use)

API Design:
  from pakhi.src.era5 import ERA5Connector

  era5 = ERA5Connector(
      variables=["temperature_2m", "msl", "wind_10m_u", "wind_10m_v"],
      pressure_levels=[850, 500],
  )

  # Monthly data for training (lazy Dask loading)
  training_data = era5.fetch(
      start="2010-01-01",
      end="2024-12-31",
      bbox=[-125, 24, -66, 50],
      chunks={"time": 365},  # Lazy chunking
  )
```

#### 3.1.3 GOES Satellite Connector

```
Purpose:  Ingest GOES-16/17/18 Geostationary Satellite data
Format:   NetCDF4 (AWS S3 bucket)
Source:   NOAA Open Data on AWS — free, real-time
Variables:
  - Band 08-10: Water vapor channels (mid/upper troposphere)
  - Band 13: Clean IR longwave (cloud top temperature)
  - Band 14: IR longwave (cloud/precipitation)
  - Cloud motion vectors (derived)
Refresh:  Every 5-15 minutes
Resolution: 2km (VIS), 10km (IR) at nadir

API Design:
  from pakhi.src.satellite import GOESConnector

  goes = GOESConnector(
      satellite="GOES-16",
      bands=["band_13", "band_14"],
      sector="CONUS",
  )

  # Latest image as xarray.DataArray
  image = goes.latest()

  # Derived: cloud motion vectors for wind estimation
  vectors = goes.cloud_motion(minutes=60)
```

#### 3.1.4 Commodity Data Connectors

```
Purpose:  Ingest commodity futures prices, weather derivatives, grid data
Source:   Yahoo Finance, CME, PJM/ERCOT APIs

API Design:
  from pakhi.src.cmes import CMEWeatherConnector
  from pakhi.src.yahoo import YahooFuturesConnector

  cmes = CMEWeatherConnector(products=["HDD_CME", "CDD_CME", "OJ"])
  settlements = cmes.latest_settlements()

  yahoo = YahooFuturesConnector(tickers=["CL=F", "NG=F", "OJ=F"])
  prices = yahoo.history(period="2y")
```

---

### 3.2 pakhi.grids — Grid Operations

#### 3.2.1 Interpolation

```
Purpose:  Convert gridded data to point locations or between grids
Methods:
  - Bilinear (fast, smooth)
  - Nearest neighbor (fast, exact value)
  - Cressman (distance-weighted, meteorological standard)
  - Kriging (geostatistical, best for sparse observations)

API Design:
  from pakhi.grids import interpolate_to_point, regrid

  # Point extraction
  temp_at_chicago = interpolate_to_point(
      grid_data=forecast,
      lat=41.8781,
      lon=-87.6298,
      method="cressman",
      search_radius_km=100,
  )

  # Regridding (0.25° → 3km for HRRR comparison)
  regridded = regrid(
      source=era5_data,
      target_grid=hrrr_grid,
      method="bilinear",
  )
```

---

### 3.3 pakhi.features — Feature Engineering

#### 3.3.1 Temporal Features

```
Purpose:  Generate time-lagged and rolling statistical features
Leverages: triples-sigfast rolling_average, ema, detect_anomalies

API Design:
  from pakhi.features.temporal import TemporalFeatures

  tf = TemporalFeatures()
  features = tf.build(
      data=forecast,
      lags=[1, 3, 6, 12, 24, 48, 72, 168],  # hours
      windows=[6, 12, 24, 48, 168],
      stats=["mean", "std", "min", "max", "trend", "anomaly"],
  )
  # Output: xarray.Dataset with 50+ temporal features per variable
```

#### 3.3.2 Teleconnection Indices

```
Purpose:  Compute ENSO, NAO, PDO, MJO indices from reanalysis
Why:      Large-scale climate patterns drive seasonal forecasts

API Design:
  from pakhi.features.teleconnection import compute_nino34, compute_nao

  nino34 = compute_nino34(era5_sst)     # Sea surface temp anomaly
  nao = compute_nao(era5_pressure)       # North Atlantic Oscillation
  mjo = compute_mjo(era5_outgoing_lw)    # Madden-Julian Oscillation
```

#### 3.3.3 Climate Indices

```
Purpose:  Compute heating/cooling degree days, growing degree days
Leverages: triples-sigfast signal processing for smoothing

API Design:
  from pakhi.features.climate import hdd, cdd, gdd

  heating = hdd(temperature, base_celsius=18.3)   # CDD for heating
  cooling = cdd(temperature, base_celsius=18.3)    # CDD for cooling
  growing = gdd(temperature, base_celsius=10.0)    # Crop growth
```

---

### 3.4 pakhi.targets — Target Variables

#### 3.4.1 Freeze Probability

```
Purpose:  Compute probability of temperature ≤ 0°C over forecast window
Relevance: Orange juice, citrus, ethanol, natural gas (heating demand)

API Design:
  from pakhi.targets.temperature import freeze_probability

  prob = freeze_probability(
      temperature_forecast=forecast_2m,
      threshold_celsius=0.0,
      window_days=7,
      method="ensemble_mean",        # or "quantile_10"
  )
  # Returns: float (0.0 to 1.0)
```

#### 3.4.2 Wind Power Forecast

```
Purpose:  Convert wind speed forecasts to power generation estimates
Relevance: Power grid trading (PJM, ERCOT, SPP markets)

API Design:
  from pakhi.targets.wind import power_curve, wind_power_forecast

  # Apply turbine power curve (Cp × ½ρAv³)
  power = power_curve(
      wind_speed=forecast_10m,
      turbine="vestas_v110",     # Reference turbine
      hub_height_m=80,
  )

  # Aggregate to wind farm level
  farm_output = wind_power_forecast(power, farm_capacity_mw=200)
```

---

### 3.5 pakhi.models — ML Forecasting

#### 3.5.1 Model Interface

```
All models implement a common interface:

  class WeatherModel(Protocol):
      def fit(self, X_train, y_train, X_val=None, y_val=None) -> None: ...
      def predict(self, X) -> ForecastResult: ...
      def predict_proba(self, X, quantiles=[0.1, 0.5, 0.9]) -> ForecastResult: ...
      def score(self, X, y, metrics=["rmse", "acc", "crps"]) -> dict: ...
```

#### 3.5.2 LSTM Forecaster

```
Architecture:
  - 2-layer BiLSTM with 128 hidden units per layer
  - Temporal attention mechanism
  - Input: 168 hours (7 days) of feature history
  - Output: 168 hours (7 days) forecast, hourly
  - Probabilistic: MC Dropout (50 forward passes)

Training:
  - Loss: Pinball loss (for quantile regression)
  - Optimizer: AdamW (lr=1e-3, weight_decay=1e-5)
  - Early stopping: patience=10 epochs
  - Batch size: 256 (GPU), 64 (CPU)
  - Framework: PyTorch

API Design:
  from pakhi.models.lstm import LSTMForecaster

  model = LSTMForecaster(
      input_dim=50,
      hidden_dim=128,
      n_layers=2,
      dropout=0.2,
      forecast_horizon=168,    # 7 days hourly
      quantiles=[0.1, 0.25, 0.5, 0.75, 0.9],
  )

  model.fit(X_train, y_train, X_val, y_val, epochs=100)
  result = model.predict(X_test)

  # result.deterministic  → best guess forecast
  # result.quantiles      → uncertainty bounds
  # result.skill_scores   → RMSE, ACC, CRPS
```

#### 3.5.3 Gradient Boosting (XGBoost/LightGBM)

```
Purpose:  Fast, tabular features → forecast. Best for operational speed.
Why:      1000× faster than LSTM, nearly as accurate for tabular data

API Design:
  from pakhi.models.gradient import GradientForecaster

  model = GradientForecaster(
      backend="lightgbm",         # or "xgboost"
      n_estimators=2000,
      max_depth=8,
      learning_rate=0.05,
      objective="quantile",
      quantiles=[0.1, 0.5, 0.9],
  )
```

#### 3.5.4 Gaussian Process

```
Purpose:  Principled uncertainty quantification for small datasets
Why:      Gives true confidence intervals, not approximations
Trade-off: Slow (O(n³)) — use for daily trading, not real-time

API Design:
  from pakhi.models.gaussian import GaussianForecaster

  model = GaussianForecaster(
      kernel="matern52",
      n_inducing=500,           # Sparse GP approximation
      noise_prior="log_normal",
  )
```

#### 3.5.5 Ensemble Model

```
Purpose:  Combine multiple models optimally
Methods:
  - Simple averaging
  - Bayesian model averaging (BMA)
  - Stacking (meta-learner on model outputs)
  - Dynamical weighting based on recent skill

API Design:
  from pakhi.models.ensemble import EnsembleForecaster

  ensemble = EnsembleForecaster(
      models=[lstm_model, xgb_model, gp_model],
      method="bma",             # Bayesian Model Averaging
      retrain_window_days=30,   # Retrain weights monthly
  )

  # Ensemble forecast with better uncertainty than any single model
  forecast = ensemble.predict(X_test)
```

---

### 3.6 pakhi.signals — Trading Signals

#### 3.6.1 Freeze Signal

```
Relevance:  Orange juice futures, ethanol, natural gas heating demand
Logic:
  1. Forecast freeze probability over next 7 days for Florida citrus region
  2. Historical: freeze → OJ futures spike 15-40% within 48 hours
  3. Signal: probability × expected magnitude × time decay

API Design:
  from pakhi.signals.freeze import FreezeSignal

  signal = FreezeSignal(
      region="florida_citrus",          # -82 to -80, 24 to 28 lat/lon
      instruments=["OJ_FUTURES", "ETHANOL_FUTURES"],
      entry_threshold=0.65,             # 65% freeze probability
      exit_threshold=0.30,
      position_sizing="kelly",
  )

  trade = signal.generate(forecast)
  # trade.action    → "LONG" / "SHORT" / "FLAT"
  # trade.size      → fraction of portfolio
  # trade.confidence → Bayesian confidence
```

#### 3.6.2 Power Grid Signal

```
Relevance:  Wholesale electricity markets (PJM, ERCOT, CAISO)
Logic:
  1. Forecast temperature and wind speed → predict demand (CDD/HDD) and supply (wind)
  2. Price model: price = f(demand, supply, fuel_cost, congestion)
  3. Signal: buy/sell power futures when model predicts price deviation

API Design:
  from pakhi.signals.heat import PowerSignal

  signal = PowerSignal(
      market="ERCOT",
      instruments=["ERCOT_FUTURES"],
      demand_model="hdd_cdd",
      supply_model="wind_power_curve",
  )
```

#### 3.6.3 Hurricane Signal

```
Relevance:  Nat gas futures, reinsurance, catastrophe bonds
Logic:
  1. Track forecast cone from GFS/ECMWF
  2. Compute landfall probability by region
  3. Expected energy disruption = f(category, population, infrastructure_age
  4. Signal: nat gas spike if Gulf production shut in

API Design:
  from pakhi.signals.hurricane import HurricaneSignal

  signal = HurricaneSignal(
      basin="ATL",
      instruments=["NG_FUTURES", "CAT_BONDS"],
      lead_days=5,
      landfall_threshold=0.3,
  )
```

---

### 3.7 pakhi.risk — Risk Metrics & Backtesting

#### 3.7.1 Forecast Verification Metrics

```
API Design:
  from pakhi.risk.metrics import brier_skill_score, crps, reliability

  # Brier Skill Score (vs climatology baseline)
  bss = brier_skill_score(forecast_prob, observed, climatology)
  # > 0.0 means better than climatology
  # 1.0 means perfect

  # Continuous Ranked Probability Score
  crps_val = crps(forecast_ensemble, observed)

  # Reliability diagram data (calibration)
  reliability_data = reliability(forecast_prob, observed, n_bins=10)
```

#### 3.7.2 Trading Backtest Engine

```
API Design:
  from pakhi.risk.backtest import BacktestEngine

  engine = BacktestEngine(
      signal=freeze_signal,
      instrument="OJ_FUTURES",
      start="2015-01-01",
      end="2025-12-31",
      initial_capital=1_000_000,
      commission_bps=5,
      slippage_bps=10,
  )

  results = engine.run()
  # results.sharpe_ratio
  # results.max_drawdown
  # results.total_return
  # results.win_rate
  # results.profit_factor
  # results.equity_curve → pd.Series
```

---

## 4. What to Steal (Ethically)

### 4.1 From MetPy (NOAA/Unidata)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Unit-aware calculations** | All Pakhi functions | Every temperature input accepts `"30 degC"` or `303.15 K`. Use `pint` or `metpy.units`. |
| **Standard atmosphere functions** | pakhi.grids.coordinate | Pressure → altitude, geopotential height conversions. |
| **Cross-section and interpolation** | pakhi.grids.interpolate | Vertical cross-section interpolation between pressure levels. |
| **Soundings / thermodynamics** | pakhi.targets.stability | CAPE, CIN, Lifted Index for convective potential (severe weather). |

**License:** BSD 3-Clause — fully compatible with MIT. Must include copyright notice.

### 4.2 From xarray (xarray-dev)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Lazy chunking with Dask** | pakhi.pipeline.stream | Don't load 500GB ERA5 into RAM. Chunk by time, process lazily. |
| **`.sel()` / `.isel()` API** | pakhi.grids.subset | Let users select by lat/lon or index. Familiar API. |
| **Coordinate-aware broadcasting** | All modules | Auto-align lat/lon/time dimensions without manual reshaping. |
| **Zarr backend** | pakhi.pipeline.cache | Store processed data in Zarr (cloud-native, chunked). |

**License:** Apache 2.0 — compatible with MIT. Must include notice.

### 4.3 From Open-Meteo

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Multi-model blending** | pakhi.models.ensemble | Weight GFS + ECMWF + HRRR based on recent forecast skill. |
| **Caching + rate limiting** | pakhi.pipeline.cache | Cache API responses. Respect NOAA/ECMWF rate limits. |
| **Clean REST API design** | pakhi API layer | JSON responses with standard variable names and units. |
| **Model selection logic** | pakhi.models.ensemble | Auto-select best model per variable/region/lead time. |

**License:** AGPL 3.0 — you can use the *ideas* but cannot AGPL your own code. **Steal the architecture, not the code.** Rewrite in your own implementation.

### 4.4 From WeatherBench (Google)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Evaluation metrics** | pakhi.risk.metrics | Use their exact RMSE, ACC, skill score formulas. |
| **Baseline definitions** | pakhi.models.climatology | Persistence and climatology baselines for BSS computation. |
| **Data preprocessing** | pakhi.grids.regridder | Standardized regridding to 2.5° and 5.625° for benchmarking. |
| **Train/val/test splits** | pakhi.models.base | Standard years: train=2010-2018, val=2019, test=2020-2024. |

**License:** Apache 2.0 — fully compatible. Copy the evaluation code directly.

### 4.5 From Pangu-Weather (Huawei)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **3D patch embedding** | pakhi.models.transformer | Embed (lat, lon, pressure) as 3D patches for transformer input. |
| **Pressure-level encoding** | pakhi.models.transformer | Separate embedding for each pressure level (850, 500, 250 hPa). |
| **Autoregressive rollout** | pakhi.predict.multi_step | Use 6-hour autoregressive steps instead of direct 7-day. |
| **Inference optimization** | pakhi.predict.deterministic | ONNX export for sub-second inference. |

**License:** Apache 2.0 — fully compatible. You can use the architecture description. **Cannot use their trained weights without permission.** Train your own.

### 4.6 From GraphCast (Google DeepMind)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Graph Neural Network architecture** | pakhi.models.transformer | Encode atmospheric state as a mesh graph. |
| **Multi-mesh encoding** | pakhi.models.transformer | Different mesh resolutions for different scales (global vs local). |
| **ERAS5 as training data** | pakhi.models.base | Train on ERA5 (same data source they used). |
| **37 vertical pressure levels** | pakhi.targets | Use their standard 37 pressure levels as feature space. |

**License:** Apache 2.0 — fully compatible. Architecture is in the paper. **Must train your own model.**

### 4.7 From Meteostat

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Observation → grid interpolation** | pakhi.grids.interpolate | Point observations interpolated to regular grids. |
| **Historical weather API** | pakhi.src.meteostat | Quick access to station-based historical data for quick tests. |

**License:** MIT — fully compatible. Can use directly.

### 4.8 From ECMWF ecCodes

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **GRIB2 indexing conventions** | pakhi.src.noaa, era5 | Use standard ECMWF parameter codes (shortName: "2t", "10u", "msl"). |
| **Level types** | pakhi.grids.coordinate | Use standard level types: sfc, pl (pressure), ml (model). |

**License:** Apache 2.0 — fully compatible. These are conventions, not code.

### 4.9 From PVLIB (Solar)

| What to Steal | Where to Apply | How |
|---------------|----------------|-----|
| **Solar position calculations** | pakhi.targets.solar | Astronomical solar position for GHI/DNI estimation. |
| **Clear-sky models** | pakhi.targets.solar | Ineichen/Perez clear-sky model as baseline. |
| **Power plant modeling** | pakhi.signals.wind | Adapt panel/inverter modeling pattern to wind turbine modeling. |

**License:** BSD 3 — fully compatible.

### 4.10 From your own triples-sigfast

| Module | Reuse in Pakhi | How |
|--------|---------------|-----|
| `rolling_average()` | pakhi.features.temporal | Smooth temperature time series. |
| `ema()` | pakhi.features.temporal | Exponential moving average of wind speed. |
| `detect_anomalies()` | pakhi.features.anomaly | Z-score anomaly detection in satellite data. |
| `savitzky_golay()` | pakhi.features.temporal | Peak-preserving smoothing of precipitation. |
| `is_converged()` | pakhi.risk.uncertainty | Check if ensemble has converged. |
| `relative_error()` | pakhi.risk.metrics | Forecast error uncertainty quantification. |
| `SigPipeline` | pakhi.pipeline.stream | Out-of-core streaming for large GRIB files. |
| `@njit` / `prange` | All modules | JIT parallelism for numerical computations. |
| `PhysicsPlot` | pakhi.viz.maps | Adapt visualization framework for weather maps. |

---

## 5. Data Flow

```
Real-time operational flow (every 6 hours):

  NOAA GFS 00Z run published (03:30 UTC)
       │
       ▼
  pakhi.src.noaa.fetch_latest()
       │
       ▼
  pakhi.grids.subset(bbox=[-82, 24, -80, 28])  → Florida citrus region
       │
       ▼
  pakhi.features.temporal.build(lags=[...], windows=[...])
       │
       ▼
  pakhi.models.ensemble.predict(features)  → 7-day hourly forecast
       │
       ▼
  pakhi.targets.temperature.freeze_probability(threshold=0.0)
       │
       ▼
  pakhi.signals.freeze.generate()  → LONG OJ signal (confidence=0.73)
       │
       ▼
  pakhi.risk.alerts.send(freeze_alert, recipients=["trader@fund.com"])
```

### Training flow (offline, monthly retrain):

```
  ERA5 reanalysis (2010-2024)
       │
       ▼
  pakhi.features.build_all()
       │
       ▼
  Split: train=2010-2022, val=2023, test=2024
       │
       ▼
  Train LSTM, XGBoost, GP → save models
       │
       ▼
  pakhi.models.ensemble.fit(models)  → ensemble weights
       │
       ▼
  pakhi.risk.backtest.run()  → Sharpe=1.8, MaxDD=12%, BSS=0.35
       │
       ▼
  Deploy to production if Sharpe > 1.5
```

---

## 6. Success Metrics

| Metric | Target (v1.0) | Target (v2.0) |
|--------|---------------|---------------|
| **Forecast RMSE** (temperature, 7-day) | < 2.5°C | < 1.8°C |
| **Brier Skill Score** (freeze, 5-day) | > 0.25 | > 0.45 |
| **Trading Sharpe Ratio** (backtest) | > 1.5 | > 2.0 |
| **Maximum Drawdown** | < 15% | < 10% |
| **Data Ingestion Speed** | 1M points/sec | 10M points/sec |
| **Forecast Latency** (single point) | < 5s | < 1s |
| **Model Retrain Time** | < 1 hour | < 30 min |
| **Test Coverage** | > 80% | > 90% |
| **GitHub Stars** | 100 | 1,000 |

---

## 7. Roadmap

### Phase 1: Foundation (Months 1-3)
- [ ] Project scaffolding, pyproject.toml, CI/CD
- [ ] NOAA GFS + ERA5 data connectors
- [ ] Grid interpolation and subsetting
- [ ] Basic feature engineering (temporal, anomaly)
- [ ] Freeze probability target variable
- [ ] XGBoost freeze forecast model
- [ ] Simple freeze trading signal
- [ ] Backtest engine with Sharpe/MaxDD
- [ ] Example: Florida freeze detection pipeline

### Phase 2: ML Models (Months 3-6)
- [ ] LSTM forecaster with attention
- [ ] Gaussian Process model
- [ ] Ensemble model (BMA stacking)
- [ ] Wind power forecast
- [ ] Power grid demand forecast
- [ ] Hurricane track prediction
- [ ] Multi-instrument signal generation
- [ ] Visualization: forecast maps, ensemble plumes

### Phase 3: Operational (Months 6-9)
- [ ] GOES satellite connector
- [ ] Real-time streaming pipeline
- [ ] Model inference optimization (ONNX)
- [ ] Alert system (email, Slack, Telegram)
- [ ] Historical backtest across multiple instruments
- [ ] Documentation and tutorials
- [ ] PyPI release v1.0

### Phase 4: Production (Months 9-12)
- [ ] Broker API integration (Interactive Brokers)
- [ ] Live paper trading mode
- [ ] Performance monitoring dashboard
- [ ] JOSS paper submission
- [ ] Community launch
- [ ] PyPI release v2.0

---

## 8. Dependencies

### Core (required)
- `numpy>=1.24`
- `xarray>=2023.1`
- `dask[dataframe]>=2023.1`
- `pandas>=2.0`
- `numba>=0.57`
- `scipy>=1.10`
- `requests>=2.28`

### Data Access (required)
- `cfgrib>=0.9.12` — GRIB2 reading
- `eccodes>=1.6` — GRIB/BUFR (conda-forge)
- `netCDF4>=1.6` — NetCDF reading
- `zarr>=2.14` — Chunked storage
- `cdsapi>=0.6` — ERA5 Copernicus Data Store

### ML (optional)
- `scikit-learn>=1.3` — preprocessing, metrics
- `xgboost>=2.0` — gradient boosting
- `lightgbm>=4.0` — gradient boosting (faster)
- `torch>=2.0` — LSTM, Transformer
- `gpytorch>=1.10` — Gaussian Process

### Trading (optional)
- `yfinance>=0.2` — Yahoo Finance futures
- `ib-insyng>=1.0` — Interactive Brokers API

### Visualization (optional)
- `matplotlib>=3.7`
- `cartopy>=0.22` — Map projections
- `plotext>=5.2` — Terminal plots
- `plotly>=5.15` — Interactive maps

### Tied to triples-sigfast
- `triples-sigfast>=2.2.0` — Signal processing, statistics, pipeline

---

## 9. Open Questions

1. **ERA5 access:** CDS API requires registration. Should we bundle a sample
   dataset for quickstart, or require users to register?
2. **GPU training:** LSTM/Transformer training needs GPU. Should we provide
   pre-trained models on Hugging Face Hub?
3. **Broker integration:** IB API is complex. Should v1.0 output CSV signals
   only, or attempt live execution?
4. **Licensing:** AGPL or MIT? MIT allows commercial use; AGPL forces sharing.
5. **Name:** "Pakhi" is Bengali. Should we explain the name in the README
   with the bird metaphor, or keep it mysterious?
6. **Revenue model:** Open-source core + paid premium features (live signals,
   proprietary models, managed API)?

---

*End of PRD — Pakhi v1.0.0-draft*
