# WS-6 Billing & Metering Contract (LOCKED)

Status: **LOCKED 2026-08-15 — T0 gate APPROVED-CONDITIONAL** (three amendments
folded in, below). Machine twin: `data/ws6/billing_metering_contract.json`
(self-hash-pinned). Blueprint: `docs/WS6_EXECUTION_BLUEPRINT.md` v1.2.
This contract is the **single source of truth** for every billing number in
more than one place: units, prices, reconciliation, drift response, sync
cadence, trial, support.

---

## 1. Honest premise

G1 remains UNDER-POWERED (N = 7 < N_min = 8); WS-6 bills **service, compute,
and data access**, never validated alpha. The paid surface is point-in-time
data, backtests, signals-as-data, and feeds. No metering row, invoice, or
support commitment implies a performance claim. The 99.9 % uptime language
remains a conditional offer whose evidence accrues in the WS-5 window.

Billing is real money, so the controlling principle is **trust by
construction**: the meter is a read-only aggregation of the tamper-evident
WS-4 audit chain, so we can never bill a client for a request they did not
make — and (the three amendments) we can never *fail* a client's invoice into
free service while they keep consuming.

## 2. Billable units

Each unit is defined against an existing audited event — nothing is invented,
nothing is counted twice.

| Unit | Definition | Source (audited) | Never billed |
|---|---|---|---|
| `api_call` | Authenticated request returning **2xx/3xx (successful)** | WS-4 audit chain row (action `read` + API write rows; the chain records only status < 400) | 4xx (incl. 429), 5xx, 503 (incl. fail-closed) |
| `feed_hour` | One authenticated `/stream/signals` subscription active ≥ 1 h (connect→disconnect delta, floored) | Audit chain + feed connect/disconnect events | < 1 h, unauthenticated connects |
| `backtest_hour` | One `backtest_jobs` row reaching `status=done`, wall-clock `started_at`→`finished_at` (locked per-job floor) | `backtest_jobs` | `failed`/`cancelled` jobs |

429 is **never** billed: it means the client exceeded its tier (WS-5 rule that
429s are never downtime extends to "429s are never invoices"). 5xx/503 are
never billed: they are server faults, and fail-closed 503s are recorded
separately per WS-4/WS-5. `api_call` is 2xx/3xx only: the audit chain records
successful requests (status < 400), so client errors (4xx) are never billable
by construction.

## 3. Tiers (locked mapping)

Rate-limit buckets are the locked WS-4 value; billing prices anchor the
commercial blueprint (`docs/BLUEPRINT.md` §1.3). Stripe price ids live in the
machine twin.

| WS-4 tier | Rate limit | Commercial tier | Price anchor |
|---|---|---|---|
| `free` | 30 req/min | Tier 1 (Community) | $0 |
| `pro` | 120 req/min | Tier 2 (Managed API) | $1,500–5,000/mo (base + usage) |
| `labs` | 300 req/min | Tier 3 (Enterprise) | $10,000+/mo (custom/annual) |

A tenant's Stripe price must match its WS-4 bucket; a mismatch is a boot/
reconciliation error, never a silent override. Stripe price ids (machine twin
`stripe.price_ids`): `free` → `price_free`, `pro` → `price_pro`,
`labs` → `price_labs`; the subscription tier sync validates price ↔ tier on
every webhook and rejects contradictions.

## 4. Reconciliation (money = durable sources only)

1. **Audit chain — exact.** Rollup totals == chain-derived counts (identity;
   catches rollup bugs by construction).
2. **Structured access logs — tolerance.** Chain-derived counts vs WS-5
   access-log request counts within `reconciliation.tolerance_percent`
   (catches lost audit rows; the `omission_reconciliation` machinery exists in
   `pakhi/ws4/audit.py`).

**The Redis token buckets are excluded from money reconciliation.** They are
ephemeral rolling-window counters (a control, not a ledger) and remain an ops
signal only.

### 4.1 Drift response (fail-closed, escalated — never a silent drop)

| State | Condition | Response |
|---|---|---|
| Normal | within tolerance | nothing |
| Drift | beyond `tolerance_percent` | **S1 incident paged**; invoicing blocked *and flagged* for the affected tenant |
| Extreme | no rollup producible, or drift beyond `hard_threshold_percent` | **Temporary key suspension** (stops un-metered consumption) + S1 + `metering.suspend` audit row; **auto-lift** on reconciliation |

Un-metered service is an incident, never a quiet state: a hedge fund must
never consume heavy compute for free because its invoice was quietly dropped.

## 5. Stripe billing

- **Sync cadence: daily.** `scripts/run_ws6_stripe_sync.py` submits each
  completed day's usage as an idempotent per-day batch **every 24 h** — a
  Tuesday outage leaves 29 days before invoice finalization. A
  `pakhi_stripe_last_sync_timestamp` gauge + staleness alert (> 24 h) makes a
  silent failure impossible.
- **Idempotency:** per-day batch id → Stripe usage-record id, 1:1; re-send is a
  no-op.
- **Usage records attach to a Subscription Item, never a tenant.** Stripe's
  usage-records API requires the tenant's Stripe **Subscription Item id**
  (`si_...`). It is captured from the `customer.subscription.updated` webhook
  (`data.object.items.data[0].id`), stored on the tenant row, and passed by the
  sync — the internal `tenant_id` is never sent as `subscription_item`. A paid
  tenant with no captured item id fails the sync loudly (ops alert), never a
  silent drop; a free/trial tenant is skipped silently. `customer.subscription.
  deleted` clears the linkage so cancelled subscriptions stop receiving usage.
- **Webhooks:** verified by signature; deduped on Stripe event id; a duplicate
  event is applied once; signature failures are rejected.
- **No card data, ever:** Stripe-hosted surfaces only; our schema/logs/DB never
  see a PAN/CVV.
- Stripe is the system of record for charges; the meter feeds it, the chain
  backs it.

## 6. Trial & onboarding

- 14 days from tenant creation; **one trial per contact/org** (second attempt
  refused + audited); expiry **downgrades to `free`**, never deletes data;
  conversion opens a paid subscription.
- Every transition (`onboarding.*`, `trial.*`, `billing.*`,
  `metering.suspend`) writes an audit row into the WS-4 chain — a compliance
  story with no chain rows is a config file, not a control.
- Notifications = webhook outbox + audit rows; email/CRM deferred (honest:
  notices are webhook-deliverable, not email-guaranteed).

## 7. Support SLA (paid tiers)

| Severity | Meaning | Response target | Triage keywords (locked) |
|---|---|---|---|
| S1 | Service down / data-integrity event | ≤ 4 h | down, outage, unavailable, data integrity, corrupt, breach, suspended, incident |
| S2 | Degraded or blocking bug | ≤ 12 h | degraded, blocking, bug, error, slow, timeout, fail |
| S3 | Minor bug / question | ≤ 2 business days | question, minor, typo, docs, feature, request, how, why |

Operational commitments (how fast we respond), distinct from the conditional
99.9 % offer. An S1 is an incident → written to `/v1/status` + audit chain.
Severity parsing is deterministic (locked keywords + escalation matrix) and
pinned by a test. Escalation: S1 pages on-call immediately (invoicing blocked
if metering-related); S2 responds within target with workaround when possible,
escalates to S1 on data-integrity or extended outage; S3 responds within
business days, batched with the next maintenance window.

## 8. Financial record retention

Metering buckets, rollup rows, and billing transitions are audit-chain rows and
inherit its retention; they are **never pruned by the normal retention job**.
Stripe records are the external system of record (their retention governs the
invoice copy). Financial-audit assertions cover this in T4.

## 9. Backwards compatibility

Metering is **read-only aggregation**. The WS-3/WS-4/WS-5 request contract,
audit chain, and rate-limit behavior are unchanged; their suites stay green
after every change.

---

## Amendment record

- **v1.1 → v1.2 (2026-08-15, T0 conditional approval):** (1) drift is S1 +
  suspension on extreme drift, never a silent bill-drop; (2) daily Stripe sync
  cadence + staleness alert; (3) reconciliation targets = audit chain (exact)
  + access logs (tolerance); Redis limiters are ops-signal only.
- **v1.2 → v1.3 (2026-08-15, T1 alignment):** `api_call` tightened to 2xx/3xx
  successful requests only — the audit chain records status < 400, so 4xx (incl.
  429) and 5xx/503 are never billable. Conservative and source-exact.
