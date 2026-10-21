"""Source registry: the record of every preserved evidence artifact.

Callers depend on the `SourceRegistry` protocol. `RegistryFileSources` keeps a
validated `SourceRegistryDocument` in memory and saves it through
`finura.storage`, so existing registry files are never replaced without a
backup.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Protocol, Self

from finura.schemas.documents import SourceRegistryDocument
from finura.schemas.io import dump_model, load_model
from finura.schemas.source import SourceDocument
from finura.storage import BackupRecord, replace_files, sha256_bytes


class UnknownSourceError(LookupError):
    """No registered source has the requested identifier."""


class SourceConflictError(ValueError):
    """A registration contradicts an existing record."""


class SourceRegistry(Protocol):
    def get(self, source_id: str) -> SourceDocument: ...

    def find_by_sha256(self, sha256: str, company_id: str | None) -> SourceDocument | None: ...

    def register(self, document: SourceDocument) -> SourceDocument: ...

    def sources(self) -> tuple[SourceDocument, ...]: ...


def new_source_id(company_id: str | None, canonical_url: str | None, sha256: str) -> str:
    """Deterministic source ID; the same derivation as `pipeline/register_source.py`."""
    identity = "|".join([company_id or "", canonical_url or "", sha256])
    return "src_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


class RegistryFileSources:
    def __init__(self, document: SourceRegistryDocument):
        self._document = document

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls(load_model(path, SourceRegistryDocument))

    @property
    def document(self) -> SourceRegistryDocument:
        return self._document

    def get(self, source_id: str) -> SourceDocument:
        source = self._document.get(source_id)
        if source is None:
            raise UnknownSourceError(f"no registered source {source_id!r}")
        return source

    def find_by_sha256(self, sha256: str, company_id: str | None) -> SourceDocument | None:
        return next(
            (s for s in self._document.sources if s.sha256 == sha256 and s.company_id == company_id),
            None,
        )

    def register(self, document: SourceDocument) -> SourceDocument:
        """Add a source, or return the existing record for identical content.

        Re-registering the same bytes for the same company returns the original
        record unchanged. Reusing a source_id for different content is refused.
        """
        existing = self._document.get(document.source_id)
        if existing is not None:
            if existing.sha256 != document.sha256 or existing.company_id != document.company_id:
                raise SourceConflictError(f"source_id {document.source_id!r} is already registered for other content")
            return existing
        duplicate = self.find_by_sha256(document.sha256, document.company_id)
        if duplicate is not None:
            return duplicate
        self._document = SourceRegistryDocument(
            sources=(*self._document.sources, document), lineage=self._document.lineage
        )
        return document

    def sources(self) -> tuple[SourceDocument, ...]:
        return self._document.sources

    def save(self, path: Path, *, backup_dir: Path | None, stamp: datetime) -> tuple[BackupRecord, ...]:
        return replace_files({path: dump_model(self._document)}, backup_dir=backup_dir, stamp=stamp)


def hash_evidence_file(evidence_root: Path, local_path: str) -> str:
    """SHA-256 of a file that must sit inside the evidence root."""
    root = evidence_root.resolve()
    path = (root / local_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"evidence path escapes the evidence root: {local_path}")
    if not path.is_file():
        raise UnknownSourceError(f"evidence file not found: {local_path}")
    return sha256_bytes(path.read_bytes())
