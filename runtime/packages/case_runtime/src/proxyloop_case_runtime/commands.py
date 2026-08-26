"""Strict internal commands and compact PostgreSQL transition receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from proxyloop_contracts import Money
from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

CASE_COMMAND_SCHEMA_VERSION: Literal["phase-05a-v1"] = "phase-05a-v1"


class CaseCommandType(StrEnum):
    CREATE_CASE = "create_case"
    APPEND_EVENT = "append_event"
    DECIDE_APPROVAL = "decide_approval"
    EXPIRE_APPROVAL = "expire_approval"


class CaseCommand(BaseModel):
    """One idempotent application command issued by a durable Workflow."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["phase-05a-v1"] = CASE_COMMAND_SCHEMA_VERSION
    command_id: UUID4
    case_id: UUID4
    command_type: CaseCommandType
    occurred_at: datetime
    expected_revision: int | None = Field(default=None, ge=1)
    current_monthly_total: Money | None = None
    target_monthly_total: Money | None = None
    mobile_hotspot_required: Literal[True] | None = None
    device_financing_change_forbidden: Literal[True] | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    event_type: Literal["consumer_message"] | None = None
    approval_id: UUID4 | None = None
    decision: Literal["approved", "rejected"] | None = None
    expected_case_revision: int | None = Field(default=None, ge=1)
    expected_action_intent_revision: int | None = Field(default=None, ge=1)
    approval_expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_command_shape(self) -> CaseCommand:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("occurred_at must be a timezone-aware UTC datetime")
        if self.approval_expires_at is not None and (
            self.approval_expires_at.tzinfo is None
            or self.approval_expires_at.utcoffset() != timedelta(0)
        ):
            raise ValueError(
                "approval_expires_at must be a timezone-aware UTC datetime"
            )

        create_fields = (
            self.current_monthly_total,
            self.target_monthly_total,
            self.mobile_hotspot_required,
            self.device_financing_change_forbidden,
        )
        approval_fields = (
            self.approval_id,
            self.decision,
            self.expected_case_revision,
            self.expected_action_intent_revision,
            self.approval_expires_at,
        )
        if self.command_type is CaseCommandType.CREATE_CASE:
            if any(value is None for value in create_fields):
                raise ValueError("create_case requires all four intake facts")
            if self.expected_revision is not None:
                raise ValueError("create_case cannot have an expected revision")
            if (
                self.content is not None
                or self.event_type is not None
                or any(value is not None for value in approval_fields)
            ):
                raise ValueError("create_case contains fields for another command")
        elif self.command_type is CaseCommandType.APPEND_EVENT:
            if self.content is None or self.event_type != "consumer_message":
                raise ValueError("append_event requires consumer_message content")
            if any(value is not None for value in (*create_fields, *approval_fields)):
                raise ValueError("append_event contains fields for another command")
        elif self.command_type is CaseCommandType.DECIDE_APPROVAL:
            if self.approval_id is None or self.decision is None:
                raise ValueError("decide_approval requires approval id and decision")
            if self.approval_expires_at is not None:
                raise ValueError("decide_approval cannot set approval expiry")
            if any(value is not None for value in create_fields) or (
                self.content is not None or self.event_type is not None
            ):
                raise ValueError("decide_approval contains fields for another command")
        else:
            if (
                self.approval_id is None
                or self.expected_revision is None
                or self.approval_expires_at is None
            ):
                raise ValueError(
                    "expire_approval requires approval id, revision, and expiry"
                )
            if self.decision is not None or any(
                value is not None
                for value in (
                    *create_fields,
                    self.content,
                    self.event_type,
                    self.expected_case_revision,
                    self.expected_action_intent_revision,
                )
            ):
                raise ValueError("expire_approval contains fields for another command")
            if self.occurred_at != self.approval_expires_at:
                raise ValueError("expire_approval must occur at the exact expiry")
        return self


class CaseTransitionRef(BaseModel):
    """Compact durable pointer to a PostgreSQL-authoritative Case transition."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["phase-05a-v1"] = CASE_COMMAND_SCHEMA_VERSION
    command_id: UUID4
    case_id: UUID4
    command_type: CaseCommandType
    before_revision: int | None = Field(default=None, ge=1)
    after_revision: int = Field(ge=1)
    event_cursor: int = Field(ge=0)
    route: str = Field(min_length=1, max_length=128)
    approval_id: UUID4 | None = None
    approval_expires_at: datetime | None = None
    terminal: bool
    deduplicated: bool = False

    @model_validator(mode="after")
    def validate_reference(self) -> CaseTransitionRef:
        if self.approval_expires_at is not None and (
            self.approval_expires_at.tzinfo is None
            or self.approval_expires_at.utcoffset() != timedelta(0)
        ):
            raise ValueError(
                "approval_expires_at must be a timezone-aware UTC datetime"
            )
        if self.command_type is CaseCommandType.CREATE_CASE:
            if self.before_revision is not None:
                raise ValueError("create transition cannot have a before revision")
        elif self.before_revision is None:
            raise ValueError("non-create transition requires a before revision")
        if (self.approval_id is None) != (self.approval_expires_at is None):
            raise ValueError("approval wait reference requires id and expiry together")
        return self


__all__ = [
    "CASE_COMMAND_SCHEMA_VERSION",
    "CaseCommand",
    "CaseCommandType",
    "CaseTransitionRef",
]
