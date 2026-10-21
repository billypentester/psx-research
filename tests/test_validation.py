"""Phase 6, step 1: accounting rules, provenance checks, and the readiness verdict."""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from finura.accounting_rules import AccountingRuleSet, load_accounting_rules
from finura.companies import RegistryFileCompanies
from finura.schemas import Company, FinancialFact, FinancialFactsDocument, SourceDocument, SourceRegistryDocument
from finura.schemas.v1 import load_v1_financial_facts, load_v1_source_registry
from finura.sectors import load_sector_profiles
from finura.validation import (
    ClassificationStatus,
    FindingCode,
    RuleStatus,
    Verdict,
    main,
    resolve_classification,
    validate,
)
from pipeline.validate import check_cash_flows, check_reconciliations
from tests.network_guard import NoNetworkTestCase

ROOT = Path(__file__).resolve().parents[1]
FFC_FACTS = ROOT / "data/v2/facts/FFC/financial_facts.json"
FFC_SOURCES = ROOT / "data/v2/sources/source_registry.json"
FFC_COMPANIES = ROOT / "data/v2/companies/company_registry.json"
SYNTHETIC = ROOT / "tests/fixtures/v1_synthetic"
RULES = load_accounting_rules(ROOT / "config/accounting_rules.json")
PROFILES = load_sector_profiles(ROOT / "config/sector_profiles.json")
COMPANIES = RegistryFileCompanies.load(SYNTHETIC / "companies.json")
AT = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
UNAVAILABLE = ClassificationStatus(state="unavailable", detail="no company record was supplied")


def ffc():
    facts = FinancialFactsDocument.model_validate_json(FFC_FACTS.read_text(encoding="utf-8"))
    sources = SourceRegistryDocument.model_validate_json(FFC_SOURCES.read_text(encoding="utf-8"))
    return facts, sources


def synthetic(company):
    facts = FinancialFactsDocument(company_id=company, facts=load_v1_financial_facts(SYNTHETIC / company / "financial_facts.json").facts)
    sources = SourceRegistryDocument(sources=load_v1_source_registry(SYNTHETIC / "source_registry.json").documents)
    return facts, sources


def with_facts(document, facts):
    return FinancialFactsDocument(company_id=document.company_id, facts=tuple(facts))


def replace_fact(document, match, **changes):
    updated = [fact.model_copy(update=changes) if match(fact) else fact for fact in document.facts]
    return with_facts(document, (FinancialFact.model_validate(dict(fact)) for fact in updated))


def verified_classification(company_id):
    company = COMPANIES.get(company_id)
    attestation = COMPANIES.get("SYNBANK").classification.attestation.model_dump(mode="json")
    sector = {"SYNBANK": "commercial_banks", "SYNIND": "cement"}[company_id]
    return Company.model_validate({**company.model_dump(mode="json"), "classification": {"sector_key": sector, "attestation": attestation}})


def run(facts, sources, classification=UNAVAILABLE, evidence_root=None, rules=RULES):
    return validate(facts, sources, rules, classification=classification, evidence_root=evidence_root, validated_at=AT)


def results(report, rule_id=None, status=None):
    return [r for r in report.rule_results if (rule_id is None or r.rule_id == rule_id) and (status is None or r.status is status)]


def codes(report):
    return {finding.code for finding in report.findings}


def legacy_passes(module, company="FFC"):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = module.main(company)
    return status, output.getvalue()


class TestFfcRegression(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.facts, self.sources = ffc()
        self.report = run(self.facts, self.sources, evidence_root=ROOT)

    def test_balance_sheet_matches_legacy_four_cases(self):
        status, output = legacy_passes(check_reconciliations)
        legacy = set(re.findall(r"PASS: Balance sheet reconciles: (\w+) (\S+)", output))
        self.assertEqual((status, len(legacy)), (0, 4))
        new = {(r.group.scope.value, r.group.period_end.isoformat()) for r in results(self.report, "balance_sheet_assets_equal_equity_and_liabilities", RuleStatus.PASSED)}
        self.assertEqual(new, legacy)

    def test_cash_flows_match_legacy_eight_cases(self):
        status, output = legacy_passes(check_cash_flows)
        activities = set(re.findall(r"PASS: Activity totals reconcile, (\w+) (\S+)", output))
        balances = set(re.findall(r"PASS: Cash balance reconciles, (\w+) (\S+)", output))
        self.assertEqual((status, len(activities) + len(balances)), (0, 8))
        for rule_id, legacy in (("cash_flow_activities_sum_to_net_change", activities), ("cash_roll_forward", balances)):
            new = {(r.group.scope.value, r.group.period_end.isoformat()) for r in results(self.report, rule_id, RuleStatus.PASSED)}
            self.assertEqual(new, legacy, rule_id)
        for result in results(self.report, status=RuleStatus.PASSED):
            self.assertEqual(result.difference, 0)

    def test_fy2025_merger_cash_assumption_is_reported(self):
        assumed = [f for f in self.report.findings if f.code is FindingCode.OPTIONAL_TERM_ASSUMED]
        self.assertEqual(sorted((f.group.scope.value, f.group.period_end.isoformat()) for f in assumed), [("consolidated", "2025-12-31"), ("standalone", "2025-12-31")])
        for finding in assumed:
            self.assertEqual(finding.rule_id, "cash_roll_forward")
            self.assertIn("taken as nil", finding.assumption)
            self.assertEqual({ref.period_end.isoformat() for ref in finding.facts}, {"2025-12-31"})
            self.assertEqual(finding.source_ids, ("src_e4abb64ff4886ffc",))

    def test_ffc_never_passes_while_sector_unverified(self):
        self.assertIs(self.report.verdict, Verdict.INCOMPLETE)
        self.assertIn(FindingCode.SECTOR_UNVERIFIED, codes(self.report))
        self.assertIn(FindingCode.RULE_NOT_EVALUATED_SECTOR_UNVERIFIED, codes(self.report))
        company = RegistryFileCompanies.load(FFC_COMPANIES).get("FFC")
        unverified = run(self.facts, self.sources, resolve_classification(company, PROFILES), ROOT)
        self.assertEqual(unverified.classification.state, "unverified")
        self.assertIs(unverified.verdict, Verdict.INCOMPLETE)

    def test_evidence_and_provenance_are_reported_not_changed(self):
        self.assertFalse({FindingCode.EVIDENCE_HASH_MISMATCH, FindingCode.EVIDENCE_FILE_MISSING} & codes(self.report))
        gaps = [f for f in self.report.findings if f.code is FindingCode.FACT_PROVENANCE_GAP]
        self.assertEqual(len(gaps), 6)
        self.assertTrue(all(len(f.facts) == 60 for f in gaps))
        self.assertEqual(self.report.fact_count, 60)

    def test_inputs_are_not_modified(self):
        before = {path: path.read_bytes() for path in (FFC_FACTS, FFC_SOURCES)}
        run(*ffc(), evidence_root=ROOT)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        statuses = {f.verification_status.value for f in self.facts.facts}
        self.assertEqual(statuses, {"verified"})


class TestSyntheticFixtures(NoNetworkTestCase):
    def test_verified_bank_rules_pass_and_general_rules_are_not_applicable(self):
        facts, sources = synthetic("SYNBANK")
        current = with_facts(facts, (f for f in facts.facts if f.period.end.year == 2025))
        classification = resolve_classification(COMPANIES.get("SYNBANK"), PROFILES)
        self.assertEqual(classification.statement_model.value, "banking")
        report = run(current, sources, classification, SYNTHETIC)
        for rule_id in ("balance_sheet_assets_equal_liabilities_and_net_assets", "net_markup_interest_income_subtotal"):
            self.assertEqual([r.status for r in results(report, rule_id)], [RuleStatus.PASSED], rule_id)
        for rule_id in ("balance_sheet_assets_equal_equity_and_liabilities", "cash_flow_activities_sum_to_net_change", "gross_profit_subtotal"):
            self.assertEqual([r.status for r in results(report, rule_id)], [RuleStatus.NOT_APPLICABLE], rule_id)
        self.assertIs(report.verdict, Verdict.PASSED_WITH_WARNINGS)
        self.assertIn(FindingCode.FACT_NOT_VERIFIED, codes(report))

    def test_verified_bank_with_partial_comparatives_fails(self):
        facts, sources = synthetic("SYNBANK")
        report = run(facts, sources, resolve_classification(COMPANIES.get("SYNBANK"), PROFILES), SYNTHETIC)
        prior = [r for r in report.rule_results if r.group.period_end.year == 2024]
        by_rule = {r.rule_id: r.status for r in prior}
        self.assertEqual(by_rule["net_markup_interest_income_subtotal"], RuleStatus.INPUTS_MISSING)
        self.assertEqual(by_rule["balance_sheet_assets_equal_liabilities_and_net_assets"], RuleStatus.NOT_EVALUATED)
        self.assertIs(report.verdict, Verdict.FAILED)
        self.assertIn(FindingCode.REQUIRED_RULE_INPUTS_MISSING, codes(report))

    def test_unverified_bank_sector_never_infers_a_statement_model(self):
        facts, sources = synthetic("SYNBANK")
        company = COMPANIES.get("SYNBANK")
        unverified = Company.model_validate(
            {**company.model_dump(mode="json"), "classification": {"sector_key": "commercial_banks", "attestation": {"state": "unverified"}}}
        )
        report = run(facts, sources, resolve_classification(unverified, PROFILES), SYNTHETIC)
        self.assertEqual(report.classification.state, "unverified")
        self.assertFalse(results(report, status=RuleStatus.NOT_APPLICABLE))
        self.assertTrue(all(r.required is None for r in report.rule_results))
        # Rules whose inputs are all present still run; nothing can pass overall.
        self.assertTrue(results(report, "balance_sheet_assets_equal_liabilities_and_net_assets", RuleStatus.PASSED))
        self.assertIs(report.verdict, Verdict.INCOMPLETE)

    def test_industrial_quarter_passes_without_mixing_year_to_date(self):
        facts, sources = synthetic("SYNIND")
        report = run(facts, sources, resolve_classification(COMPANIES.get("SYNIND"), PROFILES), SYNTHETIC)
        self.assertEqual(report.classification.state, "unverified")
        gross = {r.group.period_type.value: r for r in results(report, "gross_profit_subtotal")}
        self.assertIs(gross["quarterly"].status, RuleStatus.PASSED)
        self.assertEqual({ref.period_type.value for ref in gross["quarterly"].facts}, {"quarterly"})
        self.assertIs(gross["year_to_date"].status, RuleStatus.NOT_EVALUATED)
        self.assertEqual(gross["year_to_date"].missing_concepts, ("gross_profit", "cost_of_sales"))
        self.assertIs(report.verdict, Verdict.INCOMPLETE)

    def test_verified_industrial_reports_missing_statements(self):
        facts, sources = synthetic("SYNIND")
        classification = resolve_classification(verified_classification("SYNIND"), PROFILES)
        self.assertEqual(classification.statement_model.value, "general")
        report = run(facts, sources, classification, SYNTHETIC)
        quarter = {r.rule_id: r.status for r in report.rule_results if r.group.period_type.value == "quarterly"}
        self.assertEqual(quarter["gross_profit_subtotal"], RuleStatus.PASSED)
        self.assertEqual(quarter["balance_sheet_assets_equal_equity_and_liabilities"], RuleStatus.NOT_EVALUATED)
        self.assertEqual(quarter["net_markup_interest_income_subtotal"], RuleStatus.NOT_APPLICABLE)
        ytd = {r.rule_id: r.status for r in report.rule_results if r.group.period_type.value == "year_to_date"}
        self.assertEqual(ytd["gross_profit_subtotal"], RuleStatus.INPUTS_MISSING)
        self.assertIs(report.verdict, Verdict.FAILED)

    def test_clean_complete_fact_set_passes(self):
        facts, sources = synthetic("SYNBANK")
        source = sources.sources[0]
        clean_source = SourceDocument.model_validate(
            {**source.model_dump(mode="json"), "retrieved_at": "2026-03-01T09:30:00+05:00", "access_basis": "licensed", "upstream": [], "publisher": "Synthetic Bank Limited"}
        )
        self.assertEqual(clean_source.provenance_gaps, ())
        provenance = {
            "verification_status": "verified",
            "verified_by": "analyst",
            "verified_at": "2026-03-02T10:00:00+05:00",
            "verification_evidence": "visual check of page 10",
            "extraction_method": "manual_transcription",
            "extracted_at": "2026-03-01T12:00:00+05:00",
        }
        clean = [
            FinancialFact.model_validate({**f.model_dump(mode="json"), **provenance, "period": {**f.period.model_dump(mode="json"), "start": "2025-01-01"}})
            for f in facts.facts
            if f.period.end.year == 2025
        ]
        report = run(with_facts(facts, clean), SourceRegistryDocument(sources=(clean_source,)), resolve_classification(COMPANIES.get("SYNBANK"), PROFILES), SYNTHETIC)
        self.assertEqual([f.code for f in report.findings if f.severity.value != "info"], [])
        self.assertIs(report.verdict, Verdict.PASSED)


class TestRejections(NoNetworkTestCase):
    def test_altered_total_fails(self):
        facts, sources = ffc()
        altered = replace_fact(facts, lambda f: f.concept == "total_assets" and f.scope.value == "standalone" and f.period.end.year == 2025, value=1)
        report = run(altered, sources, evidence_root=ROOT)
        failed = [f for f in report.findings if f.code is FindingCode.RULE_FAILED]
        self.assertEqual([(f.rule_id, f.group.scope.value) for f in failed], [("balance_sheet_assets_equal_equity_and_liabilities", "standalone")])
        self.assertIs(report.verdict, Verdict.FAILED)

    def test_unit_mismatch_fails_without_conversion(self):
        facts, sources = synthetic("SYNIND")
        mismatched = replace_fact(facts, lambda f: f.concept == "cost_of_sales", unit="PKR_thousand")
        report = run(mismatched, sources, evidence_root=SYNTHETIC)
        self.assertEqual([r.status for r in results(report, "gross_profit_subtotal") if r.group.period_type.value == "quarterly"], [RuleStatus.UNIT_MISMATCH])
        self.assertIn(FindingCode.RULE_UNIT_MISMATCH, codes(report))
        self.assertIs(report.verdict, Verdict.FAILED)

    def test_unregistered_source_fails(self):
        facts, sources = synthetic("SYNBANK")
        report = run(facts, SourceRegistryDocument(sources=tuple(s for s in sources.sources if s.company_id != "SYNBANK")))
        self.assertIn(FindingCode.SOURCE_NOT_REGISTERED, codes(report))
        self.assertIs(report.verdict, Verdict.FAILED)

    def test_source_of_another_company_fails(self):
        facts, sources = synthetic("SYNBANK")
        moved = replace_fact(facts, lambda f: f.concept == "total_assets", source_id="src_synind2025q3")
        report = run(moved, sources)
        finding = next(f for f in report.findings if f.code is FindingCode.SOURCE_COMPANY_MISMATCH)
        self.assertEqual(finding.source_ids, ("src_synind2025q3",))
        self.assertIs(report.verdict, Verdict.FAILED)

    def test_exchange_wide_source_is_allowed(self):
        facts, sources = synthetic("SYNBANK")
        wide = SourceRegistryDocument(sources=tuple(s.model_copy(update={"company_id": None}) if s.company_id == "SYNBANK" else s for s in sources.sources))
        self.assertNotIn(FindingCode.SOURCE_COMPANY_MISMATCH, codes(run(facts, wide)))

    def test_tampered_and_missing_evidence_fail(self):
        facts, sources = synthetic("SYNBANK")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(SYNTHETIC, root, dirs_exist_ok=True)
            self.assertFalse({FindingCode.EVIDENCE_HASH_MISMATCH, FindingCode.EVIDENCE_FILE_MISSING} & codes(run(facts, sources, evidence_root=root)))
            (root / "raw/SYNBANK/annual_2025.txt").write_text("tampered", encoding="utf-8")
            tampered = run(facts, sources, evidence_root=root)
            self.assertIn(FindingCode.EVIDENCE_HASH_MISMATCH, codes(tampered))
            self.assertIs(tampered.verdict, Verdict.FAILED)
            (root / "raw/SYNBANK/annual_2025.txt").unlink()
            self.assertIn(FindingCode.EVIDENCE_FILE_MISSING, codes(run(facts, sources, evidence_root=root)))

    def test_evidence_not_checked_without_root(self):
        facts, sources = synthetic("SYNBANK")
        self.assertIn(FindingCode.EVIDENCE_NOT_CHECKED, codes(run(facts, sources)))

    def test_empty_fact_set_is_incomplete(self):
        _, sources = synthetic("SYNBANK")
        report = run(FinancialFactsDocument(company_id="SYNBANK", facts=()), sources, resolve_classification(COMPANIES.get("SYNBANK"), PROFILES))
        self.assertIn(FindingCode.EMPTY_FACT_SET, codes(report))
        self.assertIs(report.verdict, Verdict.INCOMPLETE)

    def test_no_evaluable_rule_is_incomplete(self):
        facts, sources = synthetic("SYNBANK")
        eps_only = with_facts(facts, (f for f in facts.facts if f.concept == "earnings_per_share"))
        report = run(eps_only, sources, resolve_classification(COMPANIES.get("SYNBANK"), PROFILES))
        self.assertIn(FindingCode.NO_CHECKS_EVALUATED, codes(report))
        self.assertIs(report.verdict, Verdict.INCOMPLETE)

    def test_warnings_never_hide_errors(self):
        facts, sources = ffc()
        altered = replace_fact(facts, lambda f: f.concept == "cash_and_cash_equivalents_ending", value=0)
        report = run(altered, sources)
        self.assertIn(FindingCode.FACT_PROVENANCE_GAP, codes(report))
        self.assertIs(report.verdict, Verdict.FAILED)


class TestRulesAndDeterminism(NoNetworkTestCase):
    def rule_set(self, **component_changes):
        payload = json.loads((ROOT / "config/accounting_rules.json").read_text(encoding="utf-8"))
        payload["rules"][0]["components"][0].update(component_changes)
        return payload

    def test_shipped_rules_load(self):
        self.assertEqual(len(RULES.rules), 6)

    def test_malformed_coefficients_are_rejected(self):
        for coefficient in (0, "1", True, 1.5, None):
            with self.subTest(coefficient=coefficient):
                with self.assertRaises(ValidationError):
                    AccountingRuleSet.model_validate(self.rule_set(coefficient=coefficient))

    def test_optional_terms_need_an_assumption(self):
        with self.assertRaises(ValidationError):
            AccountingRuleSet.model_validate(self.rule_set(optional=True))
        with self.assertRaises(ValidationError):
            AccountingRuleSet.model_validate(self.rule_set(assumption_when_absent="unused"))

    def test_duplicate_rule_ids_and_unjustified_tolerance_are_rejected(self):
        payload = self.rule_set()
        payload["rules"].append(payload["rules"][0])
        with self.assertRaisesRegex(ValidationError, "duplicate rule_id"):
            AccountingRuleSet.model_validate(payload)
        payload = self.rule_set()
        payload["rules"][0]["tolerance"] = 1
        with self.assertRaisesRegex(ValidationError, "tolerance_basis"):
            AccountingRuleSet.model_validate(payload)

    def test_unknown_concepts_are_allowed_and_reported(self):
        payload = self.rule_set(concept="not_a_known_concept")
        rules = AccountingRuleSet.model_validate(payload)
        report = run(*ffc(), rules=rules)
        finding = next(f for f in report.findings if f.code is FindingCode.RULE_CONCEPTS_NOT_IN_FACTS)
        self.assertIn("not_a_known_concept", finding.message)

    def test_repeated_runs_are_identical(self):
        facts, sources = ffc()
        first = run(facts, sources, evidence_root=ROOT)
        second = run(facts, sources, evidence_root=ROOT)
        self.assertEqual(first, second)
        self.assertEqual(len(first.findings), len(second.findings))


class TestCommandLine(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main([str(a) for a in arguments])
        return status, stdout.getvalue() + stderr.getvalue()

    def ffc_args(self, out):
        return ("--facts", FFC_FACTS, "--sources", FFC_SOURCES, "--evidence-root", ROOT, "--companies", FFC_COMPANIES, "--out", out)

    def test_ffc_report_is_incomplete_with_exit_3_and_overwrite_protection(self):
        out = self.dir / "report.json"
        status, output = self.cli(*self.ffc_args(out))
        self.assertEqual(status, 3, output)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "incomplete")
        self.assertEqual({r["role"] for r in report["inputs"]}, {"facts", "sources", "rules", "sector_profiles", "companies", "evidence_root"})
        self.assertEqual(self.cli(*self.ffc_args(out))[0], 4)
        self.assertEqual(self.cli(*self.ffc_args(out), "--backup-dir", self.dir / "bak")[0], 3)
        self.assertEqual(len(list((self.dir / "bak").iterdir())), 1)

    def test_exit_codes_for_failed_and_passing_verdicts(self):
        facts, sources = synthetic("SYNBANK")
        facts_path, sources_path = self.dir / "facts.json", self.dir / "sources.json"
        sources_path.write_text(sources.model_dump_json(), encoding="utf-8")
        common = ("--sources", sources_path, "--companies", SYNTHETIC / "companies.json", "--evidence-root", SYNTHETIC)
        facts_path.write_text(facts.model_dump_json(), encoding="utf-8")
        self.assertEqual(self.cli("--facts", facts_path, *common, "--out", self.dir / "failed.json")[0], 1)
        current = with_facts(facts, (f for f in facts.facts if f.period.end.year == 2025))
        facts_path.write_text(current.model_dump_json(), encoding="utf-8")
        status, output = self.cli("--facts", facts_path, *common, "--out", self.dir / "warn.json", "--backup-dir", self.dir / "b")
        self.assertEqual(status, 0, output)
        self.assertIn("passed_with_warnings", output)

    def test_refuses_protected_locations_and_inputs(self):
        for out in (ROOT / "data/v2/validation.json", ROOT / "runs/FFC/report.json", FFC_FACTS):
            with self.subTest(out=out):
                status, output = self.cli(*self.ffc_args(out))
                self.assertEqual(status, 4)
                self.assertIn("refusing", output)
        self.assertFalse((ROOT / "data/v2/validation.json").exists())
        self.assertFalse((ROOT / "runs").exists())

    def test_invalid_input_writes_nothing(self):
        bad = self.dir / "bad.json"
        bad.write_text('{"schema_version": 2, "record_type": "financial_facts", "company_id": "X", "facts": [{"value": true}]}', encoding="utf-8")
        status, output = self.cli("--facts", bad, "--sources", FFC_SOURCES, "--out", self.dir / "report.json")
        self.assertEqual(status, 4)
        self.assertIn("Validation refused", output)
        self.assertFalse((self.dir / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
