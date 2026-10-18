# PSX Research — Ingestion Pipeline

## 1. Objective

Maintain a reproducible, source-traceable workflow for collecting
official PSX financial documents, extracting financial facts, checking
their integrity, and preparing validated data for analysis.

The initial implementation uses FFC FY2025 financial results. The
workflow should ultimately be reusable for other PSX companies.

## 2. Pipeline Stages

### Stage 1: Source discovery

- Identify official PSX filings and company financial reports.
- Record the document title, URL, publication date, period, and type.
- Do not treat search snippets as financial evidence.
- Discovery and downloading remain manual workflow steps.

### Stage 2: Preserve and register

- Preserve original documents under `data/raw/<COMPANY>/`.
- Register sources using `pipeline/register_source.py`.
- Record source metadata and SHA-256 integrity hashes.
- Avoid registering identical content repeatedly for the same company.
- Preserve corrections and replacement documents as separate sources.

### Stage 3: Extract

- Extract financial statement values from source documents.
- Use OCR when necessary for scanned documents.
- Preserve signs, original labels, units, reporting periods, scope,
  and source locations.
- Treat OCR output as unverified until checked against the original.

### Stage 4: Normalize

- Store facts in `data/normalized/<COMPANY>/financial_facts.json`.
- Follow the implemented schema in `DATA_SCHEMA.md`.
- Distinguish standalone from consolidated statements.
- Distinguish quarterly figures from cumulative year-to-date figures.
- Keep reporting dates and units consistent.
- Preserve source references for every fact.

### Stage 5: Verify

- Compare extracted values against the original source.
- Check row labels, signs, year columns, units, and reporting scope.
- Inspect high-resolution page images when OCR is ambiguous.
- Record review evidence and discrepancies.
- Do not mark a fact verified solely because OCR matching or
  arithmetic reconciliation passes.

### Stage 6: Validate

Run these commands from the repository root:

```bash
python -m pytest -q
python pipeline/validate/validate_financial_facts.py
python pipeline/validate/check_reconciliations.py
python pipeline/validate/check_cash_flows.py
```
