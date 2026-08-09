# Changelog

All notable changes to Pakhi will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Temporal features: short series no longer crash — rolling windows larger than the
  series length are skipped with a warning instead of raising in triples-sigfast
- Gradient forecaster: refitting single-target after a multi-output fit no longer
  returns stale multi-output shapes (`_multioutput_models` reset in `fit`)
- Heat index: simple Steadman formula now converts °C→°F before applying the °F
  constants (was returning ~23 °C for 30 °C / 10 % RH); removed unreachable `RH < 13`
  adjustment branch (Rothfusz path requires `RH >= 40`)
- Sortino ratio: downside deviation uses `sqrt(mean(downside²))` (downside risk)
- LSTM: sliding-window dataset padded so predictions align 1:1 with inputs
  (`n_samples == len(y)`); NaN-guarded pinball loss
- Multi-step AR predictor: corrected output-matrix shape `(n - steps + 1, steps)`
- CLI: `get_instrument` `KeyError` handled gracefully; Open-Meteo geocode fallback
- Spatial gradients: scale d/dx, d/dy by `cos(lat)` in km when `dx_km` is None
- Climate heatwave streaks: `_streak_xr` rewritten to correct window alignment
- Meteostat: use the canonical `tmax/tmin/tavg/prcp/...` response field names
- ERA5: cache filename hashed per variable set; Zarr path cleanup
- GFS (NOAA): cfgrib `backend_kwargs={"indexpath": ""}` instead of `index_keys`
- Paper trader: unrealised PnL includes entry cost basis; cash handling fix
- Scheduler: `next_run` update guarded by lock to avoid races on job removal
- CME HDD/CDD: Celsius detection threshold `100 → 50` °F
- Viz heatmap: annotation contrast derived from actual data range
- Anomaly features: guard zero/negative climatology std via `np.where`
- Precipitation SPI: guard NaN variance and short cumulative windows
- Ensemble signal: use timezone-aware `datetime.now(timezone.utc)`
- Power signal: guard empty wind-capacity-factor arrays
- Stream processor: drop unused `dask.array` import; robust compute check

### Tests
- Coverage raised to 99.61 % (24 → 22 missed lines); `temperature.py` at 100 %
- Regression tests for temporal short-series, gradient multi-output refit,
  heat-index °C/°F conversion
- 23 new coverage test files; lint clean (`ruff check pakhi/`)

## [1.0.0] - 2025-07-21

### Added
- **Data Connectors** — ERA5, GFS/HRRR/NAM, GOES-16/17/18, Yahoo Finance, CME Weather, Open-Meteo, Meteostat
- **Grid Operations** — Bilinear, nearest-neighbor, Cressman interpolation; lat/lon ↔ km conversion; pressure ↔ altitude
- **Feature Engineering** — Temporal lags/rolling/EMA, spatial weighting, climate indices (HDD/CDD/GDD/frost/heatwave), anomaly detection (z-score/SPI), teleconnections (ENSO/NAO/PDO/MJO), satellite features
- **Target Variables** — Freeze probability, wind power curve, hurricane classification (Saffir-Simpson/RI/wind radius), precipitation accumulation, solar position
- **Forecasting Models** — Persistence, climatology, gradient boosting (XGBoost/LightGBM), bidirectional LSTM with attention, Gaussian processes, ensemble (BMA/stacking/blending)
- **Prediction** — Deterministic, multi-step autoregressive, probabilistic (ensemble/quantile/MC dropout), verification metrics (RMSE/ACC/Brier/CRPS)
- **Signal Generation** — Freeze → OJ futures, heatwave → power, hurricane → NG/insurance, drought → grains, wind → power generation, multi-signal ensemble
- **Risk Management** — Sharpe/Sortino/VaR/CVaR/max drawdown, backtest engine, uncertainty quantification, alert system
- **Trading** — Paper trader, instrument definitions (11 weather-sensitive instruments), PnL tracking, Kelly criterion position sizing
- **Visualization** — Geographic forecast maps, time series plots, ensemble plume diagrams, terminal dashboard
- **CLI** — `pakhi forecast`, `pakhi signal`, `pakhi status`, `pakhi backtest`
- **Docker** — Multi-stage Dockerfile, docker-compose, health checks
- **CI/CD** — GitHub Actions: lint (ruff), test (Python 3.10–3.13), Docker build, PyPI publish
- **Developer Experience** — Makefile, pre-commit hooks, ruff config, coverage reporting
- **5 example scripts** — All runnable with synthetic data, no API keys needed
- **224 tests** — Comprehensive coverage across all modules

### Fixed (from deep review)
- `xr.concat()` missing positional `datasets` argument in 4 connectors (NOAA, ERA5, satellite, Open-Meteo)
- ERA5 wrong CDS product type when mixing single-level and pressure-level variables
- Satellite `cloud_motion` single-image crash → returns zeros gracefully
- Temporal features: removed 4 bogus `dim=` args from `rolling_average()` API calls
- Temporal features: `detect_anomalies()` z-score threshold confused with window size
- Anomaly features: SPI `_apply_spi` was flattening spatial dimensions
- Satellite features: correlation peak offset sign error; confidence normalization (~0.01 → proper 0-1)
- Solar position: LSTM computed from wall-clock hour instead of longitude
- Solar position: air mass formula producing complex numbers for zenith > 90°
- Hurricane RI: intercept sign wrong (`+3.94` → `-3.94`, Kaplan-DeMaria 2003)
- Precipitation: `dt_hours` off-by-one in accumulation; division by zero guard
- CRPS ensemble formula corrected
- Sortino ratio denominator: `mean(downside²)` → `std(downside, ddof=1)`
- Backtest look-ahead bias: full DataFrame passed to signal generator → now uses `df.iloc[:i+1]`
- Backtest PnL: only captured last day → now tracks entry equity per trade
- Trading execution: cash not deducted on open; commission double-charged; `close_position` ignores fill_price
- Signals hurricane: `landfall_probability=0.0` falsy check → `is not None`
- Viz import chain: graceful `ImportError` when matplotlib not installed
- Risk alerts: deprecated `datetime.utcnow()` → `datetime.now(timezone.utc)`
