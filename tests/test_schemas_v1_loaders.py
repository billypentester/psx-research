"""Equivalence tests: the v1 FFC files load into v2 models without loss."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import finura
from finura.schemas import (
    FinancialFact,
    SchemaLoadError,
    SourceDocument,
    Unit,
    VerificationStatus,
    load_v1_financial_facts,
    load_v1_source_registry,
)

ROOT = Path(__file__).resolve().parents[1]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
REGISTRY_FILE = ROOT / "data/source_registry.json"


def file_fingerprint(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


class TestV1FinancialFactsEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(FACTS_FILE.read_text(encoding="utf-8"))
        cls.loaded = load_v1_financial_facts(FACTS_FILE)

    def test_all_sixty_facts_load(self):
        self.assertEqual(len(self.raw["facts"]), 60)
        self.assertEqual(len(self.loaded.facts), 60)
        self.assertEqual(len(self.loaded.file.facts), 60)

    def test_every_fact_preserves_identity_value_and_source_link(self):
        for index, (raw, fact) in enumerate(zip(self.raw["facts"], self.loaded.facts, strict=True)):
            with self.subTest(fact=index, metric=raw["metric"]):
                self.assertEqual(fact.company_id, self.raw["company_id"])
                self.assertEqual(fact.currency, self.raw["currency"])
                self.assertEqual(fact.concept, raw["metric"])
                self.assertEqual(fact.value, raw["value"])
                # int stays int and float stays float, so no precision changes.
                self.assertIs(type(fact.value), type(raw["value"]))
                self.assertEqual(fact.unit.value, raw["unit"])
                self.assertEqual(fact.period.end.isoformat(), raw["period_end"])
                self.assertEqual(fact.period.type.value, raw["period_type"])
                self.assertEqual(fact.scope.value, raw["scope"])
                self.assertEqual(fact.source_id, raw["source_id"])
                self.assertEqual(fact.source_location, raw["source_page"])
                self.assertEqual(fact.verification_status.value, raw["verification_status"])
                self.assertEqual(fact.classification.value, raw["fact_classification"])

    def test_v1_mirror_records_match_raw_payload_exactly(self):
        for index, (raw, record) in enumerate(zip(self.raw["facts"], self.loaded.file.facts, strict=True)):
            with self.subTest(fact=index):
                self.assertEqual(record.model_dump(mode="json", exclude_unset=True), raw)

    def test_fixture_composition_is_unchanged(self):
        units = [fact.unit for fact in self.loaded.facts]
        self.assertEqual(units.count(Unit.PKR_THOUSAND), 56)
        self.assertEqual(units.count(Unit.PKR_PER_SHARE), 4)
        self.assertTrue(all(fact.verification_status is VerificationStatus.VERIFIED for fact in self.loaded.facts))

    def test_absent_v1_metadata_stays_absent(self):
        for index, fact in enumerate(self.loaded.facts):
            with self.subTest(fact=index):
                self.assertIsNone(fact.period.start)
                self.assertIsNone(fact.extraction_method)
                self.assertIsNone(fact.extracted_at)
                self.assertIsNone(fact.verified_by)
                self.assertIsNone(fact.verified_at)
                self.assertIsNone(fact.verification_evidence)
                self.assertEqual(
                    fact.provenance_gaps,
                    (
                        "period.start",
                        "extraction_method",
                        "extracted_at",
                        "verified_by",
                        "verified_at",
                        "verification_evidence",
                    ),
                )

    def test_every_source_link_resolves_to_the_registry(self):
        source_ids = {document.source_id for document in load_v1_source_registry(REGISTRY_FILE).documents}
        for fact in self.loaded.facts:
            self.assertIn(fact.source_id, source_ids)

    def test_v2_facts_round_trip_through_json(self):
        for fact in self.loaded.facts:
            self.assertEqual(FinancialFact.model_validate_json(fact.model_dump_json()), fact)


class TestV1SourceRegistryEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        cls.loaded = load_v1_source_registry(REGISTRY_FILE)

    def test_registry_loads(self):
        self.assertEqual(len(self.loaded.documents), len(self.raw))
        self.assertEqual(self.loaded.documents[0].source_id, "src_e4abb64ff4886ffc")

    def test_registry_fields_are_preserved(self):
        for raw, document in zip(self.raw, self.loaded.documents, strict=True):
            with self.subTest(source=raw["source_id"]):
                for field in ("source_id", "company_id", "title", "local_path", "sha256", "page_number", "notes"):
                    self.assertEqual(getattr(document, field), raw[field], field)
                self.assertEqual(document.canonical_url, raw["url"])
                self.assertEqual(document.source_type.value, raw["source_type"])
                self.assertEqual(document.published_at, raw["published_at"])
                self.assertEqual(document.registered_at, datetime.fromisoformat(raw["retrieved_at"]))

    def test_download_and_publication_dates_are_not_invented(self):
        document = self.loaded.documents[0]
        self.assertIsNone(document.published_at)
        self.assertIsNone(document.retrieved_at)
        self.assertIsNone(document.provider)
        self.assertIsNone(document.retrieval_method)
        self.assertIsNone(document.publisher)
        self.assertIsNone(document.access_basis)
        self.assertIsNone(document.upstream)
        self.assertEqual(
            document.provenance_gaps,
            ("publisher", "published_at", "retrieved_at", "provider", "retrieval_method", "access_basis", "upstream"),
        )

    def test_v1_mirror_records_match_raw_payload_exactly(self):
        for raw, record in zip(self.raw, self.loaded.records, strict=True):
            self.assertEqual(record.model_dump(mode="json", exclude_unset=True), raw)

    def test_documents_round_trip_through_json(self):
        for document in self.loaded.documents:
            self.assertEqual(SourceDocument.model_validate_json(document.model_dump_json()), document)


class TestLoadersAreReadOnly(unittest.TestCase):
    def test_original_files_are_unchanged_by_loading(self):
        before = {path: file_fingerprint(path) for path in (FACTS_FILE, REGISTRY_FILE)}
        load_v1_financial_facts(FACTS_FILE)
        load_v1_source_registry(REGISTRY_FILE)
        after = {path: file_fingerprint(path) for path in (FACTS_FILE, REGISTRY_FILE)}
        self.assertEqual(before, after)


class TestLoaderRejectsInvalidFiles(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.facts = json.loads(FACTS_FILE.read_text(encoding="utf-8"))

    def write(self, payload, name="facts.json"):
        path = Path(self.directory.name) / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return path

    def test_duplicate_fact_identity_is_rejected(self):
        self.facts["facts"].append(dict(self.facts["facts"][0], value=1))
        with self.assertRaisesRegex(SchemaLoadError, "duplicate fact identities"):
            load_v1_financial_facts(self.write(self.facts))

    def test_unknown_fact_field_is_rejected_not_dropped(self):
        self.facts["facts"][0]["restated"] = True
        with self.assertRaisesRegex(SchemaLoadError, "restated"):
            load_v1_financial_facts(self.write(self.facts))

    def test_duplicate_json_key_is_rejected(self):
        text = '{"company_id": "FFC", "currency": "PKR", "currency": "USD", "facts": []}'
        with self.assertRaisesRegex(SchemaLoadError, "duplicate JSON key 'currency'"):
            load_v1_financial_facts(self.write(text))

    def test_nan_literal_in_json_is_rejected(self):
        text = json.dumps(self.facts).replace("432410443", "NaN", 1)
        with self.assertRaisesRegex(SchemaLoadError, "finite"):
            load_v1_financial_facts(self.write(text))

    def test_fact_company_must_match_file_company(self):
        self.facts["facts"][0]["company_id"] = "ENGRO"
        with self.assertRaisesRegex(SchemaLoadError, "differs from file company_id"):
            load_v1_financial_facts(self.write(self.facts))

    def test_file_currency_must_match_units(self):
        self.facts["currency"] = "USD"
        with self.assertRaisesRegex(SchemaLoadError, "does not match unit"):
            load_v1_financial_facts(self.write(self.facts))

    def test_missing_file_is_reported(self):
        with self.assertRaisesRegex(SchemaLoadError, "cannot read file"):
            load_v1_financial_facts(Path(self.directory.name) / "absent.json")

    def test_registry_must_be_an_array(self):
        with self.assertRaisesRegex(SchemaLoadError, "JSON array"):
            load_v1_source_registry(self.write({"sources": []}, "registry.json"))

    def test_duplicate_source_ids_are_rejected(self):
        registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(SchemaLoadError, "duplicate source_id"):
            load_v1_source_registry(self.write(registry * 2, "registry.json"))


class TestPackageImport(unittest.TestCase):
    def test_package_imports_outside_repository_root(self):
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-c", "import finura.schemas, finura; print(finura.__file__)"],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(Path(completed.stdout.strip()), Path(finura.__file__))


if __name__ == "__main__":
    unittest.main()
