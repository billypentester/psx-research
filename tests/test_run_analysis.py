import json
import unittest
from pathlib import Path

from pipeline.run_analysis import render_markdown, report_data


ROOT = Path(__file__).resolve().parents[1]


class TestRunAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        facts = json.loads(
            (ROOT / "data/normalized/FFC/financial_facts.json").read_text()
        )
        derived = json.loads(
            (ROOT / "data/derived/FFC/derived_metrics.json").read_text()
        )
        cls.data = report_data(
            "FFC",
            (facts["company_id"], facts["facts"]),
            derived,
            json.loads((ROOT / "data/source_registry.json").read_text()),
        )

    def test_report_is_explicit_about_latest_period_and_gaps(self):
        self.assertEqual(self.data["latest_period"]["period_end"], "2025-12-31")
        self.assertTrue(self.data["gaps"])
        self.assertEqual(self.data["valuation"]["status"], "unavailable")

    def test_empty_report_is_marked_data_unavailable(self):
        empty = report_data(
            "ABC",
            ("ABC", []),
            {"metrics": []},
            [],
        )
        self.assertEqual(empty["status"], "data_unavailable")
        self.assertTrue(empty["next_steps"])

    def test_markdown_contains_provenance_sections(self):
        markdown = render_markdown(self.data)
        self.assertIn("## Sources", markdown)
        self.assertIn("## Data gaps", markdown)
        self.assertIn("src_e4abb64ff4886ffc", markdown)


if __name__ == "__main__":
    unittest.main()
