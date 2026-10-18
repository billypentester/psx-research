
cat > docs/SOURCE_POLICY.md <<'EOF'
# PSX Research — Source Policy

## 1. Objective

Ensure every financial figure, market value, and Shariah status is
supported by an identifiable source and can be independently verified.

## 2. Source Hierarchy

### Financial statements
1. Official PSX-filed financial statements and result announcements.
2. Official company annual reports and quarterly reports.
3. Official company presentations and investor-relations material.
4. Reputable third-party financial-data providers, for cross-checking only.

### Market prices and volume
1. Official PSX market data, subject to access and licensing terms.
2. Other providers only as secondary verification, with source and
   adjustment methodology documented.

### Corporate actions
1. Official PSX announcements.
2. Official company notices and shareholder communications.
3. Third-party calendars only for cross-checking.

### Macroeconomic data
1. State Bank of Pakistan for monetary and banking indicators.
2. Pakistan Bureau of Statistics for official statistical releases.
3. Relevant government departments and official agencies for other
   indicators.
4. Third-party sources only when official data is unavailable.

### Shariah status
1. Applicable official PSX/KMI screening publications and methodology.
2. Official company disclosures where relevant.
3. Other screening providers only as separately identified opinions.

Always record the source, methodology, effective date, and screening
universe when available. Never assume a company's status is permanent.

## 3. Conflict Resolution

- Prefer the latest official filing that explicitly corrects or restates
  an earlier figure.
- Do not silently overwrite earlier values.
- Preserve both the original and corrected source records.
- Record the reason for choosing the authoritative value.
- If a conflict cannot be resolved, mark the fact as disputed and
  exclude it from dependent calculations.
- A presentation does not override a filed financial statement without
  documented evidence of a correction.

## 4. Evidence Requirements

For every extracted financial fact, retain:
- Source identifier and document title.
- Original URL and retrieval timestamp.
- Page number or source location, where available.
- Original statement label.
- Original value and unit, where practical.
- Normalized value and unit.
- Verification status and reviewer notes.

A search-result snippet alone is not sufficient evidence for a
financial figure.

## 5. Data Classification

- reported: explicitly published by a source.
- calculated: derived from identified input facts and a recorded formula.
- estimated: an approximation with a disclosed method and assumptions.
- missing: unavailable or not reliably established.

Do not present estimates as reported figures. Do not replace missing
values with zero.

## 6. Verification

- Verify extracted values against the original document.
- Reconcile statement totals where applicable.
- Check units, dates, reporting scope, and period type.
- Distinguish quarterly results from year-to-date cumulative results.
- Identify audited, unaudited, restated, and comparative figures.
- Record unresolved discrepancies and block affected calculations.

## 7. Automation and Access

- Prefer official downloads, documented APIs, and permitted data access.
- Respect website terms, copyright, rate limits, and market-data licences.
- Do not bypass authentication or access restrictions.
- Preserve source files and calculate a SHA-256 hash when practical.
- Never fabricate a source URL, publication date, page number, or value.

## 8. Hermes Analysis Rules

- Use validated data for financial calculations and conclusions.
- Cite source identifiers for material financial claims.
- Explicitly disclose missing or disputed information.
- Separate source facts, calculations, assumptions, and interpretation.
- Do not claim that a figure was verified unless verification occurred.
EOF


## 7. Verification Status Definitions

The `verification_status` field describes the evidence state of a fact;
it does not describe whether the figure was reported or calculated.

- `verified`: checked against the original source document, with the
  source location and evidence recorded.
- `ocr_unverified`: extracted or corroborated through OCR, but not yet
  confirmed against the original document.
- `needs_final_review`: a candidate value or source match exists, but
  final review is still required.
- `pending`: verification has not yet been completed.
- `rejected`: the candidate value or extraction was found to be wrong
  or unsupported. Preserve the evidence and correction history.

A matching number on an OCR page is not sufficient for `verified`.
Row-label matching and arithmetic reconciliation are supporting checks,
not substitutes for confirming the source value. Do not automatically
change verification statuses based only on automated matching results.
