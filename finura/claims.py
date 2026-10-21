"""Listing claims: reviewable statements about a company's listing.

A claim says something about a listing symbol as of a date (its company's
legal name, listing status, sector label, or a symbol change) and cites the
registered evidence for it. Parsing or fetching only ever produces
`discovered` claims. A person moves a claim to `verified` or `rejected` with
`review_claim`; nothing else changes a claim's status.

Company records are proposed from explicitly selected claims; a proposal's
identity is verified only when every claim it uses is verified.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import combinations
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from finura.schemas.company import Attestation, Company, SymbolPeriod
from finura.schemas.enums import AttestationState, ListingStatus
from finura.schemas.provenance import EvidenceReference
from finura.schemas.types import AwareTimestamp, Identifier, IsoDate, ListingSymbol, NonEmptyStr, Sha256
from finura.sources.registry import SourceRegistry


class ClaimStatus(StrEnum):
    DISCOVERED = "discovered"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ClaimError(ValueError):
    """A claim operation was invalid; see the message."""


class ListingAssertion(BaseModel):
    """What a claim states about `symbol`, as of `as_of`.

    `previous_symbol` records a symbol change: `symbol` replaced
    `previous_symbol` from `valid_from`. `listing_status` with `valid_from`
    gives the date that status took effect.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: ListingSymbol
    as_of: IsoDate
    legal_name: NonEmptyStr | None = None
    listing_status: ListingStatus | None = None
    # Sector text exactly as the evidence states it; not a Finura sector key.
    sector_label: NonEmptyStr | None = None
    valid_from: IsoDate | None = None
    valid_to: IsoDate | None = None
    previous_symbol: ListingSymbol | None = None

    @model_validator(mode="after")
    def _is_a_meaningful_statement(self) -> Self:
        stated = (self.legal_name, self.listing_status, self.sector_label, self.valid_from, self.valid_to, self.previous_symbol)
        if all(value is None for value in stated):
            raise ValueError(f"claim about {self.symbol} states nothing beyond the symbol")
        if self.valid_from is not None and self.valid_to is not None and self.valid_from >= self.valid_to:
            raise ValueError(f"claim about {self.symbol}: valid_from must be before valid_to")
        if self.previous_symbol is not None:
            if self.previous_symbol == self.symbol:
                raise ValueError(f"claim about {self.symbol}: previous_symbol equals symbol")
            if self.valid_from is None:
                raise ValueError(f"symbol change to {self.symbol} needs the valid_from date it took effect")
        return self

    def interval(self) -> tuple[date, date]:
        """Half-open dates the statement covers: its validity range, else its as-of day."""
        start = self.valid_from or self.as_of
        end = self.valid_to or self.as_of + timedelta(days=1)
        return (start, end) if end > start else (start, start + timedelta(days=1))


class ClaimEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Identifier
    # The registered hash when the claim was made, pinning the exact bytes.
    source_sha256: Sha256
    location: NonEmptyStr
    excerpt: NonEmptyStr | None = None


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal[ClaimStatus.VERIFIED, ClaimStatus.REJECTED]
    reviewer: NonEmptyStr
    reviewed_at: AwareTimestamp
    note: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _rejection_has_reason(self) -> Self:
        if self.decision is ClaimStatus.REJECTED and self.note is None:
            raise ValueError("a rejected claim needs a note explaining why")
        return self


class ListingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{16}$")
    assertion: ListingAssertion
    evidence: tuple[ClaimEvidence, ...] = Field(min_length=1)
    discovered_by: NonEmptyStr
    discovered_at: AwareTimestamp
    status: ClaimStatus
    review: ClaimReview | None = None

    @model_validator(mode="after")
    def _is_consistent(self) -> Self:
        if self.claim_id != claim_id_for(self.assertion, self.evidence):
            raise ValueError(f"{self.claim_id}: claim_id does not match the claim content")
        if self.status is ClaimStatus.DISCOVERED and self.review is not None:
            raise ValueError(f"{self.claim_id}: a discovered claim cannot carry a review")
        if self.status is not ClaimStatus.DISCOVERED:
            if self.review is None or self.review.decision is not self.status:
                raise ValueError(f"{self.claim_id}: status {self.status.value} needs a matching review")
            if self.review.reviewed_at < self.discovered_at:
                raise ValueError(f"{self.claim_id}: reviewed before it was discovered")
        return self


def claim_id_for(assertion: ListingAssertion, evidence: Iterable[ClaimEvidence]) -> str:
    """Content-derived ID: the same statement and evidence always get the same ID."""
    payload = {
        "assertion": assertion.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"clm_{digest[:16]}"


def discover_claim(
    assertion: ListingAssertion, evidence: tuple[ClaimEvidence, ...], *, discovered_by: str, discovered_at: datetime
) -> ListingClaim:
    return ListingClaim(
        claim_id=claim_id_for(assertion, evidence),
        assertion=assertion,
        evidence=evidence,
        discovered_by=discovered_by,
        discovered_at=discovered_at,
        status=ClaimStatus.DISCOVERED,
    )


def review_claim(
    claim: ListingClaim,
    decision: Literal[ClaimStatus.VERIFIED, ClaimStatus.REJECTED],
    *,
    reviewer: str,
    reviewed_at: datetime,
    note: str | None = None,
) -> ListingClaim:
    """Record a person's decision. Only a discovered claim can be reviewed."""
    if claim.status is not ClaimStatus.DISCOVERED:
        raise ClaimError(f"{claim.claim_id} is already {claim.status.value}")
    try:
        review = ClaimReview(decision=decision, reviewer=reviewer, reviewed_at=reviewed_at, note=note)
        return ListingClaim.model_validate({**dict(claim), "status": decision, "review": review})
    except ValidationError as exc:
        raise ClaimError(str(exc)) from exc


def check_claim_evidence(claims: Iterable[ListingClaim], sources: SourceRegistry) -> None:
    """Every cited source must be registered with the hash the claim recorded."""
    for claim in claims:
        for item in claim.evidence:
            source = sources.get(item.source_id)
            if source.sha256 != item.source_sha256:
                raise ClaimError(f"{claim.claim_id}: source {item.source_id} no longer has the cited SHA-256")


def find_ambiguities(claims: Iterable[ListingClaim]) -> list[str]:
    """Contradictions among non-rejected claims about the same symbol and dates.

    Two claims conflict when their date intervals overlap and they state
    different legal names or different listing statuses. A symbol reused
    after a delisting does not conflict, because the intervals do not overlap.
    """
    by_symbol: dict[str, list[ListingClaim]] = defaultdict(list)
    for claim in claims:
        if claim.status is not ClaimStatus.REJECTED:
            by_symbol[claim.assertion.symbol].append(claim)
    problems = []
    for symbol, group in sorted(by_symbol.items()):
        for first, second in combinations(group, 2):
            (a_start, a_end), (b_start, b_end) = first.assertion.interval(), second.assertion.interval()
            if a_start >= b_end or b_start >= a_end:
                continue
            for field in ("legal_name", "listing_status"):
                a_value, b_value = getattr(first.assertion, field), getattr(second.assertion, field)
                if a_value is not None and b_value is not None and a_value != b_value:
                    problems.append(
                        f"{symbol}: {first.claim_id} and {second.claim_id} state different {field} "
                        f"({a_value!r} vs {b_value!r}) for overlapping dates"
                    )
    return problems


class ListingClaimsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_type: Literal["listing_claims"] = "listing_claims"
    claims: tuple[ListingClaim, ...]

    @model_validator(mode="after")
    def _is_unambiguous(self) -> Self:
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claim_id values")
        problems = find_ambiguities(self.claims)
        if problems:
            raise ValueError("ambiguous listing claims: " + "; ".join(problems))
        return self

    def get(self, claim_id: str) -> ListingClaim:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        raise ClaimError(f"no claim {claim_id!r}")

    def merged(self, new_claims: Iterable[ListingClaim]) -> "ListingClaimsDocument":
        """Add claims; a claim already present keeps its existing review state."""
        known = {claim.claim_id for claim in self.claims}
        added = tuple(claim for claim in new_claims if claim.claim_id not in known)
        return ListingClaimsDocument(claims=(*self.claims, *added))

    def replaced(self, claim: ListingClaim) -> "ListingClaimsDocument":
        self.get(claim.claim_id)
        return ListingClaimsDocument(claims=tuple(claim if c.claim_id == claim.claim_id else c for c in self.claims))


@dataclass(frozen=True)
class CompanyProposal:
    company: Company
    claim_ids: tuple[str, ...]
    unverified_claim_ids: tuple[str, ...]
    # Sector text found in the claims, for a reviewer to map to a sector key.
    sector_labels: tuple[str, ...]


def propose_company(company_id: str, claims: Iterable[ListingClaim]) -> CompanyProposal:
    """Build a company record from claims a reviewer selected for one company.

    The claims' symbols must form one chain of symbol changes. Identity is
    verified only when every claim is verified; otherwise the record is
    unverified and lists the claims' evidence as candidate evidence. No sector
    classification is set: sector labels are returned for review instead.
    """
    selected = tuple(claims)
    if not selected:
        raise ClaimError("a proposal needs at least one claim")
    rejected = [claim.claim_id for claim in selected if claim.status is ClaimStatus.REJECTED]
    if rejected:
        raise ClaimError(f"rejected claims cannot support a proposal: {rejected}")
    problems = find_ambiguities(selected)
    if problems:
        raise ClaimError("; ".join(problems))

    latest_first = sorted(selected, key=lambda claim: claim.assertion.as_of, reverse=True)
    legal_name = next((c.assertion.legal_name for c in latest_first if c.assertion.legal_name), None)
    if legal_name is None:
        raise ClaimError("no claim states the company's legal name")
    status_claim = next((c for c in latest_first if c.assertion.listing_status is not None), None)
    status = status_claim.assertion.listing_status if status_claim else None
    delisted_on = None
    if status_claim is not None and status is ListingStatus.DELISTED:
        delisted_on = status_claim.assertion.valid_from
        if delisted_on is None:
            raise ClaimError("a delisting claim needs the valid_from date it took effect")

    unverified = tuple(c.claim_id for c in selected if c.status is not ClaimStatus.VERIFIED)
    references = _evidence_references(selected)
    if unverified:
        identity = Attestation(state=AttestationState.UNVERIFIED, evidence=references)
    else:
        reviews = [c.review for c in selected if c.review is not None]
        identity = Attestation(
            state=AttestationState.VERIFIED,
            evidence=references,
            verified_by=", ".join(sorted({review.reviewer for review in reviews})),
            verified_at=max(review.reviewed_at for review in reviews),
        )
    try:
        company = Company(
            company_id=company_id,
            legal_name=legal_name,
            listing_status=status,
            delisted_on=delisted_on,
            symbols=_symbol_history(selected, delisted_on),
            identity=identity,
        )
    except ValidationError as exc:
        raise ClaimError(f"claims do not form a consistent company record: {exc}") from exc
    return CompanyProposal(
        company=company,
        claim_ids=tuple(c.claim_id for c in selected),
        unverified_claim_ids=unverified,
        sector_labels=tuple(sorted({c.assertion.sector_label for c in selected if c.assertion.sector_label})),
    )


def _symbol_history(claims: tuple[ListingClaim, ...], delisted_on: date | None) -> tuple[SymbolPeriod, ...]:
    by_symbol: dict[str, list[ListingAssertion]] = defaultdict(list)
    for claim in claims:
        by_symbol[claim.assertion.symbol].append(claim.assertion)
    predecessor: dict[str, str] = {}
    for symbol, assertions in by_symbol.items():
        previous = {a.previous_symbol for a in assertions if a.previous_symbol is not None}
        if len(previous) > 1:
            raise ClaimError(f"{symbol} is claimed to replace several symbols: {sorted(previous)}")
        if previous:
            predecessor[symbol] = previous.pop()
    successors: dict[str, list[str]] = defaultdict(list)
    for symbol, replaced in predecessor.items():
        successors[replaced].append(symbol)
    branching = {symbol: sorted(after) for symbol, after in successors.items() if len(after) > 1}
    if branching:
        raise ClaimError(f"symbols are claimed to have several successors: {branching}")
    heads = [symbol for symbol in by_symbol if symbol not in successors]
    if len(heads) != 1:
        raise ClaimError(f"claims describe {len(heads)} unconnected symbol chains: {sorted(heads)}")

    chain = [heads[0]]
    while chain[-1] in predecessor:
        chain.append(predecessor[chain[-1]])
        if len(chain) > len(by_symbol) + 1:
            raise ClaimError("symbol changes form a cycle")
    chain.reverse()

    # A symbol's dates come only from statements about the symbol itself: a
    # symbol change (start), a `listed` status with valid_from (start), the
    # successor's change date (end), or the delisting date (end). Dates on
    # name or sector statements describe those statements, not the symbol.
    periods = []
    for index, symbol in enumerate(chain):
        assertions = by_symbol.get(symbol, [])
        change = next((a for a in assertions if a.previous_symbol is not None), None)
        listed_from = sorted(
            {a.valid_from for a in assertions if a.listing_status is ListingStatus.LISTED and a.valid_from is not None}
        )
        valid_from = change.valid_from if change else (listed_from[0] if listed_from else None)
        if index + 1 < len(chain):
            valid_to = next(a.valid_from for a in by_symbol[chain[index + 1]] if a.previous_symbol == symbol)
        else:
            valid_to = delisted_on
        periods.append(SymbolPeriod(symbol=symbol, valid_from=valid_from, valid_to=valid_to))
    return tuple(periods)


def _evidence_references(claims: tuple[ListingClaim, ...]) -> tuple[EvidenceReference, ...]:
    references: dict[tuple[str, str], EvidenceReference] = {}
    for claim in claims:
        for item in claim.evidence:
            key = (item.source_id, item.location)
            references.setdefault(
                key, EvidenceReference(description=f"{claim.claim_id}: {item.location}", source_id=item.source_id)
            )
    return tuple(references.values())
