# PAKHI: DaaS PRODUCTION BLUEPRINT & ROADMAP

**From polished library → market-ready, industry-standard Data-as-a-Service**

*Document Status:* PRODUCTION PLAN
*Version:* 1.0
*Author:* TripleS Studio
*Prereq:* [BLUEPRINT.md](./BLUEPRINT.md) (product & commercial strategy)

---

## 1. READINESS ASSESSMENT

### 1.1 Verdict

**Pakhi is not yet a DaaS product. It is a world-class open-source library and CLI — the Community Edition engine.**

This is not bad news. The engineering core (data connectors, feature engineering, ML models, signal engine, risk/backtest, trading) is the deepest and hardest 50% of a weather-quant platform, and it is real, tested, and CI-green. What is missing is the *productized service layer* (API, auth, billing, operations, compliance) and — most critically — *proof of real-world value* (validated, cost-adjusted alpha on real data).

### 1.2 What Already Exists (real, tested)

| Area | Evidence |
|---|---|
| Data connectors | NOAA GFS, ERA5, Open-Meteo, satellite, Meteostat, CME, Yahoo — with auto-failover logic |
| As-published archive | `pakhi/src/noaa.py:GFSConnector.archive()` — fetches historical GFS runs exactly as published per date × cycle |
| Feature engineering | temporal (JIT via `triples-sigfast`), teleconnection, climate indices, spatial, anomaly, satellite |
| Models | persistence, climatology, XGBoost/LightGBM, LSTM, Gaussian Process, BMA/stacking ensembles |
| Prediction | deterministic, multi-step, probabilistic, verification (BSS/CRPS) |
| Signals | freeze, heat, hurricane, drought, wind-power, ensemble |
| Risk | `BacktestEngine` with `walk_forward`, `commission_bps`, `slippage_bps`, Sharpe/max-DD/win-rate/profit-factor |
| Trading | instruments (11), execution, PnL, portfolio |
| Scheduling | `RefreshScheduler` (in-process) |
| Quality | 1462 passed / 5 skipped; 99.63% line coverage (re-verified `coverage.xml`, commit `386350f`); all model modules 98.8–100% covered; ruff clean; CI green on 3.10–3.13 for commits `86b3d80`/`37d9f68`/`386350f` |

**Scope of this evidence (important caveat):** these tests validate that code paths *execute* and that deterministic math is *correct* — e.g., exact known-value checks (`RMSE == √(2/3)` on a hand-computed case, `bias == 2.0`, `MAPE == 7.5`, `ACC ≈ 1.0` on learnable synthetic data, `ACC == 0.0` on the degenerate case), and that models fit and reproduce training data (`RMSE ≈ 0`). This is behavioral, not just instantiation. **But line coverage does not establish that any forecast is *market-useful*.** A model that trains and never generalizes — or a signal that is pure noise on real data — passes every line-coverage gate. That is precisely the gap G0/G1 exist to close, and why §3 sequences alpha validation ahead of all infrastructure spend.

### 1.3 What Is Missing (the DaaS gap)

1. **No public API** — no REST server, no WebSocket push, no OpenAPI spec, no SDK.
2. **No auth/security** — no API-key management, no JWT/RBAC, no rate limiting, no multi-tenancy, no audit logs.
3. **No commercial proof** — zero real-world, cost-adjusted, out-of-sample backtests; all published numbers are synthetic architecture-validation only.
4. **No production data operations** — no deployed 6-hourly ingestion jobs, no data-availability monitoring, no failover runbooks.
5. **No serving layer** — signals are computed in-process and discarded; nothing is persisted or served.
6. **No observability** — no metrics, structured logs, tracing, dashboards, SLOs, or alerting.
7. **No billing/metering** — no subscriptions, usage metering, or invoicing.
8. **No compliance** — no SOC2 controls, no TOS, no privacy policy, no data-provenance audit trail surfaced to clients.
9. **No docs/onboarding** — no API docs, quickstarts, or client libraries for the product.

### 1.4 Readiness Scorecard (industry-standard bar)

| Dimension | Now | Target | Gap |
|---|---|---|---|
| Engine & algorithms | 9/10 | 10/10 | small |
| Backtest integrity | 6/10 | 10/10 | as-published data pipeline end-to-end |
| Real-world alpha proof | 0/10 | 10/10 | **the critical gap** |
| Public API & SDK | 0/10 | 10/10 | full build |
| Auth/security/tenancy | 0/10 | 10/10 | full build |
| Data ops & scheduling | 2/10 | 9/10 | orchestration, monitoring, failover |
| Observability & SLOs | 0/10 | 9/10 | full build |
| Billing & commercial ops | 0/10 | 9/10 | full build |
| Compliance (SOC2, TOS) | 0/10 | 8/10 | staged |
| Docs & onboarding | 2/10 | 9/10 | full build |

---

## 2. TARGET ARCHITECTURE (DaaS)

### 2.1 Principle: Precompute, then Serve Fast

Weather data arrives on a known cadence (GFS 00/06/12/18Z). **Signals and forecasts are computed on that schedule and stored — never computed per-request.** The API is a fast read layer over precomputed, versioned results. This is how serious weather-data vendors (DTN, WeatherSource) operate, and it makes latency and cost predictable.

```text
                       ┌─────────────────────────────┐
                       │  INGESTION WORKER (cron)    │
                       │  GFS/ERA5/OpenMeteo/...     │
                       │  auto-failover, validation, │
                       │  schema checks, provenance  │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  COMPUTE WORKER (on publish)│
                       │  features → models (vX.Y.Z) │
                       │  → signals (freeze/power/   │
                       │    hurricane/disagreement)  │
                       └──────────────┬──────────────┘
                                      ▼
            ┌──────────────────────────────────────────┐
            │  DATA STORE                                │
            │  Object store: raw GRIB/NetCDF             │
            │  TimescaleDB/PostgreSQL: signals, metrics  │
            │  Model registry: versions + lineage        │
            └────────────────────┬─────────────────────┘
                                 │ (fast reads)
        ┌────────────────────────┴─────────────────────────┐
        │  API GATEWAY (FastAPI)                             │
        │  REST: /v1/forecasts /v1/signals /v1/backtests    │
        │  WebSocket: live signal streams                    │
        │  Auth: API keys + JWT, RBAC, rate limits, audit    │
        │  Metering: usage → billing                          │
        └────────────────────────┬─────────────────────────┘
                                 ▼
                     ┌──────────────────────────┐
                     │  CLIENTS                  │
                     │  SDK (pakhi-client)       │
                     │  Hedge funds / energy desks│
                     └──────────────────────────┘
```

### 2.2 Backtest-as-a-Service (heavy compute path)

Long-running portfolio simulations must not block the API. Use a job queue:

```text
POST /v1/backtests  →  job_id (202 Accepted)
job_id status polling → /v1/backtests/{id}
Worker (Prefect/Celery) runs BacktestEngine over GFSConnector.archive()
Results stored with full provenance (forecast runs used, costs, model versions)
```

### 2.3 Key Design Decisions

1. **Batch precompute + read-only API** — signals are not computed on request.
2. **Provenance on everything** — every served value carries `{model_version, forecast_cycle, publication_ts, algorithm}`. This is the trust contract (§6).
3. **As-published discipline everywhere** — backtests read `GFSConnector.archive()` only; ERA5 is training-ground-truth only.
4. **Stateless API, stateful workers** — API scales horizontally; workers own the schedule.
5. **Postgres/TimescaleDB for signals, object store for raw data, DuckDB/Parquet for backtest staging.**
6. **Async API (FastAPI) with sync compute in workers** — the existing engine is sync/DataFrame-based; don't rewrite it, isolate it in workers.

### 2.4 The Product Thesis (open-core) — write this down explicitly

The Community Edition — including `pakhi.signals.freeze` and its exact thresholds — is already public on GitHub. Anyone can run Pakhi today. So the DaaS pitch cannot be *"use Pakhi"*; the thesis must be:

> **"The open-source core is the proof. The product is that we run it reliably, on schedule, with provenance and SLAs — so you don't have to."**

Every sales artifact, status page, and pricing page should be tested against that sentence. It is what the first sales call actually hinges on: reliability, freshness, provenance, and operational guarantees over code that a client could theoretically run themselves but shouldn't.

---

## 3. THE SEQUENCING DECISION: ALPHA FIRST

**The single most important decision in this roadmap: prove real-world value before building the service layer.**

Rationale:
- Building a SOC2-compliant multi-tenant API on top of unvalidated alpha is a 6–12 month investment with a 50%+ chance of being wasted.
- The first enterprise meeting will be won or lost on one question: *"Do you have a real, cost-adjusted, out-of-sample track record?"* No API polish answers that.
- A validated signal (even on one instrument) turns every subsequent engineering hour into de-risked work.

**Wedge selection is a founder-led-sales decision, and it is named as such.** The wedge instrument is chosen by *network access* (who can you get a meeting with) rather than by where an edge is statistically most likely to exist. That is a defensible call for a solo founder, but it must be named now so that a G1 pivot reads correctly: a pivot on the chosen wedge means *"this market is already efficient / the entry timing is wrong"* — **not** *"the engineering failed."* Do not let the two narratives blur when the gate arrives; the engineering quality is measured by G0 (infrastructure), the market edge by G1 (alpha).

**Decision Gate G1 (end of Phase 1):** If no real instrument shows cost-adjusted, out-of-sample edge above noise after Phase 1, **pivot the product** (reinsure/cat-bond analytics are more forgiving than hedge-fund alpha; or sell as pure data/analytics rather than signals) rather than continuing to build infra.

**Gate numbering (fixed, matches §5/§7):**
- **G0 (end of Phase 0, week 4):** infrastructure readiness — the real-data point-in-time pipeline runs and the first walk-forward backtest reproduces honestly (it may refute the synthetic numbers; G0 is not a pivot decision).
- **G1 (end of Phase 1, week 12):** the actual go/no-go — cost-adjusted out-of-sample Sharpe > 1.0 at adequate sample size, or documented pivot.

G0 asks *"does the test infrastructure work?"* G1 asks *"is there real alpha?"* They are different questions and must not be conflated — the highest-stakes call in the roadmap is G1, and it happens at week 12, not week 4.

---

## 4. WORKSTREAMS

### WS-0 — Real-Data Foundation (2–4 weeks)
- Acquire real historical **as-published** GFS archive for the wedge instrument (via `GFSConnector.archive()`; backfill from NOMADS/NCEI; consider ERA5 for training only).
- Acquire historical **market data** for the wedge (OJ_FUTURES / NG_FUTURES / ERCOT or CME HDD/CDD) — free/cheap sources: CME settlement data, NREL, ISO RTM archives (ERCOT publishes historical DAM prices).
- **Build continuous contracts with roll adjustment.** OJ, NG, and ERCOT futures expire and roll; a naive splice of front-month prices has phantom jumps at roll dates that are unrelated to the signal and can inflate or wreck a Sharpe ratio. Build back- (ratio-) adjusted continuous series *before* any price feature is computed, and record the roll rule (date, adjustment type, ratio/back-adjustment) per contract in the dataset provenance.
- **Track data vintage, not just timestamps.** Weather archives get reprocessed and revised after original publication. An archived GFS run fetched today for a past cycle is not automatically bit-for-bit what was available in real time — the classic "vintage" lookahead bug that survives a timestamp-only check. Use the **operational (as-published) archive** for backtests, record the archive version/publication state per cycle, and treat any reanalysis-derived field (ERA5) as training-ground-truth only. Where a true as-published backfill is unavailable for part of the history, mark the vintage explicitly and exclude it from the test window rather than silently mixing.
- Build the **point-in-time aligned dataset**: for each trading day, the forecast run published *before* the market decision, and the realized outcome — joined to the roll-adjusted continuous contract.
- Automate re-generation: a script that rebuilds the dataset from raw sources (so results are reproducible).

### WS-1 — As-Published Backtest Platform (2–4 weeks)
- Extend `BacktestEngine` to accept point-in-time aligned feature frames from WS-0 (it already supports `commission_bps`/`slippage_bps` and `walk_forward`).
- Add **provenance logging**: every trade records `forecast_cycle_id`, `publication_ts`, `model_version`, `costs`, and the **contract roll state** (which contract month, adjustment factor).
- Add **no-lookahead guardrails**, in two layers:
  - *Timestamp layer:* no feature at time *t* references data published after the decision cutoff.
  - *Vintage layer:* assert the forecast run was fetched from the as-published archive and carry its archive-version hash through the feature frame; fail the backtest if any feature's vintage predates its own timestamp.
- Add **roll-jump assertion**: no continuous-price move at a roll date larger than X× the daily σ unless driven by a modeled event — catches accidental roll mis-adjustment rather than trading it.
- **Statistical significance, not point estimates.** Define the G1 sample-size rule now: a Sharpe ratio from a handful of trades is a coin flip. Require a minimum trade count (e.g., ≥ 30 signal-triggered trades) *and* a confidence interval (bootstrap or Sharpe t-statistic) around the estimate before G1 counts it. For rare events (e.g., Florida freeze), this means using multi-year history or explicitly shrinking the edge claim — a Sharpe > 1.0 on 4 trades and on 40 trades must not trigger the same decision.
- Reproduce the full backtest for the wedge instrument: train on `[train_window]`, walk-forward test on `[test_window]`, with costs.

### WS-2 — Signal Service (batch precompute + store) (3–4 weeks)
- Extract signal computation (`pakhi.signals.*`, ensemble disagreement) into a **compute worker** runnable on a schedule.
- Persist outputs to Postgres/TimescaleDB with full provenance.
- Build the **ingestion worker**: connectors + auto-failover + data-validation (schema, completeness, staleness) + alerting.
- Orchestration: start with a simple deployed scheduler (systemd/cron on one VM, or GitHub Actions with a runner); graduate to Prefect when multi-step DAGs appear.
- A **pipeline must never return an empty DataFrame** — failover and explicit error states, per the commercial blueprint.

### WS-3 — Public API (REST + WebSocket) (4–6 weeks)
- **FastAPI** service (async) exposing:
  - `GET /v1/health`, `GET /v1/status` (uptime, last data cycle, data freshness)
  - `GET /v1/instruments`, `GET /v1/signals/{instrument}` (latest + history)
  - `GET /v1/forecasts/{instrument}?lead=7d`
  - `POST /v1/backtests` + `GET /v1/backtests/{id}` (job queue)
  - `GET /v1/ensemble/disagreement`
  - `WS /v1/stream/signals` — push on each new model cycle
- **OpenAPI/Swagger** docs autogenerated; versioned (`/v1`); rate-limit headers.
- **SDK**: `pakhi-client` Python package wrapping the API (thin, typed, documented).
- Deployment: single Docker image (extend existing `Dockerfile`), managed VM or ECS/Fly.io.

### WS-4 — Auth, Security, Compliance (weeks 4–8 parallel, SOC2 controls at Phase 3+)
- **API keys** (hashed at rest) for machine clients + **JWT + RBAC** for human tenants.
- **Rate limiting** per key/tier (token bucket).
- **Multi-tenancy**: tenant-scoped rows in the store (tenant_id on every table); tenant isolation tests.
- **Secrets management** (env-injected via the platform; never in repo).
- **Audit logs** (who accessed what signal when) — SOC2 control requirement.
- **TOS + privacy + data-licensing** — engage counsel before first commercial contract.
- **SOC2 — timeline is the constraint.** Type II requires controls to have *operated under observation* for a minimum window before certification: **3 months minimum, 6 months recommended, 12 months typical**; a first-time Type II (readiness + gap remediation + observation) commonly totals **9–15 months**. Therefore:
  - Start the **controls program at the beginning of Phase 3 (week 16)**, not the middle — document policies (access control, change management, incident response, backups) immediately.
  - **Phase 4 exit = SOC2 Type I** (point-in-time snapshot; no observation window required).
  - **SOC2 Type II lands in Phase 5 (months 12–18)**, after the observation window has genuinely elapsed. Any sales collateral must claim "SOC2 Type I, Type II in progress" until then — claiming Type II early is a credibility and legal liability.

### WS-5 — Reliability, Observability, SLAs (weeks 6–10)
- **Metrics**: Prometheus (request latency, error rate, data-cycle freshness, ingestion lag, signal compute time).
- **Dashboards**: Grafana — API health, data pipeline health, model skill tracking.
- **Alerting**: on ingestion failure, staleness, API error-rate breach, model-drift (live BSS vs baseline).
- **Structured logs** + request IDs; centralized log sink.
- **SLOs**: API 99.9% uptime; signal within 60s of run publication; data staleness < 1 cycle. Error budget policy.
- **Status page** (public) — a weather vendor without a status page is not credible.
- **Backups/DR**: DB snapshots, object-store replication, restore drills.

### WS-6 — Billing, Metering, Ops (weeks 10–14)
- **Usage metering** per API key (requests, instrument feeds, backtest-hours).
- **Billing**: Stripe subscriptions tied to metering (Tier 2/3 from the commercial blueprint).
- **Onboarding**: provision keys, tenant onboarding checklist, 14-day trial automation.
- **Support SLA**: ticket triage, severity levels, response-time commitments.

### WS-7 — Distribution & GTM (runs parallel, weeks 4–18)
- **Warm-intro pipeline** for the wedge market (alumni, conferences, quant forums) — the wedge is chosen by who you can meet.
- **Publish the real backtest** (provenance-disclosed) once WS-1 clears G1 — this is the marketing asset.
- **Live paper trading** with public performance tracking (Sharpe, max-DD, BSS vs baseline).
- **Case-study package**: reproducible repo, data provenance, methodology — the technical resume.

---

## 5. PHASED ROADMAP (ZERO TO MARKET)

### Phase 0 — Foundation & Decision (Weeks 1–4)
**Goal:** first real point-in-time dataset + first honest backtest.
- [ ] WS-0: wedge instrument chosen (network access = decision input)
- [ ] WS-0: real as-published GFS archive backfilled; real market prices acquired
- [ ] WS-1: point-in-time alignment + no-lookahead guardrails implemented
- [ ] WS-1: walk-forward backtest with `commission_bps=5`, `slippage_bps=10`
- **Exit:** a reproducible, provenance-logged backtest on real data. **G0 decision.**

### Phase 1 — Alpha Validation & Proof (Weeks 4–12)
**Goal:** prove edge or pivot. Build nothing durable yet.
- [ ] Iterate features/models on wedge instrument; walk-forward only
- [ ] Ensemble disagreement index implemented and evaluated
- [ ] CME HDD/CDD signal evaluated as alternate wedge
- [ ] Live paper-trading harness (60 days of live-published signals, tracked with costs)
- [ ] Publish honest results (or honest pivot) — the marketing asset
- **Exit:** cost-adjusted out-of-sample Sharpe > 1.0 **at adequate sample size (≥ ~30 trades + CI)** — or explicit, documented pivot.

### Phase 2 — Productized Core API (Weeks 8–16)
**Goal:** a credible single-tenant live API for trial customers.
- [ ] WS-2: ingestion + compute workers deployed on schedule; data persisted
- [ ] WS-3: FastAPI REST core (forecasts, signals, status); OpenAPI docs
- [ ] WS-4 (min): API keys, per-key rate limits, TLS, secrets
- [ ] WS-5 (min): basic metrics + alerts + structured logs
- [ ] Dockerize service; deploy to one managed host; CI/CD for the service
- [ ] `pakhi-client` SDK for trial users
- **Exit:** live API serving real, up-to-date signals with documented data freshness.

### Phase 3 — Enterprise Hardening (Weeks 16–32)
**Goal:** industry-standard reliability, security, tenancy, billing.
- [ ] WS-3: WebSocket live streams; backtest-as-a-service job queue
- [ ] WS-4: RBAC + multi-tenancy + audit logs + **SOC2 controls program starts at the beginning of this phase** (policies, access control, change management, incident response — operational from week 16 so the observation window starts counting)
- [ ] WS-5: Prometheus/Grafana, SLOs, status page, DR drills
- [ ] WS-6: metering + Stripe billing + trial automation + support SLA
- [ ] Load/soak tests; API contract tests; canary deploys
- **Exit:** 99.9% uptime over 30 days; first 1–2 paid enterprise contracts live; SOC2 controls operational and being observed.

### Phase 4 — Scale & Expansion (Months 8–12)
**Goal:** widen moat and expand instruments.
- [ ] Ag/cat-bond signal coverage (Soybeans, Corn, Wheat, CAT bonds)
- [ ] Deep-learning models (Transformer/GNN) **only after** out-of-sample skill over baselines
- [ ] Dedicated single-tenant instances (Tier 3)
- [ ] **SOC2 Type I report completed** (point-in-time snapshot; observation window for Type II continues through this phase)
- [ ] Scale: auto-scaling API, multi-region if latency demands
- **Exit:** multi-instrument platform, SOC2 Type I (Type II observation window running), repeatable sales motion.

### Phase 5 — Certification & Institutionalization (Months 12–18)
**Goal:** close the compliance loop and institutionalize operations.
- [ ] **SOC2 Type II** completed after the observation window has genuinely elapsed (≥ 3 months of operated controls, 6 recommended — first-time Type II typically runs 9–15 months end-to-end)
- [ ] Public compliance page + status page; SOC2 badge in sales collateral
- [ ] GDPR/CCPA posture finalized; data-licensing compliance documented
- [ ] Enterprise tier (Tier 3) with dedicated instances and custom models
- **Exit:** SOC2 Type II; industry-standard compliance posture; churn < 2%.

---

## 6. INDUSTRY-STANDARD "DONE" CHECKLIST

A weather-data vendor at industry standard demonstrates all of the following. Track against this quarterly.

**Product**
- [ ] Public REST API, versioned, with OpenAPI spec and changelog
- [ ] WebSocket live streams with reconnect/replay semantics
- [ ] First-party SDK (`pakhi-client`) with examples and docs
- [ ] Status page with component-level health and incident history

**Data & Provenance**
- [ ] Every output carries `{model_version, data_source, forecast_cycle, publication_ts}`
- [ ] As-published backtests only; no-lookahead guardrail is automated and asserted in CI
- [ ] Data-freshness surfaced to clients (last update, staleness)
- [ ] Public methodology + reproducibility for all published results

**Reliability & SLOs**
- [ ] 99.9% API uptime (99.99% year-1 target)
- [ ] Signal latency ≤ 60s from run publication
- [ ] Data staleness < 1 cycle with alerting
- [ ] Documented SLOs + error-budget policy + SLA credits

**Security & Compliance**
- [ ] AuthN/AuthZ (API keys hashed, JWT+RBAC), TLS everywhere
- [ ] Rate limiting per tier; audit logs; secrets management
- [ ] SOC2 Type I (Phase 4) → Type II (months 12–18) with genuine observation window; GDPR/CCPA posture; data-licensing compliance
- [ ] Incident response runbook; backup/restore drills

**Business Operations**
- [ ] Metered billing (Stripe), tiered plans, invoicing
- [ ] 14-day trial automation; onboarding docs; support SLA
- [ ] Terms of service reviewed by counsel (adviser/CTA positioning per BLUEPRINT.md)

**Proof of Value**
- [ ] Live paper-trading track record, cost-adjusted, provenance-disclosed
- [ ] BSS/CRPS vs ECMWF/GFS baseline reported continuously
- [ ] First reference customer (can be a trial) with published case study

---

## 7. KPIs & DECISION GATES

| Gate | When | Criteria |
|---|---|---|
| **G0** | End of Phase 0 | Real-data walk-forward backtest reproduces (or refutes) synthetic results — infrastructure readiness, *not* a pivot decision |
| **G1** | End of Phase 1 | Cost-adjusted out-of-sample Sharpe > 1.0 **at adequate sample size (≥ ~30 trades + confidence interval)** on wedge instrument, OR documented pivot |
| **G2** | End of Phase 2 | Live API serving real signals ≥ 30 days, first 14-day trials active |
| **G3** | End of Phase 3 | 99.9% uptime/30 days; 1–2 paid enterprise contracts; SOC2 controls operational and being observed |
| **G4** | End of Phase 4 | Multi-instrument; SOC2 Type I completed, Type II observation running; repeatable sales motion; churn < 2% |
| **G5** | End of Phase 5 (m 12–18) | SOC2 Type II completed after genuine observation window; enterprise tier live |

## 8. RISKS & MITIGATIONS

| Risk | Likelihood | Mitigation |
|---|---|---|
| No real alpha on first wedge | High | G0/G1 gates; pivot to cat-bond/reinsurance analytics (more forgiving) or pure data/analytics |
| Data licensing costs for market data | Medium | Start with free/official sources (CME settlements, ERCOT archives, NREL); license later |
| Scope creep (satellite, ag, all instruments) | High | Single wedge until G3; every instrument must clear G1-style validation |
| Solo-founder load (eng + sales + legal) | High | Defer SOC2 Type II to Phase 5 (m 12–18); use managed services; consider a technical co-founder or part-time contractor at Phase 3 |
| Lookahead-bias skepticism from quants | Medium | Provenance + two-layer no-lookahead assertion (timestamp *and* vintage) in CI + roll-adjusted contracts + disclosed methodology; the "as-published" story is our credibility |
| API latency expectations | Medium | Precompute architecture makes reads sub-second by design |
| Futures roll artifacts corrupt backtests | Medium | Continuous back-/ratio-adjusted contracts in WS-0; roll-jump assertion in WS-1 |
| Rare-event signals too few trades to trust Sharpe | High | G1 sample-size rule (≥ ~30 trades + CI); multi-year history for freeze-type events; shrink edge claims otherwise |

## 9. IMMEDIATE 30-DAY ACTION PLAN

1. **Week 1:** Choose the wedge instrument (based on data availability AND network access). 
2. **Week 1–2:** Backfill as-published GFS archive + market prices; build the point-in-time aligned dataset script (WS-0).
3. **Week 2–3:** Wire point-in-time frames into `BacktestEngine` with costs; add no-lookahead assertions (WS-1).
4. **Week 3–4:** Run the first real walk-forward backtest. Record every trade with provenance.
5. **Week 4:** Decision Gate **G0** — confirm the point-in-time pipeline runs and the first real backtest is reproducible (honest result, whatever it says). This is *not* the pivot decision; **G1** at week 12 is.
6. **Weeks 5–12:** iterate features/models on the wedge instrument; grow the as-published backtest. 
7. **Week 12:** Decision Gate **G1** — cost-adjusted out-of-sample Sharpe > 1.0 at adequate sample size, or documented pivot.

**Do not build the API before G1. The backtest is the product until proven otherwise.**
