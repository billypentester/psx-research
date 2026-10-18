# Ingestion and Verification Pipeline

This is the operating procedure for turning public source material into
auditable financial facts and a reproducible analysis report. The pipeline is
company-agnostic; FFC is the current fixture.

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
                                      |
                                      v
                         fundamental analysis report
```

Automated checks support review. They do not replace reading the source
document, checking signs and columns, or resolving ambiguities.

## Stage 1: Discover the source

For a new ticker, initialize the generic workspace first:

```bash
python pipeline/init_company.py --company ENGRO
```

This creates empty contracts under `data/normalized/ENGRO/`. Empty contracts
are safe but contain no evidence; the analysis report will remain low
confidence until sources are collected, normalized, and verified.

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

For structured CSV, JSON, or HTML responses, use an explicit mapping:

```bash
python pipeline/normalize_external.py \
  --company FFC \
  --input data/raw/FFC/external/psx/prices.csv \
  --mapping config/ffc_market_mapping.json \
  --source-id src_example \
  --kind market \
  --output data/normalized/FFC/market_data.json
```

Mappings are provider- and response-specific. Imported financial facts remain
`needs_final_review` until the original response is checked.

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

If `market_data.json` exists, also run:

```bash
python pipeline/validate/validate_market_data.py --company FFC
```

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

## Stage 8: Derive metrics

Run the company-agnostic calculation layer:

```bash
python pipeline/derive_metrics.py --company FFC
```

It writes `data/derived/<COMPANY>/derived_metrics.json`. Calculations are
created only from `verified` inputs. Missing prior periods, zero denominators,
and unverified inputs are retained as explicit missing results with reasons.
The output records formulas and normalized input fact keys so Hermes can cite
the calculation instead of treating it as a reported number.

## Stage 9: Analyze

Only use facts whose source, period, scope, unit, and verification state are
clear. Label derived ratios and calculations as calculations, identify
assumptions, and disclose missing or disputed data. See the
[`psx-equity-analyst` skill](/home/bilal/projects/psx-research/skills/psx-equity-analyst/SKILL.md)
for the analysis workflow.

## Stage 10: Run the complete pipeline

The one-command workflow is:

```bash
python pipeline/run_company.py --company ENGRO --validate
```

This command requires normalized financial facts. Initializing a company does
not fetch or invent statistics. For an intentional empty readiness report,
use `--allow-empty`.

It initializes missing company contracts before running the analysis. To
include bounded public-source collection:

```bash
python pipeline/run_company.py \
  --company ENGRO \
  --fetch-discover \
  --validate
```

It produces an additional `reports/<COMPANY>/hermes_context.json` evidence
package. Hermes should consume that package rather than reading arbitrary
provider pages directly.

After source collection and normalization, run:

```bash
python pipeline/run_analysis.py --company FFC --validate
```

To include a bounded public-source collection pass:

```bash
python pipeline/run_analysis.py --company FFC --fetch-discover --validate
```

Or provide explicit permitted URLs:

```bash
python pipeline/run_analysis.py --company FFC \
  --url "https://example.com/public/ffc-report.pdf" --validate
```

This validates normalized facts, runs accounting controls, regenerates
derived metrics, and writes:

```text
data/derived/<COMPANY>/derived_metrics.json
reports/<COMPANY>/fundamental_analysis.json
reports/<COMPANY>/fundamental_analysis.md
```

The report uses the latest normalized period, but it does not imply that the
latest period is the latest period available on the internet. That depends on
which permitted sources have been collected and normalized. Missing market
data, dividends, debt, segments, peers, or valuation inputs are reported as
gaps rather than inferred.

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
