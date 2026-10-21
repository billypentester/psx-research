"""Strict-validation tests for canonical v2 models, using synthetic records."""

import math
import unittest
from datetime import date

from pydantic import ValidationError

from finura.schemas import (
    DuplicateFactIdentityError,
    FinancialFact,
    SourceDocument,
    ensure_unique_identities,
    find_duplicate_identities,
)


def fact_payload(**overrides):
    payload = {
        "company_id": "TEST",
        "concept": "net_turnover",
        "value": 1000,
        "unit": "PKR_thousand",
        "currency": "PKR",
        "period": {"end": "2025-12-31", "type": "annual"},
        "scope": "standalone",
        "source_id": "src_0000000000000000",
        "source_location": "page 1",
        "classification": "reported",
        "verification_status": "verified",
    }
    payload.update(overrides)
    return payload


def source_payload(**overrides):
    payload = {
        "source_id": "src_0000000000000000",
        "company_id": "TEST",
        "source_type": "announcement",
        "title": "Synthetic source",
        "registered_at": "2026-10-17T19:05:55+00:00",
        "local_path": "data/raw/TEST/source.pdf",
        "sha256": "0" * 64,
    }
    payload.update(overrides)
    return payload


class TestFinancialFactValidation(unittest.TestCase):
    def assertRejected(self, **overrides):
        with self.assertRaises(ValidationError):
            FinancialFact.model_validate(fact_payload(**overrides))

    def test_valid_payload_is_accepted(self):
        fact = FinancialFact.model_validate(fact_payload())
        self.assertEqual(fact.value, 1000)
        self.assertEqual(fact.schema_version, 2)

    def test_rejects_non_finite_and_non_numeric_values(self):
        for value in (True, False, math.nan, math.inf, -math.inf, "1000", "1,000", "(1000)", None, [1000]):
            with self.subTest(value=value):
                self.assertRejected(value=value)

    def test_accepts_negative_and_fractional_values_unchanged(self):
        self.assertEqual(FinancialFact.model_validate(fact_payload(value=-5)).value, -5)
        fact = FinancialFact.model_validate(fact_payload(value=51.69, unit="PKR_per_share"))
        self.assertEqual(fact.value, 51.69)

    def test_rejects_unknown_scopes(self):
        for scope in ("group", "Standalone", "", None):
            with self.subTest(scope=scope):
                self.assertRejected(scope=scope)

    def test_rejects_unsupported_units(self):
        for unit in ("USD", "PKR_million", "pkr_thousand", "ratio", ""):
            with self.subTest(unit=unit):
                self.assertRejected(unit=unit)

    def test_rejects_malformed_dates(self):
        for end in ("2025-13-01", "2025-02-30", "31-12-2025", "20251231", "2025-12-31T00:00:00", 20251231, ""):
            with self.subTest(end=end):
                self.assertRejected(period={"end": end, "type": "annual"})

    def test_rejects_period_start_after_end(self):
        self.assertRejected(period={"start": "2026-01-01", "end": "2025-12-31", "type": "annual"})

    def test_rejects_unknown_period_type(self):
        self.assertRejected(period={"end": "2025-12-31", "type": "TTM"})

    def test_rejects_invalid_schema_versions(self):
        for version in (1, 3, "2", 2.5, None):
            with self.subTest(version=version):
                self.assertRejected(schema_version=version)

    def test_rejects_statuses_not_accepted_by_v1(self):
        for status in ("pending", "rejected", "VERIFIED"):
            with self.subTest(status=status):
                self.assertRejected(verification_status=status)

    def test_rejects_unknown_fields(self):
        self.assertRejected(restated=True)

    def test_rejects_currency_that_contradicts_unit(self):
        self.assertRejected(currency="USD")

    def test_rejects_non_canonical_concept_names(self):
        for concept in ("Revenue", "net turnover", "", "1_metric"):
            with self.subTest(concept=concept):
                self.assertRejected(concept=concept)

    def test_rejects_naive_timestamps(self):
        self.assertRejected(extracted_at="2026-10-18T18:53:12")

    def test_rejects_missing_values_recorded_as_facts(self):
        self.assertRejected(classification="missing", value=0)
        self.assertRejected(verification_status="missing", value=0)

    def test_rejects_verification_details_on_unverified_facts(self):
        for field, value in (
            ("verified_by", "reviewer"),
            ("verified_at", "2026-10-18T18:53:12+05:00"),
            ("verification_evidence", "audit.json"),
        ):
            with self.subTest(field=field):
                self.assertRejected(verification_status="ocr_unverified", **{field: value})

    def test_rejects_extraction_time_without_method(self):
        self.assertRejected(extracted_at="2026-10-18T18:53:12+05:00")
        fact = FinancialFact.model_validate(fact_payload(extraction_method="ocr", extracted_at="2026-10-18T18:53:12+05:00"))
        self.assertNotIn("extracted_at", fact.provenance_gaps)

    def test_timestamps_serialize_without_changing_offset_text(self):
        fact = FinancialFact.model_validate(fact_payload(extraction_method="ocr", extracted_at="2026-10-18T18:53:12+00:00"))
        self.assertIn('"extracted_at":"2026-10-18T18:53:12+00:00"', fact.model_dump_json())

    def test_facts_are_immutable(self):
        fact = FinancialFact.model_validate(fact_payload())
        with self.assertRaises(ValidationError):
            fact.value = 1

    def test_verification_gaps_only_apply_to_verified_facts(self):
        unverified = FinancialFact.model_validate(fact_payload(verification_status="ocr_unverified"))
        self.assertNotIn("verified_by", unverified.provenance_gaps)
        verified = FinancialFact.model_validate(fact_payload())
        self.assertIn("verified_by", verified.provenance_gaps)


class TestFactIdentity(unittest.TestCase):
    def test_identity_uses_documented_key(self):
        fact = FinancialFact.model_validate(fact_payload())
        self.assertEqual(
            tuple(fact.identity),
            ("TEST", "net_turnover", "standalone", date(2025, 12, 31), "annual", "PKR_thousand"),
        )

    def test_same_identity_with_different_values_is_a_duplicate(self):
        facts = [
            FinancialFact.model_validate(fact_payload(value=1)),
            FinancialFact.model_validate(fact_payload(value=2)),
        ]
        self.assertEqual(list(find_duplicate_identities(facts).values()), [2])
        with self.assertRaises(DuplicateFactIdentityError):
            ensure_unique_identities(facts)

    def test_facts_differing_in_any_key_field_are_distinct(self):
        base = FinancialFact.model_validate(fact_payload())
        variants = [
            fact_payload(company_id="OTHER"),
            fact_payload(concept="gross_profit"),
            fact_payload(scope="consolidated"),
            fact_payload(period={"end": "2024-12-31", "type": "annual"}),
            fact_payload(period={"end": "2025-12-31", "type": "quarterly"}),
            fact_payload(unit="PKR"),
        ]
        for payload in variants:
            with self.subTest(payload=payload):
                ensure_unique_identities([base, FinancialFact.model_validate(payload)])


class TestSourceDocumentValidation(unittest.TestCase):
    def assertRejected(self, **overrides):
        with self.assertRaises(ValidationError):
            SourceDocument.model_validate(source_payload(**overrides))

    def test_valid_payload_is_accepted_without_invented_dates(self):
        document = SourceDocument.model_validate(source_payload())
        self.assertIsNone(document.published_at)
        self.assertIsNone(document.retrieved_at)
        self.assertIn("retrieved_at", document.provenance_gaps)

    def test_rejects_invalid_hashes(self):
        for sha256 in ("0" * 63, "A" * 64, "g" * 64, ""):
            with self.subTest(sha256=sha256):
                self.assertRejected(sha256=sha256)

    def test_rejects_non_http_urls(self):
        for url in ("ftp://example.com/x.pdf", "file:///tmp/x.pdf", "example.com/x.pdf", ""):
            with self.subTest(url=url):
                self.assertRejected(canonical_url=url)

    def test_rejects_invalid_dates_and_timestamps(self):
        self.assertRejected(published_at="2025-31-12")
        self.assertRejected(registered_at="2026-10-17T19:05:55")
        self.assertRejected(registered_at=1760727955)

    def test_rejects_unknown_source_type_and_schema_version(self):
        self.assertRejected(source_type="press_release")
        self.assertRejected(schema_version=1)

    def test_rejects_evidence_paths_that_escape_their_root(self):
        for local_path in ("/etc/passwd", "../outside.pdf", "data/../../outside.pdf", "data\\raw\\x.pdf"):
            with self.subTest(local_path=local_path):
                self.assertRejected(local_path=local_path)

    def test_rejects_coerced_integers(self):
        self.assertRejected(page_number="3")
        self.assertRejected(page_number=True)
        self.assertRejected(http_status="200")


if __name__ == "__main__":
    unittest.main()
