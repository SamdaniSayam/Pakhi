# WS-2 T0 — Live Paper-Trading Protocol: Pre-Registration

**Status:** LOCKED in writing **before any live event is recorded** (2026-08-12).
Machine twin: `data/ws2/paper_trading_protocol.json` (payload sha256
`d59a1f64…`). Scope source: `docs/WS2_EXECUTION_BLUEPRINT.md` §4 T0.

This is the WS-2 twin of the WS-1 evaluation contract
(`docs/WS1_EVALUATION_CONTRACT.md`): the rules that will later decide the **G1
re-run** on live paper-trading events are pre-committed and hash-pinned. Any
amendment requires a new version + re-lock; the accumulated paper ledger is
void unless re-validated (change control).

---

## 1. Why this exists (the honest premise)

WS-1 G1 is **UNDER-POWERED** (N = 7 OOS event-trades < N_min = 8,
`docs/WS1_G1_REPORT.md`). The only G1-authorized Phase 2 mandate is the
**60-day live OJ paper-trading harness** to accumulate event-trades to N ≥ 8
and re-run G1. Every number below is frozen here *before* the harness records
its first event, so the re-run verdict is non-gamable.

## 2. Signal (frozen, no live re-estimation)

A live PIT row fires iff:

    freeze_prob ≥ θ_p   AND   temperature_min ≤ θ_t

- **θ_p = 0.036364** (median of the **55** historical freeze rows with
  `freeze_prob > 0` and `date ≤` G1 date 2026-08-12). **Frozen single value.**
  Derived by the same estimator as the backtest
  (`pakhi.ws1.candidate.estimate_thresholds`), never hand-typed.
- **θ_t = 0.0 °C** — fixed physical freeze gate, not estimated.
- **≤ 1 trade per episode:** the **first** firing row is the entry.
- **Hold: 2 trading sessions** (entry session close → 2nd next trading close).
- **Re-estimation is forbidden on live data.** Re-estimating θ_p from the
  accumulating dataset would be exactly the tuning-lookahead WS-1 banned. The
  only permitted re-estimation is at the **N ≥ 8 G1 re-run**, under the same
  estimator, on the combined historical + live ledger — and the new value is
  frozen in a new protocol version.

## 3. Cycle & timing (decision-cutoff discipline)

- **Signal cycle: 12Z** (locked operational cycle). Publication ~15:35Z, i.e.
  **before** the ICE OJ decision cutoff (14:00 America/New_York) ⇒ same-day
  fill on trading days. 00/06/18Z are not ingested for the signal path
  (18Z publishes after the cutoff).
- **Fill:** the **first trading-session close on/after** the firing row's cycle
  date — never a prior-close fill (v1.1 rule). Weekend/holiday cycles fill at
  the next trading close.
- **Late cycle = skip, never backfill a fill:** a cycle published after the
  cutoff, or missing OJ close data, is rejected and alerted — it never enters
  the ledger.

## 4. Trade construction & costs (identical to WS-1 §5)

| Field | Locked value |
|---|---|
| Gross return | `close[fill+2]/close[fill] − 1` |
| Costs | 30 bps round trip (5 bps commission + 10 bps slippage × 2) |
| Net | `gross − 0.0030` |
| Benchmark | always-long OJ over the matched 2-session window |
| Net-of-benchmark | `gross − 0.0030 − rbar` |
| rbar (live) | recomputed at the G1 re-run on the accumulated window with the WS-1 formula (backtest OOS rbar = +0.2405 %) |

## 5. Event counting & the G1 re-run

- **Scored:** live OOS event-trades in the paper window, not embargoed
  (5-session embargo).
- **N_min = 8.** Decision rules identical to WS-1 §8: PASS (N ≥ 8 ∧
  Sharpe > 1.0 ∧ CI LB > 0) / FAIL→PIVOT / UNDER-POWERED (N < 8) / ZERO_TRADES.
- The re-run calls the **exact** `pakhi.ws1.significance.significance_report`
  on the live ledger (ledger columns identical to
  `data/ws1/t4_candidate_ledger.csv`).

## 6. Live armor (WS-1 §9 semantics, carried forward)

Every ingested cycle runs the three gates; any violation ⇒ **`RejectCycleError`**
— the cycle is never persisted and never fills a paper trade, and an alert is
raised:

1. **Timestamp:** `publication_ts ≤` the decision cutoff (14:00 NY) of the fill
   session.
2. **Vintage:** fetched bytes hash matches the as-published `noaa-gfs-bdp-pds`
   archive.
3. **Roll-jump:** roll-date move > 5× daily σ without a modeled freeze event
   ⇒ halt (`RollJumpError`).

## 7. Data integrity

- **Never an empty DataFrame** — failures throw
  `DataStalenessError` / `UpstreamMissingError` / `RejectCycleError`, never a
  silent drop.
- **Provenance on every row:** `model_version`, `forecast_cycle_id`,
  `publication_ts`, `archive_source`, `vintage_hash`, `fetch_date`.
- **Stored-vs-offline equivalence:** the stored ColdGrip output must equal
  `pakhi.ws1.candidate` output on the same cycle, or the worker halts.
- **DB:** Postgres (TimescaleDB only if Phase-3 volume justifies it).

## 8. G2 scope & deferred items

- **G2 = infrastructure proof only** (autonomous, no-lookahead,
  provenance-complete store feeding the ledger). It does **not** clear G1.
- **Deferred until the G1 re-run verdict:** ensemble disagreement, NG,
  CME HDD/CDD, WS-3 API build, TimescaleDB at scale, multi-tenancy.

## 9. Anti-gaming (pre-committed)

- Protocol locked in writing **before any live event** is recorded.
- θ_p frozen; **no live re-estimation** from the accumulating dataset.
- No metric feedback into tuning.
- One-shot evaluation per locked version.
- Pre-registration committed to git.
- Change control: any amendment ⇒ new version + re-lock; prior accumulated
  ledger void unless re-validated.

## 10. Exit criterion (T0)

*Protocol + machine JSON approved and hash-pinned; artifacts exist.* — Done:
`docs/WS2_PAPER_TRADING_PROTOCOL.md` + `data/ws2/paper_trading_protocol.json`
(payload sha256 `d59a1f64756f000e4f9e5c93026fff629039cf30abb65f533e028dac21a08f84`),
reproduced by `scripts/run_ws2_t0_protocol.py`.
