# Terms of Service — REVIEW DRAFT (not legal advice)

**Status:** review-draft for counsel. Any capitalized term is defined in §1.

## 1. Definitions

- **"Service"** — the Pakhi API: precomputed forecast-instrument signals,
  instrument metadata, the backtesting job API, and the administrative API,
  as served at the then-current endpoints.
- **"Tenant"** — the legal entity that holds an API key or issues human tokens.
- **"Data"** — the signals, cycles, and backtest results the Service returns.
- **"Inputs"** — publicly available forecast datasets (including NOAA GFS) from
  which Data is precomputed, and any user-supplied backtest parameters.

## 2. Access

1. Access requires a valid credential (API key or token) issued under the access
   control policy. Credentials are non-transferable, confidential, and revocable
   at any time with or without cause.
2. The tenant is responsible for activity under its credentials and must
   notify Pakhi promptly of suspected compromise. Token reuse triggers family
   revocation.
3. Tier rate limits (free/pro/labs) apply per the tenant's plan; the Service may
   enforce them at the edge.

## 3. Acceptable use

Tenants may not: (a) resell raw Data without a data-licensing agreement; (b)
attempt to access another tenant's records (per-tenant isolation is enforced and
audited, and circumvention attempts may be reported); (c) use the Service to
bypass import/export restrictions; (d) hold the Service out as investment
advice.

## 4. Data and provenance

1. Data is precomputed from published Inputs with full provenance attached
   (`archive_source`, `model_version`, `publication_ts`). The Service makes
   **infrastructure-integrity claims** — cycle complete/current/degraded —
   not accuracy or fitness claims for trading.
2. Pakhi provides the Data "as is", without warranties of merchantability or
   fitness for a particular purpose, and without a guarantee that a cycle will
   always be published on time.

## 5. Availability

The Service is provided on a best-efforts basis; scheduled and incident-driven
downtime is handled per the incident-response runbook. RPO/RTO commitments, once
operationalized (backup policy), are stated separately, not as a warranty here.

## 6. Suspension and termination

Pakhi may suspend or terminate access: for breach of this agreement; for
credential compromise (immediate revocation is the containment action); or on
notice for material change to the Service.

## 7. Limitation of liability

To the maximum extent permitted by law, Pakhi's aggregate liability under this
agreement is limited to the fees paid by the tenant in the twelve months before
the claim, and Pakhi is not liable for indirect, special, or consequential
damages (including lost trading profits). **Counsel question:** confirm this
limitation survives the data-resale use case and any mandatory consumer-law
territories.

## 8. Changes

Pakhi may change these terms on notice (posted + email to the account). Material
changes take effect 30 days after notice; continued use is acceptance.

## 9. Governing law and venue

**Counsel question:** determine governing law/venue based on incorporation and
customer geography (draft placeholder: the jurisdiction of Pakhi's principal
place of business).

## 10. Contact

Security and legal inquiries via the `SECURITY.md` channel and the contact
address supplied with the invoice.
