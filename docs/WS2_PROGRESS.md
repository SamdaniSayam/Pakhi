# WS-2 Progress Tracker — Signal Service (batch precompute + store)

Per working agreement: every execution step is logged here with terminal evidence,
and the user is shown the running terminal live.

- Blueprint: `docs/WS2_EXECUTION_BLUEPRINT.md` (**REVISED post-review v1.1**,
  awaiting user approval 2026-08-12; approved to proceed to T0)
- Gate: G2 (end of Phase 2 / week 16) — **infrastructure proof, not an edge claim**
- Started: 2026-08-12

---

## Log

### 2026-08-13 — Audit-hardened WS2 (ruff + 1708 tests + docker build green), pushed to main
- **Independent audit verified + fixed:** `recomputed_rbar` now computes the live-window
  benchmark from the OJ close series and records an honest `rbar_source` in the G2 record
  (`locked_ws1_oos_fallback` until the live window accumulates ≥3 realized sessions — the
  frozen +0.2405 % label never over-claims); `append_cycle_pin`/`_revert_pin` wrapped in an
  advisory file lock (manifest TOCTOU); webhook `status >= 400` dead branch documented.
- **Also fixed (shared code):** PaperTrader sizes by total equity (was remaining cash);
  harness cross-validation skips events without a 2-session hold (end-of-data guard);
  CI `ws2-daily` gained a Postgres 16 service container; junk backup/scratch dirs gitignored.
- Full suite **1708 passed / 5 skipped**; `ruff check` + `ruff format --check` clean;
  `docker build` green with `pakhi --version` / `pakhi status` verified in-container.

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
  `1ce98669f2c3997ce1d19a3fa0d9a709972d7df388f6f5e7f3e91aea48c2cd80`).
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
  payload values byte-identical, pinned sha256 `1ce98669…` unchanged — no
  re-lock needed); pre-registration committed to git (anti-gaming rule, WS-1
  §10 discipline).
- Full suite green: **1669 passed / 5 skipped**; ruff clean.

### 2026-08-13 — T1 Ingestion Worker COMPLETE (12Z + OJ, live armor)
- **New `pakhi/ws2/ingest.py`:** `ingest_cycle` pulls the locked 12Z cycle
  (NOMADS primary, `noaa-gfs-bdp-pds` AWS archive fallback) + the latest
  realized OJ close, validates schema / wedge completeness / staleness, pins
  the raw-byte content hash into `data/ws2/vintage_manifest.json`, and runs the
  **three live armor gates** (timestamp / vintage / roll-jump). Any violation ⇒
  `RejectCycleError` — the cycle is never persisted and never fills a paper
  trade.
- **Never an empty DataFrame:** `DataStalenessError` / `UpstreamMissingError` /
  `RejectCycleError` raise loudly; on failure the cycle's raw files + pin are
  reverted. Failover + staleness + offline paths tested.
- **Runner** `scripts/run_ws2_t1_ingest.py` (CI entry, exit 0/1) + `--dry-run`.
- **Tests** `tests/test_ws2_ingest.py` (13): staleness (old/future), missing
  upstream raises, schema/completeness rejection, empty-frame ban, failover,
  armor → RejectCycleError, OJ stale close, pin append + manifest revert,
  `ingest_cycle` persist/skip, never-empty.
- **Evidence:** full suite 1669 → 1691 passed; ruff clean.

### 2026-08-13 — T2 Compute Worker & Paper-Ledger Persistence COMPLETE
- **New `pakhi/ws2/compute.py`:** `evaluate_cycle` runs the **frozen** θ_p/θ_t
  from the hash-pinned T0 protocol payload plus a stored-vs-offline
  **equivalence gate** (DB verdict must equal `pakhi/ws1/candidate.fires` on
  the same cycle or the worker halts with `EquivalenceError`).
  `build_ledger_row` emits the locked WS-1 `t4_candidate_ledger.csv` shape
  (gross = `close[fill+2]/close[fill]−1`, net = gross − 0.0030,
  net_of_benchmark = gross − 0.0030 − rbar, contract roll, embargo/scored) —
  rejecting any firing event without a realized OJ close (never a fabricated
  fill). `compute_cycle` UPSERTs `forecast_cycles` provenance for every cycle
  and signal+ledger only on fire (dialect-aware `ON CONFLICT`, Postgres +
  SQLite).
- **Runner** `scripts/run_ws2_t2_compute.py` (exit 0/1, `--db`/`--dry-run`).
- **Tests** `tests/test_ws2_compute.py` (9): frozen thresholds match the locked
  payload hash; equivalence pass/fire; mismatch halts; **known-value DB
  round-trip** reproduces WS-1's locked 2026-01-14 row (gross 0.054895, net
  0.051895, nob 0.049490, Mar26 roll, provenance); UPSERT idempotency;
  no-fire upserts cycle-only; missing-session rejection; never-silent-drop.
- **Live smoke:** `data/ws2/paper.db` populated with `forecast_cycles` for
  ingested 20260810_12z / 20260812_12z (neither fired — real live freeze_probs
  < θ_p).
- **60-day accumulation clock starts at T2 end.**

### 2026-08-13 — T3 Orchestration & Failover COMPLETE
- **New `pakhi/ws2/alerts.py`:** best-effort, never-blocking alerting —
  console + JSONL file always-on, optional webhook (`PAKHI_ALERT_WEBHOOK_URL`)
  / SMTP email; `send_alert` never raises (a dead sink is logged, the pipeline
  continues). Alerts are loud: ingestion failure / staleness > 1 cycle / armor
  rejection / compute crash.
- **New `pakhi/ws2/orchestrate.py`:** the single-chain ingest→compute→store
  loop. `orchestrate_cycle` returns a terminal status in {ok, rejected
  (designed loud skip), failed} and appends a JSONL record to **one structured
  sink** (`data/ws2/logs/orchestrate.jsonl`). Stable `episode_id` allocation
  keeps UPSERT re-runs idempotent. `replay_cycles` drives the **identical**
  pipeline over cached GFS parquets offline (each cycle with its own
  `ref_time` so staleness is exercised honestly) into a **separate replay DB**
  — the live ledger that decides G1 is never polluted by backfilled
  infrastructure runs.
- **`ingest.py` offline mode** (`offline=True`): read cached parquets instead
  of the network; raw files are never deleted on failure (shared cache).
- **Scheduler wiring:** `deploy/ws2-orchestrate.{service,timer}` (systemd,
  daily 16:05Z) + `.github/workflows/ws2-daily.yml` (runner option).
- **Runner** `scripts/run_ws2_t3_orchestrate.py` (live + `--replay START END`).
- **Tests** `tests/test_ws2_orchestrate.py` (9): replay autonomy end-to-end
  (armor + equivalence + ledger), idempotent re-run, missing-cycle loud reject
  with cache preserved, compute-crash → CRITICAL alert, alert-never-raises,
  webhook no-url no-op, JSONL sink, scheduler units present.
- **48 h autonomy milestone (accelerated):** replayed **121** cached cycles
  (2025-12-01 → 2026-03-31) through the full ingest→compute→store path: **121
  ok / 0 rejected / 0 failed, 12 fired → 12 replay-ledger rows**, 0 silent
  drops, all alarms clean. Replay ledger reproduces WS-1's locked 2026-01-14
  row **exactly** (gross 0.054895 / net 0.051895 / nob 0.049490) —
  cross-validating the live pipeline against the WS-1 ledger. Real wall-clock
  accumulation continues in the live DB from the T2 start.

### 2026-08-13 — T4 G1 Re-run & G2 Handoff COMPLETE
- **New `pakhi/ws2/g2.py`:** `load_live_ledger` reads the DB back in the
  locked `t4_candidate_ledger.csv` column shape; the G1 re-run calls the
  **exact** `pakhi.ws1.significance.significance_report` on the live scored
  events (same N gate, Sharpe > 1, bootstrap CI lower bound, Newey-West).
  `build_g2_decision` derives (never hand-types) the outcome and emits a
  **self-hash-pinned** machine twin mirroring `pakhi.ws1.g1`, plus G1
  predecessor facts, live-window state, recomputed rbar (WS-1 formula on the
  accumulated window) and the WS-3 gating note. G2 = infrastructure proof
  only; it does not clear G1.
- **Runner** `scripts/run_ws2_t4_g2_report.py` → `data/ws2/g2_decision.json`
  (payload sha256 `10e262b5e34d…`) + `docs/WS2_G2_REPORT.md` (exit 0/1).
- **Tests** `tests/test_ws2_g2.py` (8): ledger shape == WS-1 CSV columns;
  self-hash determinism; honest ZERO_TRADES / UNDER_POWERED (N<8) / PASS (N≥8
  positive) / FAIL_PIVOT (negative) verdict paths; tamper breaks the pin; JSON
  artifact matches a fresh build.
- **Current live state:** 0 scored paper events (live window opened
  2026-08-12; the archive's OJ sessions end 2026-08-10) ⇒ honest **ZERO_TRADES
  / UNDER-POWERED-track** outcome; G1 re-run stays open until the 60-day window
  accumulates scored events. G1 re-run verified on the populated replay ledger
  (12 rows → correctly unscored pre-G1).

## Status board

| Task | Status | Notes |
|---|---|---|
| T0 Live Protocol Pre-Registration | **DONE** | θ_p frozen 0.036364 (median, 55 rows, date ≤ G1); next-close fill, 30 bps RT, net = gross −0.0030 − rbar, N_min=8; live armor (timestamp/vintage/roll-jump) ⇒ RejectCycleError; hash-pinned doc + machine JSON |
| T1 Ingestion Worker (12Z + OJ) | **DONE** | `ingest_cycle` + failover + staleness + live armor + never-empty; 13 tests; CLI exit 0/1 |
| T2 Compute Worker & Ledger Persistence | **DONE** | frozen-θ worker, stored-vs-offline gate, WS-1-shaped ledger, known-value round-trip; 9 tests |
| T3 Orchestration & Failover | **DONE** | single-chain loop, alerts (webhook/email/JSONL), one log sink, systemd/GH-Actions wiring, offline replay + 48 h autonomy harness (121 cycles, 0 silent drops); 9 tests |
| T4 G1 Re-run & G2 Handoff | **DONE** | exact `significance_report` on the live ledger; self-hash-pinned G2 record + report; 8 tests |

## Open items / risks

- **Event scarcity:** N≥8 may not be reached in 60 days — G1 stays
  UNDER-POWERED; honest report, never a stretched claim (protocol §5). Current
  live window has 0 scored events (opens 2026-08-12).
- **Live θ_p leakage** is the highest-risk failure: frozen at 0.036364 in T0; any
  live re-estimation invalidates the ledger (change control).
- **Late 12Z / missing OJ close:** cycle skipped + alerted, never a fabricated or
  back-filled paper trade (protocol §3).
- **Wall-clock accumulation** requires the live scheduler (systemd timer /
  GH Actions runner) to keep running daily after T2; the replay harness proves
  autonomy but is infra proof on a separate DB, not the live ledger.
