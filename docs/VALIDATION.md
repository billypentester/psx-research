# Validation Engine (Phase 6, Step 1)

`finura.validation` checks one company's v2 facts document against
configurable accounting rules and the source registry, and returns a
structured report with a readiness verdict. It is deterministic, reads local
files only, and never modifies its inputs. The legacy validators in
`pipeline/validate/` are unchanged and still validate v1 data.

```bash
uv run python -m finura.validation \
  --facts data/v2/facts/FFC/financial_facts.json \
  --sources data/v2/sources/source_registry.json \
  --evidence-root . \
  --companies data/v2/companies/company_registry.json \
  --out /path/outside/the/repository/ffc-validation.json
```

| Option | Meaning |
| --- | --- |
| `--facts`, `--sources`, `--out` | Required, explicit paths |
| `--evidence-root` | Check each cited source file against its registered SHA-256; without it, evidence is reported as not checked |
| `--companies` | Company registry used to find a verified sector classification. Without it the classification is unavailable |
| `--rules`, `--sector-profiles` | Default to `config/accounting_rules.json` and `config/sector_profiles.json` |
| `--backup-dir` | Required to replace an existing report |

The command refuses to write over an input or into `data/v2/` (migration
only) or `runs/` (company runs need a verified company and a later phase).
Every input path and its SHA-256 are recorded in the report.

**Exit status:**

| Status | Meaning |
| --- | --- |
| 0 | `passed` or `passed_with_warnings` |
| 1 | `failed` |
| 3 | `incomplete` |
| 4 | Inputs or output refused; nothing is written |
| 2 | argparse usage error |

## Accounting rules

`config/accounting_rules.json` (schema version 1). Each rule states
`total == sum(coefficient × component)` for facts sharing one company, scope,
period end, and period type.

- Amounts are compared with the sign the statement presents: outflows and
  expenses are stored as negative values, as in the FFC and synthetic
  fixtures.
- Coefficients are non-zero integers.
- Tolerance defaults to exact equality. A positive tolerance requires a
  written `tolerance_basis`.
- An optional component must declare `assumption_when_absent`. Each time it
  is absent the rule still runs and an `OPTIONAL_TERM_ASSUMED` warning
  records the assumption.
- Rule IDs must be unique. Concepts not found in the facts are allowed and
  reported, because there is no concept dictionary yet (Phase 5).

| Rule | Model | Equation | Origin |
| --- | --- | --- | --- |
| `balance_sheet_assets_equal_equity_and_liabilities` | general | total_equity_and_liabilities = total_assets | `check_reconciliations.py` |
| `balance_sheet_assets_equal_liabilities_and_net_assets` | banking | total_assets = total_liabilities + net_assets | banking layout; synthetic bank |
| `cash_flow_activities_sum_to_net_change` | general | net change = operating + investing + financing | `check_cash_flows.py` |
| `cash_roll_forward` | general | ending cash = beginning + net change + FX effect + merger cash (optional) | `check_cash_flows.py` |
| `gross_profit_subtotal` | general | gross_profit = net_sales + cost_of_sales | synthetic industrial |
| `net_markup_interest_income_subtotal` | banking | net mark-up income = mark-up earned + mark-up expensed | synthetic bank |

The merger-cash term is optional, and its assumption is recorded each time
it is applied. The legacy script silently treats a missing value as zero.

## Which rules are required

| Classification | Rule outside the statement model | Rule inside it: all required inputs present | Some present | None present |
| --- | --- | --- | --- | --- |
| Verified identity and sector, with a profile | `not_applicable` (info) | evaluated | `inputs_missing` (**error**) | `not_evaluated` (**incomplete**) |
| Unverified, missing, or no company record | — (never inferred) | evaluated anyway | `not_evaluated` (incomplete) | `not_evaluated` (incomplete) |

Partial inputs within a statement suggest an extraction or transcription
error, so they are errors. A statement with no facts at all is a coverage
gap, so it is incomplete. With an unverified sector, the statement model is
never inferred from the facts. Rules whose inputs are all present still run,
so arithmetic errors are caught, but the verdict cannot pass.

Units are never converted. If a rule's inputs use different units, or a
concept appears in more than one unit, the result is `RULE_UNIT_MISMATCH`
(error).

## Findings and verdict

Each finding has a stable code, a fixed severity, a message, and, where
relevant, the rule, the period group, the affected facts (company, concept,
scope, period end and type, unit, source), source IDs, the assumption
applied, or the reason evaluation was skipped.

| Severity | Codes |
| --- | --- |
| error | `RULE_FAILED`, `RULE_UNIT_MISMATCH`, `REQUIRED_RULE_INPUTS_MISSING`, `SOURCE_NOT_REGISTERED`, `SOURCE_COMPANY_MISMATCH`, `EVIDENCE_PATH_OUTSIDE_ROOT`, `EVIDENCE_FILE_MISSING`, `EVIDENCE_HASH_MISMATCH` |
| incomplete | `EMPTY_FACT_SET`, `NO_CHECKS_EVALUATED`, `SECTOR_UNVERIFIED`, `REQUIRED_RULE_NOT_EVALUATED`, `RULE_NOT_EVALUATED_SECTOR_UNVERIFIED` |
| warning | `OPTIONAL_TERM_ASSUMED`, `FACT_NOT_VERIFIED`, `FACT_PROVENANCE_GAP`, `SOURCE_PROVENANCE_GAP` |
| info | `RULE_NOT_APPLICABLE`, `RULE_CONCEPTS_NOT_IN_FACTS`, `EVIDENCE_NOT_CHECKED` |

**Verdict precedence:** any error → `failed`; else any incomplete →
`incomplete`; else any warning → `passed_with_warnings`; else `passed`.
Provenance warnings therefore never hide an accounting error or an
unevaluated required check, and an empty fact set never passes.

A source with `company_id: null` (an exchange-wide document) may support any
company's facts. Verification states and provenance fields are reported,
never changed.

## Current results

- **FFC (v2 candidates):** all 12 legacy checks pass with zero difference
  (balance sheet 4, cash-flow activities 4, cash roll-forward 4). The FY2025
  roll-forward applies the merger-cash assumption in both scopes. The verdict
  is `incomplete`, because FFC's identity and sector are unverified.
- **Synthetic bank (verified banking sector):** the banking rules pass for
  2025, and the general rules are not applicable. The fixture's partial 2024
  comparatives give `failed`; without them the result is
  `passed_with_warnings`.
- **Synthetic industrial (sector unverified):** the quarterly gross-profit
  rule passes. Year-to-date facts are evaluated separately and are not
  evaluated (inputs missing). The verdict is `incomplete`.

## Limitations

- No concept dictionary: FFC's `net_turnover` and the rule's `net_sales` are
  not linked, and nothing checks whether a unit suits its concept (Phase 5).
- Sign conventions are assumed from the fixtures, not declared per concept.
- Banking cash-flow rules are not defined, because no fixture shows that
  layout.
- The verdict covers validation only. Run manifests and decision gates come
  in Phases 12–13.
