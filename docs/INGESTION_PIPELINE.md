
cat > docs/INGESTION_PIPELINE.md <<'EOF'
# PSX Research — Ingestion Pipeline

## 1. Objective

Build a reproducible pipeline that collects official financial documents,
extracts financial facts, normalizes values, validates data integrity,
and stores source-linked records for downstream analysis.

Initial target: Fauji Fertilizer Company (FFC).

## 2. Pipeline Stages

### Stage 1: Source discovery
- Identify official PSX filings and FFC financial reports.
- Record document title, URL, publication date, reporting period, and type.
- Do not treat search snippets as financial evidence.

### Stage 2: Fetch
- Download documents through permitted official access methods.
- Save original files under data/raw/FFC/.
- Avoid downloading the same unchanged document repeatedly.
- Record retrieval timestamp, source URL, and SHA-256 hash.
- Report failed downloads without silently skipping them.

### Stage 3: Register sources
- Assign each document a stable source_id.
- Save source metadata in a machine-readable manifest.
- Keep the original file unchanged.
- Track corrections and replacement documents separately.

### Stage 4: Extract
- Extract tables and relevant statement values from PDFs or other files.
- Preserve the original labels, values, units, and page numbers.
- Flag ambiguous, scanned, incomplete, or poorly extracted content.
- Never automatically treat OCR output as verified.

### Stage 5: Normalize
- Map source labels to canonical metric names in DATA_SCHEMA.md.
- Normalize dates, reporting periods, currency, and units.
- Distinguish standalone from consolidated statements.
- Distinguish quarterly figures from cumulative year-to-date figures.
- Retain original values and labels for auditability.

### Stage 6: Validate
- Check required fields, types, units, period dates, and source references.
- Check duplicates and inconsistent reporting scopes.
- Reconcile reported subtotals and totals where possible.
- Compare extracted facts against the original document.
- Mark records pending, verified, or rejected.
- Block dependent calculations when required inputs are disputed.

### Stage 7: Persist
- Save normalized facts separately from raw files.
- Keep calculated metrics separate from reported facts.
- Use deterministic record identifiers and documented update rules.
- Never silently overwrite a previously reported or restated value.

### Stage 8: Calculate
- Calculate ratios and growth metrics using Python.
- Record formulas and the exact input fact identifiers.
- Validate calculations with unit tests and known examples.

### Stage 9: Analyze
- Supply Hermes with validated data and source references.
- Require it to distinguish facts, calculations, assumptions, and opinions.
- Disclose material missing data and unresolved discrepancies.

## 3. Initial Deliverables

1. FFC source manifest.
2. Raw official financial reports.
3. Extracted financial facts in JSON.
4. Normalized financial facts in JSON.
5. Validation report identifying passed and failed checks.
6. Unit-tested Python calculation functions.
7. Source-linked financial summary for Hermes.

## 4. Initial Metrics

Revenue, cost of sales, gross profit, operating profit, finance cost,
profit before tax, income tax expense, profit after tax, EPS, total
assets, total liabilities, total equity, operating cash flow, investing
cash flow, financing cash flow, capital expenditure, cash balances,
borrowings, and dividends per share.

Extract only metrics supported by the source.

## 5. Error Handling

- Network failure: report the error and allow a controlled retry.
- Missing document: log it; do not invent or substitute data silently.
- Extraction failure: quarantine the document for manual review.
- Validation failure: mark affected facts as rejected or pending.
- Conflicting sources: apply SOURCE_POLICY.md and retain provenance.
- Schema change: document the change and test existing records.

## 6. Acceptance Criteria

The first FFC dataset is acceptable only when:
- Every reported fact has a source reference.
- Values, units, reporting periods, and scopes are consistent.
- A reviewer can locate the original figure in its source document.
- Validation failures are visible rather than hidden.
- Calculations are reproducible from stored inputs.
- Re-running ingestion does not create duplicate records.

## 7. Implementation Order

1. Build source manifest and document registry.
2. Fetch and preserve one official FFC report.
3. Extract a small set of facts manually or with assisted extraction.
4. Normalize and validate those facts.
5. Add automated PDF extraction.
6. Add calculation functions and tests.
7. Expand to additional reporting periods only after acceptance criteria pass.
EOF
