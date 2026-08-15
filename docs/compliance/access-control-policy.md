# Access Control Policy

**Status:** operational — every control below maps to code that exists and is
machine-checked in CI.

**Owner:** WS-4 (security/tenancy track). **Scope:** humans (users/administrators)
and machines (API keys, service identities) that reach the Pakhi API and data plane.

## 1. Policy

1. **Least privilege.** Every identity receives exactly the roles it needs. No
   identity holds roles it does not use; no tenant can read or mutate another
   tenant's records.
2. **Two lanes.** Humans authenticate with short-lived bearer tokens issued by
   the identity service. Machines authenticate with per-tenant API keys. The
   lanes never overlap: a token cannot be an API key and an API key cannot be a
   token.
3. **Roles are enforced per route, by a dependency.** RBAC is not advisory:
   `require_role(...)` runs on every protected handler, so a missing check fails
   a test, not a review note.
4. **Identity is resolved once.** Middleware resolves the caller to a scoped
   identity (`ws4_scope`) before handlers run; handlers never re-parse tokens
   or re-derive roles.
5. **Administration is scoped.** Only `admin` roles reach the `/v1/admin/*`
   surface. Operator keys may read public data only. In the authenticated
   (secured) posture the ledger is admin-only.
6. **Access is audited.** Every sensitive action writes a chained, atomic audit
   row (see `audit-log-policy` notes in `../WS4_SECURITY_AND_TENANCY_CONTRACT.md`
   §3.5); reads are covered by the omission-reconciliation sweep.

## 2. Mapping of policy to implementation

| Control | Where it lives | Evidence |
|---|---|---|
| Roles per route | `pakhi/api/ws4_auth.py` (`require_role`), `pakhi/api/routes/admin.py` | `tests/test_ws4_t2_tenancy.py` — operator denied admin routes (403) |
| Token issuance / refresh + rotation + reuse revocation | `pakhi/ws4/service.py` (`issue_tokens`, `refresh_tokens`) | `tests/test_ws4_t1_tokens.py` |
| Per-tenant API keys, sha256 at rest | `pakhi/ws4/service.py` (`create_api_key`), `pakhi/api/auth.py` (`db_key_validator`) | `tests/test_ws4_t2_tenancy.py`, `tests/test_ws4_t3_secrets.py` |
| Tenant scoping at the query layer | backtest/job queries filter by resolved `tenant_id`; cross-tenant read = 404 | `tests/test_ws4_t2_tenancy.py` (isolation tests) |
| Audit of all sensitive actions | `pakhi/ws4/audit_events.py`, `pakhi/api/ws4_audit.py` | `tests/test_ws4_t4_audit.py` |
| Secrets never in the tree | `pakhi/ws4/secret_scan.py` + `scripts/secret_scan.py` | CI `Secrets scan` step; `ws4-security.yml` job |

## 3. Human administration

- The only human with `admin` at bootstrap is the operator who configures the
  runtime JWT secret. `POST /v1/admin/tenants`, `/keys`, and `/tokens` create
  tenants, machine keys, and human tokens — every one of these writes a chained
  audit row (action `tenant.create`, `api_key.create`, `api_key.revoke`,
  `token.issue`, `token.refresh`).
- `GET /v1/admin/audit` is the single read surface for the access log: admin-only,
  paginated, filterable. A human who can read audit history is themselves an
  admin — there is no separate audit-role.

## 4. Machine identities

- API keys are issued per tenant, default role `operator`. The raw key is
  returned exactly once; only its SHA-256 is stored.
- Key validity is enforced at the middleware (`db_key_validator`), fail-closed
  when the store is unavailable — a DB outage must not widen access.
- Revocation is immediate: the next request with a revoked key is 401, and the
  revocation is itself audited.

## 5. Reviews and revocation

- Token reuse triggers family revocation (audit outcome `revoked_family`).
- Tier limit (free 30 / pro 120 / labs 300 requests/minute) is enforced per
  tenant via the bearer lane and per-key limiter; `X-RateLimit-*` headers are
  returned to the caller.

## 6. Exceptions

- The unauthenticated development posture (no JWT secret configured) retains the
  WS-3 behavior for local/dev only; in that posture the admin surface returns
  503 and the ledger is open as before. Production (WS-4 enabled) requires a
  secret at boot and closes the admin surface to non-admins.
- Any requested exception requires the change-management policy (approval trail)
  and an audit note.
