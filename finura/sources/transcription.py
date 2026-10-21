"""Parse a reviewer's transcription of listing evidence into discovered claims.

When a publisher's terms allow only manual, personal downloads (as PSX's do),
a person saves the notice, registers it as a source, and records what it
states in a CSV with these columns:

    symbol, as_of, legal_name, listing_status, sector_label, valid_from,
    valid_to, previous_symbol, source_id, location, excerpt

Empty cells are unknown. Rows with the same statement and different evidence
become one claim citing every piece of evidence. Parsing is offline and never
verifies anything: every claim it produces is `discovered`.
"""

import csv
import io
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from finura.claims import ClaimEvidence, ListingAssertion, ListingClaim, discover_claim, find_ambiguities
from finura.sources.registry import SourceRegistry, UnknownSourceError

ASSERTION_COLUMNS = (
    "symbol",
    "as_of",
    "legal_name",
    "listing_status",
    "sector_label",
    "valid_from",
    "valid_to",
    "previous_symbol",
)
EVIDENCE_COLUMNS = ("source_id", "location", "excerpt")
TRANSCRIPTION_COLUMNS = ASSERTION_COLUMNS + EVIDENCE_COLUMNS


class TranscriptionError(ValueError):
    """The transcription is malformed, cites unknown sources, or is ambiguous."""


def parse_listing_transcription(
    content: bytes, *, sources: SourceRegistry, discovered_by: str, discovered_at: datetime
) -> tuple[ListingClaim, ...]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TranscriptionError(f"transcription is not UTF-8: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = tuple(reader.fieldnames or ())
    if sorted(header) != sorted(TRANSCRIPTION_COLUMNS) or len(header) != len(set(header)):
        missing = sorted(set(TRANSCRIPTION_COLUMNS) - set(header))
        unknown = sorted(set(header) - set(TRANSCRIPTION_COLUMNS))
        raise TranscriptionError(f"bad header: missing {missing}, unknown {unknown}, duplicated columns not allowed")

    grouped: dict[ListingAssertion, list[ClaimEvidence]] = {}
    for line, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise TranscriptionError(f"line {line}: wrong number of cells")
        cells = {key: (value.strip() or None) for key, value in row.items() if key is not None and value is not None}
        assertion = _build(line, ListingAssertion, {key: cells[key] for key in ASSERTION_COLUMNS})
        source_id = cells["source_id"]
        if source_id is None:
            raise TranscriptionError(f"line {line}: source_id is required")
        try:
            source = sources.get(source_id)
        except UnknownSourceError as exc:
            raise TranscriptionError(f"line {line}: {exc}") from exc
        evidence = _build(
            line,
            ClaimEvidence,
            {"source_id": source_id, "source_sha256": source.sha256, "location": cells["location"], "excerpt": cells["excerpt"]},
        )
        items = grouped.setdefault(assertion, [])
        if evidence in items:
            raise TranscriptionError(f"line {line}: duplicate row")
        items.append(evidence)
    if not grouped:
        raise TranscriptionError("transcription has no rows")

    claims = tuple(
        discover_claim(assertion, tuple(evidence), discovered_by=discovered_by, discovered_at=discovered_at)
        for assertion, evidence in grouped.items()
    )
    problems = find_ambiguities(claims)
    if problems:
        raise TranscriptionError("ambiguous listing records: " + "; ".join(problems))
    return claims


def _build[M: (ListingAssertion, ClaimEvidence)](line: int, model: Callable[..., M], values: dict[str, str | None]) -> M:
    try:
        return model(**values)
    except ValidationError as exc:
        raise TranscriptionError(f"line {line}: {exc}") from exc
