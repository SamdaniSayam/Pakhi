# WS-4 — Auth, Security, Tenancy, Compliance: Execution Blueprint

Status: **DRAFT 2026-08-14 — prepared under the honest-premise discipline below;
awaiting user approval + T0 gate decision before any build**
Progress: tracked in `docs/WS4_PROGRESS.md` (created only after this blueprint is approved)
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-4 + Phase 3/4 checkboxes;
`docs/WS3_EXECUTION_BLUEPRINT.md` §8 handoff
Gate: **an explicit, user-made infra-first decision** (mirrors WS-3 T0) — G1 is still
UNDER-POWERED, so WS-4 is infrastructure, never an edge claim. Long-term gate is **G3**
(Production Blueprint §5: end of Phase 3 — 99.9% uptime/30 d, first paid contracts,
SOC2 controls operational). **Anchoring note on G3:** the timeline here is measured
*from T0 approval*, not fixed calendar weeks, and Phase 3's 99.9%-uptime exit depends
on WS-5 (Redis-backed multi-worker state + failover) which is **not yet blueprinted** —
so G3's *uptime* clause is currently **unanchored in time** and is explicitly not
promised before WS-5 (§3.4). WS-4's measurable contribution to G3 is the SOC2 controls
clock, tenancy, and the audit program; the uptime clause is handed to WS-5 intact,
not redefined here.

---

## 0. Honest premise (what WS-4 is actually for)

WS-1 G1 is **UNDER-POWERED** (N = 7 < N_min = 8). The 60-day live OJ paper harness
(started 2026-08-12) is accumulating scored events; **0 scored events so far**. WS-3
was approved and executed under an explicit infra-first mandate — a single-tenant,
fast-read API that discloses `X-Pakhi-Edge-Status` on every signal/ledger response.
WS-3 shipped keys + rate limits (T5), but nothing more.

**Where N_min = 8 comes from (no power calculation, said plainly):** `N_min = 8` is
locked in `pakhi/ws1/significance.py` (§3, `docs/WS1_EVALUATION_CONTRACT.md`) as a
**data-availability cap, not a power-derived sample size**. The full-power target
`N ≥ 30` is structurally unreachable for a freeze-triggered signal on the OJ archive
(hard ceiling **13** OOS episodes; measured, `docs/WS1_EVALUATION_CONTRACT.md` §2).
N_min was therefore set to the highest bar the archive can support — **≥ 62 % of the
13 episodes** — and the G1 verdict is judged by **bootstrap CI width, never a point
Sharpe alone** (a Sharpe CI at N ≈ 8 is genuinely wide; the CI-lower-bound gate is
what stops "PASS at N=8" from reading as a confident edge). There is **no effect-size
or variance power calculation behind 8** — a deliberate, documented shrink of the
claim.

Two honest qualifications on that framing, filed here so they are never silently
overstated:
- **`N ≥ 30` is not a clean reference point for this data.** The rule of thumb was
  built for roughly symmetric, well-behaved return distributions; freeze-driven
  futures moves are the opposite shape — mostly flat, with occasional large spikes.
  At N=30 it would *not* obviously be "enough" for that distribution either, so
  "unreachable vs 30" is descriptive, not the statistical argument. The real,
  permanent constraint is the **population cap of 13 episodes itself** — a capped
  population argues for a different tool (below), not for a shrunken frequentist
  threshold masquerading as a power level.
- **The bootstrap CI at N = 7–8 can read *narrower* than it should.** Resampling
  pools the same 7–8 points, so the resample distribution is drawn from exactly the
  sample it estimates; `ci_lower > 0` passing at N=7 is not the guarantee it would be
  at N=70. The gate stops premature confidence; it does not manufacture it.

**Statistical cross-checks filed for the G1 re-run (recorded here, not WS-4
scope):** three concrete upgrades are logged for the WS-1/WS-2 re-run path — (a) run a
**Bayesian posterior with a skeptical prior** (centered near zero edge — competitive
space) alongside the bootstrap CI, treating *disagreement* between the two as the
informative result, not either number alone; (b) re-examine whether **13 is a hard
ceiling or a Florida-citrus-only ceiling** — a hierarchical model pooling
quasi-independent freeze episodes from other citrus-growing regions could inform the
same signal without pretending they are one identical population; (c) **subsample
agreement before pooling:** before historical + live events are combined into one N,
check the two subsamples roughly agree (e.g. a two-sample comparison of their event
returns) — otherwise pooling could paper over a regime shift or a flaw in the original
backtest rather than confirm a stable edge. Neither is WS-4 work; WS-4 only records
that the current framing is an availability cap and that these checks are owed before
any PASS-level claim can lean on it. Throughout, WS-4 never treats a small N as
evidence of edge **or** as evidence of no edge — it inherits the protocol's honest
UNDER-POWERED path and stays out of the statistics.

**Season awareness, stated plainly:** the live harness is **calendar-fixed, not
season-aware** — a 60-day clock from 2026-08-12 (locked in the WS-2 T0 protocol),
whereas Florida citrus **freeze risk is a December–February phenomenon**. That means
mid-August → mid-October is close to the worst window for producing qualifying events.
A low N in October is therefore the **expected seasonal outcome, not model-skill
evidence**. WS-4 does not reinterpret N either way; the protocol's honest
UNDER-POWERED path (`docs/WS2_PAPER_TRADING_PROTOCOL.md`) already covers a zero/rare
event window, and no WS-4 decision depends on the harness's calendar position. (A
season-aware re-window is a WS-2 protocol change — hash-pinned T0 — and is out of
WS-4 scope, but the misalignment is recorded here so it is never silently read as
skill.) **Pooling — one shared counter, no separate live track:** live scored events
**pool with the historical 7** toward the same `N_min = 8` at the G1 re-run, under
the same estimator on the combined historical + live ledger
(`docs/WS2_PAPER_TRADING_PROTOCOL.md` §2, lines 38–40: "re-estimation … at the N ≥ 8
G1 re-run, under the same estimator, on the combined historical + live ledger"). The
live harness does **not** have its own target — there is exactly one counter, and it
is the pooled N. This is one pooled claim, not an independent check.

WS-4's mandate, read honestly, is therefore:

> **Hardening before tenants.** Build the security, tenancy, and compliance
> infrastructure that Phase 3 needs — *before* the first trial/enterprise customer
> exists, so that onboarding a tenant never requires a security retrofit. WS-4 does
> not claim, and cannot clear, G1.

**Why now and not later:** SOC2 Type II has a hard floor — controls must *operate
under observation* for ≥ 3 months (6 recommended) before certification; first-time
Type II commonly runs 9–15 months end-to-end. The Production Blueprint therefore
mandates the controls program **start at the beginning of Phase 3 (week 16)**, not
the middle. Every week WS-4 is idle is a week added to the certification calendar.
The same honesty rule from WS-3 applies to the *product* side: multi-tenancy exists
to serve real tenants, so the build is **gated on T0 below** — never on an assumed
sales pipeline.

**Deferred explicitly:** WS-5 owns observability (Prometheus/Grafana, SLOs, status
page), multi-worker rate-limit state (Redis), DR/backups. WS-6 owns metering and
billing (Stripe), which builds on WS-4's per-key/tenant accounting and WS-3's
rate-limit headers. WS-4 does **not** pre-commit to a billing model, a tenancy
tiering price, or any compliance claim beyond the controls program being operational.

---

## 1. Purpose

Transition the single-tenant WS-3 API into a **tenant-safe, auditable, secret-safe
service** that Phase 3 can onboard its first customers onto:

- **Identity & authorization** — machine API keys (WS-3, retained) **plus** human
  JWTs with role-based access control (viewer / operator / admin).
- **Multi-tenancy** — tenant-scoped ownership of tenant-owned data
  (keys, backtest jobs, audit events) with **proven isolation** (tests, not vibes);
  market reference data stays shared, the live paper ledger stays admin-only.
- **Rate limiting per key/tier** — extend the WS-3 token bucket to a per-tenant tier
  so limits can differ by plan without a code change.
- **Secrets management** — no secrets in the repo; injected via the platform; the
  API fails fast at boot on a missing/weak secret (never silently defaults).
- **Audit logs** — append-only, hash-chained, tamper-evident record of
  who-accesses-what-when (a SOC2 control, and the raw material for WS-6 metering).
- **Compliance program kick-off** — policies (access control, change management,
  incident response, backups) drafted and **operational**, plus the TOS / privacy /
  data-licensing posture documented for counsel review before any commercial
  contract (SOC2 Type I at Phase 4 exit, Type II in months 12–18).

Success = a multi-tenant-capable API where a cross-tenant read is impossible by
construction (not by policy), every sensitive action is on an append-only audit
chain, no secret ships in the tree, and the SOC2 controls program is running and
being observed.

## 2. Readiness audit (verified 2026-08-14)

| Layer | Status | Evidence |
|---|---|---|
| WS-3 single-tenant API | ✅ Built | REST + WS, keys, rate limits, NOTIFY push, backtests — `docs/WS3_PROGRESS.md` 2026-08-14 QC entry (suite 1776 passed / 5 skipped, ruff clean; CI green at `f2019ab`) |
| Machine API keys (SHA-256 hashed) | ✅ Built | `pakhi/api/auth.py` `hash_key`; keys from `PAKHI_API_KEYS` env / `data/ws3/api_keys.json` (gitignored); 401/429 covered by `tests/test_ws3_auth_limiter.py` |
| Rate limiting (in-memory token bucket) | ✅ Built | `TokenBucketLimiter` (thread-safe); single-worker documented; `X-RateLimit-*` headers asserted in `tests/test_ws3_auth_limiter.py` |
| `client_id` on backtest jobs | ✅ Built | `backtest_jobs.client_id` (key-hash or IP); per-key cap asserted in `tests/test_ws3_jobs.py::test_per_key_queue_cap` — the seed of tenancy |
| Human identity (JWT) | ⚠️ Missing | Greenfield |
| RBAC / roles | ⚠️ Missing | Greenfield |
| Tenancy model (tenants, tenant_id scoping) | ⚠️ Missing | All store tables are global today |
| Per-tier rate limits | ⚠️ Missing | Single fixed limit today |
| Secrets management | ⚠️ Missing | `api_keys.json` on disk; JWT signing key will need a real home |
| Audit log (append-only, chained) | ⚠️ Missing | Greenfield |
| Compliance docs (TOS/privacy/licensing) | ⚠️ Missing | `SECURITY.md` exists (vuln reporting); no TOS/privacy |
| SOC2 controls program | ⚠️ Missing | Nothing operational yet; **clock has not started** |
| Secrets scan in CI | ⚠️ Missing | `.github/workflows/ci.yml` has no secret-scan step |

**Evidence bar (deliberately higher for security code):** for WS-4, "tests pass" is
not the claim. Every security property must be proven by a **behavioral test that
would fail if the property broke**, and each task's exit evidence cites the test
file + scenario by name (cross-tenant isolation, chain-tamper, chain-omission,
fail-fast secret boot), not a bare suite count. Bare "N passed" numbers are cited in
readiness only with their report/commit reference, per the repo's cross-reference
discipline.

## 3. Architecture & Data Model

WS-4 extends the WS-3 API in place — same FastAPI app, same two-engine policy
(`read_engine` / `write_engine`), same locked error envelope, same sync-`def` /
async-only-for-WebSockets policy. No new services, no brokers; Postgres remains the
single source of truth.

```
┌──────────────┐   JWT (human, HS256) ─────────┐   ┌──────────────────────────┐
│  Human admin │   X-Pakhi-Key (machine) ──────┤──▶│ WS-3 FastAPI (in place)  │
└──────────────┘                               │   │  AuthAndRateLimit → new  │
┌──────────────┐   per-tenant tier quota       │   │  AuthzDep (roles)         │
│  WS-2 worker │──▶ Postgres: tenants, users,  │   │  tenant scope wrapper     │
│  (writes ref │   api_keys, backtest_jobs,    │   │  audit appender (tx)      │
│   data only) │   audit_events (+ global ref) │   └───────────┬──────────────┘
└──────────────┘                                └─────────────▶ pakhi.client
```

### 3.1 Identity model — machine + human, separate lanes

- **Machine lane (unchanged from WS-3):** `X-Pakhi-Key`, SHA-256 hashed, token-bucket
  rate limit. WS-4 adds **per-tenant keys stored in Postgres** (prefix `pk_live_` /
  `pk_test_` for rotation + environment separation, hashed at rest) with the env/file
  source retained only as a **bootstrap/admin key**.
- **Human lane (new):** short-lived **access JWTs** (HS256, 15 min) carrying
  `{sub, tenant_id, roles[]}` + **rotating refresh tokens** (opaque, hashed at rest,
  revoked on rotation). Issued by `POST /v1/admin/tokens` (admin key or admin JWT)
  and by the CLI bootstrap script. The signing key comes from the platform secret
  store (`PAKHI_JWT_SECRET`) — **never** a committed default.
- Both lanes funnel through the existing middleware stack: the middleware resolves
  `client_id` + `tenant_id` + `roles` once per request; handlers never re-parse tokens.

### 3.2 Tenancy model — what is shared vs tenant-owned vs admin-only

The store's tables split into **three tenancy classes** (locked in T0, enforced by
tests, not by discipline):

| Class | Tables | Scoping rule |
|---|---|---|
| **Global reference data** | `forecast_cycles`, `signals`, `metrics` | No `tenant_id`. Same market data for every tenant; provenance surfaced verbatim (WS-3 rule). Readable by any authenticated caller. |
| **Tenant-owned** | `tenants`, `users`, `api_keys`, `backtest_jobs`, `audit_events` | `tenant_id` on every row; every query is scoped `WHERE tenant_id = :tid` injected by the tenant-scope dependency. |
| **Admin-only** | `paper_ledger` | The company's live track record. No tenant_id; only `role=admin` can read; always labeled *paper / not live capital* + `X-Pakhi-Edge-Status`. |

Tenant isolation is enforced **at the query layer** (a `get_tenant_scope` dependency
that every tenant-owned route requires and injects into its query), and proven by
**cross-tenant tests**: tenant A reading tenant B's key/job/audit row must get
404/403 — never tenant B's data.

### 3.3 RBAC roles (frozen in T0)

| Role | Capabilities |
|---|---|
| `viewer` | Read global reference data only (signals/forecasts/cycles). |
| `operator` | `viewer` + submit/manage own-tenant backtests + manage own-tenant keys. |
| `admin` | `operator` + tenant management, human-user management, audit-log read, paper-ledger read. |

Roles are JWT claims (human) or key-scoped grants (machine, default `operator`).
A FastAPI dependency enforces them per-route; a test asserts every sensitive route
declares the minimum role.

### 3.4 Rate limiting per tier

WS-3's token bucket is **per-`client_id` already**; WS-4 adds a **tier** to the
tenant row (`tier: free | pro | labs`), mapping to `{limit_per_min}`. The middleware
reads the limit from the tenant tier instead of one global constant. Single-worker
remains the documented contract (multi-worker bucket state = WS-5/Redis).

**No uptime commitment to a paying customer before WS-5 — stated explicitly.** A
single uvicorn process is a single point of failure (no rolling deploys without
dropping rate-limit/WS state, no failover). The master blueprint's 99.9 % uptime
language therefore **does not become an offer to any tenant until WS-5 ships
multi-worker state (Redis) + failover/DR**; trial customers in Phase 3 get the
service with the honest single-worker posture and a documented best-effort
availability, not an SLA. WS-4's contract (§3.4 entry) locks this no-SLA-before-WS-5
statement so it survives into sales copy.

### 3.5 Audit log — append-only, tamper-evident

New `audit_events` table: `id`, `tenant_id`, `actor_id` (key hash prefix or user id),
`action`, `resource`, `resource_id`, `request_id`, `outcome`, `ts`, `prev_hash`,
`hash`. Each row is chained: `hash = sha256(prev_hash | canonical_payload)`, so any
retroactive edit breaks every subsequent link. Reads are admin-only
(`GET /v1/admin/audit`). Not a metering store — WS-6 consumes it, WS-4 only
guarantees append-only integrity.

**The chain catches tampering *and* omission — no "where possible":** audit rows are
split into two guarantees, neither optional:

- **Mutations (token issue, key create/revoke, backtest submit, tenant create):
  atomic, always.** The audit row is written in the **same transaction** as the
  mutation, with no exception — a mutation that commits without its audit row is a
  transaction failure, and a rolled-back action never leaves a phantom audit row.
- **Reads/access (who hit what signal when):** cannot be transactional, so they are
  appended post-response via the middleware and protected by an **omission
  reconciliation**. The reconciliation is anchored on a **request log written outside
  the app's code path — the reverse-proxy (nginx) access log**, never the app's own
  middleware: if the audit row and the source of truth for the sweep were produced by
  the same code path, a single bug (a request that never reaches the audited handler
  at all) could suppress both at once and reconciliation would compare nothing against
  nothing. The app middleware stamps `request_id`; nginx is configured to log it per
  request, so the sweep replays *nginx's* log against `audit_events` by `request_id`
  and fails on any mutating `request_id` with no audit row. **nginx is therefore a WS-4
  T4 dependency, not an assumption** — the repo has no proxy config today, and T4
  ships it (request_id propagation + access-log stanza + a documented parse format).
  The T4 test suite proves **both** directions: a tamper test (edit a middle row ⇒
  chain breaks) **and** an omission test (a mutation's audit row deleted ⇒ the sweep,
  fed by a *fixture* access log standing in for nginx, fails). A missing row is now
  as detectable as an edited one, and the sweep's input never shares the bug surface
  it is checking.

**Deliberate boundary — worker writes are outside this chain:** the WS-2 worker
writes reference data (`forecast_cycles`, `signals`, `metrics`, `paper_ledger`)
directly to Postgres as a system process, bypassing the API. That is intentional:
those writes are governed by WS-2's own append-only `orchestrate.jsonl` + G1/G2
controls, and the API audit chain covers **API-mediated** actions only. This is a
stated boundary, not something a reader must infer from the architecture diagram.

### 3.6 Secrets management

- Boot-time secret validation: the app refuses to start on a missing
  `PAKHI_JWT_SECRET` (or a value equal to the documented test default) — **fail fast,
  never a silent default**. Same gate for the admin bootstrap key.
- Tenant API keys live hashed in Postgres; only the **prefix** is ever stored or
  returned. Plaintext is shown exactly once at creation.
- Repo rule: no secret values, no `.env` commits, no test fixtures with real-looking
  keys where the "secret" is asserted present (tests use obvious `test_` values).
- CI: a secret-scan step (and a test that walks the tree asserting no
  `pk_live_`-prefixed or `PAKHI_JWT_SECRET=<value>` leaks).

### 3.7 Compliance artifacts (written with counsel, never self-certified)

WS-4 **starts the controls program** — it does not claim compliance:
- **Policies drafted + operational (SOC2 control evidence):** access control
  (who can touch what, via the RBAC + audit records), change management (branch →
  PR → CI → release, already the repo norm, now documented as a control), incident
  response (from `SECURITY.md` + WS-2 alerting, formalized as a runbook), backups
  (defined in WS-5 DR — WS-4 documents the *policy*, WS-5 operationalizes it).
- **TOS / privacy / data-licensing:** drafted in-tree as review drafts **for counsel**;
  explicitly marked "not legal advice, not signed"; no claim of GDPR/CCPA/SOC2
  compliance anywhere in product copy until genuinely true.

## 4. Tasks, sequencing, exit criteria

### T0 — Gate decision + security/tenancy contract freeze
Before any endpoint ships:
- Record the gate verdict in `docs/WS4_PROGRESS.md`: **explicit user infra-first
  decision** (mirroring WS-3 T0). If the user declines, WS-4 stays **prepared, not
  executed** — the honest state while G1 is UNDER-POWERED.
- Freeze the **WS-4 security & tenancy contract**: `docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md`
  + machine twin `data/ws4/security_tenancy_contract.json` (self-hash-pinned, same
  pattern as WS-2/WS-3). Lock: identity lanes (§3.1), tenancy classes (§3.2), roles
  (§3.3), tier map (§3.4), audit event taxonomy (§3.5), secrets policy (§3.6), and
  the **backwards-compat rule**: the WS-3 `X-Pakhi-Key`-only flow must keep working
  for existing keys (no breaking change to the WS-3 contract).
- Add `pakhi/ws4/` package skeleton (audit appender + tenant-scope dependency,
  import-clean, no side effects).
- **Exit:** contract doc + machine JSON approved and hash-pinned; gate verdict
  recorded; `pakhi/ws4` imports cleanly; WS-3 suite still green (no regression).

### T1 — Human identity: JWT + refresh (week 1)
- New tables `users`, `refresh_tokens` (hashed, rotated); migration run as the app role.
- `POST /v1/admin/tokens` (admin key or admin JWT) → short-lived HS256 access JWT
  (15 min, claims `{sub, tenant_id, roles}`) + rotating refresh token.
- Bootstrap CLI `scripts/run_ws4_t1_tokens.py` (create admin user + first token, exit 0/1).
- Middleware upgrade: resolve `tenant_id` + `roles` from either lane; handlers keep
  a single `AuthContext` object. **WS-3 `X-Pakhi-Key` flow unchanged.**
- **Exit:** valid JWT passes, expired/invalid/malformed JWT → 401 locked envelope;
  refresh rotation revokes the old token; refresh reuse detection (a reused revoked
  token revokes the whole family); test asserts WS-3 key flow still works untouched.

### T2 — Multi-tenancy + RBAC enforcement (week 1–2)
- New tables `tenants`, `api_keys` (per-tenant, hashed, `pk_live_`/`pk_test_` prefixes);
  `tenant_id` column added to `backtest_jobs` (migrating the existing `client_id`
  semantics under a default tenant = "pakhi-internal").
- `get_tenant_scope` dependency + role dependency; every tenant-owned route refactored
  to query through them. `paper_ledger` restricted to `role=admin`.
- Tenant admin routes: `POST /v1/admin/tenants`, key create/revoke, key list (prefixes
  only).
- **Exit:** cross-tenant isolation tests — tenant A reading tenant B's job/key/audit
  row → 404/403; admin-only ledger denied to `operator`; a role matrix test asserts
  each route's minimum role; per-tier rate limit applies different buckets.

### T3 — Secrets management (week 2)
- Boot-time secret gate (missing/weak `PAKHI_JWT_SECRET` refuses startup); the env/file
  API-key source demoted to bootstrap-only, tenant keys live in Postgres.
- `data/ws3/api_keys.json` handling: kept for bootstrap; documented that runtime keys
  are DB-hashed.
- **Exit:** app refuses to boot with a missing/weak JWT secret (test asserts the 500
  never happens — it's a boot error, not a served response); no plaintext key exists
  in the tree or any fixture; a tree-walk test + CI secret-scan step pass; WS-3 tests
  still green with the old env-key path.

### T4 — Audit logs (week 2–3)
- `audit_events` table + append-only appender implementing the §3.5 split
  **without exception**: mutations are audited atomically in the same transaction
  (a commit without its audit row is a transaction failure); reads are appended
  post-response via the middleware and covered by the omission-reconciliation sweep.
- Middleware stamps `request_id` + resolved `client_id`/`tenant_id`.
- **Reverse proxy (nginx) ships here as the reconciliation anchor:** request_id
  propagation through the proxy, an access-log stanza logging it per request, and a
  documented parse format — the sweep's input is *independently written* (§3.5), so a
  bug that suppresses an audit row cannot also erase the evidence against it.
- `GET /v1/admin/audit` (admin-only, paginated, filterable).
- **Exit:** every sensitive action (token issue, key create/revoke, backtest submit,
  tenant create) produces a chained audit row; a tamper test edits a middle row and
  the chain verification fails; an **omission test** deletes a mutation's audit row
  and the reconciliation fails — fed by a fixture access log standing in for nginx (a
  missing row breaks nothing in the chain — the reconciliation is what catches it); a
  rolled-back action produces no audit row; audit reads are admin-only (403 for
  `operator`).

### T5 — Compliance program + docs + CI (week 3)
- **Policies operational:** access-control (maps to RBAC + audit), change-management
  (branch → PR → CI → release, documented as a control), incident-response runbook
  (from `SECURITY.md` + WS-2 alerts), backup policy (referencing the WS-5 DR work —
  WS-4 documents the *policy*, WS-5 operationalizes it). Stored in `docs/compliance/`.
- **Legal drafts (for counsel) — "drafted and sent" is the WS-4 deliverable; "counsel
  signed off" is not.** TOS, privacy, data-licensing are drafted in-tree, marked
  review-draft / not legal advice, and **sent to counsel** — that sending is a real,
  verifiable WS-4 exit item. Counsel's turnaround is an **external dependency and
  explicitly not on the WS-4 calendar**: a signed TOS is a Phase-3/4 sales-blocking
  gate, never a WS-4 exit criterion. WS-4 does not schedule, and cannot promise,
  legal sign-off.
- `.github/workflows/ws4-security.yml` (or extend `ci.yml`): secret scan + tenancy/
  audit/identity tests against a Postgres 16 service container.
- **Exit:** every control has a document + at least one CI check producing evidence;
  legal drafts **sent to counsel** and flagged as such; CI green; full suite green;
  the SOC2 **observation clock is recorded as started** in `WS4_PROGRESS.md` (this
  date is the earliest possible Type II observation start).

## 5. Rules & Discipline (applies to all tasks)

1. **No breaking change to WS-3.** The locked `X-Pakhi-Key` flow, error envelope,
   route table, and rate-limit headers keep working; WS-4 layers *on top* (contract
   T0 locks this).
2. **Isolation by construction, not policy.** Tenant scoping is injected at the query
   layer and proven by cross-tenant tests — a missing scope filter fails a test, never
   a review note.
3. **Audit everything sensitive, honestly.** Mutation audit rows are atomic with the
   action's transaction (no "where possible" — a mutation without its audit row fails);
   read/access rows are covered by the omission-reconciliation sweep, so a silent gap
   is caught, not just an edit.
4. **Secrets fail fast.** Missing/weak secrets are a boot error; no fallback default
   at runtime; nothing secret lives in the tree.
5. **No compliance claim without the clock.** "Operational controls program" is the
   honest Phase-3 claim; SOC2 Type I/Type II, GDPR/CCPA posture are only claimed when
   genuinely earned (Production Blueprint §5-Phase4/5).
6. **Role separation for humans and machines.** RBAC roles are enforced per route by
   a dependency; the middleware resolves identity once; handlers never re-parse tokens.
7. **Precompute + single source of truth unchanged.** WS-4 adds no new services; all
   state stays in Postgres; `read_engine`/`write_engine` roles still enforced.
8. **Cross-reference pass before any "final".** Every document that ships with a
   "final / locked / done" label gets a final pass that greps **every number and
   definition that appears more than once** (inside the doc and across the doc set:
   N_min, N, dates, price bands, thresholds, ranges) and reconciles them — the pattern
   that produced the Tier-2/Tier-3 pricing split in `docs/BLUEPRINT.md` §1.3 vs
   Appendix A.2, now fixed, is exactly what this step exists to catch. A bare
   "N passed" suite count is never a standalone evidence claim; it must reference
   its report/commit.

## 6. Timeline

Build weeks are measured **from T0 approval** (the honest-premise gate, not the
calendar). **Counsel turnaround is not on this calendar** — T5's deliverable is
"drafted + sent", never "signed":

| Week | Focus | Deliverable |
|---|---|---|
| T0 | Gate + contract | Verdict recorded; `security_tenancy_contract.json` hash-pinned; `pakhi/ws4` skeleton; no WS-3 regression |
| 1 | T1 + T2 start | JWT + refresh + RBAC dependencies; tenants/api_keys tables + bootstrap; WS-3 key flow untouched |
| 2 | T2 + T3 + T4 start | Tenant scoping + isolation tests; secrets gate; audit appender + chain |
| 3 | T4 + T5 | Audit admin surface + tamper **and omission** tests; compliance policies + legal drafts **sent to counsel**; CI secret scan; SOC2 clock recorded |

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Hardening before any tenant exists is wasted spend** | T0 gate = explicit infra-first decision (mirrors WS-3); WS-4 is the documented prerequisite for every Phase-3 outcome; if the user declines, it stays *prepared, not executed* |
| **Multi-tenant build on UNDER-POWERED edge** | Honest-premise framing (§0); `X-Pakhi-Edge-Status` already on every signal/ledger response; no tenancy implies an edge claim |
| **Harness window misaligned with the freeze season (Aug–Oct vs Dec–Feb)** | Named in §0 as a calendar-fixed, season-unaware window; low N in the window is the expected seasonal outcome, never read as skill evidence; WS-4 decisions do not depend on N (season re-window = WS-2 protocol change, out of scope) |
| **N_min = 8 read as a power-derived threshold** | §0 states plainly it is an archive-cap (13-episode ceiling; 30 structurally unreachable) with CI-width gating, not an effect-size calculation |
| **Breaking the locked WS-3 contract** | T0 contract freezes the backwards-compat rule; a CI test re-runs the full WS-3 suite against WS-4 changes |
| **Tenant isolation leaks (cross-tenant read)** | Query-layer scope injection + cross-tenant test suite; a missing scope filter fails CI |
| **Secrets in the tree / weak defaults** | Boot-time fail-fast gate; prefix-hashed DB keys; tree-walk test + CI secret scan |
| **Audit chain catches edits but not a missing row** | Mutations are atomic with their audit row (no exception); reads get an omission-reconciliation sweep **anchored on the independent nginx access log** (T4 ships it) — a bug that suppresses an audit row cannot also erase the log that exposes it; T4 tests cover tamper *and* omission (§3.5) |
| **Single worker reads as a reliability commitment** | §3.4 locks a no-SLA-before-WS-5 statement; trial tenants get the honest single-worker posture, not an uptime promise |
| **SOC2 calendar slips again** | Observation clock starts at T5 (recorded in progress doc); policies operational, not just drafted; Type II target honestly lands in months 12–18 |
| **Counsel turnaround assumed on the schedule** | T5 exit = "drafted + sent"; legal sign-off is an explicit external dependency, never a WS-4 exit criterion |
| **JWT/refresh abuse** | 15-min access tokens; rotating + reuse-revoking refresh tokens (T1 test) |
| **Rate-limit tiers drift from billing** | Tier map frozen in the T0 contract; WS-6 metering consumes WS-4's per-tenant accounting |

## 8. Handoff to WS-5 / WS-6

WS-4 leaves a multi-tenant, audited, secret-safe API with an operational controls
program. **WS-5** operationalizes observability and resilience (Prometheus/Grafana,
SLOs, status page, multi-worker rate limiting via Redis — which is also the
precondition for any customer-facing uptime claim, DR/backups — the backup *policy*
from WS-4 T5 becomes the DR *implementation*). **WS-6** builds metering and billing
on WS-4's per-key/per-tenant accounting and WS-3's rate-limit headers. The Phase-4
exit (**SOC2 Type I**, Type II observation running) depends directly on WS-4 T5's
controls clock — this is why the T5 date is recorded, not estimated.

**Moat caveat on ensemble disagreement (for the GTM work, not WS-4):** the ensemble
disagreement index is a genuinely useful data product, but "hard to copy" is the
wrong claim — GFS-vs-ECMWF divergence is computable by anyone with both free feeds.
The defensible moat is a **validated mapping from disagreement level to tradeable
outcome**, which requires the same real-data, real-N proof as the freeze signal.
WS-4 makes no moat claim via that index and does not treat the metric's cleverness
as evidence; the evidence bar travels with it.

## 9. Progress tracking

Per working agreement: after approval, all execution progress is tracked in
**`docs/WS4_PROGRESS.md`**, updated at each step with terminal evidence. The first
entry records the **T0 gate verdict** — the explicit user infra-first decision (or
**GATED** with the reason). No entry is written until the gate is recorded.
