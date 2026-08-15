# WS-5 — Reliability, Observability, SLAs, DR: Execution Blueprint

Status: **DRAFT 2026-08-14 — prepared under the honest-premise discipline below;
awaiting user approval + T0 gate decision before any build**
Progress: tracked in `docs/WS5_PROGRESS.md` (created only after this blueprint is approved)
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-5 + Phase 2/3 checkboxes;
handoffs locked by WS-4: `docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md` §5
(multi-worker bucket state → WS-5/Redis), §4 §3.4 no-SLA-before-WS-5,
`docs/WS4_EXECUTION_BLUEPRINT.md` §3.4/§4 T5, `docs/compliance/backup-policy.md`
(policy in force, machinery is WS-5)
Gate: **an explicit, user-made reliability decision** (mirrors WS-3/WS-4 T0).
Long-term gate is **G3** (Production Blueprint §5: end of Phase 3 — 99.9%
uptime/30 d, first paid contracts, SOC2 controls operational and being observed).
**WS-5 is the workstream that makes G3's *uptime* clause reachable and
offerable**: before WS-5 the 99.9% language is explicitly not an offer (locked
in WS-4 §3.4); after WS-5 ships it becomes one, still measured honestly.

---

## 0. Honest premise (what WS-5 is actually for)

WS-1 G1 is UNDER-POWERED (N = 7 < N_min = 8; 0 scored live events). WS-3 (API)
and WS-4 (auth/security/tenancy/compliance) shipped under explicit infra-first
mandates and did not change that. WS-4 additionally locked the **no-SLA
posture**: the current deployment is **single-worker**, token buckets live
in-memory in that worker, there is no failover, and the master blueprint's
99.9 % uptime language must **not become an offer** to any tenant until WS-5
ships multi-worker state (Redis) + failover/DR
(`docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md` §5).

WS-5's mandate, read honestly, is therefore:

> **Make the service operationally credible before anyone pays for it.** Ship
> the observability, the multi-worker state, the SLO discipline, the status
> page, and the tested disaster-recovery machinery that turn "best-effort
> single worker" into "a service with a measured, budgeted, honestly-offered
> availability claim". WS-5 does not claim, and cannot clear, G1. WS-5 also
> does **not** prove 99.9 % over a window — it builds the machinery to measure
> and defend it; the *evidence* of meeting 99.9 % accrues in the 30-day window
> that starts only once the machinery is running.

**Why now:** Phase 3's enterprise-hardening exit is "99.9% uptime over 30
days" and the first paid contracts — both of which the WS-4 contract already
conditioned on WS-5. The SOC2 Type II observation clock (started 2026-08-14)
also needs the reliability controls (backup drills, monitoring, incident
response) to be **operational, not just documented**, to count as controls
under observation. Every week WS-5 is idle is a week of un-observed controls
and an un-offerable SLA.

**What is NOT being decided here:** WS-5 does not set the price of an SLA, does
not choose a cloud provider, does not promise multi-region or auto-scaling
(Phase 4), and does not schedule SOC2 certification. WS-5 builds the machinery
and the honest claim language; the clock starts when the machinery runs.

---

## 1. Purpose

Turn the single-worker best-effort API into a **measured, monitored,
multi-worker-capable, DR-tested service**:

- **Multi-worker rate-limit state (Redis)** — token buckets shared across
  uvicorn workers so horizontal scale does not multiply quota. The locked
  WS-4 commitment, and the structural prerequisite for the 99.9% offer.
- **Multi-worker-safe audit chain** — the WS-4 chain is append-serialized
  in-process; with >1 worker the append must be serialized across processes
  (Postgres advisory lock) so `prev_hash` chains stay valid.
- **Metrics (Prometheus)** — request latency / error rate, data-cycle
  freshness, ingestion lag, signal compute time, store + audit health.
- **Dashboards + alerting (Grafana)** — API health, pipeline health,
  model-skill/status tracking; alerts on ingestion failure, staleness,
  API error-rate breach.
- **SLOs + error-budget policy** — API 99.9% uptime; signal within 60 s of
  run publication; data staleness < 1 cycle; budget consumed, tracked, and
  repaid — and the WS-4 no-SLA clause lifted **only when** the machinery and
  the 30-day clock are real.
- **Structured logs + centralized sink** — the JSON-lines discipline extended
  to one sink; request ids correlated end-to-end (nginx → API → audit).
- **Public status page** — `/v1/health` stays DB-free liveness for probes;
  `/v1/status` is the deep, cached, rate-limited human/machine page; a weather
  vendor without a status page is not credible.
- **DR/backups operationalized** — base + WAL backup scripts, off-host copy,
  and a **restored-and-verified** drill (chain + ledger + suites pass against
  the restored DB), rehearsed in CI — turning `backup-policy.md` from policy
  into machinery.

**Deferred explicitly:** WS-6 owns metering (per-key request/feed/backtest-hour
accounting on the audit + rate-limit data WS-5 exposes) and billing (Stripe).
WS-7 owns GTM. Auto-scaling and multi-region are Phase 4. WS-5 does **not**
choose billing/tiering, does not promise N workers by default, and does not
claim an achieved uptime number until the window has elapsed.

---

## 2. Out of scope (explicitly)

- Metering/billing/Stripe (WS-6), GTM (WS-7).
- Auto-scaling, multi-region, k8s (Phase 4).
- SOC2 Type I/II certification scheduling (the observation clock continues; the
  reliability controls becoming *operational* is WS-5's contribution to it).
- Model-skill *algorithm* work (the drift alert monitors live BSS vs the
  locked baseline — it consumes the existing ledger, it does not re-derive it).
- Changing the WS-3/WS-4 request contract: the unset-`PAKHI_REDIS_URL`
  single-worker path must behave byte-identically to today.

---

## 3. Detailed design

### 3.1 Reliability contract & SLOs

A new locked contract `docs/WS5_RELIABILITY_CONTRACT.md` + machine twin
`data/ws5/reliability_contract.json` (self-hash-pinned, same pattern as
WS-2/WS-3/WS-4). It is the **single source of truth** for thresholds consumed
by alert rules, the status page, the error-budget accounting, and the SLA offer
language.

- **SLO-1 API availability:** 99.9% over a rolling 30-day window. Downtime
  defined as 5xx-series (or connection-level failure) at the edge; 4xx and
  429 are *client* errors, never downtime. Budget = 43.2 min/30 d.
- **SLO-2 Signal latency:** a live signal is visible via the API within 60 s
  of its run's publication timestamp.
- **SLO-3 Freshness:** the served data is never older than one cycle
  (`staleness_seconds < cycle_period`); exceeding it flips the pipeline to
  `DEGRADED` on the status page.
- **Error budget policy:** 429s are billable to the *client* tier, never the
  API budget; each consumed budget slice has an owner and a repayment (a
  reliability fix) before new features ship; a budget burn-down alert fires at
  50 % consumed.

The no-SLA clause in the WS-4 contract is **amended in T6**, not sooner: the
offer language flips only after Redis (T1), metrics (T2), SLO accounting (T4),
and a green DR drill (T5) are in, and a 30-day measurement window is open and
being recorded.

### 3.2 Metrics taxonomy

All metrics carry `{tenant?, tier, status, path, method}` labels where
meaningful; **no PII, no raw keys, no raw tokens** — the same rule as the
audit store. Export endpoint `GET /metrics` (no auth, admin network only).

**Multiprocess mode is mandatory, not optional.** T1 opens `--workers N`, and
`prometheus_client` keeps counters in-memory **per process** by default: with
N workers the load balancer round-robins `/metrics` scrapes across workers, so
Prometheus would see counters jump (worker A reports 10, worker B reports 3),
corrupting every rate and histogram. Therefore the registry **must** use
`prometheus_client`'s Multiprocess Mode: each worker writes its metrics to
memory-mapped files in a single shared `PROMETHEUS_MULTIPROC_DIR`, and
`/metrics` aggregates the files across all workers (`CollectorRegistry`
multi-process registry + `generate_latest(registry, multiprocess=True)`). The
same shared dir is used by every worker of the same deployment; a misconfigured
dir (empty/unset) with workers > 1 is a boot error, never a silent per-worker
registry.

- **API:** `pakhi_http_requests_total`, `pakhi_http_request_duration_seconds`
  (histogram), `pakhi_http_5xx_total`, `pakhi_ratelimit_rejections_total{tier}`,
  active WebSocket gauge.
- **Pipeline/cycle:** `pakhi_cycle_freshness_seconds`,
  `pakhi_cycle_ingestion_lag_seconds`, `pakhi_cycle_compute_duration_seconds`,
  `pakhi_cycle_status` (0/1), `pakhi_cycle_last_ok_timestamp_seconds`.
- **Store/security:** DB pool in-use/max gauges, `pakhi_audit_rows_appended_total`,
  `pakhi_audit_chain_ok` (1/0 — polled `verify_chain_in_store`),
  `pakhi_db_key_validator_fail_closed_total`.
- **Model-skill (drift):** live BSS vs locked baseline from the ledger,
  published as a gauge (WS-2 data), alert on sustained regression.

### 3.3 Redis multi-worker rate-limit state

- New env `PAKHI_REDIS_URL` (additive; unset ⇒ today's in-memory single-worker
  behavior, byte-compatible).
- `RedisTokenBucketLimiter` implements the exact `check`/`peek` interface of
  `pakhi/api/auth.py::TokenBucketLimiter` (`(allowed, limit, remaining,
  reset_secs)`), so middleware code does not branch on storage backend. Bucket
  ops are atomic via a Lua script (single round-trip, no torn read-modify-write
  across workers).
- **Fail-closed discipline (mirrors WS-4):** with `PAKHI_REDIS_URL` set,
  Redis unavailability ⇒ 503 on rate-limited requests and a readiness flip —
  quota is **never** silently lifted or over-counted across workers. With the
  URL unset, the single-worker in-memory path is unchanged.
- **Multi-worker audit chain appends:** the WS-4 `_APPEND_LOCK` is
  process-local. With N workers the append becomes: one `INSERT … RETURNING`
  computing `prev_hash` from the last committed row **inside the same
  transaction, serialized by a Postgres advisory transaction lock**
  (`pg_advisory_xact_lock`) — so any number of workers append a valid chain.
  **Lock keying is a contract value, never an accident:** the advisory lock id
  is the named constant `AUDIT_APPEND_LOCK_ID = 4815162342` (64-bit, unique to
  the Pakhi audit ledger, recorded in the reliability contract twin), so the
  audit lock can never collide with other locks or silently lock the whole
  app. **Locked-block discipline:** the transaction around the lock is strictly
  limited to the chain-head read + `prev_hash` computation + the audit INSERT —
  zero external network calls, DB round-trips to other stores, or heavy
  computation inside the locked block (the caller's business logic runs
  *before* the block; only the append is serialized).
- Uvicorn `--workers N` becomes a supported, contract-gated configuration
  (workers > 1 only with Redis + Postgres advisory locking; the health/status
  page exposes the worker count).

### 3.4 Structured logs + centralized sink

- Extend the WS-4 JSON-lines access log: add `path_params`-free safe labels
  (route template, `tenant_id`, `tier`), one line per request with
  `request_id`, `duration_ms`, `status`. No bodies, no keys, no tokens.
- Ship a documented centralized-sink contract: the API logs JSONL to stdout
  (existing), an optional collector (Loki/Grafana Alloy) is wired in
  docker-compose so nginx, API, pipeline, and backup logs land in one queryable
  place correlated by `request_id` / `cycle_id`. The sink is optional at
  runtime; the format contract is not.

### 3.5 Liveness vs deep status (separated by design)

- **`GET /v1/health`** stays the **ultra-lightweight liveness** endpoint — the
  WS-3 contract already defines it as "liveness only (Docker/K8s probes)" and
  it touches **no DB, no Redis**: it answers 200 `{"status": "ok"}` if the
  process is breathing. Load balancers and orchestration probes scrape this,
  never `/v1/status`. If the DB is slow, probes keep the worker alive while
  the deep page reports the problem — a slow status read must never look like
  a dead process (that is how probe-timeouts cascade into killing the API).
- **`GET /v1/status`** is the **deep, human-facing status page** — DB/Redis
  reachability, cycle freshness, error budget remaining, audit chain health,
  worker count. It is **rate-limited** (free-tier bucket) and **aggressively
  cached in memory (10 s TTL)** so a flood of status checks — or a probe mis-
  wired to it — cannot thrash the database. The cache is invalidated by a
  push (pipeline write) and by the 10 s TTL, whichever comes first.
- Public, no auth, still rate-limited; JSON when `Accept: application/json`,
  HTML when `Accept: text/html` — one route, two views.

### 3.6 DR/backups operationalization (`backup-policy.md` → machinery)

- `scripts/run_ws5_backup.py` — base snapshot (`pg_dump` / sqlite copy for dev)
  + continuous WAL archive to a configured directory, then an **off-host copy**
  hook; exits 0/1 and writes a JSONL record per run (correlated into the log
  sink).
- `scripts/run_ws5_restore_drill.py` — restore the latest trusted base + WAL
  into a **scratch database**, then verify: `verify_chain_in_store` passes,
  WS-3/WS-4 suites pass against the restored DB, and the latest published cycle
  matches the off-host log. Exit 0 only if all three pass — the backup-policy's
  "tested restore" clause, executed, not described.
- A **restore drill runs in CI** (Postgres 16 service container): snapshot →
  wipe → restore → verify chain + ledger. This makes the quarterly rehearsal a
  habit rather than a calendar hope.

### 3.7 Prometheus / Grafana / alerting topology

- `pakhi` API exposes `/metrics`; `docker-compose` gains `prometheus` (scrape
  config generated from the reliability contract JSON) and `grafana` (dashboards
  + alert rules provisioned from the repo: API health, pipeline health,
  model-skill/status).
- Alerts: ingestion failure (WS-2 alert → metric), staleness > 1 cycle,
  API error-rate breach, error-budget > 50% consumed, Redis down in
  multi-worker mode, audit chain verify failing. Alert rules parse-tested in CI
  (JSON validity + thresholds equal the contract twin); live Grafana alerting is
  runtime, not CI-testable.

---

## 4. Tasks, sequencing, exit criteria

### T0 — Gate decision + reliability contract freeze
Before any build:
- Record the gate verdict in `docs/WS5_PROGRESS.md`: **explicit user
  reliability-first decision** (mirroring WS-3/WS-4 T0). If declined, WS-5
  stays prepared, not executed.
- Freeze `docs/WS5_RELIABILITY_CONTRACT.md` + `data/ws5/reliability_contract.json`
  (self-hash-pinned). Lock: SLOs + definitions (what counts as downtime, what
  never does), error-budget policy, metrics taxonomy, Redis fail-closed rule,
  status-page semantics, DR RPO/RTO + drill criteria, and the **backwards-compat
  rule** (unset `PAKHI_REDIS_URL` single-worker path is byte-identical).
- Add `pakhi/ws5/` package skeleton (metrics registry + contract access,
  import-clean, no side effects).
- **Exit:** contract doc + machine JSON approved and hash-pinned; gate verdict
  recorded; `pakhi.ws5` imports cleanly; WS-3 + WS-4 suites still green.

### T1 — Redis multi-worker state (week 1)
- `RedisTokenBucketLimiter` (same interface, Lua-atomic); `PAKHI_REDIS_URL`
  wiring; fail-closed 503 on Redis down in multi-worker mode; single-worker
  in-memory fallback unchanged.
- Multi-worker-safe audit chain appends via Postgres advisory xact lock using
  the named constant `AUDIT_APPEND_LOCK_ID = 4815162342` (recorded in the
  contract twin); the locked block contains only chain-head read + `prev_hash`
  + INSERT — no external calls; `--workers N` supported configuration;
  status/health exposes the worker count.
- **Exit:** tests — two limiter instances sharing one Redis enforce a single
  bucket (N workers cannot multiply quota); Redis-down-with-URL-set ⇒ 503, not
  a loosened limit; unset-URL path byte-identical (WS-3 rate-limit headers
  unchanged); two concurrent audit appends produce a valid chain
  (`verify_chain_in_store` passes); the advisory lock id constant equals the
  contract twin value; WS-3 + WS-4 suites green.

### T2 — Prometheus metrics (week 1–2)
- `/metrics` endpoint; API, pipeline/cycle, store/audit, and drift gauges per
  §3.2; `GET /metrics` on the admin network.
- **Multiprocess mode required:** `PROMETHEUS_MULTIPROC_DIR` shared
  memory-mapped registry; `/metrics` aggregates across workers; empty/unset dir
  with workers > 1 is a boot error, never a silent per-worker registry.
- **Exit:** tests assert the named metric lines appear and carry the locked
  labels (request latency histogram, cycle freshness gauge, ratelimit
  rejections by tier); a two-process aggregation test proves counters sum
  across workers (scrape never shows a single worker's partial count); no
  PII/keys/tokens in any metric; WS-3/WS-4 green.

### T3 — Grafana + alerting (week 2)
- `docker-compose` `prometheus` + `grafana`; scrape config and dashboards
  provisioned from the contract twin; alert rules for staleness, ingestion
  failure, error-rate breach, budget burn, Redis-down, chain-verify failure.
- **Exit:** configs parse (CI test); every alert threshold equals the contract
  twin value (reconciliation test); a local `docker compose up` runs and the
  status page reflects the same numbers the alert rules use.

### T4 — SLOs, error budget, log sink, status page (week 2–3)
- Error-budget accounting (consumed/remaining from `/metrics`), the
  budget-burn alert, and the SLO measurement window recorder.
- Structured-log extensions (route template, `tenant_id`, `tier`) + centralized
  sink wiring (optional collector, correlated by `request_id`/`cycle_id`).
- **Liveness/deep-status split:** `/v1/health` stays DB-free liveness (probes
  scrape only this); `/v1/status` becomes the deep page — rate-limited,
  in-memory 10 s TTL cache, JSON + HTML views, driven by the contract twin.
- **Exit:** tests — a probe flood of `/v1/health` never touches the DB (it
  performs no query); `/v1/status` is served from the 10 s cache without a DB
  round-trip on repeat calls within TTL; it reflects `DEGRADED` when the fixture
  pipeline goes stale; 429 is never counted as downtime in budget accounting;
  access-log lines carry `request_id` + route template; WS-3/WS-4 green.

### T5 — DR/backups operationalized (week 3)
- `run_ws5_backup.py` + `run_ws5_restore_drill.py`; off-host copy hook;
  restore-drill CI job (Postgres 16 service container): snapshot → wipe →
  restore → verify chain + ledger + suites.
- **Exit:** a wipe-and-restore drill in CI passes end-to-end against a real
  Postgres 16; `backup-policy.md`'s tested-restore clause is now executable and
  rehearsed; RPO (≤ 1 cycle) and RTO (≤ 4 h) are stated in the contract twin as
  targets the drill measures.

### T6 — SLA offer + exit evidence (week 3–4)
- Amend the WS-4 contract's no-SLA clause: the 99.9% language becomes an offer
  **conditioned on** the machinery being live and the 30-day window open and
  recorded (the *evidence* of meeting it accrues over the window; WS-5 does not
  fabricate it). Re-pin both contract twins.
- **Exit:** full suite green (WS-3 + WS-4 + WS-5); a 30-day measurement window
  started and recorded in `docs/WS5_PROGRESS.md`; SOC2 observation clock entry
  notes the reliability controls (metrics, alerting, backup drills) are
  operational; every control in §4 has a test or a rehearsed drill, not a
  config file; `data/ws1/g1_decision.json` reverted after the run.

---

## 5. Rules & discipline (applies to all tasks)

1. **No breaking change to WS-3/WS-4.** The unset-`PAKHI_REDIS_URL`
   single-worker path is byte-identical to today; WS-3 + WS-4 suites stay green
   after every change.
2. **Fail-closed, never fail-open.** Redis down in multi-worker mode = 503, never
   a silently loosened quota. DB key validity stays fail-closed (WS-4).
3. **Honest SLOs.** Nothing is claimed without a metric behind it; the
   error-budget policy is documented in the contract twin **before** any SLA
   language flips; 4xx/429 are client faults, never downtime.
4. **Single source of truth.** Every threshold appears once — in
   `data/ws5/reliability_contract.json` — and alert rules, status page, and
   budget accounting are reconciled against it by a test (the WS-4
   cross-reference rule, applied to numbers).
5. **Evidence-driven exit.** Each task's exit is a test or a rehearsed drill;
   "the config looks right" is never an exit.
6. **DR is rehearsed.** A restore that has never run is not a backup; the CI
   restore drill is the smallest habit that makes the quarterly requirement real.
7. **No fabricated uptime.** WS-5 builds the machinery; the 99.9 % claim is an
   offer that starts with the 30-day window, and evidence accrues only when the
   machinery is live. The SOC2 observation clock continues from WS-4.
8. **Multiprocess metrics are non-negotiable above one worker.** Any deployment
   with `--workers N > 1` must use the shared `PROMETHEUS_MULTIPROC_DIR`
   registry; per-worker in-memory counters at N > 1 are a boot error, never a
   silent partial picture.
9. **Cross-reference pass before any "final".** Every number/definition used in
   more than one place (SLO targets, budget %, alert thresholds, staleness
   limits, tier limits, `AUDIT_APPEND_LOCK_ID`) is reconciled inside and across
   the doc set before a doc is labeled final.

---

## 6. Timeline

Build weeks are measured **from T0 approval**. T1–T2 are the critical path for
the SLA offer (Redis → multi-worker → measured window). T3/T4 can overlap T2;
T5 is independent until the DR drill lands. Estimated: **4 weeks** to a fully
green WS-5 with the 30-day window open. G3's uptime evidence then accrues from
the window's start — WS-5 schedules the *machinery and the clock*, never the
number itself.
