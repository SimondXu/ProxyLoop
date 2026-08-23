from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
)
from pydantic.types import UUID4

SchemaVersion = Literal["1.0"]
Revision = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ExternalRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
HumanText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UUID4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
UTC_RFC3339_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|\+00:00)$"
)


def require_canonical_uuid4(value: object) -> object:
    if isinstance(value, str) and re.fullmatch(UUID4_PATTERN, value) is None:
        raise ValueError("identifier must be a canonical lowercase UUIDv4")
    return value


EntityId = Annotated[
    UUID4,
    BeforeValidator(require_canonical_uuid4),
    WithJsonSchema(
        {
            "type": "string",
            "format": "uuid",
            "pattern": UUID4_PATTERN,
        }
    ),
]


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


UtcDateTime = Annotated[
    datetime,
    AfterValidator(require_utc),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "pattern": UTC_RFC3339_PATTERN,
        }
    ),
]


class ContractModel(BaseModel):
    """Strict immutable value crossing the canonical contract seam."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class VersionedContract(ContractModel):
    schema_version: SchemaVersion
    revision: Revision


def require_time_order(start: datetime, end: datetime, label: str) -> None:
    if end <= start:
        raise ValueError(f"{label} must be after its start timestamp")


def uuid_strings(values: tuple[UUID, ...]) -> set[str]:
    return {str(value) for value in values}
