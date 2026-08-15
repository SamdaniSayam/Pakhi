# WS-6 Progress Tracker — Billing, Metering, Ops

Per working agreement: every execution step is logged here with terminal
evidence, and the user is shown the running terminal live.

- Blueprint: `docs/WS6_EXECUTION_BLUEPRINT.md` (**REVISED 2026-08-15 v1.2** —
  three T0-approval amendments: drift→S1+suspension, daily Stripe sync,
  reconciliation vs chain/logs not limiters)
- Contract: `docs/WS6_BILLING_METERING_CONTRACT.md` + `data/ws6/billing_metering_contract.json` (LOCKED)
- Gate: **APPROVED-CONDITIONAL** (T0 verdict below) — explicit user
  billing/product decision; the three amendments are the condition
- SOC2 observation clock: running since 2026-08-14 (WS-4); WS-6 must make
  financial/metering controls *operational* (meter, reconciliation, retention)
  to count
- Started: 2026-08-15

---

## T0 — Gate verdict + billing/metering contract freeze

**Gate verdict (2026-08-15):** the user approved the WS-6 execution blueprint
**conditionally**. The revision review confirmed full scope, all three billable
units (`api_call`, `feed_hour`, `backtest_hour`), the 14-day one-trial-per-org
downgrade-not-delete trial policy, and the support targets (S1 ≤ 4h / S2 ≤ 12h /
S3 ≤ 2 business days). Three amendments are folded into the blueprint v1.2 and
the contract:

1. **No revenue bleed on drift (T1):** drift beyond tolerance is an **S1
   incident** with invoicing blocked *and flagged*; drift beyond the locked
   hard threshold (or an un-producible rollup) **temporarily suspends the
   tenant's API keys** with an `metering.suspend` audit row, auto-lifted on
   reconciliation — never a silent bill-drop that lets a hedge fund consume
   heavy compute for free.
2. **Daily Stripe sync (T2):** `scripts/run_ws6_stripe_sync.py` pushes each
   completed day's usage as an idempotent per-day batch **every 24 h**;
   staleness alert > 24 h — a Tuesday outage leaves 29 days before
   finalization instead of losing a month.
3. **Reconcile against durable money sources (T1):** metering reconciles
   **exactly** to the WS-4 audit chain and **within tolerance** to the WS-5
   structured access logs; the ephemeral Redis token buckets are a *control,
   not a ledger* — ops signal only.

**Contract frozen:** `docs/WS6_BILLING_METERING_CONTRACT.md` + machine twin
`data/ws6/billing_metering_contract.json` v1.2, sha `8715fc39…`, self-hash
verified.

---

## Log

### 2026-08-15 — T0 DONE: Gate + billing/metering contract freeze
- Gate verdict **APPROVED-CONDITIONAL** recorded above; three amendments
  folded into the blueprint v1.2 and the locked contract.
- **Contract + machine twin frozen:** units (api_call / feed_hour /
  backtest_hour, each sourced from an existing audited event), never-billed
  rule (5xx/503/429), tier price mapping (free $0 / pro $1,500 / labs
  $10,000+), reconciliation targets (chain exact / access-logs tolerance,
  `tolerance_percent = 1.0`, `hard_threshold_percent = 10.0`), drift response
  (S1 → suspension, auto-lift), daily Stripe sync + 24 h staleness alert,
  trial policy, support SLA, financial retention, backwards-compat rule.
  Twin sha `8715fc3932…`, self-hash verified.
- **Exit evidence:** blueprint v1.2 + contract doc + machine twin hash-pinned;
  WS-3/WS-4/WS-5 suites green (verified **1891 passed / 10 skipped** on
  2026-08-15 before T0; ruff clean; g1 reverted).

### 2026-08-15 — T1 DONE: Usage metering + reconciliation
- **`pakhi/ws6/` package** (import-clean, no side effects): `contract.py`
  accessors (single source of truth), `db.py` (`metering_rollups`,
  `metering_suspensions`, `metering_invoice_blocks` on the shared store),
  `metering.py`, `reconcile.py`, `metrics.py`, `feed_events.py`.
- **Meter = read-only aggregation** (`pakhi/ws6/metering.py`): `api_call`
  counts WS-4 audit-chain rows minus internal actions; `feed_hour` from
  `feed.connect`/`feed.disconnect` rows paired by session_id, **floored**
  (1.5 h → 1, < 1 h → 0); `backtest_hour` from `status="done"` jobs
  (started→finished wall-clock; failed/out-of-period excluded). Rollups write
  `metering_rollups` + `action="metering.rollup"` chain rows.
- **Contract tightened v1.2 → v1.3 (T1 alignment):** `api_call` = **2xx/3xx
  successful only** — the audit chain records status < 400, so 4xx (incl. 429)
  and 5xx/503 are never billable by construction (re-pinned
  `2041c8ec…`, self-hash verified).
- **Feed metering wired** (`pakhi/api/routes/stream.py`): the WS route now
  resolves the tenant from the key and records connect/disconnect audit rows
  (best-effort by design — a missing row surfaces as reconciliation drift →
  S1, never as a broken stream; the route stays the only async def).
- **Reconciliation** (`pakhi/ws6/reconcile.py`, contract §4): **chain exact**
  (rollup == independent chain recount; a mismatch is a rollup bug) +
  **access-logs tolerance** (catches lost audit rows; 4xx/5xx pre-filtered so
  they never look like drift). Drift response — **never a silent drop**:
  beyond `tolerance_percent` (1 %) → **S1 audit row + invoice block**; beyond
  `hard_threshold_percent` (10 %) → **key suspension** (revoked keys recorded
  in the suspension row so **auto-lift never un-revokes a manual revoke**);
  auto-clear on return to normal.
- **Tests `tests/test_ws6_t1_metering.py` (12, hermetic SQLite):** api_call
  counts chain rows only; 5xx/503/429 never billed (contract + no false
  drift); feed hours floored; backtest hours wall-clock/done-only; rollup
  rows + chain rows written; classify thresholds from the twin; chain-exact +
  log-tolerance reconciliation; rollup mismatch is drift not silence;
  drift → S1 + invoice block (keys live); extreme → suspension then auto-lift;
  auto-lift preserves manual revokes; no PII in metering rows + twin
  self-hash.
- **Exit evidence:** full suite **1903 passed / 10 skipped** (ws3+ws4+ws5+ws6
  subset 195 passed / 5 skipped); ruff clean; both new and prior contract
  twins self-hash; `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-15 — T2 DONE: Stripe billing (daily sync, webhooks, tier sync)
- **Thin Stripe client** (`pakhi/ws6/stripe.py`, no SDK dep — REST over
  `httpx` + stdlib HMAC): injectable transport (tests use a recording fake,
  production/CI the HTTP path with **test mode only, no live keys**). Money
  rules from the contract twin, never re-derived.
- **Daily sync, never end-of-month** (`scripts/run_ws6_stripe_sync.py`):
  ``sync_day`` submits each completed day as an idempotent per-day batch
  (``usage-<day>-<tenant>`` = our unique key **and** the Stripe idempotency
  key → re-send is a no-op). A failed batch records ``status="failed"`` and
  ``pakhi_stripe_last_sync_timestamp`` (gauge, now wired into the submit path)
  + ``is_sync_stale`` (> 24 h cadence from the twin) surface it — a Tuesday
  outage leaves 29 days before invoice finalization. Cron:
  `.github/workflows/ws6-stripe-sync.yml` (01:30 UTC, seeded usage, runs the
  real script twice to prove idempotency in CI).
- **Subscription ↔ tier sync:** ``sync_subscription_tier`` validates price ↔
  tier from the twin's new ``stripe.price_ids`` (``price_free`` / ``price_pro``
  / ``price_labs``); a contradiction or unknown tenant is a
  ``TierMismatchError`` (boot error), never a silent override. Twin re-pinned
  **v1.3** `2041c8ec…` → `01067463…` (additive: price-ids section; the doc
  already locked "Stripe price ids live in the machine twin").
- **Webhooks:** ``verify_webhook_signature`` (HMAC-SHA256 over ``t.payload``,
  constant-time, missing/malformed/mismatch → rejected, never
  logged-and-applied); ``apply_webhook`` **dedupes on Stripe event id** (applied
  once; duplicate delivery is a no-op; tier-mismatch on
  ``customer.subscription.updated`` is a boot error).
- **No card data, ever:** test asserts `card_number`/`cvc`/`cvv`/`exp_month`/
  `exp_year`/`pan` never appear in `pakhi/ws6/stripe.py` or the sync script,
  and the twin locks `card_data = "never stored on our servers"`.
- **Tests `tests/test_ws6_t2_stripe.py` (11, hermetic SQLite + fake
  transport):** twin self-hash + price-ids mapping; daily batch idempotency
  (re-sync submits nothing new); retry never double-submits; failed batch →
  stale; staleness after cadence + never-synced; tier sync + mismatch boot
  errors (tier never overridden); signature verify incl. tamper/wrong-secret;
  webhook applied once, duplicate no-op; bad signature rejected (no ledger
  row); tier-mismatch webhook is a boot error; no card fields anywhere.
- **Exit evidence:** full suite **1914 passed / 10 skipped** (ws3+ws4+ws5+ws6
  subset 206 passed / 5 skipped); ruff + format clean; ws6 twin self-hash;
  sync script smoke-tested end-to-end (seeded sqlite, `--fake`, run twice →
  1 batch both times); `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-15 — T3 DONE: Onboarding + 14-day trial automation (audited lifecycle)
- **Onboarding checklist executed** (`pakhi/ws6/trial.py` +
  `onboard_tenant`): provision tenant → issue API key (WS-4 `create_api_key`,
  raw key returned once) → assign tier → start 14-day trial → expiry →
  downgrade to `free` (never delete) → conversion to paid. Every transition
  writes an audit row (`onboarding.*` / `trial.*` / `billing.*`) into the
  WS-4 chain, atomically with the transition.
- **Trial policy = locked twin** (`trial.days = 14`): 14 days from tenant
  creation; **one trial per contact/org** — the DB enforces it via unique
  `tenant_id` *and* unique `contact_id`; a second attempt is refused **and
  audited** (`trial.denied`). Expiry is a downgrade, never a deletion (the
  trial row + data persist). Conversion keeps the trial row as evidence,
  records `converted_at`, upgrades the tier (audited
  `billing.tier_upgrade`), and writes `trial.converted` +
  `billing.subscription_created`.
- **Expiry automation** (`expire_due_trials`, idempotent): expired-and-not-
  converted/downgraded trials → tier downgrade to `free` (audited
  `billing.tier_downgrade` + `trial.expired`) — a converted trial is never
  touched. Pre-expiry `trial.expiring` notices enqueued once per trial (no
  daily spam) for trials inside the 2-day window.
- **Notifications = webhook outbox + audit rows** (contract §6 honest
  wording, email/CRM deferred): `notification_outbox` table;
  `deliver_outbox` marks sent on transport accept, keeps a failed delivery
  pending for retry (never dropped); `outbox_pending` reads it.
- **Meter honesty (T1/T3 invariant):** the lifecycle rows are internal
  bookkeeping, not client requests — added `trial.*`,
  `billing.subscription_created`, `billing.tier_upgrade`,
  `billing.tier_downgrade`, `onboarding.tenant_provisioned` to the metering
  `INTERNAL_ACTIONS` denylist so a trial/conversion/suspension never inflates
  the invoice (verified: a full lifecycle + 1 real read counts exactly 2
  client actions: `read` + `api_key.create`).
- **Tests `tests/test_ws6_t3_trial.py` (8, hermetic SQLite):** twin locks
  trial policy; onboarding checklist provisions tenant+key+trial (all three
  audit rows); one-trial-per-org refusal for same org and same contact (2
  `trial.denied`, 1 trial row ever); expiry downgrades to free, never deletes,
  idempotent second pass; `trial.expired` + `trial.expiring` webhook-deliverable
  outbox; delivery marks sent / keeps failures pending then retries;
  conversion hooks subscription + upgrades tier (pro → 120/min, audited);
  lifecycle rows never count as API calls.
- **Exit evidence:** full suite **1922 passed / 10 skipped** (ws3+ws4+ws5+ws6
  subset 214 passed / 5 skipped); ruff + format clean; twin self-hash;
  `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-15 — T4 DONE: Support SLA + financial-integrity wrap
- **Support contract** (`docs/WS6_SUPPORT_SLA.md`): severities + response
  targets + escalation matrix + status-page linkage + retention, all reading
  the locked twin (§7/§8). Targets are operational commitments, distinct from
  the conditional 99.9 % offer (WS-5 window, untouched).
- **Severity parser** (`pakhi/ws6/support.py::classify_severity`): reads the
  **locked keywords** now in the twin (`support_sla.severities.*.keywords`,
  priority S1→S2→S3, first-hit wins, unmatched → S3 default) +
  `response_target` / `escalation_path`. Twin re-pinned **v1.3**
  `01067463…` → `e852603d…` (support_sla extended with keywords + escalation).
- **Status-page linkage (S1 = incident):** `_deep_status` now surfaces an
  `"incidents"` feed read **straight from the WS-4 audit chain** (recent
  `metering.s1` / `metering.suspend` / `metering.block_invoice` rows) — the
  feed *is* the ledger of truth, not a config file; it cannot drift from the
  S1 path that wrote it (T1). Rendered on the HTML page too. Read-only
  addition; WS-5 status assertions untouched.
- **Financial retention (contract §8):** metering/rollup/billing rows are
  audit-chain rows; the repo has **no production DB-delete path at all** —
  the only deletes/unlinks prune backup and ingest *files*. Asserted by a test
  that scans `pakhi/` production code for `.delete(` / `DELETE FROM` (must be
  empty) and pins the twin's retention clause.
- **SOC2 observation-clock entry:** the metering, reconciliation, and billing
  controls (T1–T3) are **operational**, not config files — the clock running
  since 2026-08-14 (WS-4) observes a live metering + reconciliation +
  Stripe-sync + trial lifecycle control program, each with on-disk machine
  evidence (`pakhi/ws6/*`, the sync script + workflow, and the hermetic
  suites). Recorded in this progress log.
- **Tests `tests/test_ws6_t4_support.py` (6, hermetic SQLite):** targets +
  locked keywords hash-pinned in twin; parser deterministic (S1/S2/S3 hits,
  defaults, S1-over-S2 precedence, case-insensitivity); escalation matrix
  documented; S1 feed reads the chain (newest first, only incident actions);
  `/v1/status` surfaces the incidents list (full TestClient app, seeded store);
  no production DB deletes + retention clause pinned.
- **Exit evidence:** full suite **1928 passed / 10 skipped** (ws3+ws4+ws5+ws6
  subset 220 passed / 5 skipped); ruff + format clean; twin self-hash
  (`e852603d…`); `data/ws1/g1_decision.json` reverted after the run.

### 2026-08-15 — T5 DONE: Exit evidence + full regression
- **Full suite green:** **1936 passed / 10 skipped** (ws3+ws4+ws5+ws6 subset
  228 passed / 5 skipped) — the largest yet; ruff + format clean.
- **CI job for the money-critical suites:** `.github/workflows/ws6-stripe-sync.yml`
  now also runs `test_ws6_t1_metering.py` + `test_ws6_t2_stripe.py`
  (reconciliation + webhook idempotency) every nightly cron, not just on push
  (the push `ci.yml` runs the whole `tests/` suite, so the same suites run
  there too).
- **T0 skeleton evidence added** (`tests/test_ws6_t0_skeleton.py`, 5): fresh
  interpreter import of `pakhi.ws6` pulls neither fastapi nor
  prometheus_client; twin self-hash + `contract_consistent()`; accessors return
  the locked values (units, never-billed, prices, reconciliation targets +
  tolerance/hard thresholds, trial days, sync cadence + staleness, severities);
  backwards-compat rule locked.
- **Cross-reference pass** (`tests/test_ws6_t5_crossref.py`, 3; blueprint rule
  2 / WS-5 rule 9): the doc set (contract, support SLA, blueprint) promises
  exactly the twin's numbers — every unit name, tier price ("1500" or "1,500"),
  trial policy, severity target ("4h" ↔ "≤ 4 h"), tolerance/hard thresholds,
  and staleness hours appear in the docs; runtime consumers (`stripe.py`,
  `trial.py`, `support.py`) read the twin and never hard-code a contract
  number.
- **All three twins self-hash:** ws6 `e852603d…` (v1.3), ws5 `68d82132…`,
  ws4 `7ecc5247…`.
- **`data/ws1/g1_decision.json` reverted** after the run — G1 stays
  UNDER-POWERED; WS-6 never claims live trials or paid contracts (those are
  runtime exits G2/G3 accrue when real tenants board).

### 2026-08-15 — T2/T1/T3 AUDIT FIXES: three production-blocking bugs closed
An independent audit of the WS-6 execution found three fatal business-logic
flaws that the hermetic test suite masked (a fake transport that validated
nothing + edge cases of human admin intervention). All three are confirmed,
fixed, and pinned by new tests.

1. **Stripe sync sent the internal tenant id as `subscription_item`**
   (`scripts/run_ws6_stripe_sync.py`). Stripe's usage-records API requires a
   valid **Subscription Item id** (`si_...`) — every real daily sync would 400
   and no client would ever be billed. **Fix:** the `customer.subscription.
   updated` webhook now extracts `data.object.items.data[0].id` (+ `customer`),
   stores them on the tenant row (`tenants.stripe_customer_id` /
   `stripe_subscription_item_id`), and the sync passes that id — never the
   tenant id. Both fakes now validate the `si_` prefix so the exact bug is
   caught at test time. `customer.subscription.deleted` clears the linkage
   (audited `billing.subscription_removed`, added to `INTERNAL_ACTIONS` so it
   never bills). A **paid** tenant with usage but no captured item id fails the
   sync loudly (ops/staleness alert) instead of silently dropping; free/trial
   tenants are skipped silently. Contract doc §5 + twin re-pinned
   (`e852603d…` → `5be1aa0d…`, self-hash verified).
2. **Auto-lift un-revoked manual revocations** (`reconcile.py`). The lift set
   `revoked_at = None` on every key in the suspension, so a key an admin
   manually re-revoked *after* the system suspended the tenant would be
   restored the moment drift cleared (a banned abusive tenant gets API access
   back). The old test only covered a key created after the suspension.
   **Fix:** `_suspend` records the exact `suspended_at`; `_lift_suspensions`
   restores a key only when `revoked_at == suspended_at` (the system's own
   revocation). A human ban (moved `revoked_at`) survives auto-lift **and**
   explicit `lift_suspension`. New tests pin both paths.
3. **Trial expiry downgraded manually-upgraded paying tenants**
   (`trial.py`). `expire_due_trials` downgraded any non-free tenant; a tenant
   an admin upgraded to pro by hand (bypassing `convert_trial`, so
   `converted_at` stays None) would be silently dropped to `free` at expiry.
   **Fix:** the expiry now compares `tenant.tier` to the trial's snapshot
   `tier_at_trial` — unchanged tier → contract downgrade applies; changed tier
   → the trial record is closed (`trial.expired` + `downgraded_at`) and the
   current tier is **left untouched** (`kept_paid_tier`). The old test encoded
   the bug (seeded pro, expected downgrade); it now seeds the trial tier and a
   new test pins the admin-upgrade survival, including idempotency.
- **Exit evidence:** full suite **1944 passed / 10 skipped** (ws6 subset 53
  passed — T1 14, T2 16, T3 9, T4 6, T5 3, T0 5); sync script smoke-tested
  end-to-end against seeded sqlite (`--fake`, item id attached, second run
  submits nothing); ruff + format clean; all three twins self-hash
  (ws6 `5be1aa0d…`, ws5 `68d82132…`, ws4 `7ecc5247…`);
  `data/ws1/g1_decision.json` reverted after the run.

---

WS-6 T0–T5 all DONE (2026-08-15). The API is now **meterable, billable,
onboardable, and supportable** while keeping the honest-premise discipline:
billing sells service/compute/data access, never validated alpha (G1
UNDER-POWERED retained); the conditional 99.9 % offer's evidence stays the
WS-5 window; "first 14-day trials active" and "first paid contracts live" are
runtime exits that accrue when real tenants board — WS-6 ships the machinery
and the honest claim language, never the number itself.

| Task | Evidence |
|---|---|
| T0 gate + contract freeze | APPROVED-CONDITIONAL; twin v1.3 self-hash |
| T1 metering + reconciliation | 14 tests; chain-exact + log-tolerance; S1/suspend on drift; lift never un-revokes manual bans |
| T2 Stripe billing | 16 tests; daily idempotent sync + staleness; webhook dedupe; real `si_…` item id captured + passed; no card data |
| T3 onboarding + trials | 9 tests; audited lifecycle; one-trial-per-org; downgrade-not-delete; admin-upgraded paid tiers kept |
| T4 support SLA + retention | 6 tests; severity parser; incident feed; retention; SOC2 entry |
| T5 exit evidence | 8 tests (5 skeleton + 3 cross-ref) |
| Audit fixes (T1/T2/T3) | **1944 passed / 10 skipped**; three production-blocking bugs closed + pinned; twins self-hash; g1 reverted |
