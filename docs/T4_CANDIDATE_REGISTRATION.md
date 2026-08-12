# WS-1 T4 — Candidate Signal Pre-Registration: "ColdGrip"

**Status:** REGISTERED in writing **before** any OOS fold is scored (Evaluation
Contract v1.1 §4, §10 — one-shot evaluation; no re-tuning after seeing OOS
results). Machine twin: `data/ws1/t4_candidate.json`. Registered 2026-08-12.

---

## 1. Why a redefinition

G0 refuted the pre-committed baseline `FreezeSignal(entry=0.6)`: `freeze_prob`
never reaches 0.6 (archive max **0.2182**, 55 of 1612 PIT rows flag a freeze),
so the baseline produces **0 trades** and its Spearman vs. 1-session returns is
negative (−0.062). The threshold is structurally unreachable, not the event:
the model *does* flag genuine sub-zero freeze events (16 episodes, 13 OOS), it
just never scores them at 0.6.

T4 therefore redefines the *bar* the model must clear, re-estimated **inside**
each walk-forward fold from train-window data only, with ≤ 3 free parameters
and ≤ 1 trade per episode (contract §4).

## 2. Rule family (fixed, pre-registered)

A PIT row fires iff:

    freeze_prob ≥ θ_p   AND   temperature_min ≤ θ_t

- **θ_t = 0.0 °C** — *fixed*, the physical definition of a freeze. Not
  estimated; it is the temperature gate from contract §4's example list and it
  simply asserts the forecast event is genuinely sub-zero (the archive emits
  `freeze_prob > 0` only under a sub-zero `temperature_min`).
- **θ_p = median of `freeze_prob` over the fold's train-window freeze rows**
  (rows with `date ≤ fold_train_end` and `freeze_prob > 0`). The **only free
  parameter**, re-estimated at each fold boundary (expanding window, contract
  §2). Rationale: the median is the most defensible single-number summary of
  the model's *typical* freeze call — it replaces the dead 0.6 bar with "a
  freeze reading at least as strong as the model usually produces in the
  already-seen data", and it is a pure function of train data.
- **≤ 1 trade per episode:** the **first** firing row of each episode is the
  entry (contract §4.3); later firing rows of the same episode are ignored.
- **Hold: 2 trading sessions** (entry session close → 2nd next trading close) —
  *locked* by contract §5, not a free parameter.

**Free parameters:** 1 (θ_p) + θ_t fixed physical ⇒ **≤ 3** ✓.

## 3. Estimation procedure (walk-forward, no leakage)

For each test fold `k` (test window per contract §2):

1. Train window = all PIT rows with `date ≤` the previous fold's train end
   (seed window for fold 1; expanding thereafter).
2. Train freeze rows = train rows with `freeze_prob > 0`.
3. `θ_p = median(train freeze rows' freeze_prob)`; `θ_t = 0.0`.
4. Apply the gates to fold-`k` test rows only; mark first-firing-row-per-episode
   entries; hold 2 sessions.
5. If a fold's train window has **no** freeze rows, θ_p is undefined ⇒ the fold
   fires nothing (no evidence) — documented, never a fabricated threshold.

No `ojd_*`/`fwd*` outcome column is read anywhere during estimation or firing;
the gates are pure functions of `freeze_prob` and `temperature_min`.

## 4. What this does NOT do (anti-gaming)

- No parameter search over the full window.
- No metric feedback: the rule family, θ_t and the θ_p estimator (median over
  train freeze rows) are fixed here; the OOS result is produced once.
- The candidate does **not** read `ojd_close`/`fwd*` during definition; trade
  construction and costs remain fully locked (§5: gross =
  `close[fill+2]/close[fill] − 1`, net = gross − 30 bps, net-of-benchmark vs.
  the always-long +0.2405 % mean).

## 5. Roll-jump safety (contract §9.3, X = 5)

Reuses the WS-0 machinery (`pakhi/ws0/roll.py`):

- `back_adjust(..., n_sigma=5.0)` measures the continuous-price gap **at each
  roll date**; a gap ≥ 1 + 5σ (or ≤ 1/(1+5σ)) that is left unadjusted is a
  roll artifact the signal could exploit. Any such flagged roll date that is
  **not co-located** (± 3 trading sessions) with a modeled freeze episode
  ⇒ **halt** (`RollJumpError`; run INVALID, §9).
- `roll_jump_assertion(...)` additionally reports the stricter ±3-day
  near-roll net (extreme moves near roll dates) with per-move weather-co-location
  flags, so an unexplained giant move near a roll is visible in the report even
  when it sits outside the traded path.

The 2023-11-02 OJ crash (−7.5 %, 5.73σ, one session after the 2023-11-01 FND
roll) is a **real** market move in the back-adjusted series, not a roll gap:
`back_adjust` flags **0** of 34 roll gaps on the real archive, and no candidate
trade enters/exits near it — the gate therefore passes and the move is reported
as context.

## 6. Exit criterion

*A new signal generator capable of firing trades under OOS constraints without
exploiting roll gaps.* — "ColdGrip" fires when the model's freeze call reaches
the train-typical level under a physically sub-zero temperature, ≤ 1 trade per
episode, holds the locked 2 sessions, and the roll-jump gate aborts any run
whose traded path touches an unadjusted roll artifact.
