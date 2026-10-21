# Finura Implementation Audit and Migration Plan

Audit date: 2026-10-21
Repository state audited: `master` at `e5849c1` ("generic adapter"), clean tree
Scope: every tracked file (109 files: 14 pipeline modules, 7 test modules,
4 documents, 1 analysis skill, source catalog/registry, FFC evidence, and
generated reports).

This document records what exists today, what was verified by executing it,
which defects were reproduced, and the smallest safe path from the current
`psx-research` pipeline to the Finura target architecture. No existing file
was modified during the audit. Pipeline runs that write artifacts were
executed in a scratch copy of the repository.

---

## 1. Baseline results

### Environment

| Item | Observed |
| --- | --- |
| System Python | 3.10.12 (readme recommends 3.12; 3.11 also installed) |
| Virtual environment | none (`.venv/` absent) |
| `pytest` | not installed; baseline run via `uv run --no-project --with pytest` |
| Packaging | no `pyproject.toml`, `requirements*.txt`, or package entry point |
| OCR / PDF tools | `tesseract`, `pdftoppm`, `pdftotext`, `ocrmypdf` absent; no `pdfplumber`, `PyMuPDF`, `pytesseract` |
| LLM SDKs | `google-genai` absent; no Hermes runtime on `PATH` |
| Available libraries | `pydantic` 2.13, `pydantic-settings` 2.14, `httpx` 0.28, `lxml` 6.1 |
| Credentials | no Gemini/Hermes environment variables set |

The FFC OCR text and page images in the repository were produced elsewhere;
the extraction step cannot be reproduced on this machine as configured.

### Test suite

```text
$ uv run --no-project --python 3.10 --with pytest python -m pytest -q
29 passed, 60 subtests passed in 0.27s
```

`python -m unittest discover -s tests -t .` fails (`tests/` is not
importable: no `__init__.py`). Tests pass only through `python -m pytest`
from the repository root, because that puts the root on `sys.path`.

### Validators and pipeline (executed in a scratch copy)

| Command | Exit | Result |
| --- | --- | --- |
| `validate_financial_facts.py --company FFC` | 0 | 60 passed, 0 warnings, 0 errors |
| `check_reconciliations.py --company FFC` | 0 | 4 checks, 0 errors (both scopes, FY2024/FY2025) |
| `check_cash_flows.py --company FFC` | 0 | 8 checks, 0 errors |
| `validate_market_data.py --company FFC` | 0 | 0 observations |
| `run_analysis.py --company FFC --validate` | 0 | confidence `low`, 4 gaps; `derived_metrics.json` byte-identical to committed |
| `verify/compare_ocr_facts.py` | 0 | `VALUE_FOUND`: 60/60 |
| `verify/verify_financial_rows.py` | 0 | `ROW_LABEL_AND_VALUE_FOUND`: 60/60 |
| `verify/verify_year_columns.py` | 0 | `YEAR_COLUMN_VALUE_MATCH`: 60/60 |
| `check_cash_flows.py --company LUCKY` | 0 | **0 checks** — vacuous pass on an empty dataset |

Regenerating outputs changed seven committed files (see D15): the committed
reports are stale relative to the code and data that produced them.

---

## 2. Component inventory

Status key: **Working** = exercised and correct for its current scope;
**Partial** = works for FFC or a narrow case; **Missing** = not present.

| Target layer | Existing implementation | Status |
| --- | --- | --- |
| Configuration | Hardcoded `ROOT` paths per script; no settings, no secrets handling | Missing |
| Company universe | `init_company.py` accepts any uppercase alphanumeric string | Missing |
| Source registry | `data/source_registry.json` + `register_source.py` (SHA-256, dedupe, atomic write) | Working |
| Source catalog | `data/source_catalog.json` (6 providers, role primary/secondary) | Partial — no reliability, lineage, or terms metadata |
| Source adapters | `fetch_sources.py` generic HTTP collector + shallow link discovery | Partial — no provider-specific adapters; never exercised against live providers in this audit |
| Raw artifact preservation | `data/raw/FFC/ffc_report.pdf` with registered hash | Working |
| PDF / OCR extraction | None in code; OCR text and images committed as artifacts | Missing (artifacts only) |
| Normalization | `normalize_external.py` mapping-driven CSV/JSON/HTML importer | Partial — overwrites output, minimal validation |
| Reconciliation (cross-source) | None | Missing |
| Schema validation | `validate_financial_facts.py`, `validate_market_data.py` | Working for v1 schema; script-only (global state) |
| Accounting validation | Balance-sheet identity and cash-flow roll-forward | Working for FFC annual data |
| OCR-assisted verification | `pipeline/verify/*` | Partial — hardcoded to FFC layout and paths |
| Deterministic calculations | `derive_metrics.py` (8 ratios) | Partial — correct for FFC; defects on other inputs (D1–D6) |
| Fundamental analysis | None (the skill describes it in prose) | Missing |
| Sector analysis | None (skill §11 lists sector KPIs) | Missing |
| Macro analysis | None; no macro dataset | Missing |
| Valuation / scenarios | `run_analysis.py` reports `"unavailable"` | Missing |
| Hermes / Gemini | `hermes_context.json` evidence package; skill has Hermes frontmatter | Missing (no runtime integration) |
| Decision gates / critique | Heuristic `confidence` field only | Missing |
| Reporting | `run_analysis.py` Markdown + JSON readiness report | Partial |
| Persistence / audit trail | JSON files in git; one manual review audit JSON | Partial |
| CLI | Separate argparse scripts; `run_company.py` chains them | Partial — no `finura` entry point |

---

## 3. Evidence that must be preserved

These are migration inputs. None may be deleted or rewritten without a
tested, equivalent replacement.

| Artifact | Why it matters |
| --- | --- |
| `data/raw/FFC/ffc_report.pdf` (SHA-256 `a8962695…41e2e`) | The only primary source document; all 60 facts point to it |
| `data/source_registry.json` | Source identity and hash; `src_e4abb64ff4886ffc` is referenced by every FFC fact |
| `data/normalized/FFC/financial_facts.json` | 60 verified facts (56 `PKR_thousand`, 4 `PKR_per_share`), standalone and consolidated, FY2024–FY2025 |
| `reports/ffc_verification_audit_20261018T185312.json` | The only recorded review evidence: 32 facts moved `ocr_unverified → verified` after visual review |
| `reports/ffc_verification_worklist.csv`, `ffc_cash_flow_*` | Review worklist and the resolved OCR discrepancy (cash ending balance 176,715,058 vs OCR 176,775,058) |
| `data/normalized/FFC/ocr_second_pass/`, `ocr_diagnostics/`, page images | Extraction evidence; the basis for OCR regression fixtures |
| `docs/SOURCE_POLICY.md`, `DATA_SCHEMA.md` | Integrity rules that Finura's spec restates and extends |
| `skills/psx-equity-analyst/SKILL.md` | Sector KPIs, calculation formulas, and the no-fabrication rules the LLM layer must follow |

Verification provenance gap: 28 of the 60 facts were already `verified` in
the initial commit (`22e1011`); no review record exists for them. The
other 32 have the audit JSON above. All 60 values are unchanged across every
commit (the `e5849c1` change only added `fact_classification`).

---

## 4. Confirmed defects

Each item below was reproduced by executing the code, not inferred from
reading it. None affects the current committed FFC outputs except D6, D14,
and D15, because the FFC data does not trigger the other paths.

### Calculations (`pipeline/derive_metrics.py`)

| ID | Defect | Reproduction |
| --- | --- | --- |
| D1 | `asset_turnover` crashes when `net_turnover` is missing but two `total_assets` periods exist (line 131 dereferences `None`) | `TypeError: 'NoneType' object is not subscriptable` |
| D2 | Prior period ignores `period_type`: an annual figure is compared with a quarterly one (lines 65–77) | FY2025 annual revenue growth computed against a 2025-09-30 quarter: `0.4667` |
| D3 | `fact_index` drops `unit` from the key (lines 53–62), so a later fact silently replaces an earlier one | EPS in `PKR_per_share` and `PKR` → `eps_growth = 1032.8` reported as `calculated` |
| D4 | Zero average assets yields `value: None` with `calculation_status: "calculated"` (line 134) | `(None, 'calculated')` |
| D5 | Growth from a negative base is reported as an ordinary number | EPS −2 → 3 gives `eps_growth = -2.5` |
| D6 | No merger/comparability detection, although `SOURCE_POLICY.md` and the skill require it | FY2024 includes cash acquired through the FFBL merger (standalone 25,949,860; consolidated 27,734,821 PKR '000), yet FY2025 vs FY2024 growth is published without a comparability flag |
| D7 | Output currency hardcoded to `PKR` regardless of input | by inspection of `derive()` |

### Validation

| ID | Defect |
| --- | --- |
| D8 | `validate_financial_facts.py` keeps errors, warnings and passes in module globals; calling `main()` twice in one process doubles them (120 passes for 60 facts). It also never checks that facts belong to the requested company or that the source's `company_id` matches. |
| D9 | `check_cash_flows.py` and `check_reconciliations.py` exit `0` with zero checks on an empty dataset (vacuous pass). `check_cash_flows.py` hardcodes `PKR_thousand` and treats an absent merger-cash line as `0` — documented, but it conflicts with the no-zero-substitution rule unless made an explicit, recorded assumption. |

### Verification, ingestion, and normalization

| ID | Defect |
| --- | --- |
| D10 | `pipeline/verify/*` hardcode FFC paths and the "Annexure A page N of 8 → PDF page N+2" mapping. `compare_ocr_facts.py` does all its work at import time. `verify_year_columns.py` fails on package import (`ModuleNotFoundError: verify_financial_rows`). |
| D11 | `fetch_sources.py` says it respects robots rules but never reads `robots.txt`; discovered links are fetched back-to-back with no delay; every non-PSX response is registered as `market_data`. `run_company.py` accepts `--delay` but never passes it on. |
| D12 | `normalize_external.py` writes its output file wholesale. Pointing `--output` at `data/normalized/FFC/financial_facts.json` would replace 60 verified facts with `needs_final_review` rows, with no merge, backup, or warning. Unit, period, and period type are not validated. |
| D13 | `register_source.py` records registration time as `retrieved_at`; the FFC entry's actual download time and `published_at` are unknown. |

### Reporting and repository hygiene

| ID | Defect |
| --- | --- |
| D14 | The FFC report lists each derived metric twice (standalone and consolidated) with **no scope label**, so a reader cannot tell 17.64% from 15.76% revenue growth. Validation results are not included in the report; `status: "ready"` is independent of validation; `confidence` is a gap-count heuristic that keeps FFC permanently `low`. |
| D15 | Committed generated artifacts are stale: the FFC report predates the `Data status` line, and the OCR/row/year-column reports still show 32 facts as `ocr_unverified`. |
| D16 | Placeholder workspaces are committed: `ABC` is not a real listing, and `LUCKY` appears to be wrong (Lucky Cement trades on PSX as `LUCK`). All three contain empty facts and generated reports. |
| D17 | No packaging or dependency declaration; `pytest` is not installed; tests rely on cwd being on `sys.path`. |
| D18 | Tests assert against committed artifacts (`derived_metrics.json`) rather than recomputing, so a stale artifact passes. `test_run_analysis` asserts valuation is `"unavailable"` for FFC, which will break once market data is added. |

---

## 5. Gap against the Finura data-integrity requirements

| Required fact metadata | Current v1 schema |
| --- | --- |
| Company identity | File-level `company_id` only; no legal name, ISIN, sector, or listing validation |
| Financial concept | Free-text `metric`; no concept dictionary, definitions, or sign conventions |
| Value, unit, currency | `value`, `unit` per fact; currency only at file level |
| Fiscal period and dates | `period_end`, `period_type`; no period start, fiscal-year label, filing date, or audited flag |
| Reporting scope | `scope` (standalone/consolidated) — present |
| Source and document | `source_id` → registry; free-text `source_page` |
| URL or artifact reference | In registry |
| Retrieval and extraction timestamps | Registration time only; no extraction timestamp |
| Extraction method | Absent |
| Verification status | Present; verifier and evidence only in a separate file for 32 facts |
| Reported / calculated / estimated / assumed | `fact_classification` present (no `assumed` value) |
| Validation findings, reconciliation history | Printed to stdout; not persisted or attached |
| Document versions, restatements, fiscal-year changes, corporate events | Absent |
| Aggregator lineage (shared upstream data) | Absent |

---

## 6. Conflicts and decisions requiring the owner

1. **Investment action vs. existing policy.** The Finura spec asks reports to
   distinguish a business assessment, a valuation conclusion, and an
   investment action. `SOURCE_POLICY.md` and the skill forbid BUY/HOLD/SELL
   labels and position sizing unless explicitly requested. Proposed
   resolution: the "investment action" section states a research action
   (for example "valuation not supported — collect price and dividend data")
   and a gated conclusion, never a trade label, unless a run is explicitly
   configured otherwise.
2. **Hermes integration contract.** The skill's frontmatter targets a Hermes
   skill format, but no Hermes runtime is installed here. Finura needs to
   know how Hermes will call it (MCP server, Python tool functions, or CLI)
   before Phase 11.
3. **Provider permissions.** The spec wants aggregators for baseline
   coverage; the existing policy requires confirming terms first. Each
   aggregator adapter needs an owner decision on whether automated access is
   permitted before it is enabled.
4. **The 28 facts with no review record.** Either re-verify them visually
   against the page images (the evidence is in the repository) and record
   the review, or migrate them with an explicit "verified, reviewer and
   evidence unrecorded" provenance note.
5. **Placeholder workspaces (`ABC`, `LUCKY`, `OGDC`).** Removing them is a
   deletion and needs approval. They hold no evidence.
6. **System dependencies.** Phase 4 needs `tesseract` and `poppler-utils`
   installed on the host (requires `sudo apt install`).

---

## 7. Target structure and the smallest safe set of changes

> **Update (Phase 2, step 2):** the company-independent design is documented
> in [ARCHITECTURE.md](./ARCHITECTURE.md). In it, company identity, sources,
> facts, sector profiles, and run paths are separate, and every
> company-scoped path comes from a verified company record.

Add one installable package beside the existing `pipeline/`, and move
behaviour into it one tested phase at a time. Each `pipeline/` script stays
runnable until its replacement passes an equivalence test against the FFC
fixture, then becomes a thin shim or is removed in Phase 14.

```text
pyproject.toml              package metadata, dependencies, pytest config, `finura` script
finura/
  schemas/                  Phase 2  canonical pydantic models, enums, v1 loaders
  config/                   Phase 2  settings, company universe
  sources/                  Phase 3  registry, adapter protocol, provider adapters
  ingest/  extract/         Phase 4  fetch, raw store, PDF/OCR extraction
  normalize/ reconcile/     Phase 5
  validate/                 Phase 6
  calc/                     Phase 7
  analysis/                 Phase 8–9 fundamentals, sector profiles, macro
  valuation/                Phase 10
  llm/                      Phase 11 provider protocol, Gemini, Hermes tool surface
  gates/                    Phase 12 run states, critique rules
  report/  cli.py           Phase 13
tests/
  fixtures/                 synthetic edge-case datasets (no real-company fabrication)
```

A subpackage is created only when its phase starts; no empty placeholder
modules. Data stays as git-tracked JSON under `data/` with an explicit
`schema_version`. A database is not justified yet.

Structural changes, in order of necessity:

1. `pyproject.toml` with a pinned Python (3.12 via `uv`, matching the
   readme), `pydantic>=2` as the first runtime dependency, and `pytest` as a
   dev dependency.
2. A canonical v2 fact schema that is a superset of v1, so the 60 FFC facts
   load without loss and missing provenance is recorded as unknown rather
   than invented.
3. A versioned migration of `data/normalized/FFC/financial_facts.json`
   to v2, with a backup and an equivalence test proving every value, unit,
   period, scope, and source link is unchanged.
4. Run outputs written to `runs/<SYMBOL>/<run_id>/` with a manifest, instead
   of overwriting committed reports in place.

---

## 8. Phased migration plan

Each phase ends with: tests run and results recorded, the real integration
path exercised, documentation updated, and limitations listed.

| Phase | Deliverable | Exit criteria | Preserves / replaces |
| --- | --- | --- | --- |
| 1. Audit | This document | Owner approval of §6 decisions | — |
| 2. Schemas & config | `pyproject.toml`; `finura.schemas` (Source, FinancialFact v2, MarketObservation, Period, enums); settings; company universe file seeded from PSX listings | FFC v1 data loads losslessly; migrated v2 file passes value-equivalence test; existing 29 tests still pass | Wraps v1 files; no data rewrite until migration test passes |
| 3. Source registry & adapters | Adapter protocol (fetch → raw artifact + metadata), provider reliability and upstream-lineage fields in the catalog, PSX DPS adapter first | PSX adapter retrieves a real FFC filing listing; failures recorded as structured source failures; robots/terms check enforced | Replaces `fetch_sources.py` discovery |
| 4. Ingestion & extraction | Raw store with hashes and document versions; PDF text + OCR extraction producing candidate facts with page/row/column evidence | Re-extracting the FFC PDF reproduces all 60 values from the source PDF (as candidates, not `verified`); OCR-error fixtures | Generalises `pipeline/verify/*`; keeps committed OCR as regression fixtures |
| 5. Normalization & reconciliation | Concept dictionary, unit/scale conversion, period alignment, cross-source reconciliation with lineage-aware corroboration | Fixtures for disagreement, unit mismatch, standalone/consolidated mismatch, restatement, shared-upstream aggregators | Replaces `normalize_external.py` (merge, never overwrite) |
| 6. Integrity & accounting validation | Pure-function validators returning findings objects; persisted validation results | FFC passes; vacuous runs fail; D8–D9 fixed | Replaces `pipeline/validate/*` |
| 7. Deterministic calculations | Formula registry with documented inputs, units, edge cases; comparability flags | FFC outputs equal current `derived_metrics.json`; regression tests for D1–D7 | Replaces `derive_metrics.py` |
| 8. Fundamental analysis | Profitability, earnings quality, balance-sheet risk, cash-flow quality, dividends — computed findings with evidence references | FFC findings trace to fact keys and formulas | — |
| 9. Sector & macro | Sector profiles (bank, fertilizer, cement, E&P first); SBP/PBS macro adapters and dated observations | Bank, cyclical, and energy fixtures select different metric sets; macro observations carry source and date | Uses skill §11 and §15 |
| 10. Valuation & scenarios | Sector-appropriate methods (e.g. P/B–ROE for banks, DDM/earnings for FFC), explicit assumptions, bear/base/bull, sensitivity | Blocked when price is stale or inputs missing; assumptions labelled `assumed` | — |
| 11. Hermes / Gemini | Provider protocol, Gemini client (timeouts, retries, rate limits, usage), typed tool surface for Hermes | Structured outputs validated; LLM outage fixture yields a clear failure state; engine runs with no LLM | Consumes the evidence package |
| 12. Critique & gates | Run states (`completed`, `completed_with_warnings`, `blocked`, `failed`); rule-based critique checking each conclusion against evidence and calculations | Each blocking condition in the spec has a test | Replaces heuristic `confidence` |
| 13. Reporting, CLI, persistence | `finura analyze SYMBOL`; Markdown + JSON report with all required sections; run manifest and audit trail | Report sections populated or explicitly blocked; scope labelled on every number | Replaces `run_analysis.py`, `run_company.py` |
| 14. End-to-end | FFC, one bank, one cyclical industrial, one energy company through the real pipeline | `finura analyze FFC` reproducible from a clean checkout | Retire superseded `pipeline/` scripts |

Defects D1–D7 are fixed when calculations move in Phase 7. They cannot
affect outputs before then, because no company other than FFC will have
facts until Phases 4–5, and FFC does not trigger them. D14 and D15 are
addressed by Phase 13's report and run-directory changes. D12 should not be
used against `data/normalized/FFC/` in the meantime.

---

### Phase status (updated 2026-10-21)

| Phase | Status |
| --- | --- |
| 1. Audit | Done |
| 2. Schemas & config | Done: v2 schemas, company model, registry, sector-profile config, generic migration; FFC candidates in `data/v2/` |
| 3. Source registry & adapters | **Done, with limitations below** ([SOURCES_AND_CLAIMS.md](./SOURCES_AND_CLAIMS.md), [PROVIDER_DUE_DILIGENCE.md](./PROVIDER_DUE_DILIGENCE.md)) |
| 4. Ingestion & extraction | Not started (needs `tesseract`/`poppler`) |
| 5. Normalization & reconciliation | Not started |
| 6. Integrity & accounting validation | Step 1 done: generic validation engine and readiness verdict ([VALIDATION.md](./VALIDATION.md)) |
| 7–14 | Not started |

#### Phase 3 closeout

Delivered:

- access policies for every catalog host;
- the policy-gated fetcher, which checks redirects and refuses unknown hosts
  before any network contact;
- the source-registry protocol;
- listing claims and evidence-based company onboarding;
- the legacy collector routed through the same gate.

Limitations at closeout:

- **PSX automated access is prohibited** under the recorded terms review.
  Changing that needs PSX's written permission or a data licence, recorded as
  `written_permission` with a reference.
- **Sarmaaya, PSX Terminal, Ticker Analysts, SCS Trade, and FinHisaab stay
  blocked** (two prohibited, three unclear). They need reviewed written
  permission and API documentation before any adapter is built.
- **Manual source registration is the only permitted evidence path.** That
  means `pipeline/register_source.py` for v1, which works offline, or the
  `finura.sources.registry` API for v2. There is no v2 registration command
  yet, and `register_source.py` still records registration time as
  `retrieved_at` (audit D13).
- **FFC's company identity and sector classification are unverified.** Its
  one listing claim is `discovered`, not reviewed.
- The quoted terms clauses in `config/access_policies.json` need owner
  confirmation against the live pages.

Decisions in force:

- v1 stays the active pipeline input.
- `data/v2/` holds migration candidates only, until a cutover is approved.
- Unknown legacy fields are rejected.
- FFC fact verification statuses are unchanged.
- **Audit decision §6.4 remains open.**

Supported invocation: `uv sync`, then `uv run pytest -q`, and
`uv run python -m finura.<module>` for the Finura commands (`migrations.v1_to_v2`,
`onboarding`, `validation`). The legacy fetch collector also needs the
project environment: `uv run python pipeline/fetch_sources.py`.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Migrating the FFC facts loses or alters a verified value | Lossless loader first; migration only with backup and field-by-field equivalence test |
| Aggregator terms forbid automated access | Owner decision per provider (§6.3); adapters disabled by default |
| Aggregators share an upstream feed and are counted as independent corroboration | Lineage field in the catalog; reconciliation counts independent upstreams, not providers |
| OCR toolchain differs from the one that produced committed OCR | Treat committed OCR as fixtures; pin tool versions; never auto-promote extracted facts to `verified` |
| Scope creep into many half-built modules | One phase at a time; subpackages created only when used |
| LLM output treated as evidence | LLM layer has read-only tools; facts and calculations are immutable inputs; outputs schema-validated and gated |
| Stale market price drives a valuation | Freshness threshold in config; stale price blocks the valuation conclusion |
| Merger and restatement effects distort growth | Comparability flags in Phase 7; FFBL merger is the first regression case |

---

## 10. First implementation task (Phase 2, step 1)

Add packaging and the canonical schema layer, without changing any data file
or existing script:

1. `pyproject.toml`: package `finura`, Python 3.12 via `uv`, runtime
   dependency `pydantic>=2`, dev dependency `pytest`, `[tool.pytest]`
   config so tests import without relying on the working directory.
2. `finura/schemas/`: pydantic models and enums for `SourceDocument`,
   `FinancialFact` (v2 superset: concept, value, unit, currency, period
   start/end/type, scope, source location, extraction method and timestamp,
   verification status and evidence reference, classification, validation
   findings), plus read-only loaders for the existing v1 registry and facts
   files. Fields that v1 does not hold are `None` and listed as provenance
   gaps — never defaulted to invented values.
3. Tests: all 60 FFC facts and the registry load; every v1 value, unit,
   period, scope, and source link survives; booleans, NaN, unknown scopes,
   units, and duplicate keys are rejected; the existing 29 tests still pass.

The next step (Phase 2, step 2) is the FFC v2 data migration, which depends
on the owner's decision in §6.4.
