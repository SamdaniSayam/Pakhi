# Incident Response Runbook

**Status:** operational — the runbook below is the control. It references the
alerting that already exists (WS-2 orchestration alerts, `SECURITY.md` report
flow) and the audit surface that proves timelines (WS-4).

## 1. Incident classes

| Class | Example | Priority |
|---|---|---|
| S1 — Security | credential leak, unauthorized cross-tenant access, secret in tree | P0 |
| S2 — Data integrity | audit chain broken (tamper/omission), replay divergence, unexpected NaN/wrong signal | P1 |
| S3 — Availability | ingest→compute→store cycle failure, API 5xx burst, DB outage | P1 |
| S4 — Platform | non-security bug found by operators or customers | P2 |

## 2. Detection

- **Automated:** `scripts/run_ws2_t3_orchestrate.py` alerts on any cycle
  failure; outcomes are persisted to `data/ws2/logs/orchestrate.jsonl`. The WS-4
  audit sweep (`scripts/run_audit_sweep.py`) is run on a schedule; an omission
  is a P1 integrity event, not a routine warning.
- **Human:** customers, operators, and the security reporting channel
  (`SECURITY.md`). Reports are acknowledged with a target update cadence.
- **Compliance:** the SOC2 observation clock (recorded in `../WS4_PROGRESS.md`)
  covers S1–S3; every incident of those classes gets a timeline entry.

## 3. Triage (first 15 minutes)

1. Confirm class and priority; assign one incident owner (single point of truth).
2. Open the incident thread with a timestamp. The timeline is the deliverable:
   detection, containment, root cause, remediation — each with a time.
3. Decide posture: is the system safe to keep serving? If a credential is
   suspected, revoke immediately (see §4); do not wait for confirmation.

## 4. Containment playbooks

### S1 credential/secret leak
1. Revoke the exposed credential now: token family revocation / key revocation
   are audited actions (`api_key.revoke`, outcome `revoked_family`) — the
   revocation itself is the first containment record.
2. If the secret is in the tree: remove it from the branch **and** history,
   rotate it, and run `python scripts/secret_scan.py`; the CI secrets scan keeps
   it out on the next push.
3. If a JWT secret leaked: rotate it at the deployment boundary (Settings fails
   fast on weak/missing secrets, so a rotation is a deliberate, reviewed change).
4. Record first-known-exposure window from audit data; deliver to the affected
   customers as required by the data-licensing agreement.

### S2 integrity
1. Run `verify_chain_in_store` via the admin audit surface. If the chain is
   broken at index *k*, stop trusted mutations until the cause is understood —
   a broken chain means the store's evidence itself is suspect.
2. Run the omission sweep against the nginx access log; reconcile any mutating
   request_id with no audit row against the store's row data.
3. Do not "repair" the chain by rewriting history. If tampering is confirmed,
   restore from the last trusted backup (backup policy) and re-sweep.

### S3 availability
1. Check the WS-2 cycle log (`orchestrate.jsonl`) for the failing stage
   (ingest/compute/store) and replay the affected cycles after the fix.
2. The API fails closed on DB-key validity — a store outage must not widen
   access; verify 401/503 behavior is correct rather than relaxed.
3. Single-worker contract: if the worker died, restart from the tagged release,
   never from an unverified state.

## 5. Root cause + remediation

- Root cause analysis is recorded in the incident thread with the change that
  caused it (change-management policy makes every merge traceable to a commit +
  CI run).
- Remediation ships as a reviewed PR; the fix is not complete until its CI run
  is green.
- Every S1/S2 incident gets a follow-up control: either a test that would have
  caught it, or a documented deviation with a reason.

## 6. Post-incident

- Timeline + root cause + remediation summarized in the incident record.
- Communication: internal first, then affected tenants, then (if required by
  law or agreement) regulators/customers — all from the recorded timeline.
- Lessons folded into this runbook and the CI gates.
