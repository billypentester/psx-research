# Source and Evidence Policy

This policy governs which evidence may support PSX financial research and
how uncertainty is represented. It applies to source registration, fact
extraction, verification, and analysis.

## Evidence hierarchy

Use the strongest applicable primary source:

### Financial statements

1. Official PSX-filed financial statements and results announcements.
2. Official company annual and quarterly reports.
3. Official company presentations and investor-relations material.
4. Reputable third-party providers for cross-checking only.

### Market data

1. Official PSX market data, subject to access and licence terms.
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
3. Other screening providers, clearly identified and dated.

Record methodology and effective dates where available. Do not assume a
company's Shariah status remains unchanged indefinitely.

## Provenance requirements

For every source, preserve:

- source ID and company ID;
- title and source type;
- original URL when known;
- publication date when known;
- retrieval timestamp with timezone;
- local path to the preserved file;
- SHA-256 hash;
- relevant scope limitations and notes.

For every financial fact, preserve:

- canonical metric;
- value and unit;
- reporting period;
- standalone/consolidated scope;
- source ID;
- supporting page or source location;
- verification status.

A hash detects file changes. It does not prove authority, completeness, or
transcription accuracy. A search-result snippet is never sufficient evidence
for a material financial claim.

## Extraction and verification

Review the original source for:

- row label;
- sign and parentheses;
- year column;
- units;
- reporting period;
- standalone/consolidated scope;
- audited/unaudited and comparative/restated context;
- source page and annexure.

OCR matching, row-label matching, and arithmetic reconciliation are
supporting checks. They do not independently establish that a value agrees
with the source. A value may be marked `verified` only after the original
source has been checked.

## Conflict and restatement handling

- Prefer the latest official filing that explicitly corrects or restates an
  earlier figure.
- Preserve earlier sources and their hashes.
- Do not silently overwrite historical records.
- Document why a source was selected as authoritative.
- Keep unresolved conflicts visible.
- Do not treat disputed values as established facts.
- Do not let a presentation override filed statements without documented
  correction evidence.

## Fact classification

Keep these concepts separate in analysis:

- **Reported:** explicitly published by a source.
- **Calculated:** derived from identified inputs and a documented formula.
- **Estimated:** approximated using a disclosed method and assumptions.
- **Missing:** unavailable or not reliably established.
- **Management-provided:** a company claim that may not be a financial
  statement figure.

The current JSON schema has no dedicated classification field for all of
these concepts. Until it is extended, document classification in analysis
and never present an estimate as a reported figure.

## Current verification statuses

The implemented validator accepts:

- `verified`;
- `ocr_unverified`;
- `needs_final_review`;
- `estimated`;
- `missing`.

`estimated` and `missing` are currently accepted for compatibility even
though they describe classification/availability more than evidence quality.
The validator does not accept `pending` or `rejected`.

## Access, licensing, and responsible use

- Prefer official downloads and permitted APIs.
- Respect website terms, copyright, rate limits, and data licences.
- Do not bypass authentication or access controls.
- Do not fabricate URLs, dates, page numbers, values, or management claims.
- Preserve source limitations rather than hiding them.

## Analysis rules

Use validated, source-linked facts for financial conclusions. Every material
claim should be traceable to a source or to an explicitly shown calculation.
Separate:

1. reported facts;
2. calculations;
3. company/management claims;
4. assumptions;
5. analyst interpretation;
6. uncertainty and data gaps.

Do not calculate derived metrics from unverified inputs. Detect mergers or
acquisitions before calculating year-over-year growth, and explain
comparability issues between pre- and post-merger periods.

The research layer should provide a fundamental thesis, valuation range when
inputs support one, catalysts, risks, and thesis-breaking conditions. Do not
add position sizing or BUY/HOLD/SELL labels unless the user explicitly asks
for them and the necessary evidence is available.
