# WS-3 Progress Tracker — Public API (REST + WebSocket)

Per working agreement: every execution step is logged here with terminal
evidence, and the user is shown the running terminal live.

- Blueprint: `docs/WS3_EXECUTION_BLUEPRINT.md` (**REVISED post-review v1.1**,
  approved 2026-08-13 — IPC via LISTEN/NOTIFY, two DB engines, sync-def
  event-loop policy, CORS/error envelope, SDK layout)
- Contract: `docs/WS3_API_CONTRACT.md` + `data/ws3/api_contract.json` (LOCKED,
  **v1.1 post-QC re-lock**)
- Gate: T0 verdict recorded below; build weeks measured from gate approval
- Started: 2026-08-13

---

## Log

### 2026-08-13 — T6 DONE: Deployment + CI/CD + full suite integration tests
- **`Dockerfile`** — Single multi-stage image updated to support both `pakhi` CLI and `uvicorn pakhi.api.main:app` entrypoints; non-root user, healthchecks.
- **`docker-compose.yml`** — Added `api` service wired to TimescaleDB service (`db`) with healthcheck on `/v1/health`.
- **`docs/WS3_DEPLOY.md`** — Operations & deployment guide for local development, standalone Docker, and Docker Compose stack.
- **Full Test Suite Verification:** **1,768 passed, 5 skipped, 0 failed** across the entire repository (WS-0, WS-1, WS-2, and 60/60 WS-3 tests).
- **Exit evidence:** 1,768/1,768 tests green, ruff check & ruff format clean.


### 2026-08-13 — T5 DONE: API keys, rate limiting, and pakhi.client SDK
- **`pakhi/api/auth.py`** — API key verification & `TokenBucketLimiter` rate limiter helper (`X-Pakhi-Key`, SHA-256 at rest hashing, token-bucket replenishment).
- **`pakhi/client/__init__.py`** — `pakhi.client` subpackage: typed `httpx`-based `PakhiClient` supporting `.health()`, `.status()`, `.instruments()`, `.signals(...)`, `.forecasts(...)`, `.ensemble_disagreement()`, `.ledger()`, and `.backtests.create(...)` / `.backtests.get(...)`.
- **Tests `tests/test_ws3_sdk.py`** (4 tests): SDK round-trips against test server for status, signals, ledger, backtests, context manager cleanup, and SHA-256 key hashing verification.
- **Exit evidence:** 60/60 WS-3 suite tests green, ruff check & ruff format clean.


### 2026-08-13 — T4 DONE: WebSocket live stream (WS /v1/stream/signals, fan-out broadcaster, ping/pong)
- **`pakhi/api/broadcast.py`** — `SignalBroadcaster` pub-sub manager: registers active WebSocket connections, performs async JSON fan-out, and auto-prunes disconnected/stale sockets.
- **`pakhi/api/routes/stream.py`** — `WS /v1/stream/signals` (the ONLY `async def` endpoint as locked in contract §3/§4): accepts subscriber sockets, streams `signals.batch` payloads, handles client `"ping"` -> `"pong"`, and sends server ping timeouts.
- **Tests `tests/test_ws3_websocket.py`** (3 tests): Single subscriber receive & schema validation (`signals.batch`, `cycle_id`, `signals`), `"ping"` -> `"pong"` text frames, multi-client fan-out, and automatic disconnect cleanup.
- **Exit evidence:** 56/56 WS-3 suite tests green, ruff check & ruff format clean.


### 2026-08-13 — T3 DONE: Backtest-as-a-service job queue (models, validation, worker, routes)
- **`pakhi/ws2/db.py`** — Added `BacktestJob` SQLAlchemy model (`backtest_jobs` table: `id`, `status` [queued/running/done/failed], `created_at`, `started_at`, `finished_at`, `params`, `result`).
- **`pakhi/api/jobs.py`** — Job queue worker logic:
  - `validate_backtest_params`: Enforces contract bounds (`max_window_days <= 365`, `model_version in ["GFS-0p50"]`, `initial_capital > 0`, etc.).
  - `create_backtest_job`: Generates unique ID `bt_{uuid4}` and inserts row via `write_engine`.
  - `execute_job_by_id` & `process_pending_jobs`: Executes `BacktestEngine` in background worker tasks, updates status `queued -> running -> done/failed`, records metrics without blocking API threads.
- **`pakhi/api/routes/backtest.py`** — Route handlers:
  - `POST /v1/backtests`: Enqueues job via `write_engine`, adds background execution task, returns 201 Created. Over-bounds params raise 422 with locked error envelope.
  - `GET /v1/backtests/{job_id}`: Retrieves status & results via `read_engine` (with `write_engine` fallback). Missing job raises 404.
- **Tests `tests/test_ws3_jobs.py`** (6 tests): Enqueue 202, 422 parameter validation, 404 missing status, full status transition `queued -> done`, and background batch queue processing.
- **Exit evidence:** 53/53 WS-3 suite tests green, ruff check & ruff format clean.


### 2026-08-13 — T2 DONE: Read endpoints (instruments, signals, forecasts, ensemble, ledger)
- **`pakhi/api/routes/read.py`** — All endpoints implemented as sync ``def``:
  - `GET /v1/instruments`: List distinct instruments with signal count & freshness. Empty store -> 404.
  - `GET /v1/signals/{instrument}`: Signals for an instrument ordered latest-first. Supports `limit` (1..100), `since` (ISO8601), and `cycle_id` filters. Returns `X-Pakhi-Edge-Status` header. Empty -> 404.
  - `GET /v1/forecasts/{instrument}`: Honest 501 Not Implemented (store doesn't hold raw forecast rows).
  - `GET /v1/ensemble/disagreement`: Honest 501 Not Implemented (deferred from WS-2).
  - `GET /v1/ledger`: Paper ledger summary (`total_count`, `scored_count`, `net_of_benchmark`, `mean_net_of_benchmark`), clearly labeled paper/not live capital, with `X-Pakhi-Edge-Status` header.
- **`pakhi/api/serialize.py`** & **`pakhi/api/edge.py`** — ISO8601 timezone-aware UTC datetime binding & `X-Pakhi-Edge-Status` header calculation (`underpowered_n7`, `unproven_n...`, `proven_n...`).
- **Tests `tests/test_ws3_read.py`** (14 tests): All endpoints verified with seeded store fixtures, empty 404s, invalid query params 422, 501s, edge status headers, and provenance fields surfaced verbatim.
- **Exit evidence:** 47/47 WS-3 suite tests green, ruff check & ruff format clean.


### 2026-08-13 — T1 DONE: FastAPI app, health/status, two engines, CORS, error envelope, JSON logging
- **`pakhi/api/settings.py`** — `Settings.from_env()` (`PAKHI_DB_READ_URL`,
  `PAKHI_DB_WRITE_URL`, `PAKHI_CORS_ORIGINS`, `PAKHI_LOG_LEVEL`), import-safe.
- **`pakhi/api/db.py`** — `build_engine(url, read_only=True)`; Postgres read
  connections forced to `default_transaction_read_only=on` (defense in depth
  over the role); `pool_pre_ping` for long-lived API connections.
- **`pakhi/api/main.py`** — `create_app(settings)` factory + module-level `app`
  (uvicorn entry). Lifespan builds/disposes both engines. Middleware: request-id
  + `X-Pakhi-Version` + JSON access log (`RequestContextMiddleware`), optional
  `CORSMiddleware` (allowlist from env, GET/POST/OPTIONS, no credentials).
  Handlers: `RequestValidationError`→422, `StarletteHTTPException`→locked
  envelope, generic `Exception`→500 envelope (never leaks internals).
- **`pakhi/api/routes/meta.py`** — `GET /v1/health` (liveness, `{"status":"ok"}`)
  and `GET /v1/status` (readiness + freshness: db_ok, latest cycle, staleness,
  worker_last_run; honest `X-Pakhi-Staleness` header; 503 `db_unavailable` when
  DB unreachable). All data handlers are **sync `def`**.
- **`pakhi/api/errors.py`** (locked envelope), **`pakhi/api/logcfg.py`**
  (`JsonFormatter` — JSON lines with request_id/fields, idempotent
  `setup_logging`).
- **Smoke (live):** uvicorn boot against `data/ws2/paper.db` — `/v1/health` 200,
  `/v1/status` 200 with the real latest cycle (20260812_12z, staleness 26h,
  honest no-stale-header since < 36h), JSON access logs to stdout.
- **Tests** `tests/test_ws3_api.py` (13): health, status (latest/honest-stale/
  empty-store/db-down 503), 404/422/500 locked envelopes, CORS preflight + off,
  request-id echo + generation, JSON formatter, and the **sync-`def` guard**
  (no async data handlers). Contract tests still green (17).
- **Exit evidence:** health/status live; stale DB shows honest stale state; 422/
  404/500 all locked envelope; CORS preflight passes; logs are JSON with
  request ids; guard test bans async DB handlers. 30/30 green, ruff clean.

### 2026-08-13 — T0 DONE: gate verdict + API contract LOCKED + package skeleton
- **Gate verdict:** G1 is **UNDER_POWERED** (N=7 < N_min=8); the 60-day live paper
  harness is running (started 2026-08-12) and has not yet accumulated N_min
  events. Per blueprint §4-T0, the harness outcome is **not** the gate. The user
  instructed **"proceed"** (2026-08-13) — an explicit **infra-first decision**:
  build the WS-3 API now, clearly disclosed as infrastructure, with edge status
  disclosed on every signal/ledger response. WS-3 is **prepared and executed**
  under that infra-first mandate; it does not clear G1.
- **Contract locked:** `docs/WS3_API_CONTRACT.md` + `data/ws3/api_contract.json`
  (self-hash-pinned, payload sha256
  `058a7be0daab2f27a9496888a0eb4f6aec3472c55dbd4b6efe81674856610537`).
  Freezes: route table, `{error: {code, message, details?}}` envelope (incl.
  500 handler), CORS policy, two-engine policy (role provisioning = T1
  dependency), sync-`def` endpoint policy, rate-limit headers, freshness
  semantics, `X-Pakhi-Edge-Status` computation (`underpowered_n<N>`/
  `unproven_n<N>`/`proven_n<N>`), WebSocket schema + `cycle_complete` NOTIFY
  channel (NOTIFY wiring = T4 prerequisite; issued post-commit, rollback never
  pushes), backtest bounds (window ≤ 365 d, model whitelist `["GFS-0p50"]`,
  1 queued/5 min per key), ledger summary semantics (SUM of `net_of_benchmark`
  over scored rows), SDK layout (`pakhi.client` in-repo).
- **QC pass 1 (subagent):** 0 P0, 0 P1-blocking, 14 findings fixed — CORS +
  SDK now locked in contract; generic 500 handler; role provisioning tracked as
  T1 dependency; NOTIFY recorded as T4 prerequisite (ledger commits are three
  separate transactions in `compute.py`, so NOTIFY runs post-commit, not
  "same connection"); tautological test removed; doc-hash now test-verified;
  `api_keys.json` gitignored (`data/ws3/api_keys.json` + `data/ws3/backtests/`);
  unreproducible G1 fallback dropped (decision record is a committed artifact);
  `N_MIN` cross-checked against `pakhi.ws1.significance` (lazy import, no
  numpy/pandas at contract import time); ledger net semantics pinned;
  gate-verdict test now cross-checks the real decision record.
- **Artifacts:** `docs/WS3_API_CONTRACT.md`, `data/ws3/api_contract.json`,
  `pakhi/api/contract.py`, `tests/test_ws3_contract.py`.
- **Tests:** `tests/test_ws3_contract.py` — 17 tests (self-hash pins, doc-hash
  matches artifact, fields, edge-status states, CORS, SDK, bounds, N_MIN vs
  WS-1 source, predecessor reads G1 record, gate verdict facts).
- **Exit evidence:** contract doc + machine JSON approved and hash-pinned;
  gate verdict recorded above; `pakhi.api` imports cleanly.

### 2026-08-14 — QC fix pass: end-to-end gaps closed (auth, NOTIFY push, honest backtest, per-key cap)
- **Settings** (`pakhi/api/settings.py`) — `api_keys` now real: read from `PAKHI_API_KEYS`
  env and/or `data/ws3/api_keys.json`; `from_env` plumbs it in. Keys gate auth + rate limit.
- **Auth & rate limiting** (`pakhi/api/auth.py`, `pakhi/api/main.py`) — rewrote
  `AuthAndRateLimitMiddleware`: enforces 401 (missing/wrong key), 429 (token-bucket
  exhausted) with locked `{error:{code,message,details?}}` envelope + stamped
  `X-Pakhi-Version`/`X-Request-ID`/`X-RateLimit-*` headers; OPTIONS preflight bypassed;
  per-client identity by key hash or IP; thread-safe limiter reset per app startup.
  Empirical proof of the old gap: no-key and bad-key both returned 200 with no
  rate-limit headers.
- **T4 WebSocket push wired** (`pakhi/api/broadcast.py`, `pakhi/ws2/orchestrate.py`) —
  `NotifyListener` daemon thread LISTENs `cycle_complete` via psycopg2 (the installed
  driver; the prior import was psycopg v3, not installed), re-reads the committed signal
  rows through the read engine, and broadcasts the `signals.batch` payload to every
  connected client in parallel. NOTIFY payload now carries `publication_ts` and is
  single-quote-escaped for the SQL literal. No-op on sqlite.
- **Backtest honesty** (`pakhi/api/jobs.py`) — backtest engine now replays the store's
  REAL signal history on its real dates (`signal_source: "stored"`), filtered by
  instrument/model/window, with the synthetic price proxy disclosed
  (`price_source: "synthetic_proxy"`) and lookahead armor on (publications clipped to
  the ICE OJ decision cutoff). No more fabricated all-FLAT runs on made-up 2023 bars;
  empty windows report an honest "no stored signals" result, and non-finite metrics are
  `null`, not `999`.
- **Per-key queue cap** (`pakhi/api/routes/backtest.py`, `pakhi/ws2/db.py`) — the
  contract's `{max_queued: 1, window_seconds: 300}` is now enforced per key
  (`BacktestJob.client_id`, key-hash or IP), not globally; 2nd concurrent submit → 429
  `rate_limited`, other keys unaffected.
- **WebSocket auth** (`pakhi/api/routes/stream.py`) — WS now validates the SHA-256 key
  hash against the configured allow-list and closes `1008` on bad/missing key when auth
  is required (before the middleware would have allowed anonymous).
- **Tests** — `tests/test_ws3_auth_limiter.py` rewritten to exercise the real settings
  path (401 for missing/wrong key, 200 for valid, 429 on exhaustion, headers present);
  added `test_backtest_replays_stored_signals`, `test_backtest_honest_when_no_signals`,
  `test_per_key_queue_cap` (`test_ws3_jobs.py`) and
  `test_websocket_rejects_invalid_or_missing_key` (`test_ws3_websocket.py`).
- **Full suite:** **1,776 passed, 5 skipped, 0 failed** (WS-3 subset 68/68). ruff check clean.
