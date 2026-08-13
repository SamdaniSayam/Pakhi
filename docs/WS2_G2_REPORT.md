# WS-2 T4 — G2 Handoff: G1 Re-run on the Live Paper Ledger

Status: generated from the live paper ledger by the exact WS-1 significance
engine (no new machinery, no re-tuning). Machine twin: `data/ws2/g2_decision.json` (payload sha256 `5e52d2742a49`).

## Decision

- **Outcome:** ZERO_TRADES
- **Statement:** architecture success: live harness running, no scored events yet
- **Reason:** architecture success: fast, rigorous disproof -> documented pivot

## Headline (net-of-benchmark event-trade Sharpe, live scored events)

- **N scored events:** 0 (N_min = 8)
- **Power class:** no trades
- **Mean net-of-benchmark:** +0.0000%
- **Event Sharpe:** 0.000 (95% CI 0.000, 0.000)
- **Classic t / Newey-West t:** 0.000 / 0.000 (lag 0)
- **Bootstrap p (edge > 0):** 1.000

## Live ledger state

- **Scored events:** 0
- **Total ledger rows:** 0
- **Window:** 2026-08-12 00:00:00 → now (span 0.00 y)
- **rbar recomputed at re-run:** +0.2405% (source: locked_ws1_oos_fallback)

## G1 predecessor

- **G1 outcome:** UNDER_POWERED (N = 7) — 
  `data/ws1/g1_decision.json`

## G2 scope (infrastructure gate only)

- **G2 proves:** an autonomous, no-lookahead, provenance-complete signal store
  feeding the paper ledger — **not** a cleared G1.
- **WS-3 API build is gated** on the G1 re-run verdict (or an explicit,
  user-made infra-first decision).
