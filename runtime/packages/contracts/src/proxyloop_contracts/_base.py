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
    ValidationInfo,
    WithJsonSchema,
)
from pydantic.config import JsonDict
from pydantic.types import UUID4

SchemaVersion = Literal["1.0"]
# Contract set 1.1 versions per type: only a type whose shape or semantics
# changed accepts "1.1"; a type new in 1.1 accepts only "1.1"; every other
# type stays "1.0", so its bytes and every fingerprint over them never move.
SchemaVersion10Or11 = Literal["1.0", "1.1"]
SchemaVersion11 = Literal["1.1"]


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


class VersionedContract10Or11(ContractModel):
    """A type whose shape or semantics changed in contract set 1.1."""

    schema_version: SchemaVersion10Or11
    revision: Revision


class VersionedContract11(ContractModel):
    """A type new in contract set 1.1."""

    schema_version: SchemaVersion11
    revision: Revision


def absent(value: object) -> bool:
    """``exclude_if`` predicate: an unset 1.1-only field is not serialised."""

    return value is None


def enforce_version_gate(
    model: VersionedContract10Or11,
    info: ValidationInfo,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    """``mode="after"``: 1.1 fields are required at 1.1 and forbidden at 1.0.

    A 1.0 JSON document may not carry a 1.1 key, not even ``null`` (the
    JSON Schema rejects it too). In Python mode ``None`` means absent, so
    ``Model(**other.__dict__)`` keeps working for 1.0 documents; strict mode
    means wire documents are only ever validated as JSON. ``model_fields_set``
    sees an explicit ``null`` key; a ``mode="before"`` validator would turn
    strict JSON input into Python input and reject every JSON timestamp.
    """

    if model.schema_version == "1.0":
        present = [
            name
            for name in (*required, *optional)
            if getattr(model, name) is not None
            or (info.mode == "json" and name in model.model_fields_set)
        ]
        if present:
            raise ValueError(f"{', '.join(present)} is not part of schema_version 1.0")
        return
    missing = [name for name in required if getattr(model, name) is None]
    if missing:
        raise ValueError(f"{', '.join(missing)} is required at schema_version 1.1")


def version_gate_json_schema(
    required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> JsonDict:
    """The JSON Schema twin of ``enforce_version_gate``."""

    return {
        "schema_version": {
            "if": {"properties": {"schema_version": {"const": "1.1"}}},
            "then": {
                "required": list(required),
                "properties": {name: {"not": {"type": "null"}} for name in required},
            },
            "else": {"properties": dict.fromkeys((*required, *optional), False)},
        }
    }


def require_time_order(start: datetime, end: datetime, label: str) -> None:
    if end <= start:
        raise ValueError(f"{label} must be after its start timestamp")


def uuid_strings(values: tuple[UUID, ...]) -> set[str]:
    return {str(value) for value in values}
