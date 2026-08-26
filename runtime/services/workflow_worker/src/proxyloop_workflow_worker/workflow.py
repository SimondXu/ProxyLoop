"""Deterministic Temporal ordering for one fictional ProxyLoop Case."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from uuid import UUID

from proxyloop_case_runtime.commands import (
    CASE_COMMAND_SCHEMA_VERSION,
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
)
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from .models import CaseCommandRequest, CaseWorkflowInput

WORKFLOW_NAME = "CaseWorkflow"
WORKFLOW_ID_PREFIX = "proxyloop-case/"
UPDATE_NAME = "apply_case_command"
ACTIVITY_NAME = "apply_case_command_activity"
COMMAND_ID_PREFIX = "case-command/"
DEFAULT_CONTINUE_AS_NEW_AFTER = 32

ACTIVITY_START_TO_CLOSE = timedelta(seconds=30)
ACTIVITY_SCHEDULE_TO_CLOSE = timedelta(minutes=2)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=5,
    non_retryable_error_types=(
        "invalid_command",
        "case_not_found",
        "case_conflict",
        "approval_expired",
        "state_invalid",
        "model_path",
    ),
)
NON_RETRYABLE_ERROR_TYPES = ACTIVITY_RETRY_POLICY.non_retryable_error_types


def workflow_id_for_case(case_id: UUID) -> str:
    """Return the stable Workflow ID for a Case UUID."""

    return f"{WORKFLOW_ID_PREFIX}{str(case_id).lower()}"


def update_id_for_command(command_id: UUID) -> str:
    """Return the stable Temporal Update ID for a command UUID."""

    return f"{COMMAND_ID_PREFIX}{str(command_id).lower()}"


def activity_id_for_command(command_id: UUID) -> str:
    """Return the stable Temporal Activity ID for a command UUID."""

    return update_id_for_command(command_id)


def _deterministic_uuid4(seed: str) -> UUID:
    """Create a stable RFC 4122 UUIDv4-shaped value without randomness."""

    raw = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def expiry_command_id(case_id: UUID, transition: CaseTransitionRef) -> UUID:
    """Derive the idempotent command ID for a pending approval timer."""

    if transition.approval_id is None or transition.approval_expires_at is None:
        raise ValueError("transition does not contain a pending approval")
    return _deterministic_uuid4(
        "proxyloop-expiry:"
        f"{case_id}:{transition.approval_id}:{transition.approval_expires_at.isoformat()}"
    )


def _invalid_command(message: str = "command rejected") -> ApplicationError:
    del message
    return ApplicationError(
        "invalid command",
        type="invalid_command",
        non_retryable=True,
    )


def _coerce_request(value: object) -> CaseCommandRequest:
    if isinstance(value, CaseCommandRequest):
        return value
    if isinstance(value, CaseCommand):
        return CaseCommandRequest.from_command(value)
    try:
        return CaseCommandRequest.model_validate(value)
    except Exception as exc:
        raise _invalid_command() from exc


@workflow.defn(name=WORKFLOW_NAME)
class CaseWorkflow:
    """Long-running Case orderer whose business truth remains in PostgreSQL."""

    @workflow.init
    def __init__(self, input: CaseWorkflowInput) -> None:
        try:
            workflow_input = (
                input
                if isinstance(input, CaseWorkflowInput)
                else CaseWorkflowInput.model_validate(input)
            )
        except Exception as exc:
            raise _invalid_command("invalid workflow input") from exc
        self._case_id: UUID | None = workflow_input.case_id
        self._run_generation = workflow_input.run_generation
        self._commands_in_run = workflow_input.commands_in_run
        self._continue_as_new_after = workflow_input.continue_as_new_after
        self._last_transition = workflow_input.last_transition
        self._command_lock = asyncio.Lock()
        self._wake_version = 0
        self._active_handlers = 0
        self._activity_in_flight = False
        self._continue_requested = False

    @workflow.run
    async def run(self, input: CaseWorkflowInput) -> None:
        """Keep the execution alive for Updates and the pending expiry timer."""

        del input

        while True:
            if (
                self._continue_requested
                and self._active_handlers == 0
                and not self._activity_in_flight
            ):
                self._continue_as_new()

            observed = self._wake_version
            pending = self._last_transition
            if (
                pending is not None
                and pending.approval_id is not None
                and pending.approval_expires_at is not None
            ):
                remaining = pending.approval_expires_at - workflow.now()
                if remaining <= timedelta(0):
                    await self._expire_pending()
                    continue
                try:

                    def wake_changed(observed_version: int = observed) -> bool:
                        return (
                            self._wake_version != observed_version
                            or self._continue_requested
                        )

                    await workflow.wait_condition(
                        wake_changed,
                        timeout=remaining,
                        timeout_summary="case approval expiry",
                    )
                except TimeoutError:
                    await self._expire_pending()
            else:

                def wake_changed(observed_version: int = observed) -> bool:
                    return (
                        self._wake_version != observed_version
                        or self._continue_requested
                    )

                await workflow.wait_condition(
                    wake_changed,
                )

    @workflow.update(name=UPDATE_NAME)
    async def apply_case_command(
        self,
        request: CaseCommandRequest | CaseCommand,
    ) -> CaseTransitionRef:
        """Validate and serialize one command through the Runtime activity."""

        # Everything before the first await is synchronous Update validation.
        command_request = _coerce_request(request)
        if self._case_id is None or command_request.case_id != self._case_id:
            raise _invalid_command("command Case id does not match Workflow")
        try:
            command = command_request.to_command(workflow.now())
        except Exception as exc:
            raise _invalid_command() from exc

        self._active_handlers += 1
        try:
            async with self._command_lock:
                transition = await self._execute_command(command)
                if transition.case_id != self._case_id:
                    raise ApplicationError(
                        "invalid activity result",
                        type="state_invalid",
                        non_retryable=True,
                    )
                self._last_transition = transition
                self._commands_in_run += 1
                self._continue_requested = (
                    self._commands_in_run >= self._continue_as_new_after
                )
                self._wake_version += 1
                return transition
        finally:
            self._active_handlers -= 1
            self._wake_version += 1

    async def _execute_command(self, command: CaseCommand) -> CaseTransitionRef:
        self._activity_in_flight = True
        try:
            transition = await workflow.execute_activity(
                ACTIVITY_NAME,
                command,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE,
                schedule_to_close_timeout=ACTIVITY_SCHEDULE_TO_CLOSE,
                retry_policy=ACTIVITY_RETRY_POLICY,
                activity_id=activity_id_for_command(command.command_id),
                result_type=CaseTransitionRef,
            )
        finally:
            self._activity_in_flight = False
        if not isinstance(transition, CaseTransitionRef):
            try:
                transition = CaseTransitionRef.model_validate(transition)
            except Exception as exc:
                raise ApplicationError(
                    "invalid activity result",
                    type="state_invalid",
                    non_retryable=True,
                ) from exc
        return transition

    async def _expire_pending(self) -> None:
        pending = self._last_transition
        case_id = self._case_id
        if (
            pending is None
            or pending.approval_id is None
            or pending.approval_expires_at is None
            or case_id is None
            or workflow.now() < pending.approval_expires_at
        ):
            return

        async with self._command_lock:
            # An approval Update may have won while the timer task was waking.
            current = self._last_transition
            if (
                current is None
                or current.approval_id is None
                or current.approval_expires_at is None
                or current.approval_id != pending.approval_id
                or current.approval_expires_at != pending.approval_expires_at
                or workflow.now() < current.approval_expires_at
            ):
                return
            expiry_request = CaseCommandRequest(
                schema_version=CASE_COMMAND_SCHEMA_VERSION,
                command_id=expiry_command_id(case_id, current),
                case_id=case_id,
                command_type=CaseCommandType.EXPIRE_APPROVAL,
                expected_revision=current.after_revision,
                approval_id=current.approval_id,
                approval_expires_at=current.approval_expires_at,
            )
            expiry_command = expiry_request.to_command(current.approval_expires_at)
            transition = await self._execute_command(expiry_command)
            if transition.case_id != case_id:
                raise ApplicationError(
                    "invalid activity result",
                    type="state_invalid",
                    non_retryable=True,
                )
            self._last_transition = transition
            self._commands_in_run += 1
            self._continue_requested = (
                self._commands_in_run >= self._continue_as_new_after
            )
            self._wake_version += 1

    def _continue_as_new(self) -> None:
        case_id = self._case_id
        if case_id is None:
            raise _invalid_command("Workflow has not initialized")
        workflow.continue_as_new(
            CaseWorkflowInput(
                schema_version=CASE_COMMAND_SCHEMA_VERSION,
                case_id=case_id,
                run_generation=self._run_generation + 1,
                commands_in_run=0,
                continue_as_new_after=self._continue_as_new_after,
                last_transition=self._last_transition,
            )
        )


__all__ = [
    "ACTIVITY_NAME",
    "ACTIVITY_RETRY_POLICY",
    "ACTIVITY_SCHEDULE_TO_CLOSE",
    "ACTIVITY_START_TO_CLOSE",
    "COMMAND_ID_PREFIX",
    "DEFAULT_CONTINUE_AS_NEW_AFTER",
    "NON_RETRYABLE_ERROR_TYPES",
    "UPDATE_NAME",
    "WORKFLOW_ID_PREFIX",
    "WORKFLOW_NAME",
    "CaseWorkflow",
    "activity_id_for_command",
    "expiry_command_id",
    "update_id_for_command",
    "workflow_id_for_case",
]
