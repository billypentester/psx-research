import json
import unittest
from pathlib import Path

from pipeline.derive_metrics import derive


ROOT = Path(__file__).resolve().parents[1]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
DERIVED_FILE = ROOT / "data/derived/FFC/derived_metrics.json"


class TestDerivedMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts_data = json.loads(FACTS_FILE.read_text())
        cls.derived_data = json.loads(DERIVED_FILE.read_text())

    def test_generated_artifact_has_expected_company(self):
        self.assertEqual(self.derived_data["company_id"], "FFC")
        self.assertTrue(self.derived_data["metrics"])

    def test_metrics_are_calculated_only_from_verified_inputs(self):
        for metric in self.derived_data["metrics"]:
            if metric["calculation_status"] == "calculated":
                self.assertEqual(metric["classification"], "calculated")
                self.assertTrue(metric["inputs"])
                self.assertTrue(
                    all(item["fact_key"] for item in metric["inputs"] if item)
                )

    def test_first_period_growth_is_explicitly_missing(self):
        growth = [
            item for item in self.derived_data["metrics"]
            if item["metric"] == "revenue_growth"
            and item["scope"] == "standalone"
            and item["period_end"] == "2024-12-31"
        ]
        self.assertEqual(len(growth), 1)
        self.assertEqual(growth[0]["calculation_status"], "missing")
        self.assertEqual(growth[0]["value"], None)

    def test_2025_standalone_margin_matches_source_facts(self):
        facts = {
            (item["metric"], item["period_end"]): item["value"]
            for item in self.facts_data["facts"]
            if item["scope"] == "standalone"
        }
        margin = next(
            item for item in self.derived_data["metrics"]
            if item["metric"] == "net_profit_margin"
            and item["scope"] == "standalone"
            and item["period_end"] == "2025-12-31"
        )
        expected = facts[("profit_after_tax", "2025-12-31")] / facts[
            ("net_turnover", "2025-12-31")
        ]
        self.assertAlmostEqual(margin["value"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
