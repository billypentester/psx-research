# PSX Financial Research Pipeline

A source-traceable financial data ingestion and validation pipeline for Pakistan Stock Exchange (PSX) equity research.

## Current Status

- Initial ingestion and validation workflow implemented using FFC FY2025 financial results.
- Source PDF and SHA-256 provenance recorded in the source registry.
- 60 financial facts extracted into normalized JSON.
- Balance sheet and cash flow reconciliation checks pass.
- OCR row-label and year-column checks pass for all 60 facts.
- 28 facts visually verified; 32 remain marked `ocr_unverified`.
- Automated tests pass.

**Important:** OCR matching and reconciliation checks do not independently prove that a financial figure matches the original source. Keep facts marked `ocr_unverified` until they have been independently checked against the source document.

## Environment Setup

Python 3.12 is recommended.