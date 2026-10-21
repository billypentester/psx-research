# Finura Architecture: Company-Independent Design

Finura researches any verified PSX-listed company with the same schemas,
registries, configuration, and code. No reusable module may name a company,
assume a statement layout, or default to a ticker. FFC is the first
regression fixture and an existing evidence workspace, nothing more.

A test (`tests/test_migration_v1_to_v2.py::TestNoCompanySpecificCode`)
fails if a company name appears in `finura/` source.

## Entities and where they live

| Entity | Model | Storage | Notes |
| --- | --- | --- | --- |
| Company identity | `finura.schemas.Company` | company registry document (`record_type: company_registry`) | Stable `company_id`, dated symbol history, listing status, attested identity and sector |
| Access policy | `finura.sources.access.AccessPolicy` | `config/access_policies.json` | Recorded terms review per host; gates every automated fetch |
| Source document | `finura.schemas.SourceDocument` | source registry document, shared across companies | Evidence path, SHA-256, publisher, canonical URL, publication/retrieval/registration times, access basis, upstream lineage |
| Listing claim | `finura.claims.ListingClaim` | listing claims document (`record_type: listing_claims`) | A cited statement about a symbol; `discovered`, `verified`, or `rejected` |
| Financial fact | `finura.schemas.FinancialFact` | one facts document per company | Value, unit, currency, period, scope, source link, provenance |
| Sector profile | `finura.sectors.SectorProfile` | `config/sector_profiles.json` | Selected only from a verified classification |
| Research run | run identifier from `finura.workspace.new_run_id` | `runs/<company_id>/<run_id>/` | Run manifest and reports arrive in Phase 13 |
| Generated report | not yet modelled | inside its run directory | Never overwrites another run's output |

Each record type has its own `schema_version`. Facts and sources are at
version 2; companies, company registries, listing claims, access policies,
and sector profiles start at version 1.

v2 candidates live under `data/v2/` and are not read by the legacy
pipeline, which still runs on v1. See [data/v2/README.md](../data/v2/README.md).

## Company identity

- `company_id` is assigned once at onboarding and never changes. It is an
  opaque key, not the current ticker. For legacy v1 data it keeps its existing
  value (for example `FFC`), and the symbol history carries the ticker.
- `symbols` is a chronological list of `[valid_from, valid_to)` ranges. A
  ticker change closes one range and opens the next. A symbol may be reused
  after a delisting, but the registry rejects two companies holding one
  symbol over overlapping dates.
- `listing_status` is `listed`, `suspended`, `delisted`, or `null` (no
  evidence recorded). A listed or suspended company must have a current symbol. A delisted company must not,
  and its `delisted_on`, when recorded, equals the last symbol's `valid_to`.
- `identity` and `classification.attestation` are attestations. `verified`
  requires evidence (a registered `source_id` or a URL), a reviewer, and a
  timezone-aware review time. `unverified` cannot name a reviewer.
- Symbol lookups need an explicit date (`resolve_symbol(symbol, on=...)`), so
  historical research cannot silently resolve to today's listing.

### Onboarding

Onboarding a company means proposing a `Company` record from listing claims,
each citing registered evidence (see
[SOURCES_AND_CLAIMS.md](./SOURCES_AND_CLAIMS.md)). Retrieving evidence never
verifies it: claims start `discovered`, and a person verifies or rejects
each one. A record's identity is verified only when every claim behind it is.
Unverified companies:

- cannot receive workspace paths (`Workspace` raises `UnverifiedCompanyError`);
- cannot have a sector profile selected;
- are reported as `company_identity: unverified` by migrations.

PSX's terms prohibit automated retrieval without written permission, so
PSX listing evidence enters through manually downloaded notices that are
transcribed into claims. The FFC record in `data/v2/companies/` is
unverified, built from one discovered claim transcribed from the committed
OCR text of its registered filing.

## Sector profiles

`config/sector_profiles.json` maps Finura sector keys to profiles. A profile
currently declares its `statement_model` (`general` or `banking`), so later
validation and analysis do not assume one statement structure for all
sectors. Metric sets, valuation methods, and macro drivers are added to
profiles in Phases 8–10. Selection fails when the classification is missing,
unverified, or unmapped; there is no default sector.

## Paths and runs

`finura.workspace.Workspace` is the only place company-scoped paths are
built:

```text
data/raw/<company_id>/            preserved evidence
data/normalized/<company_id>/     normalized documents
runs/<company_id>/<run_id>/       one research run's outputs
```

Run identifiers look like `20261021T181500Z-1a2b3c4d`: UTC start time plus a
random suffix, so runs sort chronologically and never collide.

## Rules for later phases

Every calculation and report must name the company (`company_id` plus the
symbol in effect for the period), reporting scope, period end and type, units,
and the source evidence of each input. Values from different scopes, period
types, units, or currencies are never combined without an explicit, recorded
conversion.

## Validation

`finura.validation` checks a facts document against
`config/accounting_rules.json` and the source registry, and returns a verdict
of `failed`, `incomplete`, `passed_with_warnings`, or `passed`. Required rules
come only from a verified sector's statement model; an unverified sector can
never pass. See [VALIDATION.md](./VALIDATION.md).

## Migrations

Schema changes ship as explicit, manifested migrations under
`finura/migrations/`. See `docs/DATA_SCHEMA.md` for v1 → v2.

## Open items

- FFC's company record is unverified. It needs PSX listing evidence
  (manually downloaded and registered), a reviewed claim, and a re-proposal
  before it can use workspace paths or sector profiles.
- Automated PSX listing retrieval needs PSX's written permission or a data
  licence; `config/access_policies.json` must then record it.
- Every catalog provider has a recorded review, and none permits automated
  access ([PROVIDER_DUE_DILIGENCE.md](./PROVIDER_DUE_DILIGENCE.md)). An
  automated source needs written permission or a data licence.
- The legacy `pipeline/validate/*` scripts default `--company` to `FFC`, and
  `pipeline/verify/*` hardcode FFC paths. They are superseded in Phases 4 and
  6 rather than edited now.
