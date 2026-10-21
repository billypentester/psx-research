"""v1 -> v2 migration: FFC as the real fixture, synthetic companies for generality."""

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from finura.companies import RegistryFileCompanies
from finura.migrations.v1_to_v2 import MigrationError, MigrationRequest, main, migrate_v1_to_v2
from finura.schemas import FinancialFactsDocument, SourceRegistryDocument

ROOT = Path(__file__).resolve().parents[1]
FFC_FACTS = ROOT / "data/normalized/FFC/financial_facts.json"
REGISTRY = ROOT / "data/source_registry.json"
SYNTHETIC = ROOT / "tests/fixtures/v1_synthetic"
MIGRATED_AT = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MigrationTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.out = Path(directory.name)

    def request(self, facts, registry=REGISTRY, **overrides):
        values = {
            "facts_input": facts,
            "registry_input": registry,
            "facts_output": self.out / "facts.v2.json",
            "registry_output": self.out / "registry.v2.json",
            "manifest_output": self.out / "manifest.json",
        }
        values.update(overrides)
        return MigrationRequest(**values)

    def assertNoOutputs(self):
        self.assertEqual([path.name for path in self.out.rglob("*") if path.is_file()], [])


class TestFfcMigration(MigrationTestCase):
    def setUp(self):
        super().setUp()
        self.inputs_before = {path: digest(path) for path in (FFC_FACTS, REGISTRY, ROOT / "data/raw/FFC/ffc_report.pdf")}
        self.manifest = migrate_v1_to_v2(self.request(FFC_FACTS, evidence_root=ROOT), migrated_at=MIGRATED_AT)
        self.raw = json.loads(FFC_FACTS.read_text(encoding="utf-8"))
        self.migrated = FinancialFactsDocument.model_validate_json((self.out / "facts.v2.json").read_text(encoding="utf-8"))

    def test_all_sixty_facts_migrate_losslessly(self):
        self.assertEqual(len(self.migrated.facts), 60)
        for index, (old, new) in enumerate(zip(self.raw["facts"], self.migrated.facts, strict=True)):
            with self.subTest(fact=index):
                self.assertEqual(new.concept, old["metric"])
                self.assertEqual(new.value, old["value"])
                self.assertIs(type(new.value), type(old["value"]))
                self.assertEqual(new.unit.value, old["unit"])
                self.assertEqual(new.period.end.isoformat(), old["period_end"])
                self.assertEqual(new.period.type.value, old["period_type"])
                self.assertEqual(new.scope.value, old["scope"])
                self.assertEqual(new.source_id, old["source_id"])
                self.assertEqual(new.source_location, old["source_page"])
                self.assertEqual(new.verification_status.value, old["verification_status"])

    def test_manifest_records_versions_counts_and_equivalence(self):
        manifest = self.manifest
        self.assertEqual(manifest.company_id, "FFC")
        self.assertEqual([(f.role, f.schema_version, f.record_count) for f in manifest.inputs], [("v1_financial_facts", 1, 60), ("v1_source_registry", 1, 1)])
        self.assertEqual([(f.role, f.schema_version, f.record_count) for f in manifest.outputs], [("v2_financial_facts", 2, 60), ("v2_source_registry", 2, 1)])
        self.assertEqual(manifest.fact_equivalence.records_compared, 60)
        self.assertEqual(manifest.fact_equivalence.mismatches, ())
        self.assertEqual(manifest.source_equivalence.mismatches, ())
        self.assertEqual(manifest.source_timestamps_text_identical, 1)
        self.assertEqual(manifest.validation.source_links_same_company, 60)
        self.assertEqual(manifest.validation.company_identity, "not_checked")
        self.assertEqual([check.result for check in manifest.validation.evidence_checks], ["sha256_match"])
        self.assertTrue(manifest.inputs_unchanged)

    def test_written_manifest_matches_outputs(self):
        written = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(written["outputs"][0]["sha256"], digest(self.out / "facts.v2.json"))
        self.assertEqual(written["outputs"][1]["sha256"], digest(self.out / "registry.v2.json"))
        self.assertEqual(written["inputs"][0]["sha256"], self.inputs_before[FFC_FACTS])

    def test_verification_status_is_not_upgraded(self):
        self.assertEqual(self.manifest.verification_status_counts_v1, self.manifest.verification_status_counts_v2)

    def test_unknown_provenance_remains_unknown(self):
        self.assertEqual(
            self.manifest.fact_provenance_gaps,
            {field: 60 for field in ("period.start", "extraction_method", "extracted_at", "verified_by", "verified_at", "verification_evidence")},
        )
        self.assertEqual(
            self.manifest.source_provenance_gaps,
            {field: 1 for field in ("publisher", "published_at", "retrieved_at", "provider", "retrieval_method", "access_basis", "upstream")},
        )
        written = json.loads((self.out / "facts.v2.json").read_text(encoding="utf-8"))["facts"][0]
        # Unknown values are written as explicit nulls, not omitted or defaulted.
        for field in ("verified_by", "verified_at", "verification_evidence", "extraction_method", "extracted_at"):
            self.assertIn(field, written)
            self.assertIsNone(written[field])

    def test_source_registry_identity_and_evidence_reference_preserved(self):
        registry = SourceRegistryDocument.model_validate_json((self.out / "registry.v2.json").read_text(encoding="utf-8"))
        raw = json.loads(REGISTRY.read_text(encoding="utf-8"))[0]
        source = registry.sources[0]
        self.assertEqual((source.source_id, source.local_path, source.sha256, source.canonical_url), (raw["source_id"], raw["local_path"], raw["sha256"], raw["url"]))
        written = json.loads((self.out / "registry.v2.json").read_text(encoding="utf-8"))["sources"][0]
        self.assertEqual(written["registered_at"], raw["retrieved_at"])
        self.assertIsNone(written["retrieved_at"])

    def test_lineage_points_to_v1_inputs(self):
        self.assertEqual(self.migrated.lineage.from_sha256, self.inputs_before[FFC_FACTS])
        self.assertEqual(self.migrated.lineage.from_schema_version, 1)

    def test_original_evidence_files_are_unchanged(self):
        self.assertEqual({path: digest(path) for path in self.inputs_before}, self.inputs_before)


class TestSyntheticCompanies(MigrationTestCase):
    def migrate(self, company):
        return migrate_v1_to_v2(
            self.request(
                SYNTHETIC / company / "financial_facts.json",
                SYNTHETIC / "source_registry.json",
                evidence_root=SYNTHETIC,
                company_registry=RegistryFileCompanies.load(SYNTHETIC / "companies.json"),
            ),
            migrated_at=MIGRATED_AT,
        )

    def test_bank_statement_structure_migrates(self):
        manifest = self.migrate("SYNBANK")
        self.assertEqual(manifest.outputs[0].record_count, 10)
        self.assertEqual(manifest.fact_equivalence.mismatches, ())
        self.assertEqual(manifest.validation.company_identity, "verified")
        migrated = FinancialFactsDocument.model_validate_json((self.out / "facts.v2.json").read_text(encoding="utf-8"))
        self.assertIn("net_markup_interest_income", {fact.concept for fact in migrated.facts})
        self.assertEqual(manifest.verification_status_counts_v2, {"verified": 7, "needs_final_review": 1, "ocr_unverified": 2})

    def test_industrial_interim_periods_migrate(self):
        manifest = self.migrate("SYNIND")
        self.assertEqual(manifest.outputs[0].record_count, 6)
        self.assertEqual(manifest.fact_equivalence.mismatches, ())
        migrated = FinancialFactsDocument.model_validate_json((self.out / "facts.v2.json").read_text(encoding="utf-8"))
        net_sales = {fact.period.type.value: fact.value for fact in migrated.facts if fact.concept == "net_sales"}
        self.assertEqual(net_sales, {"quarterly": 18250000000, "year_to_date": 51900000000})
        self.assertEqual(manifest.fact_provenance_gaps["verified_by"], 3)

    def test_unregistered_company_is_rejected(self):
        companies = SYNTHETIC / "companies.json"
        payload = json.loads(companies.read_text(encoding="utf-8"))
        payload["companies"] = [company for company in payload["companies"] if company["company_id"] != "SYNBANK"]
        reduced = self.out / "companies.json"
        reduced.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "not in the company registry"):
            migrate_v1_to_v2(
                self.request(
                    SYNTHETIC / "SYNBANK/financial_facts.json",
                    SYNTHETIC / "source_registry.json",
                    facts_output=self.out / "out/facts.json",
                    registry_output=self.out / "out/registry.json",
                    manifest_output=self.out / "out/manifest.json",
                    company_registry=RegistryFileCompanies.load(reduced),
                ),
                migrated_at=MIGRATED_AT,
            )
        self.assertFalse((self.out / "out").exists())


class TestMigrationRefusals(MigrationTestCase):
    def setUp(self):
        super().setUp()
        inputs = tempfile.TemporaryDirectory()
        self.addCleanup(inputs.cleanup)
        self.inputs = Path(inputs.name)
        shutil.copytree(SYNTHETIC, self.inputs, dirs_exist_ok=True)
        self.facts_path = self.inputs / "SYNBANK/financial_facts.json"
        self.registry_path = self.inputs / "source_registry.json"
        self.facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
        self.registry = json.loads(self.registry_path.read_text(encoding="utf-8"))

    def run_migration(self, **overrides):
        self.facts_path.write_text(json.dumps(self.facts), encoding="utf-8")
        self.registry_path.write_text(json.dumps(self.registry), encoding="utf-8")
        return migrate_v1_to_v2(self.request(self.facts_path, self.registry_path, **overrides), migrated_at=MIGRATED_AT)

    def assertRefused(self, pattern, **overrides):
        with self.assertRaisesRegex(MigrationError, pattern):
            self.run_migration(**overrides)
        self.assertNoOutputs()

    def test_refuses_to_write_over_an_input(self):
        self.assertRefused("over an input", facts_output=self.facts_path)

    def test_refuses_to_overwrite_existing_output_without_backup(self):
        (self.out / "facts.v2.json").write_text("previous", encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "without a backup directory"):
            self.run_migration()
        self.assertEqual((self.out / "facts.v2.json").read_text(encoding="utf-8"), "previous")

    def test_overwrite_with_backup_preserves_previous_output(self):
        (self.out / "facts.v2.json").write_text("previous", encoding="utf-8")
        manifest = self.run_migration(backup_dir=self.out / "backups")
        backup = Path(manifest.backups[0].backup_path)
        self.assertEqual(backup.read_text(encoding="utf-8"), "previous")
        self.assertEqual(manifest.backups[0].sha256, hashlib.sha256(b"previous").hexdigest())

    def test_rejects_unsupported_units(self):
        self.facts["facts"][0]["unit"] = "PKR_million"
        self.assertRefused("v1 input rejected")

    def test_rejects_malformed_periods(self):
        for bad in ("2025-13-31", "31/12/2025", "2025-12-31T00:00:00"):
            with self.subTest(period_end=bad):
                self.facts["facts"][0]["period_end"] = bad
                self.assertRefused("v1 input rejected")

    def test_rejects_unknown_period_type(self):
        self.facts["facts"][0]["period_type"] = "half_year"
        self.assertRefused("v1 input rejected")

    def test_rejects_duplicate_identities(self):
        self.facts["facts"].append(dict(self.facts["facts"][0], value=1))
        self.assertRefused("duplicate fact identities")

    def test_rejects_missing_value_recorded_as_fact(self):
        self.facts["facts"][0].update(fact_classification="missing", value=0)
        self.assertRefused("data gap")

    def test_rejects_unregistered_source(self):
        self.facts["facts"][0]["source_id"] = "src_unknown"
        self.assertRefused("unregistered source")

    def test_rejects_source_registered_to_another_company(self):
        self.facts["facts"][0]["source_id"] = "src_synind2025q3"
        self.assertRefused("registered to 'SYNIND'")

    def test_rejects_evidence_path_outside_root(self):
        self.registry[0]["local_path"] = "../outside.txt"
        self.assertRefused("v1 input rejected")

    def test_rejects_tampered_raw_evidence(self):
        (self.inputs / "raw/SYNBANK/annual_2025.txt").write_text("altered", encoding="utf-8")
        self.assertRefused("SHA-256 does not match", evidence_root=self.inputs)

    def test_rejects_missing_raw_evidence(self):
        (self.inputs / "raw/SYNBANK/annual_2025.txt").unlink()
        self.assertRefused("evidence file not found", evidence_root=self.inputs)

    def test_rejects_unknown_legacy_fields_instead_of_dropping_them(self):
        self.registry[0]["licence"] = "unknown terms"
        self.assertRefused("v1 input rejected")

    def test_missing_input_is_reported(self):
        with self.assertRaisesRegex(MigrationError, "input file not found"):
            migrate_v1_to_v2(self.request(self.inputs / "absent.json", self.registry_path), migrated_at=MIGRATED_AT)


class TestCommandLine(MigrationTestCase):
    def test_cli_runs_on_arbitrary_paths_and_refuses_reruns(self):
        arguments = [
            "--facts", str(SYNTHETIC / "SYNIND/financial_facts.json"),
            "--registry", str(SYNTHETIC / "source_registry.json"),
            "--facts-out", str(self.out / "facts.json"),
            "--registry-out", str(self.out / "registry.json"),
            "--manifest-out", str(self.out / "manifest.json"),
            "--evidence-root", str(SYNTHETIC),
            "--company-registry", str(SYNTHETIC / "companies.json"),
        ]
        self.assertEqual(main(arguments), 0)
        self.assertEqual(main(arguments), 1)


class TestNoCompanySpecificCode(unittest.TestCase):
    def test_package_source_names_no_company(self):
        names = ("FFC", "Fauji", "SYNBANK", "SYNIND", "LUCK", "OGDC")
        for path in (ROOT / "finura").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                with self.subTest(file=path.name, name=name):
                    self.assertNotIn(name, text)


if __name__ == "__main__":
    unittest.main()
