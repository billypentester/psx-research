# Ingestion and Verification Pipeline

This is the operating procedure for turning a PSX filing into auditable
financial facts. The current implementation is complete for the FFC fixture,
but source discovery and downloading remain manual by design.

## Pipeline overview

```text
official source
      |
      v
preserve raw file --> register source + SHA-256
      |
      v
extract/OCR --> normalize facts --> automated validation
                                      |
                                      v
                  OCR comparison + row/year-column checks
                                      |
                                      v
                         visual source verification
                                      |
                                      v
                              analysis-ready facts
```

Automated checks support review. They do not replace reading the source
document, checking signs and columns, or resolving ambiguities.

## Stage 1: Discover the source

Prefer an official PSX filing or company investor-relations document.
Capture, where available:

- company/ticker;
- document title and type;
- official URL;
- publication date;
- reporting period;
- whether the document is audited, unaudited, comparative, restated, or
  a results announcement;
- any scope limitation, such as an attached statement rather than a full
  annual report.

Do not use search snippets as evidence and do not fabricate missing metadata.

## Stage 2: Preserve and register

Place the original file at:

```text
data/raw/<COMPANY>/<filename>
```

Register it from the repository root:

```bash
python pipeline/register_source.py \
  --company FFC \
  --title "Document title" \
  --type announcement \
  --file data/raw/FFC/ffc_report.pdf \
  --url "https://official.example/document.pdf" \
  --published-at 2025-12-31 \
  --notes "Known limitations"
```

The registrar computes SHA-256, stores a retrieval timestamp in UTC, and
does not duplicate identical content for the same company. A different
correction or replacement file remains a separate source.

The registrar does not download, OCR, or validate the source's authority.

## Stage 3: Extract

Extract values from the original pages. Use OCR for scanned documents, but
retain:

- original row label;
- sign and parentheses;
- reporting-year column;
- statement scope;
- unit;
- period end and period type;
- source page or annexure location;
- any dash, blank, or not-applicable marker.

Store OCR text and page images under:

```text
data/normalized/<COMPANY>/
```

Do not mark a fact verified during extraction. OCR can merge columns, lose
minus signs, misread digits, or attach a value to the wrong row.

## Stage 4: Normalize

Write canonical records to:

```text
data/normalized/<COMPANY>/financial_facts.json
```

Follow [DATA_SCHEMA.md](./DATA_SCHEMA.md). Keep standalone and consolidated
records distinct and never mix quarterly values with cumulative year-to-date
values. Use a separate record for each period and unit.

## Stage 5: Run automated controls

Run the tests and validators:

```bash
python -m pytest -q
python pipeline/validate/validate_financial_facts.py
python pipeline/validate/check_reconciliations.py
python pipeline/validate/check_cash_flows.py
```

### Dataset and provenance validation

`validate_financial_facts.py` validates required fields, allowed values,
dates, finite numeric values, duplicate keys, source existence, repository
path containment, and SHA-256 integrity.

### Balance-sheet reconciliation

`check_reconciliations.py` compares, per scope and period:

```text
total_assets == total_equity_and_liabilities
```

It warns when a total is missing and errors on unit mismatches or unequal
values. This is an accounting consistency check, not proof that every
component row was transcribed correctly.

### Cash-flow reconciliation

`check_cash_flows.py` checks each current scope (`standalone`,
`consolidated`) and year (`2024`, `2025`):

```text
operating + investing + financing == net_change
beginning + net_change + FX effect + merger cash == ending
```

The merger-cash line is treated as zero when absent, matching the script's
current logic. Missing required facts produce errors. This validator is
specific to the current annual FFC data model.

## Stage 6: Generate OCR-assisted review reports

Run:

```bash
python pipeline/verify/compare_ocr_facts.py
python pipeline/verify/verify_financial_rows.py
python pipeline/verify/verify_year_columns.py
```

The scripts write:

- `reports/ffc_ocr_comparison.txt` and `.csv`;
- `reports/ffc_row_verification.txt` and `.csv`;
- `reports/ffc_year_column_verification.txt` and `.csv`.

The checks map `Annexure A, page N of 8` to the filing PDF page by adding
two pages, then inspect the corresponding second-pass OCR text. They:

- look for the stored numeric value;
- require the canonical row label for row-aware matching;
- inspect the year header and target-year column;
- handle the current merger-row dash placeholder.

These scripts are diagnostic/reporting tools. They explicitly do not mutate
facts or verification statuses.

## Stage 7: Manually verify the source

For every fact intended for analysis:

1. open the original PDF page or a high-resolution page image;
2. confirm the statement scope;
3. confirm the row label;
4. confirm the reporting-year column;
5. confirm sign, decimals, and unit;
6. confirm the source location recorded in the fact;
7. record discrepancies and review evidence;
8. set `verification_status` to `verified` only after the original is
   checked.

The current FFC review audit records a visual review of all 32 facts that
were previously `ocr_unverified`, including the cash-flow pages. The final
fixture contains 60 `verified` facts.

## Stage 8: Analyze

Only use facts whose source, period, scope, unit, and verification state are
clear. Label derived ratios and calculations as calculations, identify
assumptions, and disclose missing or disputed data. See the
[`psx-equity-analyst` skill](/home/bilal/projects/psx-research/skills/psx-equity-analyst/SKILL.md)
for the analysis workflow.

## Re-running safely

Before changing facts or scripts:

1. inspect `git status`;
2. preserve any review evidence;
3. run the baseline tests and validators;
4. make the smallest coherent change;
5. regenerate affected reports;
6. rerun tests and validators;
7. inspect warnings as well as exit codes.

Do not delete raw sources, audit reports, or backup review artifacts to hide
a discrepancy. Correct the data and document why.
