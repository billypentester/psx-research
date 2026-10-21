"""Canonical source-document record."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import AccessBasis, RetrievalMethod, SourceType
from .provenance import EvidenceReference
from .types import AwareTimestamp, CompanyId, HttpUrl, Identifier, IsoDate, NonEmptyStr, RelativePath, Sha256

SOURCE_SCHEMA_VERSION: Final = 2

# Optional fields whose absence weakens provenance. A `None` here means
# "not recorded", never "not applicable".
SOURCE_PROVENANCE_FIELDS = (
    "canonical_url",
    "publisher",
    "published_at",
    "retrieved_at",
    "provider",
    "retrieval_method",
    "access_basis",
    "upstream",
)


class SourceDocument(BaseModel):
    """A preserved source artifact and what is known about where it came from.

    Three times are kept apart and are `None` when not recorded:
    `published_at` (when the publisher issued it), `retrieved_at` (when it was
    downloaded), and `registered_at` (when it entered the registry, always
    known).

    `publisher` issued the document; `provider` is the site or service it was
    obtained from. They differ for an aggregator copy of an exchange filing.
    `upstream` lists the sources this one is derived from: `None` means
    unknown, `()` means it is an original.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = SOURCE_SCHEMA_VERSION
    source_id: Identifier
    # `None` for exchange-wide documents that concern no single company.
    company_id: CompanyId | None
    source_type: SourceType
    title: NonEmptyStr
    canonical_url: HttpUrl | None = None
    publisher: NonEmptyStr | None = None
    published_at: IsoDate | None = None
    retrieved_at: AwareTimestamp | None = None
    registered_at: AwareTimestamp
    # Relative to the evidence root (the repository for registered sources).
    local_path: RelativePath
    sha256: Sha256
    page_number: int | None = Field(default=None, strict=True, ge=1)
    notes: NonEmptyStr | None = None
    provider: NonEmptyStr | None = None
    retrieval_method: RetrievalMethod | None = None
    http_status: int | None = Field(default=None, strict=True, ge=100, le=599)
    content_type: NonEmptyStr | None = None
    access_basis: AccessBasis | None = None
    upstream: tuple[EvidenceReference, ...] | None = None

    @property
    def provenance_gaps(self) -> tuple[str, ...]:
        """Names of provenance fields that were not recorded."""
        return tuple(name for name in SOURCE_PROVENANCE_FIELDS if getattr(self, name) is None)
