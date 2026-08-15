# WS-4 Security & Tenancy Contract (v1.1)

**Status:** LOCKED before any WS-4 endpoint ships (2026-08-14); re-pinned
2026-08-14 (WS-5 T6) to upgrade the no-SLA clause to a **conditional offer**
(see §5) now that the WS-5 reliability machinery is operational.
Machine twin: `data/ws4/security_tenancy_contract.json` (self-hash-pinned,
same pattern as WS-2/WS-3). Scope source: `docs/WS4_EXECUTION_BLUEPRINT.md` §3–§5.

This contract freezes the rules WS-4's security properties are judged against.
Any amendment requires a new version + re-lock. Violations of the locked rules
below are **test failures**, never review notes.

## 1. Backwards-compatibility rule (non-negotiable)

The WS-3 `X-Pakhi-Key`-only flow — route table, error envelope, rate-limit
headers, `X-Pakhi-Edge-Status`, backtest `client_id` semantics — **keeps working
unchanged for existing keys**. WS-4 layers on top: the machine lane is retained
verbatim; `client_id` migrates under a default tenant ("pakhi-internal") without
changing observable behavior. A CI test re-runs the full WS-3 suite against every
WS-4 change.

## 2. Identity model — two lanes

| Lane | Credential | At rest | Notes |
|---|---|---|---|
| **Machine** | `X-Pakhi-Key` | SHA-256 hash only | WS-3 unchanged; WS-4 adds per-tenant keys in Postgres (`pk_live_` / `pk_test_` prefixes for rotation + env separation); env/file source demoted to bootstrap/admin-only |
| **Human** | access JWT (HS256, **15 min**) + opaque rotating refresh token | refresh token hashed; JWT signed with `PAKHI_JWT_SECRET` | Claims: `{sub, tenant_id, roles[]}`; issued by `POST /v1/admin/tokens` and the bootstrap CLI |

Both lanes resolve through the middleware once per request into an `AuthContext`
(`client_id`, `tenant_id`, `roles`); handlers never re-parse credentials.

## 3. Tenancy classes

| Class | Tables | Scoping |
|---|---|---|
| **Global reference** | `forecast_cycles`, `signals`, `metrics` | No `tenant_id`; readable by any authenticated caller |
| **Tenant-owned** | `tenants`, `users`, `api_keys`, `backtest_jobs`, `audit_events` | `tenant_id` on every row; query-layer `WHERE tenant_id = :tid` injected by `get_tenant_scope` |
| **Admin-only** | `paper_ledger` | No `tenant_id`; `role=admin` read-only; always labeled *paper / not live capital* + `X-Pakhi-Edge-Status` |

Isolation is **by construction, not policy**: a missing scope filter fails a
test. Cross-tenant reads (tenant A → tenant B's key/job/audit row) return
404/403, never data.

## 4. RBAC roles

| Role | Capabilities |
|---|---|
| `viewer` | Read global reference data only |
| `operator` | `viewer` + own-tenant backtests + own-tenant key management |
| `admin` | `operator` + tenant management, human-user management, audit-log read, paper-ledger read |

Roles are JWT claims (human) or key-scoped grants (machine, default `operator`).
Every sensitive route declares a minimum role via a dependency; a role-matrix
test asserts each route's minimum.

## 5. Tier map (rate limiting)

| Tier | Scope |
|---|---|
| `free` | default; lowest `limit_per_min` |
| `pro` | mid tier |
| `labs` | highest |

`limit_per_min` per tier is stored in the contract's `tiers` section (single
source for middleware + WS-6 metering). Token bucket stays in-memory,
thread-safe, **single-worker only** — multi-worker bucket state is WS-5/Redis.

**No achieved-uptime claim; conditional offer only.** Single-worker is the
documented posture. 99.9% is a **conditional offer**, in force only while the
WS-5 reliability machinery is live (Redis multi-worker fail-closed state,
metrics + multiprocess mode, SLO accounting + `/v1/status`, a green DR drill)
**and** a 30-day measurement window is open and recorded (WS-5 T6,
`data/ws5/reliability_contract.json` `slo.measurement_window`). The evidence of
meeting the offer accrues during the window; Pakhi never fabricates an achieved
uptime number (G1 remains UNDER-POWERED until then).

## 6. Audit event taxonomy (append-only, tamper-evident)

Every row: `{tenant_id, actor_id, action, resource, resource_id, request_id,
outcome, ts, prev_hash, hash}`; `hash = sha256(prev_hash | canonical_payload)`.

- **Mutations (atomic, always):** `token.issue`, `key.create`, `key.revoke`,
  `tenant.create`, `backtest.submit` — audit row commits in the **same
  transaction** as the action; a mutation committing without its audit row is a
  transaction failure.
- **Reads/access (post-response, middleware):** all `GET` / stream events;
  covered by the **omission-reconciliation sweep** anchored on the **nginx
  access log** (independently written, §7), never the app's own middleware.
- Chain detects tampering (edit ⇒ every subsequent link breaks) **and**
  omission (sweep replays nginx log vs `audit_events` by `request_id`; a missing
  mutation row fails).

## 7. Reconciliation anchor

The omission sweep's input is the **reverse-proxy (nginx) access log** —
written outside the app's code path — with `request_id` propagated through the
proxy and logged per request. The app's middleware does **not** feed the sweep.
nginx config ships in WS-4 T4 (it does not exist in the repo today).

## 8. Secrets policy

- Boot-time fail-fast: missing or weak `PAKHI_JWT_SECRET` (or a value equal to a
  documented test default) **refuses startup** — never a silent runtime default.
- Tenant API keys hashed in Postgres; only the prefix is stored/returned;
  plaintext shown exactly once at creation.
- Nothing secret lives in the tree; CI secret-scan step + a tree-walk test
  asserting no `pk_live_`-prefixed or `PAKHI_JWT_SECRET=<value>` leaks.
