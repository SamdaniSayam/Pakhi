# WS-6 Support SLA (paid tiers only)

Locked in `data/ws6/billing_metering_contract.json` §7 — this doc is the
readable contract; the machine twin is the source of truth and the triage
parser reads only the twin.

## 1. Severities, meanings, response targets

| Severity | Meaning | Response target |
|---|---|---|
| S1 | Service down / data-integrity event | ≤ 4 h |
| S2 | Degraded or blocking bug | ≤ 12 h |
| S3 | Minor bug / question | ≤ 2 business days |

These are **operational commitments** (how fast we respond), distinct from the
conditional 99.9 % uptime offer — that offer's evidence is the WS-5 30-day
window (2026-08-14 → 2026-09-13), untouched by WS-6. Free tier gets no SLA.

## 2. Triage discipline (deterministic)

`pakhi/ws6/support.py::classify_severity` classifies a ticket using the
**locked keyword lists** in the twin, priority S1 → S2 → S3:

- **S1:** down, outage, unavailable, data integrity, corrupt, breach,
  suspended, incident
- **S2:** degraded, blocking, bug, error, slow, timeout, fail
- **S3:** question, minor, typo, docs, feature, request, how, why

First keyword hit wins; unmatched text defaults to S3. Pinned by
`tests/test_ws6_t4_support.py` against the twin (single source of truth).

## 3. Escalation matrix

- **S1:** page on-call immediately; S1 → incident feed on `/v1/status` + audit
  chain; invoicing blocked if metering-related (T1 `metering.s1` /
  `metering.suspend`).
- **S2:** respond within target; workaround when possible; escalate to S1 on
  data-integrity or extended outage.
- **S3:** respond within business days; batch with the next maintenance window.

## 4. Status-page linkage

An S1 is an incident. `_deep_status` (WS-5 `/v1/status`) surfaces a
`"incidents"` feed read **straight from the WS-4 audit chain** (`metering.s1`,
`metering.suspend`, `metering.block_invoice` rows) — the feed *is* the ledger
of truth, not a config file. The same S1 path (T1) writes the incident row into
the chain.

## 5. Financial record retention

Metering buckets, rollup rows, and billing transitions are **audit-chain rows**
and inherit the chain's append-only, never-pruned retention. Stripe is the
external system of record for charges (its retention governs the invoice copy);
our side keeps the metering + sync ledger. Asserted in
`tests/test_ws6_t4_support.py`: no production code path deletes from the
financial tables or the audit chain (the only deletes in the repo are backup /
ingest **file** pruning).

## 6. SOC2 observation clock

Metering, reconciliation, and billing controls are **operational** (T1–T3):
the observation clock running since 2026-08-14 (WS-4) now observes a live
metering + reconciliation + Stripe-sync control program with machine evidence,
not config files. Recorded in `docs/WS6_PROGRESS.md`.
