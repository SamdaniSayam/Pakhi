# WS-6 — Billing, Metering, Ops: Execution Blueprint

Status: **REVISED 2026-08-15 v1.2 — user conditional approval with three
amendments folded in: (1) metering drift is an S1 incident + temporary key
suspension on extreme drift, never a silent bill-drop; (2) Stripe usage syncs
**daily** (`scripts/run_ws6_stripe_sync.py`), never an end-of-month dump;
(3) money reconciliation targets the WS-4 audit chain (exact) + WS-5
structured access logs (tolerance), **never** the ephemeral Redis limiters.**
T0 gate: **APPROVED-CONDITIONAL** (recorded in `docs/WS6_PROGRESS.md`).
Progress: tracked in `docs/WS6_PROGRESS.md`
Progress: tracked in `docs/WS6_PROGRESS.md` (created only after this blueprint is approved)
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-6 (weeks 10–14) + Phase 2/3
checkboxes; handoffs locked by WS-3 (`POST /v1/backtests` job queue in
`pakhi/api/jobs.py`, `/stream/signals` feed in `pakhi/api/routes/stream.py`),
WS-4 (tiers `free`/`labs`/`pro`, audit chain, API-key lifecycle, tenant
onboarding), WS-5 (30-day SLO window 2026-08-14 → 2026-09-13, `/v1/status`,
structured logs + `request_id`, DR drills)
Gate: **an explicit, user-made billing/product decision** (mirrors WS-3/WS-4/WS-5
T0). Long-term gates: **G2** (Production Blueprint §5, end of Phase 2 — live API
≥ 30 d, **first 14-day trials active**) and **G3** (end of Phase 3 — **first
1–2 paid enterprise contracts live**, 99.9 % evidence, SOC2 controls observed).
**WS-6 is the workstream that makes G2's trial clause and G3's paid contracts
reachable**: before WS-6 there is no meter, no invoice, no trial — only an API
that cannot be bought.

**T0 revision review (2026-08-15):** the user chose to revise before the gate
was recorded; the review confirmed every decision as drafted — (1) **full
scope** (metering + Stripe + trials + support SLA, T1–T4), (2) **all three
billable units** (`api_call`, `feed_hour`, `backtest_hour`), (3) **trial
policy as drafted** (14 days, one per contact/org, expiry downgrades to free,
never deletes), (4) **support targets as drafted** (S1 ≤ 4 h, S2 ≤ 12 h,
S3 ≤ 2 business days, paid tiers only).

**T0 conditional approval (2026-08-15):** the gate is **APPROVED-CONDITIONAL**
with three financial/ops amendments required before build:

1. **No revenue bleed on drift (T1).** The old "block the invoice" fail-closed
   left a paying tenant consuming heavy compute un-metered and unbilled — a
   bleeding hole, not a safe state. Amended: drift beyond tolerance is an
   **S1 incident (paged)** with invoicing blocked *and flagged*; drift beyond a
   locked **hard threshold** (or a meter that cannot produce a rollup)
   **temporarily suspends the tenant's API keys** to stop un-metered
   consumption, paired with an S1 and an `metering.suspend` audit row, lifted
   automatically on reconciliation. Un-metered service is an incident, never a
   quiet state.
2. **Daily Stripe sync cadence (T2).** Idempotency alone doesn't say *when*
   usage is submitted; a single end-of-month dump plus a Stripe outage on the
   31st invoices at $0 and loses a month of revenue. Amended: a cron script
   `scripts/run_ws6_stripe_sync.py` pushes each completed day's usage as an
   idempotent per-day batch **every 24 h** — a Tuesday failure leaves 29 days
   to recover before finalization; a staleness alert (> 24 h without a sync)
   makes a silent failure impossible.
3. **Reconcile against durable money sources, not the limiter (T1).** The WS-5
   Redis token buckets are ephemeral rolling-window counters that expire and
   reset — they can never reconcile to a 30-day invoice. Amended: metering must
   reconcile **exactly** to the WS-4 audit chain (its derivation source) and
   **within tolerance** to the WS-5 structured access logs (catches lost audit
   rows); the Redis limiters are a *control*, not a ledger — ops signal only.

The gate verdict is recorded in `docs/WS6_PROGRESS.md`; build may begin on
approval of these amendments.

---

## 0. Honest premise (what WS-6 is actually for)

WS-1 G1 remains **UNDER-POWERED** (N = 7 < N_min = 8; 0 scored live events).
WS-3/WS-4/WS-5 shipped infrastructure; none changed that. WS-5 opened the
30-day SLO measurement window and the 99.9 % language is a **conditional
offer** whose evidence accrues in the window — never a claim made ahead of it.
WS-6 must inherit that discipline exactly.

WS-6's mandate, read honestly, is therefore:

> **Give the operationally credible API the three things that make it
> buyable — a truthful meter, a bill, and a boarding process — without ever
> selling a performance claim.** G1 is UNDER-POWERED, so the paid surface is
> the *service*: point-in-time data, backtests, signals-as-data, feeds,
> compute. Billing sells access and compute against locked WS-4 tiers; it does
> not sell, and cannot claim, validated alpha. The "open-core / DaaS" framing
> the Production Blueprint §2.4 names as the fallback is exactly the product
> surface WS-6 bills on — so WS-6 is **branch-agnostic**: it is the correct
> next step whether G1 later clears or pivots.

**Why now:** G2's exit includes "first 14-day trials active" and G3's exit
includes "first 1–2 paid enterprise contracts live". Neither can accrue while
there is no meter, no billing, and no trial. The SOC2 observation clock
(running since 2026-08-14) also needs financial/metering controls to be
**operational, not documented**, to count as controls under observation.

**What is NOT being decided here:** WS-6 does not set pricing strategy forever
(the tier table is a revisionable contract value, not a religion), does not do
GTM/marketing/sales (WS-7), does not choose a payment jurisdiction beyond
Stripe defaults, does not store card data or pick an email/CRM vendor
(notifications = webhooks + audit rows; email is ops-deferred), and does not
schedule SOC2 certification.

---

## 1. Purpose

Turn the credible API into a **billable, onboardable, supported product**:

- **Usage metering per tenant/tier** — aggregated over the WS-4 audit chain and
  `backtest_jobs` (a *single source of truth*; metering never gets its own
  drift-able counter): authenticated API calls, instrument-feed subscription
  hours, backtest compute hours.
- **Stripe billing tied to metering** — subscriptions bound to WS-4 tiers,
  usage-based pricing, idempotent webhooks, proration, Stripe as system of
  record for money. Card data never touches our servers.
- **Onboarding + 14-day trial automation** — tenant provisioning checklist,
  key issuance, trial lifecycle, expiry downgrade, conversion hook — every step
  written into the WS-4 audit chain (compliance is not a config file).
- **Support SLA** — severity taxonomy, response-time targets for paid tiers,
  triage discipline, linkage to the WS-5 status page. Response targets are
  *operational* commitments, distinct from the conditional 99.9 % offer.

**Deferred explicitly:** GTM/marketing (WS-7), pricing-strategy iteration,
email/CRM vendor, multi-region/auto-scale (Phase 4), SOC2 certification
scheduling. WS-6 does **not** claim trials are "active at scale" until real
tenants board, does not claim the first paid contract is live until Stripe
says an invoice is paid, and does not claim an achieved uptime number.

---

## 2. Out of scope (explicitly)

- GTM, marketing, sales funnel, partner/channel work (WS-7).
- Pricing-strategy iteration; the initial tier table is a locked contract
  value that a later amendment may revise — not a Phase-3 deliverable.
- Email/CRM provider selection (webhook outbox + audit rows only; email
  deferred), payment jurisdiction beyond Stripe defaults, card/PCI handling
  beyond "never see the PAN".
- Multi-region, auto-scaling, k8s (Phase 4).
- SOC2 Type I/II certification scheduling (the observation clock continues;
  metering/billing controls becoming *operational* is WS-6's contribution).
- Changing the WS-3/WS-4/WS-5 request contract: metering is a **read-only
  aggregation** over existing audited events; request behavior is unchanged.

---

## 3. Detailed design

### 3.1 Metering contract & model

A new locked contract `docs/WS6_BILLING_METERING_CONTRACT.md` + machine twin
`data/ws6/billing_metering_contract.json` (self-hash-pinned, same pattern as
WS-2/3/4/5). It is the **single source of truth** for units, tier prices,
trial policy, severity/response targets — every number used in more than one
place lives once, here.

**Billable units** (each defined against an existing audited event, so there is
nothing to invent):

- `api_call` — an authenticated request on the API surface that returns 2xx,
  3xx, or 4xx (except 429). **5xx/503 are never billed** (server fault, and
  fail-closed 503s are recorded separately per WS-4/WS-5). **429 is never
  billed** — it means the client exceeded its tier; the WS-5 rule that 429s are
  never downtime extends to "429s are never invoices".
- `feed_hour` — one authenticated `/stream/signals` subscription active for one
  hour (connect→disconnect delta, floored per contract).
- `backtest_hour` — one `backtest_jobs` row that reached `status=done`, billed
  as wall-clock from `started_at` to `finished_at` (or a locked per-job floor).

**Metering = read-only aggregation, not a second counter.** Rows are derived
from the WS-4 audit chain (each authenticated request already appends a
hash-chained row) plus `backtest_jobs` and feed connect/disconnect events —
so billing inputs inherit the chain's tamper-evidence. A separate
increment-on-request counter would drift; we refuse to create one. Monthly
buckets per `tenant_id` + `tier`, each bucket row itself written to the audit
chain (`action="metering.rollup"`).

**Reconciliation targets (money = durable sources only).** Monthly metering
rows must reconcile against exactly two things:

1. **WS-4 audit chain — exact (identity).** The metering rollup is an
   aggregation of the chain, so rollup totals must equal the chain-derived
   counts exactly. This catches rollup bugs by construction.
2. **WS-5 structured access logs — within a locked tolerance.** The access-log
   request count for a tenant must match the chain-derived count within the
   locked tolerance, catching the one hole the chain alone cannot: **lost audit
   rows** (e.g., a DB write failed silently). The `omission_reconciliation`
   machinery already exists for this in `pakhi/ws4/audit.py`.

**The Redis token buckets are a control, not a ledger.** They are ephemeral
rolling-window counters that expire and reset — they can never reconcile to a
30-day monthly invoice and are **excluded from money reconciliation** entirely.
They remain an ops signal only (`pakhi_ratelimit_rejections_total`).

**Drift response (fail-closed, escalated — never a silent drop).** The meter
guards the money, so *un-metered service is treated as a live incident*:

- Within tolerance: normal.
- Beyond tolerance: **S1 incident (paged per the support contract)**, invoicing
  for the affected tenant blocked *and* flagged — not quietly dropped.
- Extreme (meter cannot produce a rollup, or drift beyond the locked hard
  threshold): the tenant's API keys are **temporarily suspended** to stop
  un-metered consumption (the revenue bleed). Suspension is a contract-gated
  last resort, always paired with an S1 and an `action="metering.suspend"`
  audit row, and **lifted automatically** once the meter reconciles.

### 3.2 Stripe billing

- **Subscription ↔ tier sync.** A Stripe subscription is bound to exactly one
  WS-4 tier (`free`/`labs`/`pro`). The tier → rate-limit bucket mapping is the
  locked WS-4 value; Stripe price ids for each tier are recorded in the WS-6
  contract twin. A mismatch between a tenant's Stripe price and its WS-4 bucket
  is a **boot/reconciliation error** (mirrors WS-5 rule 4: single source of
  truth applied to money).
- **Usage submission.** Metering buckets are submitted to Stripe as usage
  records (usage-based pricing), **idempotently**: each metering batch carries a
  locked batch id that maps 1:1 to a Stripe usage-record id — re-submitting the
  same batch is a no-op, never a double-charge.
- **Sync cadence — daily, never end-of-month.** A cron script
  `scripts/run_ws6_stripe_sync.py` pushes each completed day's aggregated
  usage as an idempotent per-day batch **every 24 h**. Pushing as usage
  accrues — not one end-of-month dump — means a Tuesday Stripe outage or a
  server crash leaves 29 days to recover before the invoice finalizes; a lost
  day is one day, not the whole month. A `pakhi_stripe_last_sync_timestamp`
  gauge plus a staleness alert (no successful sync in > 24 h) makes a silent
  sync failure impossible.
- **Webhooks, idempotent.** `subscription.created` / `updated` / `canceled`,
  `invoice.paid` / `invoice.payment_failed` — every event deduped on the Stripe
  event id in a `stripe_webhook_events` table (a duplicate event is applied
  once). Webhook signature verification is mandatory (Stripe-Signature header);
  a signature failure is rejected, not logged-and-applied.
- **No card data, ever.** Checkout uses Stripe-hosted surfaces; our code,
  logs, and DB never see a PAN/CVV. A test asserts no card field names exist in
  our request schema.

### 3.3 Onboarding + 14-day trial

- **Onboarding checklist** (documented and *executed*): create tenant → issue
  API keys (WS-4 `create_api_key`) → assign tier → start 14-day trial → expiry
  → downgrade to `free` (never delete) → conversion to a paid subscription.
  Every transition writes an audit row (`onboarding.*` / `trial.*` /
  `billing.*`) into the WS-4 chain.
- **Trial policy** (locked in the contract twin): 14 days from tenant creation;
  **one trial per contact/org** (anti-gaming: a second trial attempt for the
  same org is refused and audited); expiry is a downgrade, not a deletion, so
  data is never held hostage; conversion hooks to the subscription flow.
- **Notifications** = webhook outbox + audit rows. Email/CRM is deferred; the
  contract is honest that "trial expiring" notices are webhook-deliverable, not
  email-guaranteed.

### 3.4 Support SLA

- **Severities:** S1 (service down / data-integrity event), S2 (degraded or
  blocking bug), S3 (minor bug / question). Locked response-time targets for
  paid tiers (e.g., S1 ≤ 4 h, S2 ≤ 12 h, S3 ≤ 2 business days) — stated as
  targets, honest for a solo-founder operation; escalation path documented.
- **Status-page linkage:** an S1 is an incident → written to the WS-5
  `/v1/status` incident feed and the audit chain. Support response times are
  *operational* commitments and never conflict with the conditional 99.9 %
  offer (that offer's evidence is the WS-5 window, untouched by WS-6).
- **Triage discipline:** a severity-parsing rule (locked keywords + escalation
  matrix) so a ticket is classified deterministically; a test pins the parser.

---

## 4. Tasks, sequencing, exit criteria

### T0 — Gate decision + billing/metering contract freeze
Before any build:
- Record the gate verdict in `docs/WS6_PROGRESS.md`: **explicit user
  billing/product decision** (mirroring WS-3/WS-4/WS-5 T0). If declined, WS-6
  stays prepared, not executed.
- Freeze `docs/WS6_BILLING_METERING_CONTRACT.md` + `data/ws6/billing_metering_contract.json`
  (self-hash-pinned). Lock: billable units + their audit-event definitions,
  what is **never** billed (5xx/503/429), tier prices + Stripe price ids,
  **reconciliation targets (chain exact / access-logs tolerance), the drift
  tolerance + hard threshold, the S1-and-suspend drift response**, **daily
  Stripe sync cadence + staleness alert**, trial policy, severity/response
  targets, retention of financial records, and the backwards-compat rule
  (metering is read-only aggregation; request behavior is byte-identical).
- Add `pakhi/ws6/` package skeleton (import-clean, no side effects).
- **Exit:** contract doc + machine JSON approved and hash-pinned; gate verdict
  recorded; `pakhi.ws6` imports cleanly; WS-3/WS-4/WS-5 suites still green.

### T1 — Usage metering (week 1)
- Metering aggregation over the audit chain + `backtest_jobs` + feed events;
  monthly buckets per tenant/tier; `metering.rollup` audit rows; WS-5 metrics
  (`pakhi_metered_*`) so the meter is observable; drift S1 + suspension
  machinery (contract-gated, auto-lift).
- **Exit:** tests — authenticated-call counts reconcile **exactly** to
  audit-chain-derived counts and **within tolerance** to structured access-log
  counts; a simulated audit-row loss is caught by the log cross-check; extreme
  drift triggers **key suspension with an S1 + `metering.suspend` audit row**
  (never a silent bill-drop) and auto-lift on reconciliation; 5xx/503/429
  appear in *no* billable bucket; feed hours and backtest hours meter
  correctly; no PII/keys in any metering row; WS-3/WS-4/WS-5 suites green.

### T2 — Stripe billing (week 1–2)
- Subscription ↔ tier sync; idempotent usage submission (per-day batch id →
  usage record id); `scripts/run_ws6_stripe_sync.py` daily cron + staleness
  metric/alert; webhook verification + dedupe on Stripe event id; test-mode
  only.
- **Exit:** tests — a duplicate webhook event is applied once; a
  signature-missing/invalid webhook is rejected; a Stripe price ≠ WS-4 tier
  mismatch is a boot error; a per-day batch submitted twice produces exactly
  one usage record (no double-charge); **a > 24 h sync gap flips the staleness
  alert**; a test asserts our request schema contains no card fields; CI runs
  mocked (Stripe-CLI-style), never with live keys.

### T3 — Onboarding + trial automation (week 2–3)
- Onboarding checklist executable (each step audited into the chain); 14-day
  trial lifecycle; expiry → `free` downgrade; conversion hook; one-trial-per-org
  rule; webhook outbox.
- **Exit:** tests — full trial lifecycle (create → trial → expiry → downgrade)
  with an audit row per transition; second-trial-for-same-org is refused and
  audited; conversion opens a subscription; WS-4 suite green (the chain stays
  valid through the lifecycle).

### T4 — Support SLA + financial-integrity wrap (week 3)
- Support contract doc (severities, targets, escalation, incident → `/v1/status`
  linkage); severity parser; financial-record retention policy aligned with the
  audit chain + Stripe records; SOC2 observation-clock entry noting metering and
  billing controls are **operational**.
- **Exit:** severity/response targets hash-pinned in the contract twin + parser
  tests; retention assertions (financial audit rows are never pruned by the
  normal retention job); SOC2 clock entry recorded; WS-3/WS-4/WS-5 green.

### T5 — Exit evidence + full regression (week 3–4)
- **Exit:** full suite green (WS-3 + WS-4 + WS-5 + WS-6); a CI job runs the
  metering reconciliation + webhook idempotency suites; cross-reference pass
  (WS-5 rule 9) over units/prices/trial/severity across the doc set; both new
  and prior contract twins self-hash; `data/ws1/g1_decision.json` reverted after
  the run; WS-6 DONE logged in `docs/WS6_PROGRESS.md`. G2's "first 14-day trials
  active" and G3's "first paid contracts live" are **runtime** exits WS-6 makes
  reachable — they accrue when real tenants board, and are claimed only then.

---

## 5. Rules & discipline (applies to all tasks)

1. **No breaking change to WS-3/WS-4/WS-5.** Metering is read-only aggregation;
   the request contract, audit chain, and rate-limit behavior are unchanged —
   their suites stay green after every change.
2. **Single source of truth.** Units, prices, trial policy, severities, and
   response targets appear once — in `data/ws6/billing_metering_contract.json` —
   and a test reconciles every consumer (billing code, checklist, parser, docs)
   against it.
3. **Financial integrity.** Metering reconciles **exactly** to the WS-4 audit
   chain and **within tolerance** to the WS-5 structured access logs — **never
   to the ephemeral Redis limiters** (a control, not a ledger). Drift is an
   **S1 incident, not a silent correction**; un-metered service **suspends the
   tenant's keys** rather than bleeding compute for free. Stripe is the system
   of record for money; usage syncs **daily** (`run_ws6_stripe_sync.py`);
   webhooks are idempotent; 5xx/503/429 are never billed; no invented usage;
   no card data on our servers, ever.
4. **Honest claims.** G1 stays UNDER-POWERED; billing sells service/compute/
   access, never validated alpha. Support response targets are operational
   commitments, distinct from the conditional 99.9 % offer (WS-5 window).
   "Trial active" / "paid contract live" are claimed only when real.
5. **Audited lifecycle.** Every onboarding/trial/billing transition writes an
   audit row into the WS-4 chain. A compliance story with no chain rows is a
   config file, not a control.
6. **Test-mode discipline.** No live Stripe keys in tests or CI; webhooks are
   mocked with valid signatures; signature failures are rejections.
7. **Evidence-driven exit.** Each task's exit is a test or a rehearsal; "the
   config looks right" is never an exit.
8. **Cross-reference pass before any "final".** Every number used in more than
   one place (prices, trial length, tolerance, targets) is reconciled inside and
   across the doc set before a doc is labeled final.

---

## 6. Roadmap

Build weeks are measured **from T0 approval**. Critical path: T1 metering → T2
Stripe → T3 trials (trial automation is the G2 clause). T4 can overlap T2/T3.
T5 is the consolidation pass.

| Week | Deliverable | Exit evidence |
|---|---|---|
| 0 | T0 gate + contract freeze | ✅ DONE (2026-08-15): verdict APPROVED-CONDITIONAL; twin hash-pinned |
| 1 | T1 metering | ✅ DONE: chain-exact + log-tolerance reconciliation tests; S1/suspension on drift; never-billed tests |
| 1–2 | T2 Stripe billing | ✅ DONE: idempotency + tier-mismatch + no-card-field tests |
| 2–3 | T3 onboarding + trials | ✅ DONE: trial lifecycle + one-trial-per-org tests; audit rows per step |
| 3 | T4 support SLA + retention | ✅ DONE: severity parser tests; retention assertions; SOC2 clock entry |
| 3–4 | T5 exit evidence | ✅ DONE (2026-08-15): full suite green; CI job; cross-ref pass; g1 reverted |

**Position in the phased roadmap:** WS-6 is the Phase-3 (Enterprise Hardening)
workstream per `docs/PRODUCTION_BLUEPRINT.md` §5, and it is the last build
workstream before WS-7 (GTM). Estimated: **3–4 weeks** to a fully green WS-6
with a billable, onboardable API. G2's trial clause and G3's first-paid-contract
clause then accrue as runtime facts — WS-6 ships the machinery and the honest
claim language, never the number itself.


