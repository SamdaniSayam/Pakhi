# Privacy Policy — REVIEW DRAFT (not legal advice)

**Status:** review-draft for counsel.

## 1. Who we are

Pakhi operates a forecast-signal and backtesting API. This notice describes how
personal and account data are handled.

## 2. What we collect

1. **Account/credential data.** The minimum needed to run the Service: tenant
   identifiers, API key hashes (SHA-256; the raw key is never stored), refresh
   token digests (sha256), and the identities (user ids) of humans issued tokens.
   Email addresses are collected only if a tenant provides one for billing or
   contact.
2. **Audit data.** Every sensitive action (token issue/refresh, key
   create/revoke, tenant create, backtest submit) writes a chained audit row
   containing the actor id, tenant id, action, resource, request id, and
   timestamp. Read access is covered by the same audit trail. This is a
   security control (tamper-evident, omission-swept), not a behavioral profile.
3. **Operational logs.** Request logs at the proxy (nginx) capture request id,
   path, status, and timestamp for integrity reconciliation. They do not contain
   credentials or request bodies.
4. **We do not collect:** browsing behavior, device fingerprints, or marketing
   identifiers. No user PII is required to use the API.

## 3. How we use it

- Operate and secure the Service (access control, rate limits, audit, incident
  response).
- Comply with legal obligations; defend against abuse or breach attempts.

We do not sell personal data. We do not use account data for advertising.

## 4. Retention and deletion

- Credentials: kept while the account is active; hashes allow revocation checks.
- Audit chain: append-only, retained for at least the period the records it
  attests must be kept (see backup policy), and longer where required by law.
  Deletion of a tenant does not delete its historical audit rows — the chain
  must stay verifiable; rows are pseudonymous (ids, not PII).
- Tenants may request deletion of account data not needed for security/legal
  retention; requests go through the contact channel.

## 5. Sharing

- We do not share personal data with third parties except: processors who help
  operate the Service under a data-processing agreement (hosting, database,
  object storage), legal/regulatory requirements, or in connection with a
  change of control.
- Data-licensing terms govern the tenant's use of the *returned Data*, which is
  derived from publicly available Inputs and is not personal data.

## 6. Security

Account and audit data are protected by the WS-4 controls: per-tenant isolation
enforced and tested in CI, secrets fail-fast (weak/missing secret = boot error,
no plaintext keys in the tree), and a tamper-evident audit chain. Incidents are
handled per the incident-response runbook and disclosed as required by law.

## 7. Your rights

Subject to applicable law, tenants and individuals may request access,
correction, or deletion of their data, and may lodge a complaint with a
supervisory authority. **Counsel question:** confirm the GDPR/CCPA posture
claims for the territories the Service will actually serve; this draft takes no
position on territorial applicability.

## 8. Changes

Material changes posted with effective date; continued use is acceptance.
