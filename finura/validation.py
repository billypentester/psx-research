"""Deterministic validation of a v2 facts document, with a readiness verdict.

    python -m finura.validation --facts PATH --sources PATH --out PATH
        [--evidence-root DIR] [--companies PATH] [--rules PATH]
        [--sector-profiles PATH] [--backup-dir DIR]

Checks:

- accounting rules (`config/accounting_rules.json`), evaluated per company,
  scope, period end, and period type, never mixing units;
- provenance: each fact's source is registered and belongs to the same
  company, and raw evidence matches its registered SHA-256 when an evidence
  root is given;
- review state: unverified facts and unrecorded provenance are reported as
  warnings, never changed.

Which rules are required depends on a verified company identity and sector
classification. Without one, rules whose inputs are all present still run,
but nothing can be shown to be complete, so the verdict cannot pass.

Verdict precedence: any `error` finding gives `failed`; otherwise any
`incomplete` finding gives `incomplete`; otherwise any `warning` gives
`passed_with_warnings`; otherwise `passed`. Exit status: 0 for `passed` and
`passed_with_warnings`, 1 for `failed`, 3 for `incomplete`, 4 when inputs or
output are refused (argparse usage errors exit 2). The engine reads local
files only and never touches the network.
"""

import argparse
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from finura.accounting_rules import AccountingRule, AccountingRuleSet, load_accounting_rules
from finura.companies import RegistryFileCompanies, UnknownCompanyError
from finura.schemas.company import Company
from finura.schemas.documents import FinancialFactsDocument, SourceRegistryDocument
from finura.schemas.enums import PeriodType, Scope, Unit, VerificationStatus
from finura.schemas.fact import FinancialFact
from finura.schemas.io import SchemaLoadError, dump_model, load_model
from finura.schemas.source import SourceDocument
from finura.schemas.types import AwareTimestamp
from finura.sectors import SectorProfileSelectionError, SectorProfileSet, StatementModel, load_sector_profiles, select_sector_profile
from finura.storage import StorageError, replace_files, sha256_bytes

REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_RULES = REPOSITORY / "config" / "accounting_rules.json"
DEFAULT_SECTOR_PROFILES = REPOSITORY / "config" / "sector_profiles.json"
# Migration candidates and company-scoped runs are not validation output locations.
FORBIDDEN_OUTPUT_DIRS = (REPOSITORY / "data" / "v2", REPOSITORY / "runs")


class Severity(StrEnum):
    ERROR = "error"
    INCOMPLETE = "incomplete"
    WARNING = "warning"
    INFO = "info"


class Verdict(StrEnum):
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    PASSED = "passed"


class FindingCode(StrEnum):
    EMPTY_FACT_SET = "EMPTY_FACT_SET"
    NO_CHECKS_EVALUATED = "NO_CHECKS_EVALUATED"
    SECTOR_UNVERIFIED = "SECTOR_UNVERIFIED"
    RULE_FAILED = "RULE_FAILED"
    RULE_UNIT_MISMATCH = "RULE_UNIT_MISMATCH"
    REQUIRED_RULE_INPUTS_MISSING = "REQUIRED_RULE_INPUTS_MISSING"
    REQUIRED_RULE_NOT_EVALUATED = "REQUIRED_RULE_NOT_EVALUATED"
    RULE_NOT_EVALUATED_SECTOR_UNVERIFIED = "RULE_NOT_EVALUATED_SECTOR_UNVERIFIED"
    RULE_NOT_APPLICABLE = "RULE_NOT_APPLICABLE"
    OPTIONAL_TERM_ASSUMED = "OPTIONAL_TERM_ASSUMED"
    RULE_CONCEPTS_NOT_IN_FACTS = "RULE_CONCEPTS_NOT_IN_FACTS"
    SOURCE_NOT_REGISTERED = "SOURCE_NOT_REGISTERED"
    SOURCE_COMPANY_MISMATCH = "SOURCE_COMPANY_MISMATCH"
    EVIDENCE_NOT_CHECKED = "EVIDENCE_NOT_CHECKED"
    EVIDENCE_PATH_OUTSIDE_ROOT = "EVIDENCE_PATH_OUTSIDE_ROOT"
    EVIDENCE_FILE_MISSING = "EVIDENCE_FILE_MISSING"
    EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"
    FACT_NOT_VERIFIED = "FACT_NOT_VERIFIED"
    FACT_PROVENANCE_GAP = "FACT_PROVENANCE_GAP"
    SOURCE_PROVENANCE_GAP = "SOURCE_PROVENANCE_GAP"


SEVERITY = {
    FindingCode.EMPTY_FACT_SET: Severity.INCOMPLETE,
    FindingCode.NO_CHECKS_EVALUATED: Severity.INCOMPLETE,
    FindingCode.SECTOR_UNVERIFIED: Severity.INCOMPLETE,
    FindingCode.RULE_FAILED: Severity.ERROR,
    FindingCode.RULE_UNIT_MISMATCH: Severity.ERROR,
    FindingCode.REQUIRED_RULE_INPUTS_MISSING: Severity.ERROR,
    FindingCode.REQUIRED_RULE_NOT_EVALUATED: Severity.INCOMPLETE,
    FindingCode.RULE_NOT_EVALUATED_SECTOR_UNVERIFIED: Severity.INCOMPLETE,
    FindingCode.RULE_NOT_APPLICABLE: Severity.INFO,
    FindingCode.OPTIONAL_TERM_ASSUMED: Severity.WARNING,
    FindingCode.RULE_CONCEPTS_NOT_IN_FACTS: Severity.INFO,
    FindingCode.SOURCE_NOT_REGISTERED: Severity.ERROR,
    FindingCode.SOURCE_COMPANY_MISMATCH: Severity.ERROR,
    FindingCode.EVIDENCE_NOT_CHECKED: Severity.INFO,
    FindingCode.EVIDENCE_PATH_OUTSIDE_ROOT: Severity.ERROR,
    FindingCode.EVIDENCE_FILE_MISSING: Severity.ERROR,
    FindingCode.EVIDENCE_HASH_MISMATCH: Severity.ERROR,
    FindingCode.FACT_NOT_VERIFIED: Severity.WARNING,
    FindingCode.FACT_PROVENANCE_GAP: Severity.WARNING,
    FindingCode.SOURCE_PROVENANCE_GAP: Severity.WARNING,
}
_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.INCOMPLETE: 1, Severity.WARNING: 2, Severity.INFO: 3}


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactRef(_Record):
    company_id: str
    concept: str
    scope: Scope
    period_end: date
    period_type: PeriodType
    unit: Unit
    source_id: str


class PeriodGroup(_Record):
    """Facts that may be combined: one company, scope, period end, and period type."""

    company_id: str
    scope: Scope
    period_end: date
    period_type: PeriodType


class RuleStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNIT_MISMATCH = "unit_mismatch"
    INPUTS_MISSING = "inputs_missing"
    NOT_EVALUATED = "not_evaluated"
    NOT_APPLICABLE = "not_applicable"


class RuleResult(_Record):
    rule_id: str
    group: PeriodGroup
    status: RuleStatus
    # True/False from a verified statement model; None when the sector is unverified.
    required: bool | None
    unit: Unit | None = None
    reported_total: int | float | None = None
    computed_total: int | float | None = None
    difference: int | float | None = None
    tolerance: int | float
    facts: tuple[FactRef, ...] = ()
    missing_concepts: tuple[str, ...] = ()
    assumed_absent: tuple[str, ...] = ()


class Finding(_Record):
    code: FindingCode
    severity: Severity
    message: str
    rule_id: str | None = None
    group: PeriodGroup | None = None
    facts: tuple[FactRef, ...] = ()
    source_ids: tuple[str, ...] = ()
    assumption: str | None = None
    skipped_reason: str | None = None


class ClassificationStatus(_Record):
    state: Literal["verified", "unverified", "unavailable"]
    detail: str
    sector_key: str | None = None
    profile_id: str | None = None
    statement_model: StatementModel | None = None


InputRole = Literal["facts", "sources", "rules", "sector_profiles", "companies", "evidence_root"]


class InputRecord(_Record):
    role: InputRole
    path: str
    sha256: str | None


class ValidationReport(_Record):
    schema_version: Literal[1] = 1
    record_type: Literal["validation_report"] = "validation_report"
    validated_at: AwareTimestamp
    company_id: str
    verdict: Verdict
    classification: ClassificationStatus
    fact_count: int
    rule_status_counts: dict[str, int]
    finding_counts: dict[str, int]
    inputs: tuple[InputRecord, ...]
    rule_results: tuple[RuleResult, ...]
    findings: tuple[Finding, ...]


class ValidationInputError(ValueError):
    """The inputs cannot be validated together (for example, mismatched companies)."""


def resolve_classification(company: Company | None, profiles: SectorProfileSet | None) -> ClassificationStatus:
    """Statement model from a verified identity and verified sector; never inferred."""
    if company is None:
        return ClassificationStatus(state="unavailable", detail="no company record was supplied")
    if not company.identity.is_verified:
        return ClassificationStatus(state="unverified", detail=f"company {company.company_id} identity is unverified")
    if company.classification is None:
        return ClassificationStatus(state="unavailable", detail=f"company {company.company_id} has no sector classification")
    sector_key = company.classification.sector_key
    if not company.classification.attestation.is_verified:
        return ClassificationStatus(state="unverified", detail="sector classification is unverified", sector_key=sector_key)
    if profiles is None:
        return ClassificationStatus(state="unavailable", detail="no sector profiles were supplied", sector_key=sector_key)
    try:
        profile = select_sector_profile(company, profiles)
    except SectorProfileSelectionError as exc:
        return ClassificationStatus(state="unavailable", detail=str(exc), sector_key=sector_key)
    return ClassificationStatus(
        state="verified",
        detail=f"verified sector {sector_key!r} selects profile {profile.profile_id!r}",
        sector_key=sector_key,
        profile_id=profile.profile_id,
        statement_model=profile.statement_model,
    )


def validate(
    facts: FinancialFactsDocument,
    sources: SourceRegistryDocument,
    rules: AccountingRuleSet,
    *,
    classification: ClassificationStatus,
    evidence_root: Path | None,
    validated_at: datetime,
    inputs: tuple[InputRecord, ...] = (),
) -> ValidationReport:
    """Validate one company's facts. Deterministic for the same inputs and files."""
    results, findings = _evaluate_rules(facts, rules, classification)
    findings += _provenance_findings(facts, sources, evidence_root)
    if not facts.facts:
        findings.append(_finding(FindingCode.EMPTY_FACT_SET, "the fact set is empty; nothing can be validated"))
    elif not any(result.status in {RuleStatus.PASSED, RuleStatus.FAILED} for result in results):
        findings.append(_finding(FindingCode.NO_CHECKS_EVALUATED, "no accounting rule could be evaluated"))
    if classification.state != "verified":
        findings.append(
            _finding(
                FindingCode.SECTOR_UNVERIFIED,
                f"required rules cannot be determined: {classification.detail}",
                skipped_reason="the statement model is never inferred from the facts",
            )
        )
    ordered = tuple(sorted(findings, key=_finding_sort_key))
    return ValidationReport(
        validated_at=validated_at,
        company_id=facts.company_id,
        verdict=verdict_for(ordered),
        classification=classification,
        fact_count=len(facts.facts),
        rule_status_counts=_counts(result.status.value for result in results),
        finding_counts=_counts(finding.severity.value for finding in ordered),
        inputs=inputs,
        rule_results=tuple(results),
        findings=ordered,
    )


def verdict_for(findings: Iterable[Finding]) -> Verdict:
    severities = {finding.severity for finding in findings}
    if Severity.ERROR in severities:
        return Verdict.FAILED
    if Severity.INCOMPLETE in severities:
        return Verdict.INCOMPLETE
    if Severity.WARNING in severities:
        return Verdict.PASSED_WITH_WARNINGS
    return Verdict.PASSED


def _evaluate_rules(
    facts: FinancialFactsDocument, rules: AccountingRuleSet, classification: ClassificationStatus
) -> tuple[list[RuleResult], list[Finding]]:
    groups: dict[PeriodGroup, dict[str, list[FinancialFact]]] = defaultdict(lambda: defaultdict(list))
    for fact in facts.facts:
        group = PeriodGroup(
            company_id=fact.company_id, scope=fact.scope, period_end=fact.period.end, period_type=fact.period.type
        )
        groups[group][fact.concept].append(fact)

    results: list[RuleResult] = []
    findings: list[Finding] = []
    for group in sorted(groups, key=_group_sort_key):
        by_concept = groups[group]
        for rule in rules.rules:
            result, rule_findings = _evaluate_rule(rule, group, by_concept, classification)
            results.append(result)
            findings += rule_findings

    seen = {fact.concept for fact in facts.facts}
    absent = sorted({concept for rule in rules.rules for concept in rule.concepts} - seen)
    if absent and facts.facts:
        findings.append(
            _finding(
                FindingCode.RULE_CONCEPTS_NOT_IN_FACTS,
                f"rule concepts not present anywhere in the facts: {', '.join(absent)}. "
                "No concept dictionary exists yet (Phase 5), so these may be naming differences rather than gaps.",
            )
        )
    return results, findings


def _evaluate_rule(
    rule: AccountingRule,
    group: PeriodGroup,
    by_concept: dict[str, list[FinancialFact]],
    classification: ClassificationStatus,
) -> tuple[RuleResult, list[Finding]]:
    present = {concept: by_concept[concept] for concept in rule.concepts if concept in by_concept}
    refs = tuple(_ref(fact) for concept in rule.concepts for fact in present.get(concept, ()))

    verified = classification.state == "verified"
    if verified and classification.statement_model not in rule.statement_models:
        reason = f"rule applies to {[m.value for m in rule.statement_models]}, not {classification.statement_model}"
        return _result(rule, group, RuleStatus.NOT_APPLICABLE, required=False), [
            _finding(FindingCode.RULE_NOT_APPLICABLE, reason, rule=rule, group=group, skipped_reason=reason)
        ]
    required = True if verified else None

    missing = tuple(concept for concept in rule.required_concepts if concept not in present)
    if missing:
        result = _result(rule, group, RuleStatus.NOT_EVALUATED, required, facts=refs, missing_concepts=missing)
        reason = f"missing {', '.join(missing)}"
        if not verified:
            code = FindingCode.RULE_NOT_EVALUATED_SECTOR_UNVERIFIED
            message = f"not evaluated: {reason}; with an unverified sector it is unknown whether this rule applies"
        elif present:
            result = result.model_copy(update={"status": RuleStatus.INPUTS_MISSING})
            code = FindingCode.REQUIRED_RULE_INPUTS_MISSING
            message = f"required rule has only some of its inputs: {reason}"
        else:
            code = FindingCode.REQUIRED_RULE_NOT_EVALUATED
            message = f"required rule has no inputs in this period: {reason}"
        return result, [_finding(code, message, rule=rule, group=group, facts=refs, skipped_reason=reason)]

    units = {fact.unit for facts in present.values() for fact in facts}
    if len(units) > 1 or any(len(facts) > 1 for facts in present.values()):
        message = f"rule inputs are in incompatible units: {sorted(unit.value for unit in units)}; no conversion is attempted"
        return _result(rule, group, RuleStatus.UNIT_MISMATCH, required, facts=refs), [
            _finding(FindingCode.RULE_UNIT_MISMATCH, message, rule=rule, group=group, facts=refs)
        ]

    (unit,) = units
    reported = present[rule.total][0].value
    computed = sum(c.coefficient * present[c.concept][0].value for c in rule.components if c.concept in present)
    difference = reported - computed
    assumed = tuple(c for c in rule.components if c.optional and c.concept not in present)
    passed = abs(difference) <= rule.tolerance
    result = RuleResult(
        rule_id=rule.rule_id,
        group=group,
        tolerance=rule.tolerance,
        status=RuleStatus.PASSED if passed else RuleStatus.FAILED,
        required=required,
        unit=unit,
        reported_total=reported,
        computed_total=computed,
        difference=difference,
        facts=refs,
        assumed_absent=tuple(c.concept for c in assumed),
    )
    findings = [
        _finding(
            FindingCode.OPTIONAL_TERM_ASSUMED,
            f"{component.concept} is absent; the rule was evaluated under the declared assumption",
            rule=rule,
            group=group,
            facts=refs,
            assumption=component.assumption_when_absent,
        )
        for component in assumed
    ]
    if not passed:
        findings.append(
            _finding(
                FindingCode.RULE_FAILED,
                f"{rule.total} is {reported} {unit.value} but its components sum to {computed} "
                f"(difference {difference}, tolerance {rule.tolerance})",
                rule=rule,
                group=group,
                facts=refs,
            )
        )
    return result, findings


def _result(
    rule: AccountingRule,
    group: PeriodGroup,
    status: RuleStatus,
    required: bool | None,
    *,
    facts: tuple[FactRef, ...] = (),
    missing_concepts: tuple[str, ...] = (),
) -> RuleResult:
    """A result for a rule that was not computed."""
    return RuleResult(
        rule_id=rule.rule_id,
        group=group,
        tolerance=rule.tolerance,
        status=status,
        required=required,
        facts=facts,
        missing_concepts=missing_concepts,
    )


def _provenance_findings(
    facts: FinancialFactsDocument, sources: SourceRegistryDocument, evidence_root: Path | None
) -> list[Finding]:
    findings: list[Finding] = []
    by_source: dict[str, list[FinancialFact]] = defaultdict(list)
    for fact in facts.facts:
        by_source[fact.source_id].append(fact)

    linked: list[SourceDocument] = []
    for source_id in sorted(by_source):
        refs = tuple(_ref(fact) for fact in by_source[source_id])
        source = sources.get(source_id)
        if source is None:
            findings.append(
                _finding(FindingCode.SOURCE_NOT_REGISTERED, f"source {source_id} is not in the source registry", facts=refs, source_ids=(source_id,))
            )
            continue
        # An exchange-wide source (company_id null) may support any company's facts.
        if source.company_id is not None and source.company_id != facts.company_id:
            findings.append(
                _finding(
                    FindingCode.SOURCE_COMPANY_MISMATCH,
                    f"source {source_id} is registered to {source.company_id}, not {facts.company_id}",
                    facts=refs,
                    source_ids=(source_id,),
                )
            )
        linked.append(source)
        if source.provenance_gaps:
            findings.append(
                _finding(
                    FindingCode.SOURCE_PROVENANCE_GAP,
                    f"source {source_id} does not record: {', '.join(source.provenance_gaps)}",
                    source_ids=(source_id,),
                )
            )
    findings += _evidence_findings(linked, evidence_root)

    by_status: dict[VerificationStatus, list[FactRef]] = defaultdict(list)
    by_gap: dict[str, list[FactRef]] = defaultdict(list)
    for fact in facts.facts:
        if fact.verification_status is not VerificationStatus.VERIFIED:
            by_status[fact.verification_status].append(_ref(fact))
        for gap in fact.provenance_gaps:
            by_gap[gap].append(_ref(fact))
    for status, refs_list in sorted(by_status.items()):
        findings.append(
            _finding(FindingCode.FACT_NOT_VERIFIED, f"{len(refs_list)} facts have status {status.value!r}", facts=tuple(refs_list))
        )
    for gap, refs_list in sorted(by_gap.items()):
        findings.append(
            _finding(FindingCode.FACT_PROVENANCE_GAP, f"{len(refs_list)} facts do not record {gap}", facts=tuple(refs_list))
        )
    return findings


def _evidence_findings(sources: list[SourceDocument], evidence_root: Path | None) -> list[Finding]:
    if not sources:
        return []
    if evidence_root is None:
        return [
            _finding(
                FindingCode.EVIDENCE_NOT_CHECKED,
                "no evidence root was given, so raw evidence hashes were not checked",
                source_ids=tuple(source.source_id for source in sources),
            )
        ]
    root = evidence_root.resolve()
    findings = []
    for source in sources:
        path = (root / source.local_path).resolve()
        ids = (source.source_id,)
        if not path.is_relative_to(root):
            findings.append(_finding(FindingCode.EVIDENCE_PATH_OUTSIDE_ROOT, f"{source.local_path} resolves outside the evidence root", source_ids=ids))
        elif not path.is_file():
            findings.append(_finding(FindingCode.EVIDENCE_FILE_MISSING, f"evidence file not found: {source.local_path}", source_ids=ids))
        elif sha256_bytes(path.read_bytes()) != source.sha256:
            findings.append(
                _finding(FindingCode.EVIDENCE_HASH_MISMATCH, f"{source.local_path} does not match its registered SHA-256", source_ids=ids)
            )
    return findings


def _finding(
    code: FindingCode,
    message: str,
    *,
    rule: AccountingRule | None = None,
    group: PeriodGroup | None = None,
    facts: tuple[FactRef, ...] = (),
    source_ids: tuple[str, ...] = (),
    assumption: str | None = None,
    skipped_reason: str | None = None,
) -> Finding:
    if not source_ids and facts:
        source_ids = tuple(sorted({ref.source_id for ref in facts}))
    return Finding(
        code=code,
        severity=SEVERITY[code],
        message=message,
        rule_id=rule.rule_id if rule else None,
        group=group,
        facts=facts,
        source_ids=source_ids,
        assumption=assumption,
        skipped_reason=skipped_reason,
    )


def _ref(fact: FinancialFact) -> FactRef:
    return FactRef(
        company_id=fact.company_id,
        concept=fact.concept,
        scope=fact.scope,
        period_end=fact.period.end,
        period_type=fact.period.type,
        unit=fact.unit,
        source_id=fact.source_id,
    )


def _group_sort_key(group: PeriodGroup) -> tuple[str, str, str, str]:
    return (group.company_id, group.scope.value, group.period_end.isoformat(), group.period_type.value)


def _finding_sort_key(finding: Finding) -> tuple[int, str, str, tuple[str, str, str, str], str]:
    group = _group_sort_key(finding.group) if finding.group else ("", "", "", "")
    return (_SEVERITY_ORDER[finding.severity], finding.code.value, finding.rule_id or "", group, finding.message)


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return dict(sorted(counts.items()))


@dataclass(frozen=True)
class _Inputs:
    facts: FinancialFactsDocument
    sources: SourceRegistryDocument
    rules: AccountingRuleSet
    classification: ClassificationStatus
    records: tuple[InputRecord, ...]


def _load_inputs(args: argparse.Namespace) -> _Inputs:
    facts = load_model(args.facts, FinancialFactsDocument)
    sources = load_model(args.sources, SourceRegistryDocument)
    rules = load_accounting_rules(args.rules)
    profiles = load_sector_profiles(args.sector_profiles)
    company = None
    if args.companies is not None:
        try:
            company = RegistryFileCompanies.load(args.companies).get(facts.company_id)
        except UnknownCompanyError:
            company = None
    paths: list[tuple[InputRole, Path]] = [
        ("facts", args.facts),
        ("sources", args.sources),
        ("rules", args.rules),
        ("sector_profiles", args.sector_profiles),
    ]
    if args.companies is not None:
        paths.append(("companies", args.companies))
    records = [InputRecord(role=role, path=str(path), sha256=sha256_bytes(path.read_bytes())) for role, path in paths]
    if args.evidence_root is not None:
        records.append(InputRecord(role="evidence_root", path=str(args.evidence_root), sha256=None))
    classification = resolve_classification(company, profiles)
    if company is None and args.companies is not None:
        classification = ClassificationStatus(
            state="unavailable", detail=f"company {facts.company_id} is not in {args.companies}"
        )
    return _Inputs(facts, sources, rules, classification, tuple(records))


def _check_output(out: Path, inputs: Iterable[Path]) -> None:
    target = out.resolve()
    if any(target == path.resolve() for path in inputs):
        raise ValidationInputError(f"refusing to write the report over an input file: {out}")
    for forbidden in FORBIDDEN_OUTPUT_DIRS:
        if target.is_relative_to(forbidden.resolve()):
            raise ValidationInputError(f"refusing to write into {forbidden}; choose another output path")


EXIT_CODES = {Verdict.PASSED: 0, Verdict.PASSED_WITH_WARNINGS: 0, Verdict.FAILED: 1, Verdict.INCOMPLETE: 3}
EXIT_REFUSED = 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a v2 facts document and report a readiness verdict.")
    parser.add_argument("--facts", type=Path, required=True, help="v2 financial facts document")
    parser.add_argument("--sources", type=Path, required=True, help="v2 source registry")
    parser.add_argument("--out", type=Path, required=True, help="validation report to write")
    parser.add_argument("--evidence-root", type=Path, help="directory registry local_path values are relative to")
    parser.add_argument("--companies", type=Path, help="company registry; without it the sector is unavailable")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--sector-profiles", type=Path, default=DEFAULT_SECTOR_PROFILES)
    parser.add_argument("--backup-dir", type=Path, help="required to replace an existing report")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    try:
        inputs = [args.facts, args.sources, args.rules, args.sector_profiles]
        if args.companies is not None:
            inputs.append(args.companies)
        _check_output(args.out, inputs)
        loaded = _load_inputs(args)
        report = validate(
            loaded.facts,
            loaded.sources,
            loaded.rules,
            classification=loaded.classification,
            evidence_root=args.evidence_root,
            validated_at=now,
            inputs=loaded.records,
        )
        replace_files({args.out: dump_model(report)}, backup_dir=args.backup_dir, stamp=now)
    except (SchemaLoadError, ValidationInputError, StorageError, ValidationError, OSError) as exc:
        print(f"Validation refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(
        f"{report.company_id}: {report.verdict.value}; rules {report.rule_status_counts}; findings {report.finding_counts}"
    )
    print(f"Report: {args.out}")
    return EXIT_CODES[report.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
