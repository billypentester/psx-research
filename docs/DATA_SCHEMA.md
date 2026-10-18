
cat > docs/DATA_SCHEMA.md <<'EOF'
# PSX Research — Data Schema

## 1. Purpose

Define a consistent, traceable structure for storing PSX company,
financial statement, market, and derived financial data.

Initial implementation: FFC (Fauji Fertilizer Company).

## 2. Core Principles

- Every reported financial figure must have a traceable source.
- Preserve original source documents in data/raw/.
- Never silently replace reported values with calculated values.
- Distinguish reported, calculated, estimated, and missing values.
- Store currency, unit, reporting period, and reporting scope explicitly.
- Distinguish standalone from consolidated financial statements.
- Record restatements and corrections without losing historical provenance.
- Never treat missing data as zero.
- Use ISO 8601 dates: YYYY-MM-DD.
- Use machine-readable numeric values, not formatted strings.

## 3. Entities

### 3.1 Company

| Field | Type | Required | Description |
|---|---|---|---|
| company_id | string | Yes | Stable internal identifier, e.g. FFC |
| ticker | string | Yes | PSX ticker |
| name | string | Yes | Official company name |
| sector | string | Yes | Business sector |
| exchange | string | Yes | PSX |
| shariah_status | string/null | No | compliant, non_compliant, or unknown |
| shariah_source_id | string/null | No | Source supporting the status |
| shariah_effective_date | date/null | No | Date status became effective |

### 3.2 Source

| Field | Type | Required | Description |
|---|---|---|---|
| source_id | string | Yes | Unique immutable identifier |
| company_id | string | No | Related company |
| source_type | string | Yes | annual_report, quarterly_report, announcement, market_data, other |
| title | string | Yes | Document or dataset title |
| url | string/null | No | Original source URL |
| published_at | date/null | No | Publication date |
| retrieved_at | datetime | Yes | Retrieval timestamp with timezone |
| local_path | string/null | No | Path to preserved raw file |
| sha256 | string/null | No | File hash for integrity checking |
| page_number | integer/null | No | Page supporting a specific extracted fact |
| notes | string/null | No | Relevant limitations or context |

A source record identifies a document or dataset. A financial fact
may reference the source and its specific page.

### 3.3 Reporting Period

| Field | Type | Required | Description |
|---|---|---|---|
| period_id | string | Yes | Unique period identifier |
| company_id | string | Yes | Company identifier |
| period_start | date | Yes | First day of reporting period |
| period_end | date | Yes | Last day of reporting period |
| period_type | string | Yes | quarterly, half_year, nine_month, annual |
| reporting_scope | string | Yes | standalone or consolidated |
| is_audited | boolean/null | No | Audit status as reported |
| is_restatement | boolean | Yes | Whether this record reflects a restatement |

### 3.4 Financial Fact

One record represents one metric for one company, period,
reporting scope, and source version.

| Field | Type | Required | Description |
|---|---|---|---|
| fact_id | string | Yes | Unique record identifier |
| company_id | string | Yes | Company identifier |
| period_id | string | Yes | Reporting period |
| metric | string | Yes | Canonical metric name |
| value | number/null | Yes | Numeric value; null when missing |
| unit | string | Yes | PKR, PKR_million, shares, PKR_per_share, percent |
| currency | string/null | No | ISO currency code, e.g. PKR |
| status | string | Yes | reported, calculated, estimated, missing |
| source_id | string/null | Conditional | Required for reported figures |
| page_number | integer/null | No | Page supporting the figure |
| source_label | string/null | No | Original label used in the source |
| verification_status | string | Yes | Verification state: verified, ocr_unverified, needs_final_review, pending, or rejected |
| calculation_method | string/null | No | Formula or method for derived values |
| notes | string/null | No | Adjustments, caveats, or reconciliation notes |

Use null for an unavailable value, not zero. A missing fact must explain
why the value is unavailable when that reason is known.

### 3.5 Market Price

| Field | Type | Required | Description |
|---|---|---|---|
| ticker | string | Yes | PSX ticker |
| date | date | Yes | Trading date |
| open | number/null | No | Opening price |
| high | number/null | No | Highest price |
| low | number/null | No | Lowest price |
| close | number | Yes | Closing price |
| volume | integer/null | No | Traded volume |
| source_id | string | Yes | Source dataset |
| adjustment_type | string | Yes | raw or adjusted |
| currency | string | Yes | PKR |

Do not mix adjusted and unadjusted prices in the same series.

## 4. Initial Financial Metric Catalogue

Use these canonical metric names:

- revenue
- cost_of_sales
- gross_profit
- operating_profit
- finance_cost
- profit_before_tax
- income_tax_expense
- profit_after_tax
- eps
- total_assets
- total_liabilities
- total_equity
- operating_cash_flow
- investing_cash_flow
- financing_cash_flow
- capital_expenditure
- cash_and_cash_equivalents
- short_term_borrowings
- long_term_borrowings
- dividends_per_share
- shares_outstanding

Only extract metrics available in the relevant source. Do not infer
unreported figures without labelling the calculation.

## 5. Units and Normalization

- Preserve the source's original value and label in provenance fields.
- Normalize monetary values to PKR millions where appropriate.
- Normalize per-share metrics to PKR per share.
- Store percentages as numeric percentages, e.g. 12.5 means 12.5%.
- Do not combine PKR, thousands, millions, and billions without conversion.
- Store EPS and dividend per share separately from total profit and dividends.

## 6. Validation Rules

- Every fact must reference a valid company and reporting period.
- Reported facts require a source reference.
- Period start must not be after period end.
- Values must have compatible units and metric definitions.
- Check statement subtotals against reported totals within a documented tolerance.
- Verify quarterly versus year-to-date figures before comparing periods.
- Never compare standalone data with consolidated data without an explicit label.
- Preserve restated values and identify which version is authoritative.
- All calculated facts must record their formula and input fact identifiers.
- Every rejection must include a reason.

## 7. Initial Scope

First dataset: FFC annual reports for 2023–2025 and available 2026
quarterly results.

First objective: establish accurate source-linked financial facts.
Valuation, ratios, forecasting, and automated Hermes analysis follow
only after extraction and validation are reliable.
EOF
