"""Strict JSON reading shared by every Finura file loader."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


class SchemaLoadError(ValueError):
    """A file could not be read or does not satisfy its schema."""

    def __init__(self, path: Path, detail: str):
        self.path = path
        super().__init__(f"{path}: {detail}")


def read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaLoadError(path, f"cannot read file: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ValueError as exc:
        raise SchemaLoadError(path, f"invalid JSON: {exc}") from exc


def validate_model[M: BaseModel](path: Path, location: str, model: type[M], payload: Any) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        where = f"{location} " if location else ""
        raise SchemaLoadError(path, f"{where}does not match {model.__name__}: {exc}") from exc


def load_model[M: BaseModel](path: Path, model: type[M]) -> M:
    return validate_model(path, "", model, read_json(path))


def dump_model(model: BaseModel) -> str:
    """Serialize a model the way Finura writes JSON files."""
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # json.loads keeps the last value for a repeated key; a silent overwrite
    # would hide a conflicting value, so treat it as an error.
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result
