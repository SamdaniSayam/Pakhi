# Changelog

All notable changes to Pakhi will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
