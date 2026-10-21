"""Strict scalar types shared by canonical and v1 models.

Pydantic's lax mode would coerce `True` to `1`, `"12"` to `12`, a Unix
timestamp to a date, and accept NaN floats. These types reject all of that.
"""

import math
import re
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    PlainSerializer,
    StringConstraints,
    StrictFloat,
    StrictInt,
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _require_finite(value: int | float) -> int | float:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"value must be a finite number, got {value!r}")
    return value


def _parse_iso_date(value: object) -> object:
    if isinstance(value, datetime):
        raise ValueError(f"expected a date without a time, got {value!r}")
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"expected an ISO date string YYYY-MM-DD, got {value!r}")
    return date.fromisoformat(value)


def _parse_iso_timestamp(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"expected an ISO 8601 timestamp string, got {value!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp {value!r}") from exc


def _require_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if "\\" in value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must be relative, use '/', and stay inside its root, got {value!r}")
    return value


def _require_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL must be absolute http(s), got {value!r}")
    return value


# Integers stay integers and floats stay floats, so stored values round-trip exactly.
FiniteNumber = Annotated[StrictInt | StrictFloat, AfterValidator(_require_finite)]
IsoDate = Annotated[date, BeforeValidator(_parse_iso_date)]
# Timestamps must carry a UTC offset; naive local times are ambiguous. They
# serialize with `isoformat()` so "+00:00" round-trips instead of becoming "Z".
AwareTimestamp = Annotated[
    AwareDatetime,
    BeforeValidator(_parse_iso_timestamp),
    PlainSerializer(lambda value: value.isoformat(), return_type=str, when_used="json"),
]
HttpUrl = Annotated[str, StringConstraints(strict=True, min_length=1), AfterValidator(_require_http_url)]
NonEmptyStr = Annotated[str, StringConstraints(strict=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(strict=True, pattern=r"^\S+$")]
# Stable, opaque company identifier. It never changes when a ticker changes
# and must not be read as the current listing symbol.
CompanyId = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z0-9]+$")]
ListingSymbol = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z0-9]+$")]
SectorKey = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
RelativePath = Annotated[str, StringConstraints(strict=True, min_length=1), AfterValidator(_require_relative_path)]
ConceptId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
CurrencyCode = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
