# Backup & Recovery Policy

**Status:** policy in force; **operationalized by WS-5 T5** (disaster recovery).
WS-4 documented the policy and the guarantees; WS-5 built the machinery that
makes the guarantees executable: `scripts/run_ws5_backup.py` (base snapshot +
pinned manifest + off-host copy) and `scripts/run_ws5_restore_drill.py` (the
wipe-and-restore drill). The **tested-restore clause (§4/§5) is now rehearsed on
every CI run** against a real Postgres 16 store
(`.github/workflows/ws5-dr.yml`); the same drill runs hermetically against
SQLite in `tests/test_ws5_t5_dr.py`.

## 1. Policy

1. **State is in Postgres.** The single source of truth is the Postgres store
   (write ledger, tenants, keys, tokens, audit chain). Backups protect the store.
2. **RPO (recovery point objective):** no more than one production cycle of
   ingested data may be lost — i.e. the latest completed 12Z cycle and its
   ledger state must always be restorable.
3. **RTO (recovery time objective):** restore the store from a trusted backup
   and resume serving within 4 hours of a confirmed destructive event.
4. **Backups are tested.** A restore that has never been executed is a wish, not
   a backup. At least quarterly, a restore is rehearsed from an actual backup
   into a scratch database and the audit chain + ledger verified.
5. **Backups are versioned and off-host.** At least one backup must be held
   outside the primary host/region at all times (WAL archiving + periodic base
   backups).

## 2. What must be recoverable

| Artifact | Source of truth | Recovery check |
|---|---|---|
| Ledger / signals / cycles | Postgres (write + read engines) | ledger queries + WS-3 contract tests against the restored DB |
| Tenants, API keys, tokens | Postgres | WS-4 tenancy tests against the restored DB |
| Audit chain | Postgres `audit_events` | `verify_chain_in_store` passes on the restored DB |
| Raw forecast input (GFS parquets) | object storage / archive | re-ingest produces the same cycle (WS-2 replay harness) |

## 3. Backup cadence

- **Base backup:** daily (before the first 12Z cycle is published) —
  `python scripts/run_ws5_backup.py --source-url <pg-url> --backup-dir <dir>
  --off-host-dir <offhost>`. The script refuses a store whose audit chain does
  not verify and pins the latest cycle + ledger counts in the manifest.
- **WAL archive:** continuous; the archive is the incremental layer that makes
  RPO=one cycle achievable (primary `archive_mode=on`). The manifest records the
  base point so the base→last-WAL gap is bounded by `dr.rpo_cycles`.
- **Off-host copy:** after each base backup, `run_ws5_backup.py --off-host-dir`
  copies base + manifest outside the primary host.
- **Retention:** base backups ≥ 30 days (`--keep`, default 30); monthly ≥ 12
  months; the audit chain is append-only and its retention matches the records
  it attests.

## 4. Restore procedure (operationalized by WS-5 T5; this is the contract)

The executable form is `scripts/run_ws5_restore_drill.py` — run against a
scratch database (never the primary) it performs: snapshot → wipe →
restore_scratch_db → verify chain → verify ledger (counts + latest cycle match
the pinned manifest) → WS-3 read-path smoke + WS-4 evidence suite against the
restored DB. The CI drill (`.github/workflows/ws5-dr.yml`, Postgres 16) is the
rehearsal that keeps the tested-restore clause true.

1. Confirm the incident class (runbook S2/S3); declare the restore only when
   the store is deemed untrustworthy (e.g. confirmed tamper, corruption).
2. Bring the store down (no writers), restore the latest trusted base + WAL to a
   new database name, and verify:
   - `verify_chain_in_store` passes — the audit chain is the integrity check;
   - WS-3 + WS-4 test suites pass against the restored DB (the `ws4-security`
     Postgres job is the template);
   - the ledger's latest cycle matches the last published cycle in the off-host
     log.
3. Point read/write engines at the restored DB, confirm the API serves, then
   resume the WS-2 cycle. The restore event is logged as an incident timeline
   entry (runbook §6).

RPO (≤ 1 cycle) and RTO (≤ 4 h) are stated in the WS-5 contract twin
(`data/ws5/reliability_contract.json` `dr.*`) as the targets the drill measures
and reports on every run.

## 5. Integrity of backups

- The audit chain doubles as backup integrity evidence: a backup whose restored
  chain does not verify is not trusted, and the restore restarts from an older
  trusted point. Enforced at backup time too: `run_ws5_backup.py` refuses to
  take a base from a store whose chain does not verify.
- Secrets (JWT secret, master keys) are restored from the out-of-band secret
  store, never from a database backup — the DB never contains plaintext
  secrets (T3). The manifest redacts the source URL's password.

## 6. Roles

- Operations owns backup execution and the quarterly restore rehearsal; security
  owns the restore *verification* (chain check, secret handling); the change
  management path records any policy change.
