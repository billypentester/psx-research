# PSX Financial Research Pipeline

A source-traceable, evidence-first workflow for collecting, normalizing,
verifying, and validating financial data used in Pakistan Stock Exchange
(PSX) equity research.

The repository currently contains a complete first fixture for Fauji
Fertilizer Company Limited (`FFC`) and a company-agnostic schema and
calculation layer that can be populated for any PSX-listed company. It is a
research data foundation, not a trading system, portfolio manager, or
automated investment-advice service.

## What this project does

The pipeline is designed to preserve the chain from an official source
document to a normalized financial fact:

1. Discover an official filing or other permitted primary source.
2. Preserve the original file under `data/raw/`.
3. Register its metadata and SHA-256 hash.
4. Extract financial statement values, using OCR when required.
5. Normalize each value into a consistent JSON record.
6. Check source links, dates, units, duplicates, and file integrity.
7. Reconcile statement totals and cash-flow movements where applicable.
8. Compare OCR output with stored facts as a supporting check.
9. Visually verify facts against the original source before calling them
   `verified`.
10. Derive ratios only from verified inputs and preserve their formulas and
    input fact keys.
11. Use only source-linked, validated facts in downstream analysis.

OCR, arithmetic reconciliation, and row matching are controls that find
problems; none of them independently proves that a value is correct.

## Current implementation status

The current FFC fixture contains:

| Area | Current coverage |
| --- | --- |
| Company | Fauji Fertilizer Company Limited (`FFC`) |
| Source | One 10-page scanned PSX financial-results filing |
| Reporting periods | Annual years ended 31 December 2024 and 31 December 2025 |
| Statement scopes | Standalone and consolidated |
| Financial facts | 60 |
| Units | 56 `PKR_thousand`, 4 `PKR_per_share` |
| Verification | 60 facts marked `verified` |
| Source integrity | Registered SHA-256 hash |
| Automated controls | Schema/integrity, balance-sheet, cash-flow, OCR row, and year-column checks |
| Derived metrics | Company-agnostic growth, margin, cash-conversion, and asset-turnover calculations |

The filing is a results announcement with attached financial statements, not
the company's full annual report. The source registry records this limitation.

## Repository layout

```text
.
├── data/
│   ├── raw/<COMPANY>/                 Preserved source documents
│   ├── normalized/<COMPANY>/          Canonical facts, OCR, and page images
│   └── derived/<COMPANY>/             Formula-backed calculated metrics
│   ├── source_catalog.json            Configured public data providers
│   └── source_registry.json           Source metadata and SHA-256 hashes
├── docs/
│   ├── DATA_SCHEMA.md                 JSON contracts and field definitions
│   ├── INGESTION_PIPELINE.md          End-to-end operating procedure
│   └── SOURCE_POLICY.md               Evidence, provenance, and conflict rules
├── config/
│   ├── accounting_rules.json          Accounting identities and subtotals
│   ├── access_policies.json           Recorded terms reviews gating automated access
│   └── sector_profiles.json           Sector profiles selected by verified classification
├── data/v2/                           v2 candidates (not read by the legacy pipeline)
├── finura/
│   ├── schemas/                       Canonical models (company, source, fact) and v1 loaders
│   ├── sources/                       Access policies, fetcher, source registry, adapters, transcription
│   ├── migrations/v1_to_v2.py         Generic, manifested v1 → v2 migration
│   ├── claims.py                      Listing claims and company proposals
│   ├── onboarding.py                  CLI: ingest, review, propose
│   ├── companies.py                   Company registry abstraction
│   ├── sectors.py                     Sector-profile selection
│   ├── storage.py                     Backup-guarded file replacement
│   ├── accounting_rules.py            Accounting rule schema
│   ├── validation.py                  Validation engine, report, and CLI
│   └── workspace.py                   Company- and run-scoped paths
├── pipeline/
│   ├── fetch_sources.py               Fetch permitted public source responses
│   ├── normalize_external.py          Normalize mapped CSV/JSON/HTML responses
│   ├── run_company.py                One-command company workflow
│   ├── run_analysis.py                Validate, derive, and write analysis artifacts
│   ├── register_source.py             Register a local source file
│   ├── derive_metrics.py              Build auditable calculated metrics
│   ├── validate/                      Dataset and accounting controls
│   └── verify/                       OCR-assisted review reports
├── reports/                           Generated review and audit outputs
├── skills/psx-equity-analyst/         Research-analysis instructions
├── tests/                             Automated schema/data tests
└── readme.md                          This document
```

Generated OCR artifacts and reports are retained because they provide an
audit trail for extraction and review. They are not a replacement for the
original source PDF.

## Setup

The project is packaged as `finura` (`pyproject.toml`) and pinned to Python
3.12 (`.python-version`). With [uv](https://docs.astral.sh/uv/):

```bash
uv sync            # creates .venv with Python 3.12, pydantic, and pytest
uv run pytest -q
```

Without uv, use any Python 3.12 environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e . pytest
```

The legacy `pipeline/` scripts run from the repository root. Most use only
the standard library; `pipeline/fetch_sources.py` imports `finura`, so run it
with `uv run`.

Validate the v2 candidates with the Finura engine (see
[docs/VALIDATION.md](docs/VALIDATION.md)). It writes a report to a path you
choose, never into `data/v2/` or `runs/`:

```bash
uv run python -m finura.validation \
  --facts data/v2/facts/FFC/financial_facts.json \
  --sources data/v2/sources/source_registry.json \
  --evidence-root . --companies data/v2/companies/company_registry.json \
  --out /tmp/ffc-validation.json
```

FFC currently gets `incomplete` (exit status 3): all 12 accounting checks pass,
but its identity and sector are unverified.

## Validate the current dataset

Run the focused test suite:

```bash
python -m pytest -q
```

Run the executable validators:

```bash
python pipeline/validate/validate_financial_facts.py
python pipeline/validate/check_reconciliations.py
python pipeline/validate/check_cash_flows.py
python pipeline/derive_metrics.py --company FFC
python pipeline/run_analysis.py --company FFC --validate
```

Structured source responses can be normalized with an explicit mapping:

```bash
python pipeline/normalize_external.py \
  --company FFC \
  --input data/raw/FFC/external/psx/prices.csv \
  --mapping config/ffc_market_mapping.json \
  --source-id src_example \
  --kind market \
  --output data/normalized/FFC/market_data.json
```

The importer does not guess field meanings. Financial imports remain
`needs_final_review` until verified against the original source.

The expected current result is a passing test suite and zero validator
errors. Validators exit with status `0` on success and non-zero on errors.
Warnings do not necessarily fail the validator, so they must still be read.

Regenerate the OCR-assisted reports when the normalized facts, OCR text, or
verification rules change:

```bash
python pipeline/verify/compare_ocr_facts.py
python pipeline/verify/verify_financial_rows.py
python pipeline/verify/verify_year_columns.py
```

These scripts write text and CSV reports to `reports/` and deliberately do
not change financial facts or verification statuses. The verification scripts
remain source-layout-specific until an extraction adapter is supplied for a
company. Normalization, validation, and derived metrics are company-agnostic.

## Register a source

Initialize a new company workspace:

```bash
python pipeline/init_company.py --company ENGRO
```

Then collect and normalize permitted source data before running analysis.
Initializing a ticker does not create financial facts or claim that current
data exists.

Preserve the downloaded file first, then register it:

```bash
python pipeline/register_source.py \
  --company FFC \
  --title "FFC Financial Results for Year Ended 31 December 2025" \
  --type announcement \
  --file data/raw/FFC/ffc_report.pdf \
  --url "https://dps.psx.com.pk/download/document/269389.pdf" \
  --published-at 2025-12-31 \
  --notes "Describe document scope and extraction limitations."
```

Supported source types are `annual_report`, `quarterly_report`,
`announcement`, `market_data`, and `other`.

Registration:

- rejects missing files;
- accepts only `http://` and `https://` URLs;
- validates `YYYY-MM-DD` publication dates;
- computes a SHA-256 hash;
- avoids registering identical content twice for one company;
- writes an atomic registry replacement;
- stores repository-relative paths when the source is inside the repository.

The script does not download files, discover PSX filings, or verify that a
URL is authoritative. Those remain deliberate human-controlled steps.
The same registration contract applies to any ticker; replace `FFC` with the
company identifier.

Fetch public source responses from hosts whose access policy permits it:

```bash
uv run python pipeline/fetch_sources.py --company FFC --url "<permitted URL>"
uv run python pipeline/fetch_sources.py --company FFC --discover --delay 2
```

Every request, discovered link, and redirect is checked against
`config/access_policies.json` before any network contact. PSX
(`psx.com.pk` and all subdomains) is prohibited by PSX's terms of use, and
the other catalog providers are prohibited or unclear under their own terms. Both commands therefore
currently refuse every URL and exit non-zero. Download PSX documents manually
and register them with `pipeline/register_source.py` (above), which works
offline. See [docs/SOURCE_POLICY.md](docs/SOURCE_POLICY.md).

The complete deterministic analysis run is:

```bash
python pipeline/run_analysis.py --company FFC --validate
```

Or use the one-command workflow for a new or existing ticker:

```bash
python pipeline/run_company.py --company ENGRO --validate
```

This initializes missing contracts, but it requires actual normalized source
data before analysis. It does not invent statistics. Use
`--allow-empty` only when you want a data-readiness report:

```bash
python pipeline/run_company.py --company ENGRO --allow-empty --validate
```

With data present, it initializes missing contracts, runs validation, derives metrics, and
generates the report plus `reports/ENGRO/hermes_context.json`. Add
`--fetch-discover` to run the collector first. Under the current access
policies it refuses every URL, so the analysis stops with a non-zero exit:

```bash
uv run python pipeline/run_analysis.py --company FFC --fetch-discover --validate
```

Use explicit URLs when a provider exposes a known public document:

```bash
python pipeline/run_analysis.py --company FFC \
  --url "https://example.com/public/ffc-report.pdf" --validate
```

It writes [`reports/FFC/fundamental_analysis.md`](/home/bilal/projects/psx-research/reports/FFC/fundamental_analysis.md)
and the machine-readable
[`reports/FFC/fundamental_analysis.json`](/home/bilal/projects/psx-research/reports/FFC/fundamental_analysis.json).
The report's confidence and gaps reflect the data actually normalized in the
repository; it does not claim to have fetched data that is not present.

## Data and evidence rules

- Keep original documents unchanged under `data/raw/<COMPANY>/`.
- Link every fact to a `source_id` and a page or source location.
- Keep standalone and consolidated facts separate.
- Keep units, signs, reporting periods, and comparative years explicit.
- Never convert missing data to zero.
- Never treat an OCR match as manual verification.
- Do not overwrite a prior source when a correction or restatement appears;
  preserve both and document which one is authoritative.
- Separate reported facts, calculations, estimates, assumptions, and
  interpretation.
- Do not use a secondary source when a primary filing is available merely
  because extraction is inconvenient.

See [docs/DATA_SCHEMA.md](/home/bilal/projects/psx-research/docs/DATA_SCHEMA.md),
[docs/INGESTION_PIPELINE.md](/home/bilal/projects/psx-research/docs/INGESTION_PIPELINE.md),
and [docs/SOURCE_POLICY.md](/home/bilal/projects/psx-research/docs/SOURCE_POLICY.md)
for the authoritative details.

## Research-analysis skill

[`skills/psx-equity-analyst/SKILL.md`](/home/bilal/projects/psx-research/skills/psx-equity-analyst/SKILL.md)
defines the analysis layer. It requires evidence-backed fundamental research,
period-aware comparisons, explicit uncertainty, and separation of facts from
calculations and interpretation. It does not authorize unsupported price
targets, BUY/HOLD/SELL labels, position sizing, or fabricated data.

## Known limitations and future extensions

The repository is intentionally narrow at this stage:

- source discovery and downloading are manual;
- the normalized schema is JSON rather than a database;
- accounting and OCR verification scripts still need generic adapters for
  different statement layouts;
- there is no market-price, corporate-action, macroeconomic, or valuation
  dataset yet;
- OCR report generation is not an OCR engine or a substitute for visual
  review;
- there is no CI workflow or package entry point.

Future multi-company work should populate
`data/normalized/<COMPANY>/financial_facts.json` from registered sources,
parameterize source-layout adapters, add market and valuation datasets, and
retain the same provenance and verification standards.
