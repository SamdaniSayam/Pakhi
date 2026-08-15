# WS-4 Progress Tracker — Auth, Security, Tenancy, Compliance

Per working agreement: every execution step is logged here with terminal
evidence, and the user is shown the running terminal live.

- Blueprint: `docs/WS4_EXECUTION_BLUEPRINT.md` (**REVISED post-review v1.2** —
  §0 N_min/season/pooling/cross-checks, §3.5 tamper+omission with independent
  nginx access-log anchor, G3 anchoring note, T5 "drafted + sent" counsel split)
- Contract: `docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md` + `data/ws4/security_tenancy_contract.json` (LOCKED)
- Gate: **APPROVED** (T0 verdict below) — explicit user infra-first decision
- **T0–T5 DONE** (tracker below); SOC2 observation clock started 2026-08-14
- Started: 2026-08-14

---

## T0 — Gate verdict + contract freeze

**Gate verdict (2026-08-14):** The user approved the infra-first decision to
build WS-4 ahead of any paying tenant, explicitly stated as "proceed to start
WS4 entirely - one by one tasks". G1 remains **UNDER-POWERED** (N = 7 < N_min =
8); WS-4 is infrastructure, never an edge claim, and `X-Pakhi-Edge-Status`
remains on every signal/ledger response.

## Log

### 2026-08-14 — T5 DONE: Compliance program + docs + CI + SOC2 clock started
- **Operational policies in `docs/compliance/`** — every control has a document
  that maps to implemented, CI-checked code, not intentions:
  - `access-control-policy.md` — RBAC per route (`require_role`), human/machine
    lanes, tenant scoping at the query layer, key hashing, fail-closed DB lane,
    per-tier limits; evidenced by the WS-4 test suites.
  - `change-management-policy.md` — branch → PR → review → CI gate → tag →
    deploy; CI is a merge gate (full suite + secrets scan + `ws4-security`
    Postgres job); evidence preserved per commit/run; secrets rotation is a
    reviewed PR delivered out of band.
  - `incident-response-runbook.md` — S1–S4 classes, detection (WS-2
    orchestrate alerts, audit sweep, SECURITY.md channel), containment
    playbooks keyed to the real controls (revocation is audited, chain verify,
    fail-closed), timeline-as-deliverable.
  - `backup-policy.md` — RPO = one published cycle, RTO ≤ 4 h, tested quarterly
    restores, off-host + WAL, chain-verify-as-integrity; **operationalization is
    WS-5** (WS-4 documents the policy; WS-5 builds it), flagged as such.
- **Legal drafts (for counsel)** — `docs/compliance/legal/`:
  `terms-of-service-draft.md`, `privacy-policy-draft.md`,
  `data-licensing-draft.md`, plus `README.md` cover memo. All marked
  **review-draft, not legal advice**, each with the specific questions for
  counsel (liability limit, GDPR/CCPA territorial posture, NOAA/GFS provenance
  conditions on redistribution). **Sent-to-counsel flag:** drafted and flagged;
  the *sending* action + counsel turnaround are external steps recorded in this
  log when they happen — they are explicitly not WS-4 exit criteria and not on
  the WS-4 calendar.
- **`.github/workflows/ws4-security.yml`** — dedicated job: Postgres 16 service
  container, installs `.[all,api]` + `psycopg[binary]` (psycopg v3, chosen over
  the `postgres` extra's psycopg2-binary whose teardown segfault broke CI,
  noted in pyproject.toml), runs secrets scan + the WS-4 suites against the real
  store + an audit-sweep smoke run. The Postgres-backed tests
  (`tests/test_ws4_t5_ci.py`, 3) are skipped locally unless `WS4_TEST_DB_URL`
  is set and run unmodified in the job.
- **SOC2 observation clock started 2026-08-14** — recorded here as the earliest
  possible Type II observation start for the operational controls program.
  "Operational controls program" is the honest claim; Type I/II and GDPR/CCPA
  posture are only claimed when earned per Production Blueprint.
- **Exit evidence:** full suite **1837 passed / 8 skipped** (3 = Postgres tests
  gated on the CI job) in 98.6s; WS-3 subset 68/68 green; ruff clean; both
  workflow YAMLs parse; `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-14 — T4 DONE: Audit logs (chained, atomic, omissable-by-design)
- **Chained ledger** — every sensitive action (token issue/refresh,
  key create/revoke, backtest submit, tenant create) emits an `AuditEvent`
  (hash + prev_hash + request_id + actor/tenant/action/resource/resource_id/
  payload/outcome) in the *same transaction* as the mutation (commit with no
  audit row = transaction failure). Reads are appended post-response by
  `Ws4AuditMiddleware` (action=`read`); `/v1/admin*` and `/v1/health` are
  never read-audited.
- **Append + verify** — `apply_audit` appends under a process-wide
  `_APPEND_LOCK` (single-worker contract), seals via the pure chain from
  `pakhi/ws4/audit.py`, and trusts nothing stored (chain head recomputed from
  the last row). `verify_chain_in_store` returns the exact index of the first
  bad link — tampering any middle row breaks at that row.
- **Request correlation** — `RequestContextMiddleware` stamps
  `request.state.request_id` (echoed as `X-Request-ID`); admin surface exposes
  `GET /v1/admin/audit` (admin-only, paginated, filterable by tenant/actor/
  action, newest first).
- **Omission reconciliation (the anchor)** — `load_access_log` +
  `parse_nginx_access_line` consume the *nginx access log* shipped in
  `deploy/nginx/pakhi-nginx.conf` (`$request_id` log_format, access-log
  stanza). `omission_reconciliation` fails on any mutating request_id
  (POST `/v1/admin/tokens|keys|tenants`, `/v1/backtests`) with no audit row;
  `scripts/run_audit_sweep.py --access-log ... --db-url ...` is the CLI (exit 1
  on omission). The log is written by the proxy, outside the app code path, so
  a bug that suppresses an audit row cannot erase the evidence against it.
- **Tests `tests/test_ws4_t4_audit.py`** (11): every sensitive action emits a
  chained row + chain verifies; refresh reuse-revocation audited; forced audit
  failure rolls back the mutation (atomicity) and a 404 writes nothing; middle
  row tamper breaks the chain at that row; a deleted mutation row is caught by
  the sweep fed by a *fixture* access log (and clean when present); reads
  audited post-response with matching request_id; `/v1/health` not audited;
  audit reads admin-only (operator → 403); route paginated + filterable.
- **Exit evidence:** full suite **1837 passed / 5 skipped** (prior 1826 + 11
  T4) in 97.8s; WS-3 subset 68/68 green; ruff check + format clean; T1–T4
  suites 61/61 green; `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-14 — T3 DONE: Secrets management
- **Fail-fast secret gate** (`pakhi/api/settings.py`) — a weak JWT secret
  (short / obvious default) is a *construction error on every path*; a missing
  secret is a boot error when WS-4 is enabled (`PAKHI_WS4_ENABLED=1`, the
  production posture). WS-3 key-only dev posture boots unchanged; the admin
  surface 503s without a secret (never silently serves on a guessable key).
- **Env/file keys demoted to bootstrap** — `data/ws3/api_keys.json` stays as the
  bootstrap source; runtime tenant keys live in Postgres, prefix-hashed at rest
  (T2 property re-asserted by a T3 test). Documented in the contract §3.3.
- **Tree-walk + CI scan** — `pakhi/ws4/secret_scan.py` (dependency-free,
  ``git ls-files``-based so gitignored local secrets are excluded from the
  *repository* definition) + `scripts/secret_scan.py` wired into the CI test
  job as a `Secrets scan` step. Matches real credential shapes (private keys,
  AWS/GitHub/OpenAI/Stripe/Slack/Google/Twilio), never heuristic `test_` values;
  also flags any committed `.env`.
- **Tests `tests/test_ws4_t3_secrets.py`** (9): tracked tree clean, no
  committed `.env`, weak/obvious/missing secret = boot error (never a served
  500), strong secret boots with WS-4 on, WS-3 env-key path still green, DB key
  hashed at rest.
- **Exit evidence:** app refuses to boot on missing/weak secret (Settings
  raises before any app exists); `python scripts/secret_scan.py` clean; no
  plaintext key in the tracked tree or any fixture; WS-3 68/68 green.


### 2026-08-14 — T2 DONE: Multi-tenancy + RBAC
- **Schema** — `tenant_id` (nullable, back-compat; NULL reads as the default
  tenant) added to `backtest_jobs`; `migrate(engine)` in `pakhi/ws4/db.py`
  applies the additive `ALTER TABLE` for pre-WS-4 stores at boot (idempotent).
- **Tenant + key service** (`pakhi/ws4/service.py`) — `upsert_tenant`
  (tier -> contract `limit_per_min`: free 30 / pro 120 / labs 300),
  `create_api_key` (raw key returned exactly once, only sha256 stored),
  `revoke_api_key`, `list_api_keys` (prefixes only), `lookup_key` (hash ->
  tenant identity, fails closed), `TenantNotFoundError`. Token issuance is now
  gated on the tenant existing.
- **Admin surface** (`pakhi/api/routes/admin.py`) — `POST/GET /v1/admin/tenants`,
  `POST /v1/admin/keys`, `POST /v1/admin/keys/{key_id}/revoke`,
  `GET /v1/admin/keys?tenant_id=` (admin role required on all).
- **Machine lane** (`pakhi/api/ws4_auth.py`) — DB per-tenant keys now resolve to
  their stored tenant/roles/tier (default `operator`); env/file keys remain
  bootstrap admin on the default tenant. DB-down falls through to bootstrap so
  the WS-3 Auth middleware's independent hash check still decides.
- **Credential validation** (`pakhi/api/auth.py`) — `AuthAndRateLimitMiddleware`
  accepts a DB key when not in the bootstrap `allowed_keys` via the
  `db_key_validator` hook (fail-closed); per-tier token buckets resolved from
  `ws4_scope.tier`; bearer lane now keyed per-user (`user_<sub>`).
- **Scoping** (`pakhi/api/routes/backtest.py`, `read.py`) — backtest jobs are
  written with their tenant and reads are own-tenant (cross-tenant read = 404);
  ledger is admin-only in the secured posture, open in the unauthenticated dev
  posture (WS-3 byte-compatible).
- **Tests `tests/test_ws4_t2_tenancy.py`** (15): tenant/key CRUD, raw-key-once
  + hash-at-rest, revocation fails closed, cross-tenant job 404 both ways,
  jobs stamped with tenant, RBAC 403 matrix, ledger admin-only-when-secured,
  per-tier rate-limit headers (30 vs 120), WS-3 bootstrap-key = admin.
- **Exit evidence:** cross-tenant isolation proven (A reads B's job -> 404);
  operator denied admin surface + ledger (403); per-tier buckets proven;
  full suite 1817 passed / 5 skipped; ruff clean; WS-3 68/68 green.


### 2026-08-14 — T1 DONE: Human identity — JWT + refresh
- **Tables** `users`, `refresh_tokens` (+ `tenants`, `api_keys`, `audit_events`
  stubs) registered on the WS-2 store `Base` in `pakhi/ws4/db.py` — the
  existing `init_db(engine)` creates them (single store, single source of truth).
- **`pakhi/ws4/tokens.py`** — HS256 access JWT (15 min, claims
  `{sub, tenant_id, roles, tier}`, locked issuer), opaque refresh tokens (SHA-256
  at rest), strict decode (`exp`/`iat`/`sub`/`tenant_id`/`roles` required).
- **`pakhi/ws4/service.py`** — `issue_tokens` (upsert user, never escalates an
  existing user's roles) + `refresh_tokens` rotation: new pair in the same
  family, old revoked with `replaced_by`; **reuse of a revoked token revokes the
  whole family**.
- **Routes `pakhi/api/routes/admin.py`** — `POST /v1/admin/tokens` (admin key or
  admin JWT, role-gated 403 envelope) → 201 pair; `POST /v1/admin/tokens/refresh`
  (auth-exempt: the body refresh token *is* the credential) → rotation.
- **Middleware** — `pakhi/api/ws4_auth.py` `Ws4AuthMiddleware` (outermost)
  resolves `request.state.ws4_scope` from the human (JWT) or machine (bootstrap
  key = admin in T1) lane; `AuthAndRateLimitMiddleware` extended to accept the
  Bearer lane and exempt the refresh path — **the WS-3 `X-Pakhi-Key` flow is
  byte-identical**. `Settings.jwt_secret` added; T3 turns missing-secret into a
  boot failure.
- **Bootstrap CLI** `scripts/run_ws4_t1_tokens.py` — create admin user + first
  token pair (exit 0/1; refuses weak/missing `PAKHI_JWT_SECRET`).
- **Tests `tests/test_ws4_t1_tokens.py`** (13): issuance (claims decode, refresh
  hashed at rest), expired/malformed/wrong-secret JWT → 401, insufficient role →
  403, rotation + revocation, family reuse-revocation, refresh-needs-no-key,
  WS-3 key flow untouched (health 200 with key, 401 without).
- **Exit evidence:** valid/expired/invalid JWT behavior proven; rotation +
  reuse detection proven; WS-3 key flow still green; ruff clean.

### 2026-08-14 — T0 DONE: Gate + security/tenancy contract freeze + skeleton

- **Gate verdict recorded** (above): WS-4 is **executed**, not merely prepared.
- **`docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md`** — contract doc (identity lanes,
  tenancy classes, RBAC roles, tier map, audit taxonomy, secrets policy,
  backwards-compat rule).
- **`data/ws4/security_tenancy_contract.json`** — machine twin, self-hash-pinned
  (payload sha256 `92daf391…`, verified by `tests/test_ws4_t0_skeleton.py::test_contract_machine_twin_self_hashes`).
- **`pakhi/ws4/`** package skeleton: `audit.py` (hash-chained appender +
  omission-reconciliation core) and `tenant.py` (`TenantScope` + role matrix,
  machine default `operator`, `PermissionDeniedError`) — pure, import-clean, no
  side effects; FastAPI wiring isolated in `pakhi/ws4/deps.py` (not pulled in
  by `import pakhi.ws4`).
- **Tests `tests/test_ws4_t0_skeleton.py`** (13): import-clean subprocess check,
  self-hash verification, chain-tamper (middle-row edit → breaks at that row),
  chain-prev_hash tamper, omission reconciliation (missing mutation row flagged
  from the *log*, reads never flagged, clean when matched), role matrix
  (admin ⊃ operator ⊃ viewer, machine default, anonymous viewer), insufficient
  role raises.
- **No WS-3 regression:** full suite **1789 passed / 5 skipped / 0 failed**
  (1776 prior + 13 WS-4 skeleton) in 161.7s; WS-3 subset 68/68 green; ruff
  check + format clean on `pakhi/ws4/` + tests.
- **Exit evidence:** contract doc + machine JSON hash-pinned; `pakhi.ws4`
  imports cleanly (verified in a bare `python -c "import pakhi.ws4"`); WS-3
  suite green.
