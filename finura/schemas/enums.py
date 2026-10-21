"""Controlled vocabularies for canonical Finura records.

Enum values that also exist in v1 data use the exact v1 strings, so mapping a
v1 record is a lookup rather than a translation. Values are case-sensitive;
unknown values are rejected, never coerced.
"""

from enum import StrEnum


class Scope(StrEnum):
    """Statement reporting scope (v1 `scope`)."""

    STANDALONE = "standalone"
    CONSOLIDATED = "consolidated"


class Unit(StrEnum):
    """Unit attached to a fact value (v1 `unit`).

    Each unit carries its currency and scale so that compatibility can be
    checked without parsing the identifier.
    """

    PKR = "PKR"
    PKR_THOUSAND = "PKR_thousand"
    PKR_PER_SHARE = "PKR_per_share"

    @property
    def currency(self) -> str:
        return _UNIT_CURRENCY[self]

    @property
    def scale(self) -> int:
        return _UNIT_SCALE[self]


_UNIT_CURRENCY = {Unit.PKR: "PKR", Unit.PKR_THOUSAND: "PKR", Unit.PKR_PER_SHARE: "PKR"}
_UNIT_SCALE = {Unit.PKR: 1, Unit.PKR_THOUSAND: 1000, Unit.PKR_PER_SHARE: 1}


class PeriodType(StrEnum):
    """Reporting-period classification (v1 `period_type`).

    Only `annual` occurs in v1 data. `quarterly` and `year_to_date` are the
    interim period kinds named in docs/INGESTION_PIPELINE.md, which forbids
    mixing them.
    """

    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    YEAR_TO_DATE = "year_to_date"


class VerificationStatus(StrEnum):
    """Review-evidence status (v1 `verification_status`).

    `estimated` and `missing` are kept for v1 compatibility although they
    describe classification/availability rather than evidence quality
    (docs/SOURCE_POLICY.md).
    """

    VERIFIED = "verified"
    OCR_UNVERIFIED = "ocr_unverified"
    NEEDS_FINAL_REVIEW = "needs_final_review"
    ESTIMATED = "estimated"
    MISSING = "missing"


class FactClassification(StrEnum):
    """What kind of value a fact is (v1 `fact_classification`).

    `assumed` is new in v2 (required by the Finura specification); no v1
    record carries it.
    """

    REPORTED = "reported"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    ASSUMED = "assumed"
    MISSING = "missing"
    MANAGEMENT_PROVIDED = "management_provided"


class ExtractionMethod(StrEnum):
    """How a value was taken from its source. New in v2; absent in v1."""

    OCR = "ocr"
    STRUCTURED_IMPORT = "structured_import"
    MANUAL_TRANSCRIPTION = "manual_transcription"


class RetrievalMethod(StrEnum):
    """How a registered file was obtained (v1 registry `retrieval_method`)."""

    MANUAL = "manual"
    HTTP = "http"


class SourceType(StrEnum):
    """Kind of source document (v1 registry `source_type`)."""

    ANNUAL_REPORT = "annual_report"
    QUARTERLY_REPORT = "quarterly_report"
    ANNOUNCEMENT = "announcement"
    MARKET_DATA = "market_data"
    OTHER = "other"


class ListingStatus(StrEnum):
    """Exchange listing status of a company."""

    LISTED = "listed"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


class AttestationState(StrEnum):
    """Whether a claim about a company has been checked against evidence."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class AccessBasis(StrEnum):
    """Under what permission a source artifact was obtained."""

    # A person downloaded a single copy as the site's terms allow.
    MANUAL_DOWNLOAD = "manual_download"
    # Automated retrieval that the recorded terms review allows.
    AUTOMATED_PERMITTED = "automated_permitted"
    # Automated retrieval under written permission from the publisher.
    WRITTEN_PERMISSION = "written_permission"
    # Delivered through a licensed data feed.
    LICENSED = "licensed"
