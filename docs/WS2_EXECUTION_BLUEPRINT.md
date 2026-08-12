# WS-2 — Signal Service (batch precompute + store): Execution Blueprint

Status: **REVISED 2026-08-12 (post-review, v1.1) — awaiting user approval**
Progress: tracked in `docs/WS2_PROGRESS.md` (created after this blueprint is approved)
Scope source: `docs/PRODUCTION_BLUEPRINT.md` §4 WS-2
Gate: G2 (end of Phase 2 / week 16) — *infrastructure proof, not an edge claim*

---

## 0. Honest premise (what WS-2 is actually for)

WS-1 G1 is recorded **UNDER-POWERED** (N = 7 OOS event-trades < N_min = 8,
`docs/WS1_G1_REPORT.md`). That verdict authorizes **exactly one** Phase 2
mandate: the **60-day live paper-trading harness on OJ** to accumulate
event-trades to N ≥ 8 and re-run G1. There is no validated edge yet — so the
"publish the backtest" marketing asset, the public API, and durable
infrastructure are **premature** until the paper ledger reaches a verdict.

Therefore WS-2's purpose is the smallest rigorous system that runs that harness:

> A scheduled ingest→compute→store loop on the **locked D-12Z GFS cycle** that
> runs **ColdGrip with a frozen θ_p**, records **live OJ closes** for fills /
> outcomes / benchmark, appends rows to a **paper event ledger in the exact
> WS-1 ledger semantics**, re-runs the **same** armor gates live, and feeds the
> G1 re-run at N ≥ 8 — alerting on every failure, never silently dropping data.

**Explicitly deferred** (per WS-1 G1 report §4, unchanged) until the G1 re-run
verdict: ensemble disagreement, NG, CME HDD/CDD, WS-3 API build, TimescaleDB at
scale, multi-tenancy. **G2 does not clear G1.**

---

## 1. Purpose

Transition Pakhi from a just-in-time, in-process research tool to a **scheduled,
stateful, and resilient batch-compute loop**. Weather arrives on a known cadence
(GFS); signals must be precomputed on that exact schedule and persisted with full
provenance so the 60-day paper ledger accumulates automatically and the future
API layer (WS-3, *post-verdict*) only performs fast reads.

Success = an automated ingestion+compute loop, running on schedule, persisting to
a structured store with strict failure handling (never an empty DataFrame) and
zero lookahead / vintage / roll-jump leakage — *live*, not just in backtest.

## 2. Readiness audit (verified 2026-08-12)

| Layer | Status | Evidence |
|---|---|---|
| WS-1 Harness | ✅ Complete | G1 recorded UNDER-POWERED (N=7, CI (−1.02, +2.11), NW t −0.59); 60-day paper mandate is the only Phase 2 scope |
| Wedge Signal | ✅ Hardened | `ColdGrip` pre-registered, one-shot, 1 free param, ≤1 trade/episode, 2-session hold (`docs/T4_CANDIDATE_REGISTRATION.md`) |
| GFS Connector | ✅ Hardened | `GFSConnector.archive()` byte-range S3 extraction; NOMADS→AWS failover proven in WS-0 |
| OJ Market Data | ⚠️ Gap | Backtest reads the static archive; the live harness needs **daily close ingestion** (fills, outcomes, benchmark) |
| Live θ_p rule | ⚠️ Gap | θ_p was fold-estimated in WS-1; a live rule must be **frozen and pre-registered** (see T0) |
| Storage Layer | ⚠️ Missing | No Postgres/TimescaleDB instance running yet (T0: provision TimescaleDB) |
| Worker Orchestrator | ⚠️ Missing | systemd/cron or GitHub Actions runner |

## 3. Architecture & Data Model

**The Precompute Principle:** no weather model is run and no signal is evaluated
during an API request. Workers do the heavy lifting.

1. **Ingestion Worker (cron):** wakes after the locked **12Z** cycle publish
   (~15:35Z), fetches the cycle (NOMADS→AWS `noaa-gfs-bdp-pds` failover) **and
   the latest OJ daily close**. Validates schema, spatial completeness, and
   staleness. Binds the vintage hash of the raw bytes.
2. **Armor Gates (live, identical to WS-1 §9):** timestamp (publication ≤ the
   14:00 America/New_York decision cutoff of the fill session), vintage (fetched
   bytes hash matches the as-published archive), roll-jump (X = 5σ at roll
   dates). Any violation ⇒ **`RejectCycleError`** + alert; the cycle is never
   persisted and never enters the ledger.
3. **Compute Worker (on ingestion success):** runs ColdGrip with the **frozen
   θ_p** (T0). A stored-vs-offline equivalence gate must pass (the DB row equals
   `pakhi/ws1/candidate.py` output on the same cycle) or the worker halts.
4. **Database (Postgres; TimescaleDB optional at Phase-3 scale):** stores
   `forecast_cycles`, `signals`, and the **paper event ledger** with strict
   `{model_version, forecast_cycle_id, publication_ts, archive_source}` provenance
   — columns identical to `t4_candidate_ledger.csv` so `significance_report`
   consumes it unmodified.

## 4. Tasks, sequencing, exit criteria

### T0 — Live paper-trading protocol pre-registration (contract twin of WS-1 T0)
Before **any** live event is recorded:
- Write `docs/WS2_PAPER_TRADING_PROTOCOL.md` + machine twin
  `data/ws2/paper_trading_protocol.json` (hash-pinned), mirroring the WS-1
  evaluation-contract discipline.
- Lock, in writing: live θ_p (**frozen** at the G1 estimate — single value
  computed from the historical PIT frame with `date ≤` G1 date; re-estimation
  only at the N≥8 G1 re-run and only under the same estimator); fill semantics
  (next trading-session close on/after the cycle date; never prior close); cost
  (30 bps round trip); benchmark (live always-long OJ 2-session, rbar
  recomputed at re-run on the accumulated window with the WS-1 formula);
  event counting (≤1 trade/episode, 2-session hold, net = gross − 0.0030 − rbar);
  change control (any amendment requires a new version + re-lock; accumulated
  ledger void unless re-validated).
- **Exit:** protocol + machine JSON approved and hash-pinned; artifacts exist.

### T1 — Ingestion worker: weather (12Z) + OJ market data (week 1)
- Standalone `ingest-cycle` CLI: pull the locked 12Z cycle (failover NOMADS →
  AWS), pull the OJ daily close, validate schema / spatial completeness /
  staleness, pin the vintage hash of the raw bytes.
- Run the three armor gates; a violation raises an explicit exception
  (`RejectCycleError`, `DataStalenessError`, `UpstreamMissingError`) that
  triggers an alert — the cycle is **never** persisted and **never** fills a
  paper trade. The pipeline must **never return an empty DataFrame**.
- **Exit:** CLI reliably downloads + validates a cycle and an OJ close, writing
  raw artifacts with pinned hashes; a deliberately stale/missing cycle fails
  loudly (tested).

### T2 — Compute worker & paper-ledger persistence (week 2)
- Extract ColdGrip into a worker reading the **frozen θ_p** (T0). Equivalence
  gate: on the same cycle, stored output == offline `pakhi/ws1/candidate.py`
  output (halt on mismatch).
- Bulk-write with `ON CONFLICT` UPSERTs: `forecast_cycles`, `signals`, and the
  paper **event ledger** (entry cycle, fill/exit sessions, gross, net,
  net_of_benchmark, provenance) in the `t4_candidate_ledger.csv` shape.
- Known-value DB round-trip test: insert→read reproduces WS-1's locked numbers
  exactly (provenance, costs, net-of-benchmark).
- **Exit:** worker computes the signal and appends a provenance-complete ledger
  row; stored-vs-offline gate and known-value round-trip both pass.

### T3 — Orchestration & failover (week 3, *parallel* with the 60-day clock)
- The 60-day accumulation clock **starts at the end of T2**, not after T3 — the
  ledger must be collecting events while hardening happens around it.
- Simple scheduler (systemd timer or GitHub Actions runner) triggers
  ingest→compute daily; alert (webhook/email) on ingestion failure, staleness
  > 1 cycle, or compute crash; structured logs to one sink.
- 48-hour autonomy run is a **milestone** here (Prefect graduation deferred —
  the DAG is single-chain).
- **Exit:** pipeline has run autonomously ≥ 48 h while the paper ledger has
  accumulated from the T2 start.

### T4 — G1 re-run & G2 handoff (week 4)
- When the paper ledger reaches **N ≥ 8**: re-run the **exact**
  `pakhi.ws1.significance.significance_report` on the live ledger → verdict
  PASS / FAIL→PIVOT / UNDER-POWERED. If N < 8 after 60 days, record the honest
  UNDER-POWERED (events arrive only at the rate of real freezes; this is a data
  fact, not a defect).
- **G2 = infrastructure gate only:** an autonomous, no-lookahead,
  provenance-complete signal store feeding the paper ledger. It does **not**
  clear G1. WS-3 API build is gated on the G1 re-run verdict (or an explicit,
  user-made infra-first decision).
- **Exit:** G1 re-run report produced from the live ledger (self-hash-pinned),
  and G2 infrastructure proof documented.

## 5. Rules & Discipline (applies to all tasks)

1. **Never return an empty DataFrame.** Network failures or data gaps throw
   explicit exceptions (`DataStalenessError`, `UpstreamMissingError`,
   `RejectCycleError`) that trigger alerts, never silent drops.
2. **Provenance on everything.** Every row carries vintage hash, fetch date,
   model version, forecast cycle id, publication ts, archive source.
3. **Armor is live, not schema-only.** The timestamp / vintage / roll-jump gates
   run on every ingested cycle; a violation rejects the cycle, halts the worker,
   and alerts — mirroring WS-1 INVALID-run semantics.
4. **θ_p is frozen.** No live re-estimation from the accumulating dataset —
   that would be tuning-lookahead. Re-estimation only at the N≥8 G1 re-run,
   under the pre-registered estimator.
5. **Stateless API prep.** Workers handle all state; the DB is the single source
   of truth.

## 6. Timeline

| Week | Focus | Deliverable |
|---|---|---|
| 1 | T0 + T1 | Live protocol locked (hash-pinned) + 12Z weather/OJ ingestion with live armor |
| 2 | T2 | Compute worker → paper ledger; stored-vs-offline + known-value gates green; **60-day clock starts** |
| 3 | T3 | Orchestration + alerting + 48h autonomy (parallel with accumulation) |
| 4 | T4 | G1 re-run on live ledger + G2 infrastructure proof |

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Live θ_p leakage** (re-estimating from growing data = tuning-lookahead) | θ_p frozen in T0 protocol; only the G1 re-run may re-estimate, under the locked estimator |
| **Scarce events** (N≥8 may not arrive in 60 days) | G1 stays UNDER-POWERED; honest report, not a stretched claim; no threshold lowering |
| NOAA delays cycle publication | Poll with exponential backoff; alert on staleness > 1 cycle; **skip the cycle, never fill a paper trade late** |
| Market-data gap (no OJ close) | OJ ingestion is mandatory in T1; missing close ⇒ cycle skipped + alert, never a fabricated fill |
| Lookahead in live fills | Next-close fill + timestamp gate (publication ≤ 14:00 NY cutoff) on every cycle |
| DB write contention | UPSERTs (`ON CONFLICT`); TimescaleDB only if volume later justifies it |
| Pipeline silent failure | Empty-DataFrame ban + armor reject + alerting webhooks |

## 8. Handoff to WS-3

WS-2 delivers a populated, autonomously updating store plus the paper event
ledger that decides G1. **WS-3 (FastAPI fast-read layer) is gated on the G1
re-run verdict** — an API serving a signal with no proven edge is premature.
Only on PASS (or an explicit infra-first decision) does WS-3 proceed.

## 9. Progress tracking

Per working agreement: after this blueprint is approved, all execution progress
is tracked in **`docs/WS2_PROGRESS.md`**, updated at each step with terminal
evidence.
