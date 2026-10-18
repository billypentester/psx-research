# PSX Financial Research Pipeline

A source-traceable, evidence-first workflow for collecting, normalizing,
verifying, and validating financial data used in Pakistan Stock Exchange
(PSX) equity research.

The repository currently contains a complete first implementation for Fauji
Fertilizer Company Limited (`FFC`) using its FY2025 PSX financial-results
filing and comparative FY2024 figures. It is a research data foundation, not
a trading system, portfolio manager, or automated investment-advice service.

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
10. Use only source-linked, validated facts in downstream analysis.

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

The filing is a results announcement with attached financial statements, not
the company's full annual report. The source registry records this limitation.

## Repository layout

```text
.
├── data/
│   ├── raw/<COMPANY>/                 Preserved source documents
│   ├── normalized/<COMPANY>/          Canonical facts, OCR, and page images
│   └── source_registry.json           Source metadata and SHA-256 hashes
├── docs/
│   ├── DATA_SCHEMA.md                 JSON contracts and field definitions
│   ├── INGESTION_PIPELINE.md          End-to-end operating procedure
│   └── SOURCE_POLICY.md               Evidence, provenance, and conflict rules
├── pipeline/
│   ├── register_source.py             Register a local source file
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

Python 3.12 is recommended. Create or activate an environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The current test suite uses only the Python standard library and `pytest`.
If `pytest` is not available in the environment, install it in the active
virtual environment:

```bash
python -m pip install pytest
```

Run commands from the repository root.

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
```

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
are currently FFC-specific and expect the existing `data/normalized/FFC/`
layout.

## Register a source

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
- validators and verification scripts are hardcoded to the current FFC
  fixture;
- there is no market-price, corporate-action, macroeconomic, or valuation
  dataset yet;
- fact classification (`reported`, `calculated`, `estimated`, `missing`) is
  not yet a separate schema field;
- OCR report generation is not an OCR engine or a substitute for visual
  review;
- there is no CI workflow or package entry point.

Future multi-company work should parameterize company paths and source
layouts, expand the schema only with migration and test coverage, and retain
the same provenance and verification standards.
