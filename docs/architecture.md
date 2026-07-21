# Pakhi Architecture

## Overview

Pakhi is a weather intelligence and quantitative trading platform that transforms
raw meteorological data into actionable trading signals. The architecture follows
a linear data flow with clearly separated concerns, enabling each stage to be
tested, replaced, or extended independently.

```
Data Sources → Ingestion → Features → Models → Predictions → Signals → Risk
   (src/)      (src/)     (features/) (models/)  (predict/)  (signals/) (risk/)
```

## Data Flow

**1. Ingestion** (`pakhi/src/`): Connectors fetch data from external APIs and
file formats. Each connector normalizes responses into `xarray.Dataset` or
`pandas.DataFrame` with consistent coordinate naming (`time`, `lat`, `lon`).
Connectors for Open-Meteo, NOAA GFS, ERA5, GOES satellite, CME derivatives,
Yahoo Finance, and Meteostat are provided. All connectors use HTTP with retry
logic, rate limiting, and optional caching via `pakhi/pipeline/cache.py`.

**2. Feature Engineering** (`pakhi/features/`): Transforms raw meteorological
fields into predictive features. The `ClimateFeatures` class computes degree-day
indices (HDD, CDD, GDD), frost-day flags, and heatwave detection. `TemporalFeatures`
builds lagged variables, rolling statistics, trends, and anomaly scores.
`SpatialFeatures`, `TeleconnectionIndices` (ENSO, NAO, AO), and
`SatelliteFeatures` (brightness temperature, convective proxies) round out the
feature set.

**3. Modeling** (`pakhi/models/`): All models implement the `BaseModel` interface
(`fit` → `predict` → `predict_proba` → `score`). This uniform contract allows
models to be swapped freely. Available models include `PersistenceModel` and
`ClimatologyModel` (baselines), `GradientForecaster` (XGBoost/LightGBM with
native NaN handling and early stopping), `LSTMForecaster` (BiLSTM with temporal
attention via PyTorch), `GaussianForecaster` (Gaussian Process via GPyTorch), and
`EnsembleForecaster` (mean, BMA, and stacking combinators).

**4. Prediction** (`pakhi/predict/`): Wraps model output into `ForecastResult`
containers. `DeterministicPredictor` provides direct, recursive, and
multi-output strategies for multi-step forecasting. `ProbabilisticPredictor`
adds ensemble averaging, MC dropout uncertainty, quantile regression, calibration
analysis, and CRPS scoring.

**5. Signal Generation** (`pakhi/signals/`): Converts forecast outputs into
tradeable `Signal` dataclasses containing action (LONG/SHORT/FLAT), position size
(via Kelly criterion), confidence, instrument, and human-readable reasoning.
Signal generators include `FreezeSignal` (OJ futures), `PowerSignal` (ERCOT/PJM
power futures), `HurricaneSignal` (nat gas futures), `DroughtSignal` (grain
futures), and `WindPowerSignal` (electricity markets). `EnsembleSignal` combines
multiple signals with correlation-adjusted weighting.

**6. Risk Management** (`pakhi/risk/`): Computes portfolio-level metrics
(Sharpe, Sortino, Calmar, VaR, CVaR, max drawdown), runs backtests with
realistic commission/slippage via `BacktestEngine`, and generates risk alerts
through `AlertManager` with severity levels for freeze, heatwave, hurricane, and
drought events.

## Module Dependencies

```
pakhi.src       → numpy, pandas, xarray, requests, cfgrib, netCDF4, zarr
pakhi.features  → numpy, pandas, xarray (triples_sigfast for temporal/streaming)
pakhi.models    → numpy (+ scikit-learn, xgboost, lightgbm, torch, gpytorch)
pakhi.predict   → numpy, pandas, scipy
pakhi.signals   → numpy
pakhi.risk      → numpy, pandas
pakhi.pipeline  → numpy, xarray, dask
pakhi.targets   → numpy
```

Heavy ML dependencies (PyTorch, XGBoost, LightGBM, GPyTorch) are **lazy-imported**
only when the corresponding model class is instantiated. This keeps the base
installation lightweight (~50 MB) while enabling full ML capabilities via
`pip install pakhi[ml]`.

## Design Principles

**Lazy Imports**: Optional dependencies (ML libraries, visualization, financial
data) are imported at call time, not at module load time. This means `import pakhi`
never triggers a PyTorch or XGBoost import. The `models/__init__.py` uses
`__getattr__` to defer heavy imports.

**Type Hints**: Every public function and class uses PEP 604 union syntax
(`int | None`) and `from __future__ import annotations` for forward-reference
support. This enables IDE autocompletion and static analysis with mypy/pyright.

**NaN-Safe Operations**: All metric computations, model predictions, and feature
engineering functions handle NaN values gracefully. `compute_metrics` masks NaN
pairs before evaluation. Tree-based models (XGBoost/LightGBM) natively handle
missing values. The `StandardScaler` uses `np.nanmean`/`np.nanstd`.

**Composable Signals**: Every signal generator inherits from `BaseSignal` and
returns a `Signal` dataclass. Signals can be combined via `EnsembleSignal` or
chained in the `BacktestEngine`. Position sizing uses Kelly criterion with
half-Kelly variance reduction by default.

**xarray-Native**: Data flows through `xarray.Dataset` objects wherever possible,
preserving coordinate metadata (time, latitude, longitude) through the entire
pipeline. This avoids the index-alignment bugs common in pandas-based weather
workflows.

**Reproducibility**: All synthetic data generators and ML models accept a
`random_state` seed. The `train_val_test_split` function enforces chronological
splits to prevent future data leakage.
