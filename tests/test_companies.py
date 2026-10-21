"""Company identity, listing history, and the company registry."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from finura.companies import RegistryFileCompanies, UnknownCompanyError
from finura.schemas import Company, SchemaLoadError

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = ROOT / "tests/fixtures/v1_synthetic/companies.json"
VERIFIED = {
    "state": "verified",
    "evidence": [{"description": "listing page", "url": "https://example.com/listing"}],
    "verified_by": "reviewer",
    "verified_at": "2026-10-01T10:00:00+00:00",
}


def company(**overrides):
    payload = {
        "company_id": "TESTCO",
        "legal_name": "Test Company Limited",
        "listing_status": "listed",
        "symbols": [{"symbol": "TEST"}],
        "identity": VERIFIED,
    }
    payload.update(overrides)
    return payload


class TestCompanyModel(unittest.TestCase):
    def assertRejected(self, **overrides):
        with self.assertRaises(ValidationError):
            Company.model_validate(company(**overrides))

    def test_listed_company_has_current_symbol(self):
        self.assertEqual(Company.model_validate(company()).current_symbol, "TEST")

    def test_ticker_change_keeps_company_id(self):
        record = Company.model_validate(
            company(symbols=[{"symbol": "OLD", "valid_to": "2024-07-01"}, {"symbol": "NEW", "valid_from": "2024-07-01"}])
        )
        self.assertEqual(record.symbol_on(date(2024, 6, 30)), "OLD")
        self.assertEqual(record.symbol_on(date(2024, 7, 1)), "NEW")
        self.assertEqual(record.company_id, "TESTCO")

    def test_rejects_overlapping_or_unordered_symbols(self):
        self.assertRejected(symbols=[{"symbol": "A", "valid_to": "2024-07-02"}, {"symbol": "B", "valid_from": "2024-07-01"}])
        self.assertRejected(symbols=[{"symbol": "A"}, {"symbol": "B", "valid_from": "2024-07-01"}])

    def test_delisted_company_rules(self):
        delisted = Company.model_validate(
            company(listing_status="delisted", delisted_on="2023-06-30", symbols=[{"symbol": "OLD", "valid_to": "2023-06-30"}])
        )
        self.assertIsNone(delisted.current_symbol)
        self.assertRejected(listing_status="delisted", symbols=[{"symbol": "OLD"}])
        self.assertRejected(listing_status="delisted", delisted_on="2023-07-01", symbols=[{"symbol": "OLD", "valid_to": "2023-06-30"}])
        self.assertRejected(delisted_on="2023-06-30")

    def test_rejects_listed_company_without_current_symbol(self):
        self.assertRejected(symbols=[{"symbol": "OLD", "valid_to": "2023-06-30"}])

    def test_verified_attestation_requires_evidence_and_reviewer(self):
        self.assertRejected(identity={"state": "verified"})
        self.assertRejected(identity={**VERIFIED, "evidence": []})
        self.assertRejected(identity={**VERIFIED, "verified_at": "2026-10-01T10:00:00"})

    def test_unverified_attestation_cannot_name_a_reviewer(self):
        self.assertRejected(identity={"state": "unverified", "verified_by": "reviewer"})

    def test_evidence_must_point_somewhere(self):
        self.assertRejected(identity={**VERIFIED, "evidence": [{"description": "trust me"}]})

    def test_rejects_invalid_symbols_and_versions(self):
        self.assertRejected(symbols=[{"symbol": "test"}])
        self.assertRejected(schema_version=2)
        self.assertRejected(listing_status="active")


class TestCompanyRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = RegistryFileCompanies.load(COMPANIES)

    def test_get_by_stable_id(self):
        self.assertEqual(self.registry.get("SYNBANK").legal_name, "Synthetic Bank Limited (test fixture)")
        with self.assertRaises(UnknownCompanyError):
            self.registry.get("NOPE")

    def test_resolve_symbol_across_ticker_change(self):
        self.assertEqual(self.registry.resolve_symbol("SYNI", date(2024, 1, 1)).company_id, "SYNIND")
        self.assertEqual(self.registry.resolve_symbol("SYNIND", date(2025, 1, 1)).company_id, "SYNIND")
        with self.assertRaises(UnknownCompanyError):
            self.registry.resolve_symbol("SYNI", date(2025, 1, 1))

    def test_symbol_reused_after_delisting_resolves_by_date(self):
        self.assertEqual(self.registry.resolve_symbol("SYNO", date(2020, 1, 1)).company_id, "SYNOLD")
        self.assertEqual(self.registry.resolve_symbol("SYNO", date(2025, 1, 1)).company_id, "SYNNEW")
        with self.assertRaises(UnknownCompanyError):
            self.registry.resolve_symbol("SYNO", date(2023, 9, 1))

    def test_rejects_symbol_shared_over_overlapping_dates(self):
        payload = json.loads(COMPANIES.read_text(encoding="utf-8"))
        payload["companies"][3]["symbols"][0]["valid_from"] = "2023-01-01"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "companies.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(SchemaLoadError, "overlapping dates"):
                RegistryFileCompanies.load(path)

    def test_rejects_duplicate_company_ids(self):
        payload = json.loads(COMPANIES.read_text(encoding="utf-8"))
        payload["companies"].append(payload["companies"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "companies.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(SchemaLoadError, "duplicate company_id"):
                RegistryFileCompanies.load(path)


if __name__ == "__main__":
    unittest.main()
