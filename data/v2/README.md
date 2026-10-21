# data/v2: migration candidates (not active)

Nothing in this directory is read by the legacy `pipeline/` scripts. The
active pipeline input is still v1 (`data/source_registry.json` and
`data/normalized/<COMPANY>/financial_facts.json`). These files are v2
candidates for review. Do not edit them by hand; regenerate them with the
commands below.

| Path | Contents | Produced by |
| --- | --- | --- |
| `sources/source_registry.json` | v2 source registry migrated from `data/source_registry.json` | `finura.migrations.v1_to_v2` |
| `facts/FFC/financial_facts.json` | FFC's 60 facts in v2 form | `finura.migrations.v1_to_v2` |
| `migrations/20261021-v1_to_v2-FFC/manifest.json` | Hashes, record counts, validation, and field-equivalence results | `finura.migrations.v1_to_v2` |
| `companies/transcriptions/*.csv` | Reviewer transcriptions of listing evidence | written by a person |
| `companies/listing_claims.json` | Listing claims (discovered, verified, rejected) | `finura.onboarding ingest` / `review` |
| `companies/company_registry.json` | Company records proposed from claims | `finura.onboarding propose` |

## Status of the FFC records

- The FFC company record's identity is **unverified**. Its only claim
  (`clm_2d07ce7ef45ba4ea`) was transcribed from the committed OCR text of
  the registered filing `src_e4abb64ff4886ffc`. It has not been checked
  visually against the PDF, nor against PSX listing information.
- The record's listing status and sector classification are unknown (`null`).
  The symbol range has no recorded start or end date, and that range is
  itself unverified.
- The 60 FFC facts keep their v1 verification statuses unchanged. The
  outstanding review questions (audit §6.4) are not resolved here.

To verify the identity claim after inspecting the evidence:

```bash
uv run python -m finura.onboarding review --claims data/v2/companies/listing_claims.json \
  --claim-id clm_2d07ce7ef45ba4ea --decision verified --reviewer "<name>" \
  --backup-dir data/v2/backups
uv run python -m finura.onboarding propose --claims data/v2/companies/listing_claims.json \
  --sources data/v2/sources/source_registry.json --claim-id clm_2d07ce7ef45ba4ea \
  --company-id FFC --companies data/v2/companies/company_registry.json --replace \
  --backup-dir data/v2/backups
```

Verifying a claim that says FFC is the listing symbol of Fauji Fertilizer
Company Limited should rest on PSX listing evidence (for example a manually
downloaded PSX page or notice registered as a source). The filing's reference
line alone is weak evidence for that.
