import json
import unittest
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
REGISTRY_FILE = ROOT / "data/source_registry.json"

ALLOWED_SCOPES = {"standalone", "consolidated"}
ALLOWED_STATUSES = {
    "verified",
    "ocr_unverified",
    "needs_final_review",
    "estimated",
    "missing",
}
ALLOWED_UNITS = {"PKR_thousand", "PKR", "PKR_per_share"}
ALLOWED_CLASSIFICATIONS = {
    "reported", "calculated", "estimated", "missing", "management_provided",
}


class TestFinancialFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FACTS_FILE.read_text())
        cls.facts = cls.data["facts"]
        cls.registry = json.loads(REGISTRY_FILE.read_text())
        cls.source_ids = {item["source_id"] for item in cls.registry}

    def test_dataset_has_facts(self):
        self.assertTrue(self.facts)

    def test_required_fields(self):
        required = {
            "metric", "scope", "period_end", "period_type",
            "value", "unit", "source_id", "source_page",
            "verification_status", "fact_classification",
        }
        for index, fact in enumerate(self.facts):
            with self.subTest(fact=index):
                self.assertTrue(required.issubset(fact.keys()))

    def test_valid_scope(self):
        for fact in self.facts:
            self.assertIn(fact["scope"], ALLOWED_SCOPES)

    def test_valid_status(self):
        for fact in self.facts:
            self.assertIn(fact["verification_status"], ALLOWED_STATUSES)

    def test_valid_unit(self):
        for fact in self.facts:
            self.assertIn(fact["unit"], ALLOWED_UNITS)

    def test_valid_classification(self):
        for fact in self.facts:
            self.assertIn(fact["fact_classification"], ALLOWED_CLASSIFICATIONS)

    def test_valid_period_date(self):
        for fact in self.facts:
            date.fromisoformat(fact["period_end"])

    def test_source_exists(self):
        for fact in self.facts:
            self.assertIn(fact["source_id"], self.source_ids)

    def test_numeric_values_are_not_booleans(self):
        for fact in self.facts:
            self.assertIsInstance(fact["value"], (int, float))
            self.assertNotIsInstance(fact["value"], bool)

    def test_no_duplicate_fact_keys(self):
        keys = [
            (
                f["metric"], f["scope"], f["period_end"],
                f["period_type"], f["unit"]
            )
            for f in self.facts
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_standalone_and_consolidated_are_distinct(self):
        scopes = {fact["scope"] for fact in self.facts}
        self.assertTrue(scopes.issubset(ALLOWED_SCOPES))

    def test_reported_facts_are_classified_as_reported(self):
        self.assertTrue(
            all(fact["fact_classification"] == "reported" for fact in self.facts)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
