# WS-2 Progress Tracker — Signal Service (batch precompute + store)

Per working agreement: every execution step is logged here with terminal evidence,
and the user is shown the running terminal live.

- Blueprint: `docs/WS2_EXECUTION_BLUEPRINT.md` (**REVISED post-review v1.1**,
  awaiting user approval 2026-08-12; approved to proceed to T0)
- Gate: G2 (end of Phase 2 / week 16) — **infrastructure proof, not an edge claim**
- Started: 2026-08-12

---

## Log

### 2026-08-12 — T0 Live Paper-Trading Protocol LOCKED (pre-registered, hash-pinned)
- **Why:** G1 is UNDER-POWERED (N=7 < N_min=8); the only G1-authorized mandate is
  the 60-day live OJ paper-trading harness to grow N to 8 and re-run G1. WS-2 T0
  pre-commits every rule that will decide that re-run **before any live event is
  recorded** — the WS-2 twin of the WS-1 evaluation contract.
- **Frozen live θ_p:** **0.036364** — *derived*, never hand-typed, via the WS-1
  estimator (`estimate_thresholds`) over the historical PIT rows with
  `freeze_prob > 0` and `date ≤` G1 date (2026-08-12): **55 freeze rows**, median
  `0.03636363636363636`. θ_t = 0.0 °C fixed physical gate. No live re-estimation
  (re-estimation only at the N≥8 G1 re-run, under the same estimator, frozen in a
  new protocol version).
- **Locked rules (identical to WS-1):** next-close fill (never prior close),
  D-12Z signal cycle (pub ~15:35Z ≤ 14:00 NY cutoff ⇒ same-day fill), hold 2
  sessions, 30 bps round trip, net = gross − 0.0030 − rbar, ≤1 trade/episode,
  5-session embargo, N_min=8, §8 decision rules; live armor = timestamp +
  vintage + roll-jump, violation ⇒ `RejectCycleError` (cycle never persisted,
  never fills a paper trade, alert raised).
- **Live rbar:** recomputed at the G1 re-run on the accumulated window with the
  WS-1 formula (backtest OOS rbar = +0.2405 %).
- **New `pakhi/ws2/protocol.py`:** `frozen_theta_p`, `build_paper_trading_protocol`
  (self-hash-pinned payload mirroring `evaluation_contract.json`),
  `protocol_consistent`; predecessor facts read from the pinned
  `data/ws1/g1_decision.json`.
- **Runner** `scripts/run_ws2_t0_protocol.py` (CI entry, exit 0/1): derives θ_p,
  writes `data/ws2/paper_trading_protocol.json`, prints the locked summary.
- **Artifacts:** `docs/WS2_PAPER_TRADING_PROTOCOL.md` +
  `data/ws2/paper_trading_protocol.json` (payload sha256
  `d59a1f64756f000e4f9e5c93026fff629039cf30abb65f533e028dac21a08f84`).
- **Tests** `tests/test_ws2_protocol.py` (16): θ_p = median of the 55 historical
  freeze rows with `date <=` G1 (exact, and identical to the WS-1 candidate
  estimator); frozen value locked; payload `theta_p_n_historical_freeze_rows`
  consistent; self-hash pins (tamper breaks); payload sha256 deterministic;
  locked fill/cost/benchmark/N_min rules present; anti-gaming + change control;
  G1 predecessor reads the pinned decision record; machine JSON exists,
  self-consistent, and matches a fresh live build; human doc exists and embeds
  the payload hash; runner exits 0.
- **T0 finalised:** `theta_p_n_historical_freeze_rows` count tightened to
  `freeze_prob > 0 AND date <= G1` (matches the locked estimator wording;
  payload values byte-identical, pinned sha256 `d59a1f64…` unchanged — no
  re-lock needed); pre-registration committed to git (anti-gaming rule, WS-1
  §10 discipline).
- Full suite green: **1669 passed / 5 skipped**; ruff clean.

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Live Protocol Pre-Registration | **DONE** | θ_p frozen 0.036364 (median, 55 rows, date ≤ G1); next-close fill, 30 bps RT, net = gross −0.0030 − rbar, N_min=8; live armor (timestamp/vintage/roll-jump) ⇒ RejectCycleError; hash-pinned doc + machine JSON |
| T1 Ingestion Worker (12Z + OJ) | pending | weather + OJ close ingest, failover, live armor, never-empty-DataFrame |
| T2 Compute Worker & Ledger Persistence | pending | ColdGrip worker (frozen θ_p), stored-vs-offline gate, paper ledger in WS-1 shape, known-value round-trip |
| T3 Orchestration & Failover | pending | systemd/cron or GH Actions, alerting, 48h autonomy milestone; 60-day clock starts at T2 end |
| T4 G1 Re-run & G2 Handoff | pending | exact `significance_report` on live ledger at N≥8; G2 = infra proof only |

## Open items / risks

- **Event scarcity:** N≥8 may not be reached in 60 days — G1 stays
  UNDER-POWERED; honest report, never a stretched claim (protocol §5).
- **Live θ_p leakage** is the highest-risk failure: frozen at 0.036364 in T0; any
  live re-estimation invalidates the ledger (change control).
- **Late 12Z / missing OJ close:** cycle skipped + alerted, never a fabricated or
  back-filled paper trade (protocol §3).
- Storage (Postgres) + orchestration land in T1/T3; the 60-day accumulation clock
  starts at T2 end, not after T3 hardening.
