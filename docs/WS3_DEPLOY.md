# WS-3 API Deployment & Operational Guide

This document describes how to deploy, configure, and operate the Pakhi WS-3 REST + WebSocket API.

---

## 1. Architecture Summary

The WS-3 API is a **fast-read service** running over the WS-2 TimescaleDB/PostgreSQL store:
- Reads database rows through `read_engine` (`POSTGRES_USER: postgres_readonly`).
- Mutates `backtest_jobs` table through `write_engine` (`POSTGRES_USER: postgres`).
- All REST data endpoints are **sync `def`** (handled in threadpool workers, never blocking asyncio loop).
- `WS /v1/stream/signals` is **async `def`** for real-time `signals.batch` WebSocket fan-out.

---

## 2. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PAKHI_DB_READ_URL` | `sqlite:///data/ws2/paper.db` | Connection URL for read queries (read-only role in production) |
| `PAKHI_DB_WRITE_URL` | `sqlite:///data/ws2/paper.db` | Connection URL for job queue writes & bookkeeping |
| `PAKHI_CORS_ORIGINS` | `""` (disabled) | Comma-separated allowlist of origins for CORS preflight |
| `PAKHI_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `PAKHI_API_KEYS` | `""` | Comma-separated raw API keys (hashed at rest via SHA-256) |

---

## 3. Running Locally

### Development Server
```bash
# Install with API dependencies
pip install -e ".[all,api]"

# Start uvicorn development server with auto-reload
uvicorn pakhi.api.main:app --reload --host 127.0.0.1 --port 8000
```

### Verification
```bash
# Check liveness
curl http://127.0.0.1:8000/v1/health

# Check readiness & data freshness
curl http://127.0.0.1:8000/v1/status

# List instruments
curl http://127.0.0.1:8000/v1/instruments

# Query signals for OJ_FUTURES
curl http://127.0.0.1:8000/v1/signals/OJ_FUTURES?limit=5

# Check paper ledger
curl http://127.0.0.1:8000/v1/ledger
```

---

## 4. Running with Docker & Docker Compose

### Single Docker Container
```bash
# Build Docker image
docker build -t pakhi:latest .

# Run API container
docker run -d \
  --name pakhi-api \
  -p 8000:8000 \
  -e PAKHI_DB_READ_URL="postgresql://postgres:postgres@host.docker.internal:5432/pakhi" \
  -e PAKHI_DB_WRITE_URL="postgresql://postgres:postgres@host.docker.internal:5432/pakhi" \
  --entrypoint uvicorn \
  pakhi:latest pakhi.api.main:app --host 0.0.0.0 --port 8000
```

### Docker Compose Stack
```bash
# Spin up TimescaleDB + Pakhi CLI + Pakhi API service
docker compose up -d

# Check API service logs
docker compose logs -f api

# Verify API health
curl http://localhost:8000/v1/health
```

---

## 5. Python SDK (`pakhi.client`) Usage

```python
from pakhi.client import PakhiClient

# Initialize client
client = PakhiClient(base_url="http://localhost:8000")

# Check status
status = client.status()
print(f"Latest cycle: {status['latest_cycle_id']}, staleness: {status['staleness_seconds']}s")

# Get signals
signals = client.signals("OJ_FUTURES", limit=10)
for sig in signals["signals"]:
    print(f"[{sig['timestamp']}] {sig['action']} size={sig['size']} conf={sig['confidence']}")

# Submit backtest job
job = client.backtests.create(instrument="OJ_FUTURES", window_days=30)
print(f"Job queued: {job['job_id']}")

# Check job result
res = client.backtests.get(job["job_id"])
print(f"Job status: {res['status']}")
```
