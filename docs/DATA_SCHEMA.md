# Data Schema

This document defines the currently implemented JSON contracts for source
metadata and financial facts. It describes what the repository actually
accepts today; proposed extensions are listed separately.

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
  "verification_status": "verified"
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

This mixed vocabulary exposes a current schema limitation: evidence status
and fact classification are not separate fields. Do not silently introduce a
new status. A future migration should add an explicit classification field
and update validators/tests together.

## Validation rules

`pipeline/validate/validate_financial_facts.py` checks:

- readable JSON files;
- `facts` is an array;
- registry IDs are present and unique;
- all required fact fields exist;
- scope, unit, and verification status are allowed;
- values are finite numbers and not booleans;
- dates are ISO dates;
- fact uniqueness keys are not duplicated;
- source files exist inside the repository;
- source hashes match the registry.

`check_reconciliations.py` and `check_cash_flows.py` add accounting checks;
their exact assumptions are described in
[INGESTION_PIPELINE.md](./INGESTION_PIPELINE.md).

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
