import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.normalize_external import (
    normalize_financial_data,
    normalize_market_data,
    read_records,
)


class TestNormalizeExternal(unittest.TestCase):
    def test_csv_records_are_read_and_mapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv"
            path.write_text(
                "date,last,qty\n2026-10-18T10:00:00+00:00,123.45,1000\n",
                encoding="utf-8",
            )
            self.assertEqual(read_records(path)[0]["last"], "123.45")

    @patch("pipeline.normalize_external.source_record", return_value={"source_id": "src_test"})
    def test_market_data_preserves_source_and_numeric_values(self, _source):
        result = normalize_market_data(
            "ABC",
            [{"date": "2026-10-18T10:00:00+00:00", "last": "123.45"}],
            {"observed_at": "date", "price": "last"},
            "src_test",
        )
        self.assertEqual(result["observations"][0]["price"], 123.45)
        self.assertEqual(result["observations"][0]["source_id"], "src_test")

    @patch("pipeline.normalize_external.source_record", return_value={"source_id": "src_test"})
    def test_financial_data_stays_unverified_until_reviewed(self, _source):
        result = normalize_financial_data(
            "ABC",
            [{
                "name": "Revenue",
                "value": "1,000",
                "unit": "PKR_thousand",
                "period": "2025-12-31",
                "type": "annual",
                "scope": "standalone",
            }],
            {
                "metric": "name",
                "value": "value",
                "unit": "unit",
                "period_end": "period",
                "period_type": "type",
                "scope": "scope",
            },
            "src_test",
        )
        self.assertEqual(result["facts"][0]["verification_status"], "needs_final_review")

    @patch("pipeline.normalize_external.source_record", return_value={"source_id": "src_test"})
    def test_invalid_scope_is_rejected(self, _source):
        with self.assertRaises(ValueError):
            normalize_financial_data(
                "ABC",
                [{"metric": "Revenue", "value": "1", "scope": "group"}],
                {"metric": "metric", "value": "value", "scope": "scope"},
                "src_test",
            )


if __name__ == "__main__":
    unittest.main()
