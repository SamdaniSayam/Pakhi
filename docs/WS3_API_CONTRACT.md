# WS-3 Public API — Locked Contract v1.1

Status: **LOCKED 2026-08-13 (v1.1, post-QC re-lock)** — pre-registered before any
endpoint ships (WS-1 evaluation-contract / WS-2 protocol discipline).  Machine
twin: `data/ws3/api_contract.json` (payload sha256
`2c63a639adbd88538a64c183033556694ab39061d8322cb507b1cef20eba5222`).
Any amendment requires a new version + re-lock (change control).

Blueprint: `docs/WS3_EXECUTION_BLUEPRINT.md` (§3, §4).

---

## 1. Core policies

| Policy | Lock |
|---|---|
| **Two engines** | `read_engine` (`postgres_readonly`) for every `GET /v1/*`; `write_engine` (app role) **only** for `backtest_jobs` INSERT + key/rate-limit bookkeeping. Read-only never writes (42501 in CI), no GET path touches `write_engine`. Roles provisioned as a T1 dependency; the permission test is a T1 exit. |
| **Endpoint policy** | Data handlers are **sync `def`** (anyio threadpool) so the event loop stays free for WebSockets. Only `WS /v1/stream/signals` is `async def`. |
| **CORS** | `CORSMiddleware` with allowlist from `PAKHI_CORS_ORIGINS`; methods `GET/POST/OPTIONS`; headers `X-Pakhi-Key`/`X-Pakhi-Version`/`Content-Type`/`X-Request-ID`; no credentials at Phase-2. `RequestContextMiddleware` sits outside CORS so preflight responses also carry `X-Pakhi-Version`. |
| **Error envelope** | Every error — FastAPI's default 422, all `HTTPException` statuses, and unhandled 500s — is `{error: {code, message, details?}}`. No route leaks the framework shape. |
| **Versioning** | All routes under `/v1`; `X-Pakhi-Version` on every response; breaking changes bump the major version. |
| **Keys** | `X-Pakhi-Key` request header; sha256 hashes only, from `PAKHI_API_KEYS` env or `data/ws3/api_keys.json` (gitignored); unknown key → 401. |
| **Rate limits** | Token-bucket, in-memory; `X-RateLimit-Limit/-Remaining/-Reset` on every response; exceeded → 429. Deployment is **single-worker** (`uvicorn --workers 1`). |
| **Freshness** | `GET /v1/status` reports DB reachability, latest cycle, staleness. A missed cycle is a visible *stale* state (`X-Pakhi-Staleness`), never a fabricated fresh value. Empty signals → **404**, never an empty 200. |
| **Edge status** | `X-Pakhi-Edge-Status: {status}_n{n}` on `/v1/signals/*`, `/v1/ledger`, and WS frames; computed from the ledger (`scored=True`). |

## 2. Edge-status computation

```
n_scored_events = COUNT(paper_ledger WHERE scored = True)

status =
  "underpowered"  if n_scored_events < N_MIN (=8)
  "unproven"      if n_scored_events >= N_MIN but no recorded G1 re-run verdict PASS
  "proven"        only when a recorded G1 re-run verdict = PASS
header = f"{status}_n{n_scored_events}"     e.g. underpowered_n0, unproven_n8, proven_n8
```

## 3. Route table

| Method + path | Purpose | Notes |
|---|---|---|
| `GET /v1/health` | Liveness only (Docker/K8s probes) | `{"status": "ok"}` |
| `GET /v1/status` | Readiness + freshness | db_ok, latest_cycle_id, publication_ts, staleness_seconds, worker_last_run (from `metrics worker.last_run` when present, else latest cycle publication_ts as the documented proxy) |
| `GET /v1/instruments` | Distinct instruments + latest signal + freshness | 404 when the store is empty |
| `GET /v1/signals/{instrument}` | Latest + history (`?limit`, `?since`, `?cycle_id`) | Provenance verbatim; empty → 404; edge-status header |
| `GET /v1/forecasts/{instrument}` | Stored forecast rows (`?lead=7d`) | **501 not_implemented** until WS-2 stores forecast rows |
| `GET /v1/ensemble/disagreement` | Stored disagreement series | **501 not_implemented** (deferred from WS-2) |
| `GET /v1/ledger` | Paper-ledger summary | Labeled paper / not live capital; edge-status header. Semantics: `total_count` = all rows, `scored_count` = `scored=True`, `net` = SUM(net_of_benchmark) over scored rows (all-time), `mean_net_of_benchmark` over scored rows |
| `POST /v1/backtests` | Validate + enqueue (`write_engine`) | 201 `{id, status}`; bounds below; 422/429 rejections |
| `GET /v1/backtests/{id}` | Job status | `queued → running → done/failed` |
| `GET /v1/backtests/{id}/result` | Stream the stored artifact | 404 until done |
| `WS /v1/stream/signals` | Push each new signal batch on `cycle_complete` | Schema §4; heartbeat 30 s |

## 4. WebSocket + NOTIFY bridge

- Orchestrator commits all ledger writes for a cycle, then issues
  `NOTIFY cycle_complete, '{"cycle_id": ..., "publication_ts": ...}'`
  **post-commit** — a cycle that fails or rolls back never pushes. (NOTIFY
  wiring into `run_ws2_t3_orchestrate.py` is a T4 prerequisite; prose-only
  here.)
- uvicorn LISTENs on a dedicated connection (background thread →
  `asyncio.Queue` → fan-out; reconnect with backoff). The DB is the bus; the
  two OS processes never share memory.
- Frame schema (`signals.batch`, `version=1`): `cycle_id`, `publication_ts`,
  `signals[]` where each signal is the full row: instrument, action, size,
  confidence, reasoning, timestamp, forecast_cycle_id, publication_ts,
  archive_source, model_version.
- Missed subscribers are covered by `GET /v1/signals` history — NOTIFY is a
  wake-up, not the source of truth.

## 5. Backtest bounds

- `max_window_days <= 365`
- `model_version` in whitelist: `["GFS-0p50"]`
- `instrument` in whitelist: `["OJ_FUTURES"]`
- per-key cap: **1 queued job / 5 min** (429 on queue-full)

## 6. SDK layout

`pakhi.client` subpackage **inside this repository**
(`from pakhi.client import PakhiClient`), thin and typed, httpx-based:
`.status()`, `.signals(instrument)`, `.forecasts(instrument)`, `.ledger()`,
`.backtests.create(...)`, `.stream_signals(on_signal=...)`; docstrings link to
OpenAPI. No separate PyPI package or repository at Phase-2.

## 7. Deferred

- **WS-4:** JWT, RBAC, multi-tenancy, audit logs.
- **WS-5:** Prometheus/Grafana, SLOs, status page, multi-worker rate limiting,
  DR/backups.
- **WS-6:** metering/billing.

## 8. Change control

Any amendment requires a new version + re-lock of this doc and the machine twin
(new sha256). The API only ever ships against the locked contract.
