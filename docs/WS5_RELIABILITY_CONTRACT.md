# WS-5 Reliability Contract (v1.2)

**Status:** LOCKED before any WS-5 machinery ships (2026-08-14); re-pinned
2026-08-14 (T3) to add `slo.cycle_period_seconds = 86400` (daily 12Z cadence) so
staleness/burn alert thresholds reconcile with the machine twin; re-pinned
2026-08-14 (T5) to name the operationalized DR machinery (`dr.backup_scripts`,
`dr.drill_script`, `dr.rehearsal_cadence`).
Machine twin: `data/ws5/reliability_contract.json` (self-hash-pinned, same
pattern as WS-2/WS-3/WS-4). Scope source: `docs/WS5_EXECUTION_BLUEPRINT.md` §3–§6.

This contract freezes the rules WS-5's reliability properties are judged
against. Any amendment requires a new version + re-lock. Violations of the
locked rules below are **test failures**, never review notes.

## 1. Backwards-compatibility rule (non-negotiable)

The unset-`PAKHI_REDIS_URL` single-worker path behaves **byte-identically to
today** — WS-3 route table, error envelope, rate-limit headers, and the WS-4
security/tenancy surface all keep working unchanged. WS-5 layers on top: every
new env (Redis URL, multiprocess metrics dir) is additive; a CI test re-runs
the full WS-3 + WS-4 suites against every WS-5 change.

## 2. SLOs and what counts

| SLO | Target | Window | Downtime definition |
|---|---|---|---|
| SLO-1 API availability | 99.9% | rolling 30 days | 5xx-series or connection-level failure at the edge (budget = 43.2 min/30 d) |
| SLO-2 Signal latency | signal visible ≤ 60 s after run publication | rolling | exceeded when a published run's signal is not served within 60 s |
| SLO-3 Freshness | staleness < 1 cycle | rolling | `cycle_staleness_seconds ≥ cycle_period` flips pipeline to `DEGRADED` (cycle_period = `slo.cycle_period_seconds` = 86400 s = daily 12Z) |

**Never downtime:** 4xx responses and 429 rate-limit rejections are *client*
faults — they consume the client's tier quota, never the API error budget.
401/403 auth rejections are likewise never API downtime. A 503 is downtime
unless it is the documented fail-closed behavior (Redis-down in multi-worker
mode, §4) — the honest rule is that *planned* fail-closed 503s are recorded
separately in the budget ledger, not hidden.

## 3. Error-budget policy

- Budget is consumed only by downtime per §2; each consumed slice has an owner
  and a repayment (a reliability fix) before new features ship.
- A burn alert fires at **50%** of the 30-day budget consumed; the status page
  exposes `error_budget_remaining`.
- The 99.9 % language becomes an **offer** only when: Redis multi-worker state
  (T1), metrics (T2), SLO accounting + status page (T4), and a green DR drill
  (T5) are in, **and** a 30-day measurement window is open and being recorded
  (T6). The offer is conditioned on that window; the *evidence* of meeting it
  accrues only while the machinery is live.

## 4. Multi-worker rules

- **Redis fail-closed:** with `PAKHI_REDIS_URL` set, Redis unavailability ⇒
  503 on rate-limited requests and a readiness flip. Quota is **never** silently
  lifted or over-counted across workers. Unset URL ⇒ in-memory single-worker
  posture, unchanged.
- **Audit chain appends:** serialized across processes with a Postgres advisory
  transaction lock using the named constant **`AUDIT_APPEND_LOCK_ID =
  4815162342`**. The locked block contains only chain-head read + `prev_hash`
  computation + the audit `INSERT` — zero external network calls, other-store
  round-trips, or heavy computation inside it.
- **Multiprocess metrics:** any deployment with `--workers N > 1` must use the
  shared `PROMETHEUS_MULTIPROC_DIR` registry (`prometheus_client` multiprocess
  mode); `/metrics` aggregates memory-mapped counters across workers. Unset/empty
  dir with N > 1 is a boot error, never a silent per-worker registry.

## 5. Metrics taxonomy (no PII, no keys, no tokens)

| Family | Examples |
|---|---|
| API | `pakhi_http_requests_total`, `pakhi_http_request_duration_seconds`, `pakhi_http_5xx_total`, `pakhi_ratelimit_rejections_total{tier}`, websocket gauge |
| Pipeline/cycle | `pakhi_cycle_freshness_seconds`, `pakhi_cycle_ingestion_lag_seconds`, `pakhi_cycle_compute_duration_seconds`, `pakhi_cycle_status`, `pakhi_cycle_last_ok_timestamp_seconds` |
| Store/audit | DB pool in-use/max gauges, `pakhi_audit_rows_appended_total`, `pakhi_audit_chain_ok`, `pakhi_db_key_validator_fail_closed_total` |
| Skill/drift | live BSS vs locked baseline gauge (WS-2 data; alert on sustained regression) |
| SLO/error budget | `pakhi_error_budget_remaining_fraction` (published by T4 accounting; consumed by the burn alert + status page) |

Labels carry `{tenant?, tier, status, path, method}` where meaningful. `GET
/metrics` is on the admin network only. A metric must never contain raw keys,
tokens, or request/response bodies.

## 6. Liveness vs deep status

- `GET /v1/health` = **liveness only**, DB-free, probe-only target (Docker/K8s).
- `GET /v1/status` = **deep page**: rate-limited, in-memory **10 s TTL cache**,
  JSON + HTML views; reports db, redis, pipeline freshness, error budget
  remaining, audit chain health, worker count; consumed by the alert rules and
  the public page from this contract as the single source of truth.

## 7. DR / backups (operationalizes `docs/compliance/backup-policy.md`)

- **RPO ≤ 1 cycle** (latest published 12Z cycle + ledger restorable).
- **RTO ≤ 4 h** (restore into scratch DB, verify, resume serving).
- Backup = base snapshot + WAL archive + off-host copy; restore drill =
  snapshot → wipe → restore → verify chain + ledger + WS-3/WS-4 suites pass.
- **Operationalized (T5):** `scripts/run_ws5_backup.py` takes a dialect-aware
  base snapshot (`pg_dump -Fc` for Postgres; SQLite Online Backup API for the
  hermetic path), pins a manifest (latest cycle, ledger counts, base sha256,
  chain-verified-before-backup), and copies base + manifest off-host
  (`--off-host-dir`). A store whose audit chain does not verify is refused —
  the backup of an untrusted store is not taken (policy §5).
- **The drill is the control:** `scripts/run_ws5_restore_drill.py` runs
  snapshot → wipe a scratch DB → restore → `verify_chain_in_store` →
  ledger/count reconciliation against the manifest → WS-3 read-path smoke on an
  app booted against the restored DB → the WS-4 evidence suite
  (`tests/test_ws4_t5_ci.py`, the `ws4-security` template) against the restored
  DB. RPO/RTO are read from the twin and reported; the drill measures them.
- The restore drill runs in CI (**`.github/workflows/ws5-dr.yml`**, Postgres 16
  service container) on every change; a restore that has never run is not a
  backup. The hermetic SQLite equivalent is in `tests/test_ws5_t5_dr.py`.

## 8. Gate truth

WS-5 does not clear G1 (UNDER-POWERED, N = 7 < N_min = 8) and does not claim an
achieved uptime number until the 30-day window elapses. The SOC2 observation
clock (started 2026-08-14) continues; WS-5's reliability controls become
*operational* evidence for it once T1–T5 land.
