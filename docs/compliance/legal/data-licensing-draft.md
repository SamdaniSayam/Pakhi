# Data Licensing — REVIEW DRAFT (not legal advice)

**Status:** review-draft for counsel.

## 1. What "Data" is

The signals, cycles, metadata, and backtest results returned by the Service.
Data is precomputed from **publicly available Inputs** (including NOAA GFS
forecast data) and is delivered with full provenance (`archive_source`,
`model_version`, `publication_ts`).

## 2. License grant

1. **To the tenant:** a non-exclusive, non-transferable, revocable, royalty-free
   license to **use** the Data for the tenant's internal research, analysis, and
   decision-making during the term, subject to §3–§5.
2. **Derivative works:** backtest results produced by the tenant from their own
   parameters are the tenant's outputs; the Service does not claim them.

## 3. Use limits / redistribution

1. **No wholesale redistribution.** The tenant may not redistribute the Data in
   near-original form (bulk downloads, mirrors, re-serving as an API or feed)
   except under a separate reseller/data-distribution agreement.
2. **Permitted sharing:** the tenant may share extracts (a) with their own
   customers in connection with a licensed product, in transformed/aggregated
   form with attribution, or (b) as required by law or a regulator.
3. **Attribution:** redistribution permitted under §3.2(a) must note that the
   underlying Data derives from publicly available Inputs with the provenance
   provided.

## 4. What Pakhi may use back

1. The tenant grants Pakhi a non-exclusive license to use backtest parameter
   configurations and results **in aggregated, de-identified form** for product
   development and performance monitoring.
2. Pakhi will not use a tenant's configurations to reconstruct that tenant's
   proprietary strategy inputs in identifiable form.

## 5. Status of the Data

Data is delivered "as is" (per the terms of service). **Infrastructure-integrity
claims only** — cycle completion/currency/degradation. Nothing in this license
is investment advice or a recommendation to trade.

## 6. Term and termination

The license runs with the service agreement and terminates on its termination;
§3 restrictions survive for Data already received.

## 7. Counsel questions

1. Does the GFS/NOAA public-data provenance require an acknowledgment or a
   specific license note on redistribution, and does any NOAA terms-of-use
   condition attach to the delivered Data?
2. Territorial treatment of the "transformed/aggregated" safe harbor in §3.2(a).
3. Whether the aggregated-use-back license in §4 needs a separate customer
   notice in the terms of service.
