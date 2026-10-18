# PSX Research — Source Policy

## 1. Objective

Maintain reliable, source-traceable evidence for PSX financial research.
Every material financial claim must be supported by appropriate sources,
and unresolved discrepancies must remain visible.

## 2. Source Hierarchy

### Financial statements
1. Official PSX-filed financial statements and results announcements.
2. Official company annual and quarterly reports.
3. Official company presentations and investor-relations material.
4. Reputable third-party providers for cross-checking.

### Market data
1. Official PSX market data, subject to applicable access and licensing.
2. Secondary providers for cross-checking, with methodology documented.

### Corporate actions
1. Official PSX announcements.
2. Official company notices.
3. Third-party calendars for cross-checking only.

### Macroeconomic data
1. State Bank of Pakistan for monetary and banking indicators.
2. Pakistan Bureau of Statistics for official statistical releases.
3. Relevant government agencies.
4. Third-party sources when official data is unavailable.

### Shariah status
1. Applicable official PSX/KMI screening publications and methodology.
2. Official company disclosures where relevant.
3. Other screening providers, identified separately.

Record the methodology and effective date when available. Do not assume
a company's Shariah status remains unchanged indefinitely.

## 3. Provenance and Integrity

Preserve the available source metadata:

- Source ID, company ID, title, and source type.
- Original URL and publication date, when known.
- Retrieval timestamp with timezone.
- Local path to the preserved file.
- SHA-256 hash and relevant source limitations.

Each financial fact must link to a registered source and identify the
supporting page or source location.

A hash detects file changes; it does not prove that the source is
authoritative or that a financial figure was transcribed correctly.
Search-result snippets alone are not sufficient financial evidence.

## 4. Conflict Resolution

- Prefer the latest official filing that explicitly corrects or restates
  an earlier figure.
- Preserve earlier source records; do not silently overwrite history.
- Document why a source was selected as authoritative.
- Disclose unresolved conflicts and do not treat disputed figures as
  established facts.
- Do not let a presentation override filed financial statements without
  documented evidence of a correction.

## 5. Evidence and Verification

- Compare extracted values with the original source.
- Check row labels, signs, year columns, units, dates, and reporting scope.
- Reconcile statement totals where applicable.
- Distinguish quarterly figures from cumulative year-to-date figures.
- Identify audited, unaudited, comparative, and restated figures when
  the source provides that information.
- Record review evidence and discrepancies.
- Do not claim a fact was verified unless the original source was checked.

OCR matching, row-label matching, and arithmetic reconciliation are
supporting checks. None independently proves that a value matches the
original document.

## 6. Current Verification Statuses

The current validator accepts:

- `verified`: checked against the original source document.
- `ocr_unverified`: not yet confirmed against the original document.
- `needs_final_review`: requires additional review.
- `estimated`: accepted by the validator, but describes a data
  classification rather than evidence quality.
- `missing`: accepted by the validator, but describes data availability
  rather than evidence quality.

The last two statuses expose a schema limitation. A future schema
should separate fact classification from verification status.

The current validator does not accept `pending` or `rejected`. Do not
use these values until the schema, validator, and tests are updated.

## 7. Data Classification

Keep these concepts distinct:

- Reported: explicitly published by a source.
- Calculated: derived from identified inputs and a documented formula.
- Estimated: approximated using a disclosed method and assumptions.
- Missing: unavailable or not reliably established.

The current schema does not yet implement a dedicated classification
field for all these concepts. Never present an estimate as a reported
figure or replace a missing value with zero.

## 8. Access and Use

- Prefer official downloads, documented APIs, and permitted access.
- Respect website terms, copyright, rate limits, and data licences.
- Do not bypass authentication or access restrictions.
- Never fabricate source URLs, publication dates, page numbers, or values.

## 9. Hermes Analysis Rules

- Use validated, source-linked facts for financial conclusions.
- Identify sources for material financial claims.
- Separate reported facts, calculations, assumptions, and interpretation.
- Disclose missing data, limitations, and unresolved discrepancies.
- Do not describe automated checks as manual verification.
- Do not make unsupported claims about source quality or Shariah status.
