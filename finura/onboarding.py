"""Evidence-based company onboarding: ingest, review, and propose.

    python -m finura.onboarding ingest  --transcription CSV --sources REG --claims FILE --discovered-by NAME
    python -m finura.onboarding review  --claims FILE --claim-id ID --decision verified|rejected --reviewer NAME [--note TEXT]
    python -m finura.onboarding propose --claims FILE --sources REG --claim-id ID [...] --company-id ID --companies FILE [--replace]

Every command takes `--backup-dir`, which is required when it replaces an
existing file. `review` is the only command that changes a claim's status.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from finura.claims import (
    ClaimError,
    ClaimStatus,
    ListingClaimsDocument,
    check_claim_evidence,
    propose_company,
    review_claim,
)
from finura.companies import CompanyRegistryDocument
from finura.schemas.io import SchemaLoadError, dump_model, load_model
from finura.sources.registry import RegistryFileSources, UnknownSourceError
from finura.sources.transcription import TranscriptionError, parse_listing_transcription
from finura.storage import StorageError, replace_files


def ingest(args: argparse.Namespace, now: datetime) -> str:
    sources = RegistryFileSources.load(args.sources)
    claims = parse_listing_transcription(
        args.transcription.read_bytes(), sources=sources, discovered_by=args.discovered_by, discovered_at=now
    )
    existing = load_model(args.claims, ListingClaimsDocument) if args.claims.exists() else ListingClaimsDocument(claims=())
    updated = existing.merged(claims)
    replace_files({args.claims: dump_model(updated)}, backup_dir=args.backup_dir, stamp=now)
    added = len(updated.claims) - len(existing.claims)
    return f"Parsed {len(claims)} claims; added {added} new discovered claims to {args.claims}"


def review(args: argparse.Namespace, now: datetime) -> str:
    document = load_model(args.claims, ListingClaimsDocument)
    decision: Literal[ClaimStatus.VERIFIED, ClaimStatus.REJECTED] = (
        ClaimStatus.VERIFIED if args.decision == "verified" else ClaimStatus.REJECTED
    )
    reviewed = review_claim(document.get(args.claim_id), decision, reviewer=args.reviewer, reviewed_at=now, note=args.note)
    replace_files({args.claims: dump_model(document.replaced(reviewed))}, backup_dir=args.backup_dir, stamp=now)
    return f"{args.claim_id} is now {decision.value}"


def propose(args: argparse.Namespace, now: datetime) -> str:
    document = load_model(args.claims, ListingClaimsDocument)
    selected = [document.get(claim_id) for claim_id in args.claim_id]
    check_claim_evidence(selected, RegistryFileSources.load(args.sources))
    proposal = propose_company(args.company_id, selected)
    registry = (
        load_model(args.companies, CompanyRegistryDocument)
        if args.companies.exists()
        else CompanyRegistryDocument(companies=())
    )
    others = tuple(c for c in registry.companies if c.company_id != args.company_id)
    if len(others) != len(registry.companies) and not args.replace:
        raise ClaimError(f"{args.company_id} is already registered; pass --replace to update it")
    updated = CompanyRegistryDocument(companies=(*others, proposal.company))
    replace_files({args.companies: dump_model(updated)}, backup_dir=args.backup_dir, stamp=now)
    lines = [f"Proposed {args.company_id}: identity {proposal.company.identity.state.value}"]
    if proposal.unverified_claim_ids:
        lines.append(f"Unverified claims: {', '.join(proposal.unverified_claim_ids)}")
    if proposal.sector_labels:
        lines.append(f"Sector labels awaiting review (not applied): {', '.join(proposal.sector_labels)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-based company onboarding.")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest", help="parse a listing transcription into discovered claims")
    ingest_parser.add_argument("--transcription", type=Path, required=True)
    ingest_parser.add_argument("--sources", type=Path, required=True, help="v2 source registry")
    ingest_parser.add_argument("--claims", type=Path, required=True, help="listing claims document to create or extend")
    ingest_parser.add_argument("--discovered-by", required=True)

    review_parser = commands.add_parser("review", help="verify or reject one discovered claim")
    review_parser.add_argument("--claims", type=Path, required=True)
    review_parser.add_argument("--claim-id", required=True)
    review_parser.add_argument("--decision", choices=["verified", "rejected"], required=True)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--note")

    propose_parser = commands.add_parser("propose", help="build a company record from selected claims")
    propose_parser.add_argument("--claims", type=Path, required=True)
    propose_parser.add_argument("--sources", type=Path, required=True, help="v2 source registry")
    propose_parser.add_argument("--claim-id", action="append", required=True)
    propose_parser.add_argument("--company-id", required=True)
    propose_parser.add_argument("--companies", type=Path, required=True, help="company registry to create or extend")
    propose_parser.add_argument("--replace", action="store_true")

    for sub in (ingest_parser, review_parser, propose_parser):
        sub.add_argument("--backup-dir", type=Path, help="required when replacing an existing file")

    args = parser.parse_args(argv)
    handlers = {"ingest": ingest, "review": review, "propose": propose}
    try:
        print(handlers[args.command](args, datetime.now(UTC)))
    except (
        ClaimError,
        SchemaLoadError,
        StorageError,
        TranscriptionError,
        UnknownSourceError,
        ValidationError,
        OSError,
    ) as exc:
        print(f"{args.command} refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
