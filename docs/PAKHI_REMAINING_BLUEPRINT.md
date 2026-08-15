# PAKHI: REMAINING BLUEPRINT & ULTIMATE ROADMAP

**From "all workstreams executed" → industry-standard DaaS with a defensible,
honest track record.**

*Document Status:* ROADMAP — planning
*Version:* 1.0
*Author:* TripleS Studio
*Date:* 2026-08-15
*Prereqs:* [BLUEPRINT.md](./BLUEPRINT.md) (product/commercial), [PRODUCTION_BLUEPRINT.md](./PRODUCTION_BLUEPRINT.md) (DaaS plan), WS-1…WS-6 progress logs (all executed)

---

## 1. WHERE WE ARE (GROUND TRUTH, 2026-08-15)

Everything engineering-shaped is **executed**: WS-0…WS-6 complete, **1944 tests
green / 10 skipped**, ruff clean, CI workflows live (`.github/workflows/*`),
deploy units present (`docker-compose.yml`, `deploy/nginx`, `deploy/observability`,
`deploy/ws2-orchestrate.*`), every contract twin self-hash verified.

The remaining gap is **not engineering**. It is the honest-observation loop and
the go-to-market loop. Current state of each:

| Item | State (evidence) |
|---|---|
| G1 alpha validation | **UNDER-POWERED**: N = 7 OOS event-trades < N_min = 8 (`data/ws1/g1_decision.json`). No alpha claim is allowed. |
| G2 live signals + trials | **ZERO_TRADES**: harness built (`scripts/run_ws2_t3_orchestrate.py`, `data/ws2/paper.db`), but ledger is **empty** (0 events, 0 signals, 2 cycles ingested); `ws2-orchestrate.timer` **inactive** on this host. |
| G3 uptime + contracts | SLO measurement window **OPEN 2026-08-14 → 2026-09-13** (WS-5 T6); 99.9 % not yet demonstrated; zero paid contracts. |
| SOC2 | Controls operational and **being observed** (clock running since 2026-08-14); Type I / Type II not started. |
| WS-7 Distribution & GTM | Not started. |
| Legal | Counsel **not engaged**; TOS / adviser-CTA positioning / data-licensing un-reviewed. |
| Housekeeping | No baseline commit; runbooks/restore drills exist (WS-5) but not exercised on a schedule. |

## 2. THE DOCTRINE (UNCHANGED)

From `PRODUCTION_BLUEPRINT.md` §3, restated so this roadmap cannot drift from
it:

1. **Alpha first.** G1 is the go/no-go. The first enterprise meeting is won or
   lost on "do you have a real, cost-adjusted, out-of-sample track record?" —
   no API polish answers that.
2. **The backtest is the product until proven otherwise.** Build no durable
   infra on top of unvalidated alpha.
3. **Wedge is chosen by network access** (named founder decision), so a G1
   pivot reads as *"this market is efficient / entry timing wrong"*, never
   *"the engineering failed."*
4. **Observation is pre-registered and append-only.** The WS-1 evaluation
   contract, WS-2 paper-trading protocol, and WS-5 SLO window are hash-pinned;
   the paper ledger is append-only. Any change-control voids/needs
   re-validation of the ledger.
5. **Honesty is the brand.** No synthetic number is a performance claim
   (`BLUEPRINT.md` §5.1). Every served value carries provenance
   (`{model_version, forecast_cycle, publication_ts}`).

## 3. REMAINING GATES (AND WHAT EACH NEEDS)

| Gate | Current | Exit criterion | What closes it |
|---|---|---|---|
| **G1** | UNDER-POWERED (N=7 < 8) | Cost-adjusted OOS Sharpe > 1.0 at N ≥ ~30 with CI — **or documented pivot** | Live paper harness accumulates event-trades; G1 re-run at N ≥ 8 (interim verdicts), full verdict at N ≥ ~30 |
| **G2** | ZERO_TRADES | Live API serving real signals ≥ 30 days; **first 14-day trials active** | Harness running on schedule; signals persisted + served; ≥ 1 real trial tenant onboarded via WS-6 automation |
| **G3** | Window open | 99.9 % uptime / 30 days; **1–2 paid enterprise contracts**; SOC2 controls operational and observed | Window closes 2026-09-13 → first SLO accounting; WS-6 billing goes from test-mode to live subscribers |
| **G4** | Not started | Multi-instrument; **SOC2 Type I**; repeatable sales motion | Add ag/cat-bond signals (each must clear G1-style validation); Type I snapshot; documented sales playbook |
| **G5** | Not started | **SOC2 Type II**; enterprise (Tier 3) live; churn < 2 % | ≥ 3–6 months of observed controls after Type I; dedicated-instance offering |

## 4. REMAINING WORKSTREAMS

### WS-1R — G1 accumulation (live OJ paper harness) — *the critical path*
- **What exists:** `scripts/run_ws2_t1_ingest.py` (12Z GFS backfill, live), `run_ws2_t2_compute.py`, `run_ws2_t3_orchestrate.py`, `data/ws2/paper.db` (schema: forecast_cycles / signals / paper_ledger), pre-registered protocol (frozen θ_p, 2-session hold, ≤ 1 trade/episode, `data/ws2/paper_trading_protocol.json`).
- **What remains:** (a) **activate** the orchestrator (`ws2-orchestrate.timer` is inactive); (b) prove the loop appends: cycle → signal → ledger row, daily; (c) monitor event accumulation toward N ≥ 8; (d) run the G1 re-run script (`scripts/run_t6_g1_report.py` path) at the pre-registered thresholds; (e) record interim + final verdicts in `docs/WS1_G1_REPORT.md` (updates on data, one-shot rule honored).
- **Exit:** N ≥ 8 with a statistical verdict, or a documented pivot to cat-bond / reinsurance / pure-data analytics (pre-registered in the G1 decision + WS-1 blueprint §4 T6).

### WS-7 — Distribution & GTM (runs in parallel)
- Warm-intro pipeline for the wedge (alumni, trading forums, energy conferences) — wedge chosen by network access.
- Publish the real backtest (provenance-disclosed) **only after G1 verdict**; live paper-trading performance tracked publicly (Sharpe, max-DD, BSS vs ECMWF/GFS).
- Case-study package: reproducible repo, data provenance, methodology.
- Pricing/sales collateral tested against the product thesis (§2.4 of PRODUCTION_BLUEPRINT): *"The open-source core is the proof. The product is that we run it reliably, on schedule, with provenance and SLAs."*

### WS-8 — Legal & compliance readiness (before first sale)
- Engage counsel on: adviser/CTA registration exposure, TOS disclaimers of suitability, downstream-loss liability, data-licensing compliance for commercial feeds (free-tier sources today: NOAA/ERA5/Open-Meteo/CME settlements).
- Finalize the "weather intelligence provider, not trade recommendation" framing.
- Privacy policy + GDPR/CCPA posture (Phase E hardening).

### WS-9 — SOC2 program (staged)
- Controls already operational and observed (clock 2026-08-14). Remaining: policy documents (access control, change management, incident response, backups) → **Type I readiness** (Phase D exit) → external Type I → Type II after a genuine observation window (Phase E).

### WS-10 — Ops housekeeping (baseline integrity)
- Commit the WS-1…WS-6 artifact baseline (single trusted revision).
- Make DR drills + restore (`scripts/run_ws5_backup.py`, `run_ws5_restore_drill.py`) a **scheduled** event, not a one-shot.
- Runbook for the daily sync (`ws6-stripe-sync`) + staleness alert response.
- Keep `data/ws1/g1_decision.json` reverted-untouched discipline after every run.

## 5. THE ULTIMATE ROADMAP (PHASES A–E)

> Entry/exit evidence per phase. Nothing below invents a claim that hasn't
> accrued; every phase exits on **recorded observation**, not on intent.

### Phase A — Close G1 (Days 0–30)
**Goal:** a statistical verdict on OJ alpha, or an explicit pivot.
- [ ] Activate `ws2-orchestrate.timer`; verify daily cycle → signal → ledger append.
- [ ] Backfill ongoing as-published GFS cycles into `data/ws2/ingested/`.
- [ ] Monitor N growth; run the pre-registered G1 re-run at N ≥ 8.
- [ ] Parallel: engage legal counsel (WS-8); draft warm-intro list (WS-7); baseline commit (WS-10).
- **Exit:** G1 verdict on live+historical ledger (net-of-benchmark Sharpe, CI, p-value) **or** documented pivot. **This gates all spend on the productized API.**

### Phase B — Live proof + first trials (Days 30–60)
**Goal:** the API serves real, current signals; real tenants are onboarded.
- [ ] Signal stream persisted + served (`/v1/signals/{instrument}`, WS `/stream/signals`); data-freshness surfaced.
- [ ] Public status page live (component-level health + incidents — the WS-4/WS-6 incident feed feeds it).
- [ ] Publish first honest paper-trading results (provenance-disclosed).
- [ ] Onboard first real tenant through WS-6 automation: provision → API key → 14-day trial (runtime exits G2/G3 accrue here).
- **Exit:** **G2** — live API ≥ 30 days, first trial(s) active.

### Phase C — Reliability + first revenue (Days 60–120)
**Goal:** numbers a second meeting survives.
- [ ] SLO window closes 2026-09-13 → record the first 30-day 99.9 % accounting (WS-5 SLO ledger).
- [ ] WS-6 billing exits test-mode: **first 1–2 paid contracts live** on daily Stripe sync.
- [ ] SOC2 Type I readiness (policies, gap remediation).
- **Exit:** **G3** — uptime recorded, paid contracts live, SOC2 controls observed.

### Phase D — Scale & expand (Months 4–8)
**Goal:** widen the moat; institutionalize.
- [ ] Add instruments (ag futures; cat-bond / reinsurance exceedance curves) — **each clears G1-style validation first**.
- [ ] Deep-learning models only after OOS skill over ECMWF/GFS baselines.
- [ ] Dedicated single-tenant instances (Tier 3).
- [ ] **SOC2 Type I** completed.
- **Exit:** **G4** — multi-instrument, Type I, repeatable sales motion (churn tracked).

### Phase E — Certification & institutionalization (Months 8–18)
**Goal:** close the compliance loop.
- [ ] SOC2 **Type II** after a genuine ≥ 3-month observation window.
- [ ] GDPR/CCPA posture finalized; data-licensing compliance documented.
- [ ] Enterprise tier with SLAs; churn < 2 %.
- **Exit:** **G5** — Type II, industry-standard posture.

## 6. ULTIMATE ACCEPTANCE CHECKLIST (track quarterly)

Cross-walk of `PRODUCTION_BLUEPRINT.md` §6 ("industry-standard done") with the
runtime items this roadmap adds:

- [ ] Public REST API + OpenAPI + changelog; WS streams with reconnect/replay
- [ ] First-party `pakhi-client` SDK with examples
- [ ] Status page with component health + incident history
- [ ] Every output carries `{model_version, data_source, forecast_cycle, publication_ts}`
- [ ] As-published backtests only; no-lookahead guardrail asserted in CI
- [ ] 99.9 % uptime (30-day windows, recorded); signal latency ≤ 60 s; staleness alerting
- [ ] Metered billing live (Stripe), tiered plans, invoicing; trial automation exercised by real tenants
- [ ] SOC2 Type I then Type II with genuine observation; GDPR/CCPA posture; counsel-reviewed TOS
- [ ] **G1-cleared or pivoted**: a published, provenance-disclosed track record (or an honest pivot story)
- [ ] First reference customer + published case study
- [ ] Baseline committed; DR drills scheduled; daily sync alert-tested

## 7. RISKS & MITIGATIONS (REMAINING)

| Risk | Likelihood | Mitigation |
|---|---|---|
| No OJ alpha (rare events, N grows slowly) | High | Pre-registered G1 sample rule (N ≥ 8 interim, ~30 + CI full); multi-year history; pivot path to cat-bond/reinsurance (more forgiving) or pure data/analytics — decided at G1, not improvised |
| Ledger/observation drift (tuning on live data) | Medium | Append-only hash-pinned protocol; re-estimation forbidden until N ≥ 8 re-run under the locked estimator; any amendment voids and re-validates the ledger |
| Harness not running (empty ledger) | High | **Phase A task #1**; timer active + daily append asserted in CI/alerting |
| Solo-founder load (eng + sales + legal + SOC2) | High | Defer Type II to Phase E; managed services; consider part-time contractor at Phase C; WS-7 warm-intro driven, not spray-and-pray |
| Compliance cost before revenue | Medium | Type I only after G3 revenue; counsel engaged early but scoped to a fixed deliverable |
| First contract's billing path breaks | Low–Med | WS-6 sync already runs nightly in CI with staleness alerting; exercised with the first real subscriber (test-mode → live) |

## 8. IMMEDIATE 30-DAY ACTION PLAN

| Day | Action | Owner |
|---|---|---|
| 0–2 | Baseline commit (WS-10); activate `ws2-orchestrate.timer`; assert daily paper-ledger append | Eng |
| 0–7 | Engage counsel — fixed-scope: TOS + adviser/CTA positioning + data-licensing (WS-8) | Founder |
| 3–14 | Warm-intro list for the wedge market; first outreach drafts (WS-7) | Founder |
| 7–30 | Verify ingest → compute → signal → ledger daily; monitor N; draft G1 re-run at N ≥ 8 | Eng |
| 14–30 | Public status page; publish methodology page; prepare the provenance-disclosed backtest asset (hold until G1 verdict) | Eng + Founder |
| 30 | **G1 checkpoint**: verdict or pivot | Founder |

---

*This document is planning, not evidence. No statement here is a performance
claim; every exit criterion above is a recorded observation. G1 remains
UNDER-POWERED until the pre-registered re-run says otherwise.*
