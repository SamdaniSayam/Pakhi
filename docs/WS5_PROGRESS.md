# WS-5 Progress Tracker — Reliability, Observability, SLAs, DR

Per working agreement: every execution step is logged here with terminal
evidence, and the user is shown the running terminal live.

- Blueprint: `docs/WS5_EXECUTION_BLUEPRINT.md` (**REVISED 2026-08-14 v1.1** — user
  T0 amendment: `AUDIT_APPEND_LOCK_ID` lock keying + locked-block discipline,
  mandatory Prometheus multiprocess mode, liveness/deep-status split)
- Contract: `docs/WS5_RELIABILITY_CONTRACT.md` + `data/ws5/reliability_contract.json` (LOCKED)
- Gate: **APPROVED** (T0 verdict below) — explicit user reliability decision
- SOC2 observation clock: running since 2026-08-14 (WS-4); WS-5 controls must
  become *operational* (metrics, alerting, backup drills) to count
- Started: 2026-08-14

---

## T0 — Gate verdict + reliability contract freeze

**Gate verdict (2026-08-14):** The user approved the WS-5 execution blueprint
with three amendments folded into v1.1: (1) audit-chain advisory lock uses the
named constant `AUDIT_APPEND_LOCK_ID = 4815162342` with a locked block strictly
limited to chain-head read + `prev_hash` + INSERT; (2) Prometheus
`PROMETHEUS_MULTIPROC_DIR` multiprocess mode is mandatory above one worker;
(3) `/v1/health` stays DB-free liveness for probes while `/v1/status` is the
deep, rate-limited, 10 s-cached page. G1 remains **UNDER-POWERED** (N = 7 <
N_min = 8); WS-5 is reliability infrastructure, never an edge claim, and the
no-SLA-before-WS-5 clause stays in force until T6.

**Contract frozen:** `docs/WS5_RELIABILITY_CONTRACT.md` + machine twin
`data/ws5/reliability_contract.json`, hash-pinned below.

---

## Log

### 2026-08-14 — T0 DONE: Gate + reliability contract freeze
- **Gate verdict recorded** (header above): user approved the blueprint with
  three amendments folded into v1.1 — (1) `AUDIT_APPEND_LOCK_ID = 4815162342`
  advisory-lock keying + locked-block discipline (chain-head read + `prev_hash`
  + INSERT only, zero external calls inside the lock); (2) mandatory Prometheus
  multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`) above one worker, boot error
  when misconfigured; (3) `/v1/health` stays DB-free liveness for probes while
  `/v1/status` is the deep, rate-limited, 10 s-cached page.
- **Contract frozen:** `docs/WS5_RELIABILITY_CONTRACT.md` + machine twin
  `data/ws5/reliability_contract.json` (self-hash-pinned, payload sha256
  `9a1a470e2e03...`). Locks: SLOs + never-downtime definitions (4xx/429/401/403
  are client faults, never API downtime), 43.2 min/30 d budget + 50% burn
  alert, Redis fail-closed 503 rule, advisory-lock constant, multiprocess
  metrics rule, liveness/deep-status split, DR RPO ≤ 1 cycle / RTO ≤ 4 h,
  backwards-compat rule (unset-Redis single-worker path byte-identical).
- **Skeleton:** `pakhi/ws5/` — `contract.py` (twin accessor + `contract_consistent`
  self-hash + typed getters for every locked value) and `metrics.py`
  (contract-driven metric families; `prometheus_client` deliberately not
  imported at package import — T2 wires the registry).
- **Tests `tests/test_ws5_t0_skeleton.py`** (7): import-clean via subprocess
  (no fastapi/api extra), no side effects + no prometheus_client at import,
  twin self-hashes, accessor returns exactly the locked values, lock-id
  constant == twin, metric families match contract, backwards-compat rule
  present.
- **Exit evidence:** contract doc + machine JSON approved and hash-pinned; gate
  verdict recorded; `pakhi.ws5` imports cleanly; WS-3 + WS-4 suites green
  (136 passed / 3 skipped across the WS-3 + WS-4 + WS-5 T0 subset); ruff clean.

### 2026-08-14 — T1 DONE: Redis multi-worker state (fail-closed 503)
- **`pakhi/ws5/redis_limiter.py`:** `RedisTokenBucketLimiter` implements the exact
  `check`/`peek` interface of the in-memory `TokenBucketLimiter` (byte-identical
  `(allowed, limit, remaining, reset_secs)` semantics, Lua scripts `_KEY_CHECK` /
  `_PEEK_LUA`, token-bucket math mirrors `int()` flooring exactly). `build_tier_limiters`
  factory: `PAKHI_REDIS_URL` set -> one shared `redis.Redis` client + per-tier
  Redis buckets; unset -> in-memory limiters (single-worker posture, byte-identical
  to WS-3/WS-4). `RedisUnavailableError` raised on any store failure.
- **Fail-closed middleware** (`pakhi/api/auth.py`): `check`/`peek` wrapped —
  `RedisUnavailableError` -> 503 `redis_unavailable` envelope, never a loosened
  or over-counted quota. `/v1/health` stays rate-limited exactly as WS-3 for T1
  (its conversion to DB-free probe liveness is T4's scope, tracked in auth.py
  comment + test).
- **Workers gate** (`pakhi/api/settings.py`): `PAKHI_REDIS_URL` +
  `PAKHI_WORKERS` (default 1); `workers > 1` without a Redis URL = boot error
  (shared rate-limit state is mandatory, never silently multiplied quota).
- **Multi-worker audit appends** (`pakhi/ws4/audit_events.py`):
  `_acquire_cross_process_lock` acquires `pg_advisory_xact_lock(:k)` with the
  contract's `AUDIT_APPEND_LOCK_ID` (Postgres dialect only; sqlite keeps the
  in-process `_APPEND_LOCK`). Locked block = chain-head read + seal + add only.
- **Deps** (`pyproject.toml`): `redis` extra (`redis>=5.0`); `fakeredis>=2.20` +
  `lupa>=2.0` (Lua emulation) in `dev`.
- **Tests `tests/test_ws5_t1_redis.py`** (11: 9 run locally + 2 gated): shared
  bucket across limiter instances cannot multiply quota; replenish at fill rate;
  peek non-consuming; same interface as in-memory; Redis-down -> 503
  `redis_unavailable` (endpoints + health), never loosened; unset-Redis path
  byte-identical (tier headers + quota consumed); workers gate;
  Postgres-gated 8-thread concurrent audit appends -> 8 distinct links + valid
  chain; real-Redis gate (`REDIS_URL`) matching in-memory exactly.
- **CI** (`.github/workflows/ws4-security.yml`): redis:7 service container,
  `REDIS_URL` env, runs `-k "ws4 or ws5"`, inline multi-worker smoke (30 shared
  quota requests -> 31st is 429, `PAKHI_WORKERS=2`), fail-closed verified.
- **Exit evidence:** full suite 1854 passed / 10 skipped (WS-3 + WS-4 suites
  stay green: 146 passed / 5 skipped in the ws3+ws4+ws5 subset); ruff check +
  format clean; contract unchanged (Lua bucket ops claim already matches the
  locked twin).

### 2026-08-14 — T2 DONE: Prometheus /metrics + mandatory multiprocess mode
- **`pakhi/ws5/metrics.py`:** `initialize(workers)` builds the registry — workers>1
  requires a valid `PROMETHEUS_MULTIPROC_DIR` (mmap `MultiProcessCollector`, boot
  error otherwise, never a silent per-worker registry); workers=1 uses a plain
  `CollectorRegistry`. All 16 locked families defined with contract labels;
  `prometheus_client` imported lazily (T0 import-clean guarantee preserved).
  Recording helpers (http/ratelimit/cycle/audit/skill/ws/db) are no-ops until
  initialized (safe for scripts).
- **`pakhi/ws5/api.py`:** `GET /metrics` (unauthenticated, admin network) +
  `MetricsMiddleware` — outermost middleware so it records the **edge** status
  (401/429/503 included) and full latency. The `path` label is the matched
  route **template** via `scope["route"].path` (never raw paths → no PII, no
  cardinality); 404s become `unmatched`.
- **Wiring:** `create_app` initializes the registry + adds the middleware last;
  `AuthAndRateLimitMiddleware` exempts `/metrics` (no 401/429/quota) and records
  `pakhi_ratelimit_rejections_total{tier}` on 429; WebSocket handler drives
  `pakhi_ws_active`.
- **`pyproject.toml`:** `obs` extra (`prometheus-client>=0.20`); CI installs
  `.[all,api,redis,obs]`.
- **Tests `tests/test_ws5_t2_metrics.py`** (9): multiprocess aggregation via two
  real spawn children sharing one mmap dir (5+3 counters sum to 8, never a
  partial worker count); boot errors for unset/bogus mp dir (module + create_app
  level); locked families present on /metrics; route-template label (raw symbols
  AAPL/IBM never appear); no PII/keys/query strings; edge status incl. 404/503
  (5xx family); tier-labeled ratelimit rejections; cycle/audit/skill gauge
  helpers publish.
- **T0 test fix:** `test_ws5_import_has_no_side_effects` now proves the
  laziness guarantee in a fresh interpreter (subprocess) — after `create_app`
  the in-process `sys.modules` check was a false alarm, not a regression.
- **Exit evidence:** full suite **1863 passed / 10 skipped** (WS-3 + WS-4 green:
  155 passed / 5 skipped in the ws3+ws4+ws5 subset); ruff clean; contract
  unchanged.

### 2026-08-14 — T3 DONE: Prometheus + Grafana + alerting, contract-derived
- **Single source of truth:** `scripts/ws5_gen_observability.py` renders
  `deploy/observability/{prometheus.yml,alert-rules.yml}` from the contract
  twin — a threshold lives once (the twin) and is *rendered* everywhere else.
  CI regenerates to a temp dir and asserts byte-identity with the committed
  files (drift = test failure).
- **Alert rules (9):** PakhiApiErrorRateBreach (`1 - 0.999` → 5xx rate > 0.001),
  PakhiErrorBudgetBurn (`< 1 - 0.5`), PakhiSignalLatencyBreach (`> 60s`),
  PakhiStalePipeline (`> 86400 = cycle_period × max_stale`), PakhiCycleFailed,
  PakhiNoOkCycle (`> 86400`), PakhiRedisFailClosed (`status="503"` =
  `redis.fail_closed_http`), PakhiAuditChainBroken, PakhiSkillDrift
  (sustained regression below baseline). Each rule is annotated with its twin
  path + rendered value.
- **Contract amendment (re-pinned v1.1, sha `63a22ee3…`):** added
  `slo.cycle_period_seconds = 86400` and `metrics.families.slo` →
  `pakhi_error_budget_remaining_fraction` (gauge now defined in T2's registry,
  published by T4's SLO accounting; burn rule dormant until then). Doc
  `docs/WS5_RELIABILITY_CONTRACT.md` updated (§2 SLO-3 row, §5 table).
- **Grafana:** `deploy/observability/grafana/` provisioning (Prometheus
  datasource, file provider) + `api.json` dashboard (request/5xx rate, p99
  latency, cycle freshness, error-budget remaining, audit chain, tier
  rejections) — panels reference only contract families.
- **docker-compose:** `prometheus` + `grafana` services added (configs and
  dashboards mounted read-only; grafana provisions from the repo). A full
  interactive `docker compose up` is the operator's local verification;
  CI-gated evidence = compose `config -q` parse + config/rules/dashboard
  reconciliation tests.
- **Tests `tests/test_ws5_t3_alerting.py` (7):** byte-identical regeneration;
  per-rule thresholds equal the twin (incl. composed `cycle_period ×
  max_stale`); every alert consumes only contract families; prometheus config
  scrapes `api:8000` + loads rules; dashboard uses only contract families;
  compose provisions observability; compose config parses (v1/v2 CLI both
  handled).
- **Exit evidence:** full suite **1870 passed / 10 skipped** (ws3+ws4+ws5
  subset 162 passed / 5 skipped); ruff clean; twin self-hash valid.

### 2026-08-14 — T4 DONE: /v1/status deep page + /v1/health liveness split + SLO accounting
- **Liveness/deep split (contract §6):** `/v1/health` is now DB-free probe
  liveness — no auth, no rate limiting, no Redis dependency (stays 200 through
  downstream outages; Docker/K8s probe target). `/v1/status` is the deep page:
  rate-limited, 10 s in-memory TTL cache (per-app), JSON + HTML views
  (`?format=html` or `Accept: text/html`).
- **Deep page reports the contract components:** `db_ok`/latest cycle/
  staleness/worker_last_run (WS-3 keys preserved) + `status` OK/DEGRADED,
  `version`, `workers`, `pipeline.{state, cycle_period_seconds}` (DEGRADED once
  staleness ≥ `cycle_period_seconds` — SLO-3), `redis.{configured, ok,
  fail_closed_http}`, `audit_chain.{ok, checked_at}` (store replay, throttled by
  cache, tolerant of un-initialized audit store), `error_budget.*`, `cache.ttl`.
  `X-Pakhi-Staleness` header + 503 `db_unavailable` preserved; 503s are never
  cached (DB liveness re-checked per request).
- **SLO-1 accounting (`pakhi/ws5/budget.py`):** rate-based proxy that reconciles
  with the burn alert — `remaining = 1 − min(1, 5xx_rate / (1 − 0.999))`; every
  edge 5xx is ledgered (ts/endpoint/status); Redis fail-closed 503s (T1) are
  tagged via `request.state.ws5_fail_closed` in auth middleware, recorded
  separately, and never consume budget (contract §2). Publishes
  `pakhi_error_budget_remaining_fraction` (new contract family `slo`). Budget is
  reset per app lifecycle like the limiters; in-process per-worker view is
  stated honestly on the page.
- **Deliberate test migrations (blueprint-authorized):** WS-3 auth/limit tests
  (`test_ws3_auth_limiter.py`) and WS-4 tenancy/token tests
  (`test_ws4_t1_tokens.py`, `test_ws4_t2_tenancy.py`) moved their auth/rate-limit
  probes from `/v1/health` to `/v1/status`; `test_ws5_t1_redis.py` now asserts
  health stays 200 through a Redis outage while status 503s fail-closed.
- **Tests `tests/test_ws5_t4_status.py` (12):** DB-free liveness (bogus DB +
  hammered past buckets), deep-page components, DEGRADED past one cycle +
  staleness header, HTML view (both param + Accept), cache TTL + expiry + per-app
  isolation, redis-up end-to-end (real redis client → `fakeredis.TcpFakeServer`
  in a thread), 503-not-cached, ledger counts real 5xx, gauge published,
  fail-closed 503 tagged not-real-downtime.
- **Exit evidence:** full suite **1882 passed / 10 skipped** (ws3+ws4+ws5 subset
  174 passed / 5 skipped); ruff clean.

### 2026-08-14 — T5 DONE: DR scripts + backup + restore drill operationalized
- **`scripts/run_ws5_backup.py`:** dialect-aware base snapshot (`pg_dump -Fc`
  for Postgres, SQLite Online Backup API for the hermetic path), pinned
  manifest (backup_id, source (URL password redacted), base file + sha256 +
  tool, latest cycle id/ts, row counts, `verify_chain_before_backup`,
  base/wal/off-host layers, RPO/RTO from the twin, retention). Off-host copy
  hook (`--off-host-dir`); `--keep` retention prune. **Integrity gate:** the
  store's audit chain must verify before a backup is taken (policy §5) — a
  backup of an untrusted store is refused.
- **`scripts/run_ws5_restore_drill.py`:** the drill — snapshot (fresh or
  `--backup-file`) → wipe scratch DB (SQLite unlink / Postgres
  `DROP ... WITH (FORCE)` + `CREATE`) → restore → `verify_chain_in_store` →
  ledger/count reconciliation vs the manifest → WS-3 read-path smoke on an app
  booted against the restored DB (`/v1/instruments`, `/v1/ledger`,
  `/v1/status`) → WS-4 evidence suite `tests/test_ws4_t5_ci.py` via
  `WS4_TEST_DB_URL` (the `ws4-security` template). RPO/RTO read from the twin
  and reported. `PAKHI_PG_DUMP`/`PAKHI_PG_RESTORE` env overrides for
  containerized binaries.
- **CI drill `.github/workflows/ws5-dr.yml`:** Postgres 16 service container,
  seed (cycle 20260814_12z + paper-ledger row + tenant + sealed 2-row audit
  chain) → base backup + off-host copy → wipe-and-restore drill → the
  tested-restore clause rehearsed on every change.
- **Fixed latent `test_ws4_t5_ci.py` bugs** (would have failed the `ws4-security`
  Postgres job): `create_api_key` returns `ApiKeyCreated` (use `.key` +
  sha256, not `["key_hash"]`); `issue_tokens` requires `secret=`;
  `environment` must be `live|test` (not `ci`); audit rows require passing
  `AuditSpec` to the service calls. Verified: WS-4 evidence suite passes on a
  restored Postgres DB.
- **Date-bomb fix:** `test_ws3_api.py` status tests moved to now-relative
  timestamps (fixed 2026-08-13 pub crossed the 36 h staleness header threshold
  on 2026-08-15) — same `_recent_pub()` pattern as the T4 status tests.
- **Contract twin → v1.2** (re-pinned `8ef8e745…`): `dr.backup_scripts`,
  `dr.drill_script`, `dr.rehearsal_cadence = "every CI run"`,
  `dr.backup_mechanism`; accessors `rpo_cycles()` / `rto_hours()` added;
  `docs/WS5_RELIABILITY_CONTRACT.md` §7 + `docs/compliance/backup-policy.md`
  (tested-restore clause is now executable + rehearsed) updated.
- **Tests `tests/test_ws5_t5_dr.py` (4, hermetic SQLite):** manifest pins
  ledger + chain + off-host copy + twin targets; refuses a broken-chain store;
  wipe→restore verifies chain/ledger/WS-3 reads end-to-end; reusing a backup
  file + a poisoned scratch DB is wiped clean (no stale rows survive).
- **Exit evidence:** full suite **1886 passed / 10 skipped** (ws3+ws4+ws5 subset
  178 passed / 5 skipped); Postgres 16 drill verified locally end-to-end against
  a real `postgres:16` container; ruff clean; g1_decision reverted.

### 2026-08-14 — T6 DONE: SLA offer posture flip + exit evidence
- **WS-4 no-SLA clause amended → conditional offer.** `data/ws4/security_tenancy_contract.json`
  re-pinned **v1.1** (sha `7ecc5247…`): 99.9% is offered only *while* the WS-5
  machinery is live (Redis multi-worker fail-closed, metrics + multiprocess
  mode, SLO accounting + `/v1/status`, green DR drill) **and** the 30-day
  measurement window is open and recorded; single-worker stays the documented
  posture and no achieved-uptime claim is made. `docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md`
  §5 + header updated to match.
- **WS-5 twin re-pinned v1.3** (sha `68d82132…`): `slo.sla_offer_active =
  true`, `slo.measurement_window = {days: 30, started 2026-08-14, ends
  2026-09-13, recorded_in: this doc}`; `soc2.reliability_controls_operational_at`
  extended to `[t1_redis, t2_metrics, t3_alerting, t4_slo_accounting,
  t5_dr_drill]`.
- **30-day measurement window OPEN (2026-08-14 → 2026-09-13)** — recorded here.
  The *evidence* of meeting 99.9% accrues over this window while the machinery
  is live; WS-5 does not fabricate an achieved uptime number (G1 remains
  UNDER-POWERED, N = 7 < N_min = 8).
- **SOC2 observation clock entry:** the reliability controls (metrics T2,
  alerting T3, budget accounting T4, backup drill T5) are now **operational**,
  not config files — the clock running since 2026-08-14 (WS-4) has a live,
  rehearsed control program to observe.
- **Every control has machine evidence (T6 exit):** t1_redis →
  `tests/test_ws5_t1_redis.py` + `pakhi/ws5/redis_limiter.py`; t2_metrics →
  `tests/test_ws5_t2_metrics.py` + `pakhi/ws5/metrics.py`; t3_alerting →
  `tests/test_ws5_t3_alerting.py` + `scripts/ws5_gen_observability.py` +
  `deploy/observability/alert-rules.yml` (byte-identical regeneration test);
  t4_slo_accounting → `pakhi/ws5/budget.py` + `tests/test_ws5_t4_status.py`;
  t5_dr_drill → `run_ws5_backup.py` + `run_ws5_restore_drill.py` +
  `.github/workflows/ws5-dr.yml` (rehearsed on every CI run). No control is a
  bare config file.
- **Tests `tests/test_ws5_t6_sla.py` (5):** WS-4 twin upgraded to conditional
  offer + self-hash; WS-5 twin offer live with a 30-day window (dates UTC,
  ends = started + 30); every SOC2 control maps to on-disk machine evidence;
  window recorded in this doc; no fabricated uptime claim anywhere + G1
  UNDER-POWERED retained.
- **Exit evidence:** full suite **1891 passed / 10 skipped** (ws3+ws4+ws5 subset
  183 passed / 5 skipped); both twins self-hash; ruff clean;
  `data/ws1/g1_decision.json` reverted after the run.

---

## WS-5 COMPLETE
