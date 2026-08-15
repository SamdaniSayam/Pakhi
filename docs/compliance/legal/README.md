# Legal drafts — cover memo (for counsel)

**Status:** review-draft. **Not legal advice. Not a binding offer.**
These documents are drafted in-tree for counsel review; their shipping is a
WS-4 deliverable ("drafted and sent"). Counsel sign-off is an external
dependency and is **not** on the WS-4 calendar.

This memo + the three drafts below are what is sent to counsel. Each draft is
marked at the top with its status and the specific questions counsel should
answer. The business facts the drafts are anchored to:

- Pakhi is a research/data API exposing precomputed, published-dataset-derived
  signals and a backtesting job API. Signals derive from NOAA GFS forecast data
  (publicly available), precomputed on a fixed daily cycle, and archived with
  full provenance (`archive_source`, `model_version`, `publication_ts`).
- Tenants hold API keys (machine lane) or short-lived tokens (human lane);
  per-tenant isolation is enforced and audited (WS-4).
- No user PII is required to use the API; keys and tokens are credentials, and
  the system stores only hashes of keys and revoked-token digests.
- The ledger/status claims are infrastructure-integrity claims (cycle complete /
  current / degraded), never investment advice.

**Sent-to-counsel flag:** recorded in `../WS4_PROGRESS.md` (the T5 entry) with
the date; counsel's reply updates that record. The SOC2 observation clock for
the operational controls program is separate and started in the same entry.

- `terms-of-service-draft.md` — the API terms of service.
- `privacy-policy-draft.md` — the data-handling/privacy notice.
- `data-licensing-draft.md` — how tenants may use the data and what Pakhi may
  use back.
