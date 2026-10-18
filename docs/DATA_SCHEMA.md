# PSX Research — Data Schema

## 1. Purpose

Define the implemented JSON structures for source-linked PSX financial
facts and source documents. FFC is the initial implementation.

This document distinguishes the current schema from planned extensions.
The current schema is authoritative for existing data and validation.

## 2. Design Principles

- Preserve original source documents under `data/raw/`.
- Link every financial fact to a registered source and source location.
- Keep standalone and consolidated facts separate.
- Preserve reporting dates, period types, and units explicitly.
- Do not replace missing values with zero.
- Do not treat OCR output, arithmetic reconciliation, or matching labels
  as proof of source accuracy.
- Make schema changes deliberately and test existing records.

## 3. Current Financial Facts Structure

File: `data/normalized/FFC/financial_facts.json`

The top-level JSON object contains:

| Field | Type | Meaning |
|---|---|---|
| company_id | string | Company identifier, currently `FFC` |
| currency | string | Reporting currency, currently `PKR` |
| facts | array | Financial fact records |

### 3.1 Financial fact record

Each record currently contains these fields:

| Field | Type | Meaning |
|---|---|---|
| metric | string | Canonical metric identifier |
| scope | string | `standalone` or `consolidated` |
| period_end | string | Reporting period end in ISO `YYYY-MM-DD` format |
| period_type | string | Reporting period classification, e.g. `annual` |
| value | number | Reported numeric value |
| unit | string | Unit associated with the value |
| source_id | string | Identifier of a source in the registry |
| source_page | string | Page or source location supporting the value |
| verification_status | string | Current validation status of the fact |

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
