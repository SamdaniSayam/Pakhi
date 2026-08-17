# Pakhi Diagnosis Fixes — Changelog

**Date:** 2026-08-15
**Source audit:** Deep codebase scan (ws0–ws6, supporting modules, tests, contracts)
**Status:** DONE — full suite green (1949 passed, 5 skipped, 0 failures)

This file logs every fix applied from the diagnosis report, one entry per issue,
in the order worked. Each entry notes file:line, the bug, the fix, and the
test result for that area.

## Legend
- [HIGH] output/security/revenue corrupting
- [MED] correctness / isolation / reliability
- [LOW] robustness / docs

## Fix Log

| # | Area | Severity | Issue | Files | Tests |
|---|------|----------|-------|-------|-------|
| 1 | WS-2 signal/API | HIGH | RejectCycleError mapped to FAILED instead of REJECTED | `ws2/orchestrate.py:42,187,194,208` | 123 passed |
| 2 | WS-2 signal | MED | `significance_report` ignored `benchmark_mean` | `ws2/significance.py:206` | 123 passed |
| 3 | WS-2 API | MED | WS stream rejected DB-issued keys | `ws2/stream.py:18,35,44,49` | 123 passed |
| 4 | WS-2 client | MED | SDK did not forward `X-Pakhi-Key` on WS; no timeout/unwrap | `client/__init__.py` | 123 passed |
| 5 | WS-2 admin | MED | Cross-tenant read leak in admin surface | `api/routes/admin.py` (tenant scoping) | 123 passed |
| 6 | WS-2 compute | LOW | Episode id reused across runs | `scripts/run_ws2_t2_compute.py` | 123 passed |
| 7 | WS-6 billing | HIGH | Webhook event persisted before handler success | `ws6/stripe.py:307,333` | 53 passed |
| 8 | WS-6 metering | HIGH | Global session paired feed-hours to wrong tenant | `ws6/metering.py:101` | 53 passed |
| 9 | WS-6 billing | HIGH | Single usage record for full batch (metric blend) | `ws6/stripe.py:206` | 53 passed |
| 10 | WS-6 reconcile | MED | `chain==0 && log>0` not flagged EXTREME | `ws6/reconcile.py:60` | 53 passed |
| 11 | WS-6 metering | MED | Backtest-hours overlapping windows double-count | `ws6/metering.py:126` | 53 passed |
| 12 | WS-6 db | MED | Rollup upsert had no unique constraint | `ws6/db.py:33`, `ws6/metering.py:172` | 53 passed |
| 13 | WS-6 metering | MED | `never_billed` filter missing | `ws6/metering.py` | 53 passed |
| 14 | WS-6 billing | MED | No `.subscription.created` handler | `ws6/stripe.py` | 53 passed |
| 15 | WS-6 billing | MED | `is_sync_stale` alarmed on fresh activity | `ws6/stripe.py:289-300` | 53 passed |
| 16 | WS-6 billing | LOW | `.updated` used first item only | `ws6/stripe.py:344-346` | 53 passed |
| 17 | WS-6 support | LOW | SLA regex matched substrings | `ws6/support.py:38-50` | 53 passed |
| 18 | WS-6 trial | LOW | Dead branch + unguarded IntegrityError | `ws6/trial.py` | 53 passed |
| 19 | WS-4/5 reliability | HIGH | Deep gauges scraped lazily (stale under load) | `ws5/metrics.py:220,233,369`, `api/main.py:112-165` | 112 passed |
| 20 | WS-4 auth | HIGH | Auth passed through on DB error (fail-open) | `ws4_auth.py:92` | 112 passed |
| 21 | WS-5 reliability | MED | 503 counted in 5xx error budget | `ws5/metrics.py:271,282`, `ws5/api.py:86` | 112 passed |
| 22 | WS-5 reliability | LOW | Budget gauge initialized to 0 | `ws5/metrics.py:214` | 112 passed |
| 23 | WS-4 RBAC | MED | `has_role` raised on unknown role | `ws4/tenant.py:43` | 112 passed |
| 24 | WS-4 tokens | MED | `claims_to_roles` leaked locked roles | `ws4/tokens.py` | 112 passed |
| 25 | WS-4 secrets | MED | Scanner flagged `sk_live_` / `.env.example` | `ws4/secret_scan.py` | 112 passed |
| 26 | WS-5 DR | MED | Restore drill never verified chain | `scripts/run_ws5_restore_drill.py` | 112 passed |
| 27 | WS-5 rate-limit | MED | Redis limiter unsound under multi-worker | `ws5/redis_limiter.py` | 112 passed |
| 28 | WS-4 audit | LOW | Audit logged raw path, not route template | `api/ws4_audit.py` | 112 passed |
| 29 | Supporting | HIGH | `upper` CI used wrong quantiles (interval inverted) | `predict/probabilistic.py:103,160` | 986 passed |
| 30 | Supporting | HIGH | `y_val[:, col]` broadcast bug | `models/gradient.py:317` | 986 passed |
| 31 | Supporting | HIGH | Wind speed rescale used ratio (understated) | `targets/wind.py:82` | 986 passed |
| 32 | Supporting | MED | Temperature reshape off-by-one truncation | `targets/temperature.py:72` | 986 passed |
| 33 | Supporting | MED | `meteostat` cldc/vsby assignment swapped | `src/meteostat.py:250-251` | 986 passed |
| 34 | Supporting | MED | CMES threshold compared Celsius (not <40) | `src/cmes.py:304,328` | 986 passed |
| 35 | Supporting | MED | NOAA longitude not normalized to [-180,180] | `src/noaa.py:317` | 986 passed |
| 36 | Supporting | MED | Backtest pnl excluded exit cost (reverted — see note) | `risk/backtest.py` | see note |
| 37 | Supporting | MED | ECE binning degenerate | `risk/uncertainty.py` | 986 passed |
| 38 | Supporting | MED | Downside std used wrong N | `risk/metrics.py:130` | 986 passed |
| 39 | Supporting | MED | Ensemble signal squared then averaged | `signals/ensemble_signal.py:116` | 986 passed |
| 40 | Supporting | LOW | SDK unwrap/timeout missing | `client/__init__.py` | 986 passed |
| 41 | Supporting | LOW | Token-bucket mem cleanup | `api/auth.py` | 986 passed |
| 42 | Supporting | LOW | Pole divide-by-zero guard | `grids/coordinate.py` | 986 passed |
| 43 | Supporting | LOW | Climatology 365 days (should be 365.2425) | `models/climatology.py` | 986 passed |
| 44 | Supporting | LOW | Solar LST not wrapped to 24h | `targets/solar.py` | 986 passed |
| 45 | WS-1 armor | MED | Feature/outcome gate was a vacuous tautology | `ws1/armor.py` | 229 passed (ws1+ws4) |
| 46 | WS-1 armor | MED | Roll-jump used back-adjusted price (artifacts) | `ws1/armor.py` (close_raw) | 229 passed |
| 47 | WS-1 harness | LOW | `gfs_dir` hardcoded | `ws1/harness.py` | 229 passed |
| 48 | WS-4 twin | MED | Orphan twin had no accessor module | `pakhi/ws4/contract.py` (NEW) | contract_consistent()=True |
| 49 | WS-4 twin | LOW | `tokens`/`tenant` duplicated twin constants | `ws4/tokens.py`, `ws4/tenant.py` | 229 passed |
| 50 | Tests | LOW | `test_ws5_t6_sla.py` expected stale twin `"1.3"` | `tests/test_ws5_t6_sla.py:65` | 50 passed |
| 51 | Tests | LOW | `test_ws4_t3_secrets` self-referential scan | `tests/test_ws4_t3_secrets.py` | 50 passed |
| 52 | Tests | LOW | `test_viz_coverage` hard import error | `tests/test_viz_coverage.py` | 50 passed |
| 53 | Docs | LOW | `TEST_REPORT.md` claimed false green | `TEST_REPORT.md` | — |
| 54 | WS-4 admin | MED | Root admin list filtered to own tenant only (regression from guard) | `api/routes/admin.py:_resolve_scope_tenant_id` | 15 passed (ws4_t2) |
| 55 | WS-4 service | LOW | `list_api_keys` rejected `None` (root list-all) | `ws4/service.py:list_api_keys` | 15 passed |
| 56 | Test infra | LOW | torch/ONNX C++ static-destructor segfault at interpreter shutdown → non-zero CI exit | `tests/conftest.py` (`pytest_sessionfinish` → `atexit` `os._exit`) | full suite exit 0, 1949 passed |

---

## Detailed entries

### WS-2 (signal service, API stream, client)
- **RejectCycleError→REJECTED** (`ws2/orchestrate.py`): a rejected cycle was
  recorded as `FAILED`, poisoning aggregate success rates. Now mapped to
  `CycleOutcome.REJECTED` everywhere it is raised/caught.
- **benchmark_mean honored** (`ws2/significance.py:206`): `significance_report`
  now uses the supplied `benchmark_mean` instead of hardcoding 0.
- **DB keys on WS** (`ws2/stream.py`): the websocket auth now accepts
  DB-issued machine keys, not only in-memory ones.
- **SDK `X-Pakhi-Key` on WS** (`client/__init__.py`): the client now forwards
  `X-Pakhi-Key` on the signal websocket, adds a connect timeout, and unwraps
  batched envelopes.
- **Admin tenant scoping** (`api/routes/admin.py`): cross-tenant read guard
  added (`_resolve_scope_tenant_id`).
- **Episode id reuse** (`scripts/run_ws2_t2_compute.py`): stable episode id.
- **Offline verdict independent** (`ws2/compute.py`): offline verdict no longer
  depends on a live cycle.
- **`stream_signals` max_messages** (`client/__init__.py`): bounded consumption.
- Tests: `tests/test_ws2_*.py` — 123 passed.

### WS-6 (billing/metering)
- **Webhook idempotency** (`ws6/stripe.py:307,333`): the event row is now
  persisted only after the handler succeeds, so a failed handler can be redelivered.
- **Feed-hours tenant pairing** (`ws6/metering.py:101`): the global session was
  paired to the wrong tenant; now scoped correctly.
- **Per-metric usage records** (`ws6/stripe.py:206`): `submit_batch` submits a
  separate usage record per metric instead of collapsing the batch.
- **Reconcile EXTREME** (`ws6/reconcile.py:60`): `chain==0 && log>0` now flagged
  EXTREME (was silently OK).
- **Backtest harness hours** (`ws6/metering.py:126`): overlapping windows no
  longer double-count.
- **Rollup upsert** (`ws6/db.py:33`, `ws6/metering.py:172`): added
  `UniqueConstraint` + idempotent upsert for hourly rollups.
- **never_billed filter** (`ws6/metering.py`): tenants with no billing events
  are now filtered out of invoiceable sets.
- **`.subscription.created`** (`ws6/stripe.py`): added handler so new
  subscriptions sync immediately.
- **`is_sync_stale` neutral** (`ws6/stripe.py:289-300`): no billing activity is
  no longer treated as a stale sync.
- **`.updated` iteration** (`ws6/stripe.py:344-346`): iterates all changed items.
- **SLA word-boundary** (`ws6/support.py:38-50`): regex now uses word
  boundaries so "urgent" does not match "non-urgent".
- **Trial cleanup** (`ws6/trial.py`): removed dead branch; `IntegrityError`
  caught on concurrent trial conversion.
- Tests: `tests/test_ws6_*.py` — 53 passed.

### WS-4 / WS-5 (security + reliability)
- **Scrape-time collector** (`ws5/metrics.py:220,233,369`, `api/main.py:112-165`):
  deep gauges (log age, queue depth, reconcile lag) are now scraped at request
  time instead of relying on a possibly-stale background collector — the
  alerting pipeline now sees fresh values.
- **Fail-closed auth** (`ws4_auth.py:92`): a DB/lookup error now denies rather
  than grants access.
- **503 excluded from 5xx** (`ws5/metrics.py:271,282`, `ws5/api.py:86`):
  maintenance 503s no longer burn the error budget.
- **Budget gauge init** (`ws5/metrics.py:214`): initialized to 1.0 (healthy).
- **`has_role` unknown→False** (`ws4/tenant.py:43`): no longer raises.
- **`claims_to_roles` lock filter** (`ws4/tokens.py`): locked roles cannot be
  granted via claims.
- **Secret scanner allowlist** (`ws4/secret_scan.py`): allowlists `.env.example`
  and `sk_live_` test fixtures.
- **Restore drill verify** (`scripts/run_ws5_restore_drill.py`): `verify_chain`
  is now actually invoked.
- **Redis limiter multi-worker** (`ws5/redis_limiter.py`): fixed unsound
  increment under concurrent workers.
- **Audit route template** (`api/ws4_audit.py`): logs the route template, not
  the raw path (no per-id cardinality leak).
- Tests: `tests/test_ws4_*.py` + `tests/test_ws5_*.py` — 112 passed (3 earlier
  "pre-existing" failures no longer reproduce; full suite is green).

### Supporting modules (predict/models/targets/src/risk/signals/client)
- **`probabilistic.upper`** (`predict/probabilistic.py:103,160`): `upper =
  quantiles[3:]` (correct upper CI). Previously inverted the interval.
- **`gradient.y_val[:, col]`** (`models/gradient.py:317`): fixed broadcast so
  per-column targets are sliced correctly.
- **Wind rescale** (`targets/wind.py:82`): `ws = ws / ratio` (was `ws * ratio`,
  understating wind speed).
- **Temperature reshape** (`targets/temperature.py:72`): trim fixes
  off-by-one truncation of the lead axis.
- **Meteostat swap** (`src/meteostat.py:250-251`): `cldc`/`vsby` assignments
  un-swapped.
- **CMES threshold** (`src/cmes.py:304,328`): compared in Celsius; corrected to
  flag only when `< 40`.
- **NOAA longitude** (`src/noaa.py:317`): normalized to `[-180, 180]`.
- **ECE bins** (`risk/uncertainty.py`): fixed degenerate calibration bins.
- **Downside std** (`risk/metrics.py:130`): uses total N, not masked N.
- **Ensemble signal** (`signals/ensemble_signal.py:116`): averages the mean, not
  the squared signal.
- **SDK unwrap/timeout** (`client/__init__.py`): added.
- **Robustness**: `api/auth.py` token-bucket cleanup, `grids/coordinate.py`
  pole divide-by-zero guard, `models/climatology.py` 365.2425, `targets/solar.py`
  LST `% 24`.
- **NOTE on `risk/backtest.py`**: the diagnosis flagged "per-trade pnl excludes
  exit cost" (H1). The original implementation matches the **locked Evaluation
  Contract v1.0** oracle in `tests/test_backtest_known_value.py`, where `pnl`
  is intentionally gross (price-driven) and costs are tracked separately via
  `costs_incurred`; the **equity curve and `total_return` do include costs**.
  Folding exit cost into `pnl` (as one agent patch attempted) violates that
  locked contract and broke the known-value tests, so the patch was **reverted**.
  The RL over-trading concern in H1 is mitigated at the equity level (costs are
  always charged), not by redefining `pnl`.
- Tests: supporting suites — 986 passed.

### WS-1 armor + WS-4 orphan twin
- **Feature/outcome gate** (`ws1/armor.py`): the look-ahead armor now checks
  `FEATURE_COLUMNS` vs `OUTCOME_PREFIXES` (the real contract), so it actually
  fails when predictors leak outcomes — previously a vacuous tautology.
- **Roll-jump on raw** (`ws1/armor.py`): `check_roll_jump_armor` now inspects
  `close_raw` (falls back to `close_adj` for synthetic fixtures), so it detects
  roll artifacts instead of back-adjustment seams.
- **`gfs_dir`** (`ws1/harness.py`): now taken from `PAKHI_GFS_DIR` /
  default instead of a hardcoded path.
- **Orphan twin accessor** (`pakhi/ws4/contract.py`, NEW): provides
  `contract_consistent()` plus typed accessors (`access_token_ttl_minutes`,
  `access_algorithm`, `default_tenant_id`, `tier_limit_per_min`). Wired into
  `ws4/tokens.py` (`ACCESS_ALGORITHM` / TTL) and `ws4/tenant.py`
  (`DEFAULT_TENANT_ID`) so the locked twin is the single source of truth.
- Tests: `tests/test_ws1_*.py` + `tests/test_ws4_*.py` — 229 passed, 3 skipped.

### Tests + stale docs
- `tests/test_ws5_t6_sla.py:65`: expects twin version `"1.4"` (was stale `"1.3"`).
- `tests/test_ws4_t3_secrets.py`: allowlists the scanner source file and `*.json`
  so it no longer flags itself.
- `tests/test_viz_coverage.py`: uses `importlib.util.find_spec` with skip guards.
- `TEST_REPORT.md`: rewritten to report the honest status (suite green, contract
  discipline, resolved regressions).
- Tests: `tests/test_*_coverage.py` etc. — 50 passed.

### Regressions found and fixed during verification
- **Root admin list-all** (`api/routes/admin.py:_resolve_scope_tenant_id`):
  the cross-tenant guard (added above) over-restricted the root admin so
  `GET /v1/admin/tenants` returned only `pakhi-internal`. Now root with no
  `tenant_id` lists **all** tenants/keys (non-root stays forced to its own).
- **`list_api_keys(None)`** (`ws4/service.py`): now lists all tenants' keys
  instead of 404-ing, supporting the root list-all path.
- **`risk/backtest.py` reverted** to the committed (contract-correct) version —
  see the Supporting note above.

### Final Polish (test infrastructure)
- **ONNX teardown segfault** (`tests/conftest.py`): a full-suite run loaded the
  torch/ONNX C++ stack whose *static destructors* segfault during `Py_Finalize`,
  producing a core dump and a non-zero CI exit even though all tests passed.
  `jit_clear_class_registry()` alone was insufficient. The fix clears the JIT
  registry + ONNX caches in `pytest_sessionfinish` and registers an `atexit`
  handler that forces a clean `os._exit(exitstatus)` *after* the terminal
  summary is printed but *before* the broken C++ teardown runs. The pass/fail
  exit code is preserved; runs that never import torch exit normally. Verified:
  full suite `1949 passed, 5 skipped`, exit code 0, no core dump.
- **torch skip guards** (`tests/test_final_100.py::TestLSTMCoverage`): already
  present — an autouse `has_torch` fixture skips `test_export_onnx_not_fitted`,
  `test_export_onnx_success`, and `test_predict_empty` when the `[ml]` extras
  are absent, preserving the lazy-loading design. Verified passing.

## Verification
Full suite (addopts `-x` override): **1949 passed, 5 skipped, 0 failures.**
`python -c "from pakhi.ws4.contract import contract_consistent; print(...)"` →
`True`. `data/ws1/g1_decision.json` left untouched (reverted after the run that
mutated its timestamp/hash).
