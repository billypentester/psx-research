import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.init_company import initialize


class TestInitCompany(unittest.TestCase):
    def test_initializes_generic_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pipeline.init_company.ROOT", Path(directory)):
                initialize("ABC")
            facts = Path(directory) / "data/normalized/ABC/financial_facts.json"
            market = Path(directory) / "data/normalized/ABC/market_data.json"
            self.assertEqual(json.loads(facts.read_text())["company_id"], "ABC")
            self.assertEqual(json.loads(market.read_text())["observations"], [])

    def test_rejects_non_ticker(self):
        with self.assertRaises(ValueError):
            initialize("abc-test")


if __name__ == "__main__":
    unittest.main()
