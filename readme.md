# PSX Financial Research Pipeline

A source-traceable financial data ingestion and validation pipeline for Pakistan Stock Exchange (PSX) equity research.

## Current Status

- Initial ingestion and validation workflow implemented using FFC FY2025 financial results.
- Source PDF and SHA-256 provenance recorded in the source registry.
- 60 financial facts extracted into normalized JSON.
- Balance sheet and cash flow reconciliation checks pass.
- OCR row-label and year-column checks pass for all 60 facts.
- All 60 financial facts are marked `verified` following review against the original source.
- Automated tests pass.

**Important:** OCR matching and arithmetic reconciliation are supporting checks, not substitutes for source verification. Re-run tests and validators after changing facts, source files, or validation logic.

## Environment Setup

Python 3.12 is recommended.