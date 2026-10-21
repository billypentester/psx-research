# Data Schema

This document defines the currently implemented JSON contracts for source
metadata, reported financial facts, and derived metrics.

## Design goals

The schema is intentionally small and audit-friendly:

- preserve the source document;
- make every value traceable to a registered source location;
- keep statement scope, period, and unit explicit;
- distinguish missing data from zero;
- keep standalone and consolidated values separate;
- make duplicate facts and broken source links detectable.

## Source registry

File: `data/source_registry.json`

The current registry is a top-level JSON array. Each entry has this shape:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `source_id` | string | yes | Stable identifier referenced by facts |
| `company_id` | string | yes | Company/ticker identifier, currently `FFC` |
| `source_type` | string | yes | `annual_report`, `quarterly_report`, `announcement`, `market_data`, or `other` |
| `title` | string | yes | Human-readable document title |
| `url` | string or null | no | Original official URL, when known |
| `published_at` | string or null | no | Publication date as `YYYY-MM-DD` |
| `retrieved_at` | string | yes | UTC retrieval timestamp |
| `local_path` | string | yes | Repository-relative preserved file path |
| `sha256` | string | yes | SHA-256 digest of the preserved file |
| `page_number` | number or null | no | Optional default page |
| `notes` | string or null | no | Scope, limitations, or provenance notes |

The registry currently contains one source:
`src_e4abb64ff4886ffc`, the FFC FY2025 PSX filing at
`data/raw/FFC/ffc_report.pdf`.

`register_source.py` derives the ID from company, URL, and file hash; it
does not treat the ID as proof of source authority.

## Financial facts file

File: `data/normalized/<COMPANY>/financial_facts.json`

The top-level object currently contains:

```json
{
  "company_id": "FFC",
  "currency": "PKR",
  "facts": []
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `company_id` | string | Company identifier |
| `currency` | string | Reporting currency |
| `facts` | array | Financial fact records |

## Financial fact record

Each fact currently requires:

| Field | Type | Allowed/current values | Meaning |
| --- | --- | --- | --- |
| `metric` | string | Canonical identifier | E.g. `net_turnover` or `total_assets` |
| `scope` | string | `standalone`, `consolidated` | Statement reporting scope |
| `period_end` | string | ISO `YYYY-MM-DD` | End date of the reported period |
| `period_type` | string | E.g. `annual` | Reporting-period classification |
| `value` | number | Finite integer/float | Reported numeric value; booleans are invalid |
| `unit` | string | `PKR_thousand`, `PKR`, `PKR_per_share` | Unit attached to the value |
| `source_id` | string | Existing registry ID | Provenance link |
| `source_page` | string | Human-readable location | Page/annexure supporting the value |
| `verification_status` | string | See below | Evidence/review status |
| `fact_classification` | string | `reported`, `calculated`, `estimated`, `missing`, or `management_provided` | What kind of value this is |

Example:

```json
{
  "metric": "net_turnover",
  "scope": "standalone",
  "period_end": "2025-12-31",
  "period_type": "annual",
  "value": 432410443,
  "unit": "PKR_thousand",
  "source_id": "src_e4abb64ff4886ffc",
  "source_page": "Annexure A, page 2 of 8",
  "verification_status": "verified",
  "fact_classification": "reported"
}
```

The uniqueness key is:

```text
metric + scope + period_end + period_type + unit
```

Two records with the same key are rejected by validation, even if their
values differ.

## Current metric coverage

The FFC fixture currently includes turnover, gross profit, profit after tax,
profit attributable to the parent, EPS, balance-sheet totals, operating/
investing/financing cash flows, cash movements and balances, and merger cash.
The exact canonical metric names are the `metric` values in
`data/normalized/FFC/financial_facts.json`.

The fixture has 60 facts:

- 29 standalone records and 31 consolidated records;
- annual periods ending 2025-12-31 and 2024-12-31;
- 56 values in `PKR_thousand`;
- 4 values in `PKR_per_share`;
- all current records marked `verified`.

## Verification statuses

The validator accepts:

- `verified`: checked against the original source document;
- `ocr_unverified`: extracted or OCR-supported but not yet manually
  confirmed;
- `needs_final_review`: requires additional human review;
- `estimated`: accepted by the validator but describes a data
  classification, not evidence quality;
- `missing`: accepted by the validator but describes availability, not
  evidence quality.

The validator does not accept `pending` or `rejected`.

Evidence status and fact classification are separate. `verification_status`
describes review evidence, while `fact_classification` describes whether the
value was reported, calculated, estimated, missing, or management-provided.

## Derived metrics

`pipeline/derive_metrics.py` reads normalized facts and writes
`data/derived/<COMPANY>/derived_metrics.json`. Each metric records its formula,
input fact keys, period, scope, and calculation status. The current FFC
artifact includes growth, margin, cash-conversion, and asset-turnover metrics.
Missing prior periods, zero denominators, and unverified inputs produce an
explicit `missing` result rather than a fabricated value.

## Structured-source normalization

`pipeline/normalize_external.py` converts an explicitly mapped CSV, JSON, or
HTML table into normalized data. A mapping file is required; the importer
does not guess that arbitrary provider columns represent financial metrics.

Market data is written to:

```text
data/normalized/<COMPANY>/market_data.json
```

Each observation contains:

| Field | Meaning |
| --- | --- |
| `company_id` | Ticker/company identifier |
| `source_id` | Registered source response |
| `observed_at` | ISO timestamp for the price observation |
| `price` | Non-negative numeric price |
| `currency` | Currency when supplied |
| `volume` | Optional volume |
| `shares_outstanding` | Optional shares count |
| `market_cap` | Optional market capitalization |
| `dividend_per_share` | Optional dividend per share |

Example:

```bash
python pipeline/normalize_external.py \
  --company FFC \
  --input data/raw/FFC/external/psx/prices.csv \
  --mapping config/ffc_market_mapping.json \
  --source-id src_example \
  --kind market \
  --output data/normalized/FFC/market_data.json
```

Imported financial facts are deliberately marked `needs_final_review`; an
importer cannot establish that a provider table has the correct statement
scope, period, units, signs, or restatement context.

## Validation rules

`pipeline/validate/validate_financial_facts.py` checks:

- readable JSON files;
- `facts` is an array;
- registry IDs are present and unique;
- all required fact fields exist, including `fact_classification`;
- scope, unit, and verification status are allowed;
- values are finite numbers and not booleans;
- dates are ISO dates;
- fact uniqueness keys are not duplicated;
- source files exist inside the repository;
- source hashes match the registry.

`check_reconciliations.py` and `check_cash_flows.py` add accounting checks;
their exact assumptions are described in
[INGESTION_PIPELINE.md](./INGESTION_PIPELINE.md).

## Canonical v2 schema (`finura.schemas`)

The `finura` package defines canonical Pydantic models with an explicit
`schema_version` of `2`. The data files above are still v1; the package reads
them through read-only loaders and does not rewrite them. Migrating stored
files to v2 is a separate, reviewed step.

```python
from pathlib import Path
from finura.schemas import load_v1_financial_facts, load_v1_source_registry

facts = load_v1_financial_facts(Path("data/normalized/FFC/financial_facts.json"))
registry = load_v1_source_registry(Path("data/source_registry.json"))
facts.facts[0].provenance_gaps  # fields v1 never recorded
```

Each loader returns the strict v1 mirror records and the mapped v2 models
side by side, so the mapping can be checked field by field.

### Validation rules

- Values must be finite JSON numbers; booleans, NaN, infinity, and numeric
  strings are rejected. Integers stay integers and floats stay floats.
- Dates must be `YYYY-MM-DD` strings; timestamps must carry a UTC offset.
- Enum values are exact and case-sensitive; unknown values are rejected.
- Unknown fields are rejected, not dropped. Repeated JSON object keys are
  rejected instead of keeping the last value.
- A fact's `currency` must match the currency of its `unit`.
- Duplicate fact identities and duplicate `source_id`s are rejected.
- A fact cannot be classified or reviewed as `missing`: a missing figure is a
  data gap, not a number. (v1 accepted these values; no v1 record uses them.)
- `verified_by`, `verified_at`, and `verification_evidence` are allowed only
  on `verified` facts; `extracted_at` requires an `extraction_method`.
- A source's `local_path` must be relative, use `/`, and not contain `..`.
- Timestamps are written with `isoformat()`, so `+00:00` is not rewritten
  as `Z`.

### Source fields added before first persistence (Phase 3, step 1)

`SourceDocument` v2 was finalised before any v2 file was stored. `url` is
now `canonical_url`, `company_id` may be `null` for exchange-wide documents,
and `publisher`, `access_basis`, and `upstream` were added. Field meanings
are in [SOURCES_AND_CLAIMS.md](./SOURCES_AND_CLAIMS.md).

### v2 file documents

| `record_type` | Model | Contents |
| --- | --- | --- |
| `financial_facts` | `FinancialFactsDocument` | One company's facts; every fact's `company_id` must equal the document's |
| `source_registry` | `SourceRegistryDocument` | All registered sources; `source_id` unique |

Both carry `schema_version: 2` and, when produced by a migration, a
`lineage` block (`from_path`, `from_sha256`, `migrated_at`). Unknown
provenance is written as an explicit `null`.

### Migrating v1 files

```bash
uv run python -m finura.migrations.v1_to_v2 \
  --facts data/normalized/<COMPANY>/financial_facts.json \
  --registry data/source_registry.json \
  --facts-out <new path> --registry-out <new path> --manifest-out <new path> \
  --evidence-root . \
  [--company-registry <companies.json>] [--backup-dir <dir>]
```

The migration is company-independent; every path is explicit. It aborts,
writing nothing, if:

- either input fails strict v1 or v2 validation;
- a fact cites an unregistered source, or a source registered to another
  company;
- a raw evidence file is missing or fails its SHA-256 check (when
  `--evidence-root` is given);
- the company is absent from the company registry (when given);
- the re-parsed output differs from the v1 input in any mapped field, or an
  unrecorded field is set;
- an output path is an input path;
- an output exists and no backup directory was given.

On success it writes the two v2 documents and a manifest recording input and
output paths, hashes, schema versions, and record counts; backups taken; each
validation result; field-equivalence results; verification-status counts
before and after; and per-field provenance-gap counts. Inputs are re-hashed
before writing to confirm they did not change.

The v2 fact identity is
`company_id + concept + scope + period.end + period.type + unit`: the v1
key plus `company_id`, because v2 facts carry their company individually.

### v1 to v2 mapping: source registry

| v1 field | v2 `SourceDocument` field | Rule |
| --- | --- | --- |
| `source_id`, `company_id`, `title`, `local_path`, `sha256`, `page_number`, `notes` | same name | copied |
| `url` | `canonical_url` | renamed |
| — | `publisher`, `access_basis`, `upstream` | `None`: not recorded in v1 |
| `source_type` | `source_type` | copied; enum |
| `published_at` | `published_at` | copied; `null` stays `None` |
| `retrieved_at` | `registered_at` | renamed: `register_source.py` stamps registration time |
| — | `retrieved_at` | `None`: download time was not recorded |
| `provider`, `retrieval_method`, `http_status`, `content_type` | same name | copied when present, otherwise `None` |

### v1 to v2 mapping: financial facts

| v1 field | v2 `FinancialFact` field | Rule |
| --- | --- | --- |
| file `company_id` | `company_id` | inherited from the file header |
| fact `company_id` (written by `normalize_external.py`) | `company_id` | must equal the file header |
| file `currency` | `currency` | inherited; must match the unit |
| `metric` | `concept` | renamed |
| `value` | `value` | copied; numeric type preserved |
| `unit` | `unit` | copied; enum |
| `period_end`, `period_type` | `period.end`, `period.type` | copied |
| — | `period.start` | `None`: not recorded |
| `scope` | `scope` | copied; enum |
| `source_id` | `source_id` | copied |
| `source_page` | `source_location` | renamed |
| `verification_status` | `verification_status` | copied; enum |
| `fact_classification` | `classification` | renamed; enum |
| — | `verified_by`, `verified_at`, `verification_evidence` | `None`: not recorded in v1 |
| — | `extraction_method`, `extracted_at` | `None`: not recorded in v1 |

No v2 field is inferred from file content. `provenance_gaps` lists every
provenance field that is `None`; verification fields count as gaps only for
`verified` facts.

### New v2 vocabulary

- `fact_classification` adds `assumed`, which the Finura specification
  requires and no v1 record uses.
- `period.type` adds `quarterly` and `year_to_date`; v1 data contains only
  `annual`.
- `extraction_method` is new: `ocr`, `structured_import`,
  `manual_transcription`.

## Validation reports and accounting rules

`config/accounting_rules.json` (`record_type: accounting_rules`, schema
version 1) and the validation report (`record_type: validation_report`,
schema version 1) are documented in [VALIDATION.md](./VALIDATION.md).

## Safe schema evolution

When extending the schema:

1. document the field and allowed values;
2. update the validator;
3. update the unit tests;
4. migrate existing records deliberately;
5. preserve source and review evidence;
6. run all validators before and after migration.

Do not add a field only to make a report look complete, and do not use zero
as a placeholder for an unavailable figure.
