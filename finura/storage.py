"""Safe replacement of Finura JSON files.

Every write stages all files first, refuses to replace an existing file
without a backup directory, copies existing files to verified backups, swaps
the staged files in, and re-hashes what landed on disk.
"""

import hashlib
import os
import secrets
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class StorageError(Exception):
    """A write was refused or did not land as staged; see the message."""


class BackupRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_path: str
    backup_path: str
    sha256: str


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def plan_backups(targets: Iterable[Path], backup_dir: Path | None, stamp: datetime) -> tuple[BackupRecord, ...]:
    """Decide backups for targets that already exist, refusing when none is allowed."""
    plan = []
    for target in targets:
        if not target.exists():
            continue
        if backup_dir is None:
            raise StorageError(f"refusing to overwrite {target} without a backup directory")
        destination = backup_dir / f"{target.name}.{stamp.astimezone(UTC):%Y%m%dT%H%M%SZ}.bak"
        if destination.exists():
            raise StorageError(f"backup already exists: {destination}")
        plan.append(
            BackupRecord(original_path=str(target), backup_path=str(destination), sha256=sha256_bytes(target.read_bytes()))
        )
    return tuple(plan)


def write_files(contents: dict[Path, str], backups: tuple[BackupRecord, ...]) -> None:
    """Stage every file, take the planned backups, then swap each staged file in."""
    staged: dict[Path, Path] = {}
    try:
        for target, text in contents.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
            temporary.write_text(text, encoding="utf-8")
            staged[target] = temporary
        for record in backups:
            destination = Path(record.backup_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record.original_path, destination)
            if sha256_bytes(destination.read_bytes()) != record.sha256:
                raise StorageError(f"backup does not match the file it copies: {destination}")
        for target, temporary in staged.items():
            os.replace(temporary, target)
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    for target, text in contents.items():
        if sha256_bytes(target.read_bytes()) != sha256_bytes(text.encode()):
            raise StorageError(f"written file does not match the staged content: {target}")


def replace_files(contents: dict[Path, str], *, backup_dir: Path | None, stamp: datetime) -> tuple[BackupRecord, ...]:
    """Plan backups and write in one call; returns the backups taken."""
    backups = plan_backups(contents, backup_dir, stamp)
    write_files(contents, backups)
    return backups
