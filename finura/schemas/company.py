"""Company identity, listing history, and sector classification.

`company_id` is a stable, opaque identifier assigned at onboarding. Listing
symbols are a dated history attached to it, so a ticker change or a delisting
never changes which company a fact, source, or run belongs to.
"""

from datetime import date
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import AttestationState, ListingStatus
from .provenance import EvidenceReference
from .types import AwareTimestamp, CompanyId, IsoDate, ListingSymbol, NonEmptyStr, SectorKey

COMPANY_SCHEMA_VERSION: Final = 1


class Attestation(BaseModel):
    """A claim's verification state and the evidence behind it.

    `verified` requires evidence, a reviewer, and a review time. `unverified`
    may list candidate evidence but cannot name a reviewer or review time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: AttestationState
    evidence: tuple[EvidenceReference, ...] = ()
    verified_by: NonEmptyStr | None = None
    verified_at: AwareTimestamp | None = None

    @model_validator(mode="after")
    def _state_matches_details(self) -> Self:
        if self.state is AttestationState.VERIFIED:
            if not self.evidence or self.verified_by is None or self.verified_at is None:
                raise ValueError("a verified attestation needs evidence, verified_by, and verified_at")
        elif self.verified_by is not None or self.verified_at is not None:
            raise ValueError("an unverified attestation cannot record a reviewer or review time")
        return self

    @property
    def is_verified(self) -> bool:
        return self.state is AttestationState.VERIFIED


class SymbolPeriod(BaseModel):
    """A listing symbol and the half-open date range `[valid_from, valid_to)` it applied.

    `valid_from` is `None` when the start was not recorded; `valid_to` is
    `None` while the symbol is still in use.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: ListingSymbol
    valid_from: IsoDate | None = None
    valid_to: IsoDate | None = None

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.valid_from is not None and self.valid_to is not None and self.valid_from >= self.valid_to:
            raise ValueError(f"symbol {self.symbol}: valid_from must be before valid_to")
        return self

    def covers(self, day: date) -> bool:
        return (self.valid_from is None or self.valid_from <= day) and (self.valid_to is None or day < self.valid_to)


class SectorClassification(BaseModel):
    """A company's sector in Finura's sector taxonomy.

    `sector_key` is the Finura key used to select a sector profile;
    `source_label` keeps the classification text exactly as the evidence
    states it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sector_key: SectorKey
    source_label: NonEmptyStr | None = None
    attestation: Attestation


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = COMPANY_SCHEMA_VERSION
    company_id: CompanyId
    legal_name: NonEmptyStr
    # `None` when no evidence of the current listing status has been recorded.
    listing_status: ListingStatus | None = None
    delisted_on: IsoDate | None = None
    # Chronological; consecutive periods may touch but not overlap.
    symbols: tuple[SymbolPeriod, ...] = Field(min_length=1)
    identity: Attestation
    classification: SectorClassification | None = None

    @model_validator(mode="after")
    def _listing_history_is_consistent(self) -> Self:
        for earlier, later in zip(self.symbols, self.symbols[1:]):
            if earlier.valid_to is None or later.valid_from is None or later.valid_from < earlier.valid_to:
                raise ValueError(
                    f"symbol periods must be chronological and non-overlapping: {earlier.symbol} then {later.symbol}"
                )
        last = self.symbols[-1]
        if self.listing_status is ListingStatus.DELISTED:
            if last.valid_to is None:
                raise ValueError("a delisted company cannot have a symbol still in use")
            if self.delisted_on is not None and self.delisted_on != last.valid_to:
                raise ValueError("delisted_on must equal the last symbol's valid_to")
        else:
            if self.listing_status is not None and last.valid_to is not None:
                raise ValueError(f"a {self.listing_status.value} company needs a current symbol")
            if self.delisted_on is not None:
                raise ValueError("delisted_on is only allowed for delisted companies")
        return self

    @property
    def current_symbol(self) -> str | None:
        last = self.symbols[-1]
        return last.symbol if last.valid_to is None else None

    def symbol_on(self, day: date) -> str | None:
        return next((period.symbol for period in self.symbols if period.covers(day)), None)
