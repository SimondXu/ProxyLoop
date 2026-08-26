"""Compact deterministic state carried by the Temporal CaseWorkflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import RFC_4122, UUID

from proxyloop_case_runtime.commands import (
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
)
from proxyloop_contracts import Money
from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKFLOW_SCHEMA_VERSION: Literal["phase-05a-v1"] = "phase-05a-v1"


def _require_uuid4(value: UUID, field_name: str) -> UUID:
    if value.version != 4 or value.variant != RFC_4122:
        raise ValueError(f"{field_name} must be an RFC 4122 UUIDv4")
    return value


class CaseWorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["phase-05a-v1"] = WORKFLOW_SCHEMA_VERSION
    case_id: UUID
    run_generation: int = Field(default=0, ge=0)
    commands_in_run: int = Field(default=0, ge=0)
    continue_as_new_after: int = Field(default=32, ge=1, le=1000)
    last_transition: CaseTransitionRef | None = None

    @field_validator("case_id")
    @classmethod
    def case_id_is_uuid4(cls, value: UUID) -> UUID:
        return _require_uuid4(value, "case_id")


class CaseCommandRequest(BaseModel):
    """Strict Update payload with Workflow-owned command time.

    ``occurred_at`` is intentionally absent.  The Workflow supplies it from
    deterministic Workflow time immediately before scheduling the activity.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["phase-05a-v1"] = WORKFLOW_SCHEMA_VERSION
    command_id: UUID
    case_id: UUID
    command_type: CaseCommandType
    expected_revision: int | None = Field(default=None, ge=1)
    current_monthly_total: Money | None = None
    target_monthly_total: Money | None = None
    mobile_hotspot_required: Literal[True] | None = None
    device_financing_change_forbidden: Literal[True] | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    event_type: Literal["consumer_message"] | None = None
    approval_id: UUID | None = None
    decision: Literal["approved", "rejected"] | None = None
    expected_case_revision: int | None = Field(default=None, ge=1)
    expected_action_intent_revision: int | None = Field(default=None, ge=1)
    approval_expires_at: datetime | None = None

    @field_validator("command_id", "case_id", "approval_id")
    @classmethod
    def ids_are_uuid4(cls, value: UUID | None) -> UUID | None:
        # ``approval_id`` is optional at the type level, but Pydantic only
        # calls this validator for a supplied value on some Pydantic versions.
        if value is None:
            return None
        return _require_uuid4(value, "command id")

    @field_validator("approval_expires_at")
    @classmethod
    def expiry_is_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.astimezone(UTC) != value
        ):
            raise ValueError(
                "approval_expires_at must be a timezone-aware UTC datetime"
            )
        return value

    @classmethod
    def from_command(cls, command: CaseCommand) -> CaseCommandRequest:
        return cls.model_validate(command.model_dump(exclude={"occurred_at"}))

    def to_command(self, occurred_at: datetime) -> CaseCommand:
        if occurred_at.tzinfo is None or occurred_at.astimezone(UTC) != occurred_at:
            raise ValueError("Workflow time must be a timezone-aware UTC datetime")
        if self.command_type is CaseCommandType.EXPIRE_APPROVAL:
            if self.approval_expires_at is None:
                raise ValueError("expire_approval requires an expiry")
            command_time = self.approval_expires_at
        else:
            command_time = occurred_at
        return CaseCommand(
            occurred_at=command_time,
            **self.model_dump(),
        )


__all__ = [
    "WORKFLOW_SCHEMA_VERSION",
    "CaseCommandRequest",
    "CaseWorkflowInput",
]
