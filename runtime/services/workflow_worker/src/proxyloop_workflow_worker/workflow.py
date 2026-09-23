"""Deterministic Temporal ordering for one fictional ProxyLoop Case."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from uuid import UUID

from proxyloop_case_runtime.commands import (
    CASE_COMMAND_SCHEMA_VERSION,
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
)
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.exceptions import TimeoutError as ActivityTimeoutError

from .models import CaseCommandRequest, CaseWorkflowInput, ChannelDeliveryRequest

WORKFLOW_NAME = "CaseWorkflow"
WORKFLOW_ID_PREFIX = "proxyloop-case/"
UPDATE_NAME = "apply_case_command"
ACTIVITY_NAME = "apply_case_command_activity"
CHANNEL_DELIVERY_ACTIVITY_NAME = "dispatch_channel_delivery_activity"
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
EXPIRY_RETRY_INITIAL_BACKOFF = timedelta(seconds=15)
EXPIRY_RETRY_MAXIMUM_BACKOFF = timedelta(minutes=5)


def workflow_id_for_case(case_id: UUID) -> str:
    """Return the stable Workflow ID for a Case UUID."""

    return f"{WORKFLOW_ID_PREFIX}{str(case_id).lower()}"


def update_id_for_command(command_id: UUID, request_fingerprint: str) -> str:
    """Return the Temporal Update ID for one command id and request body.

    Temporal caches an Update outcome per Update ID within a run, so the ID
    binds the semantic request fingerprint too: an identical retry reuses the
    cached outcome, while a corrected body under the same command id reaches
    the Runtime, whose receipt fingerprint rules decide.
    """

    return (
        f"{COMMAND_ID_PREFIX}{str(command_id).lower()}:"
        f"{request_fingerprint[:16].lower()}"
    )


def activity_id_for_command(command_id: UUID) -> str:
    """Return the stable Temporal Activity ID for a command UUID.

    Activities run one at a time under the Workflow command lock, and Temporal
    only rejects an Activity ID that is still pending, so sequential attempts
    for one command id (a corrected retry) may share it.
    """

    return f"{COMMAND_ID_PREFIX}{str(command_id).lower()}"


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


def _expiry_failure_category(error: BaseException) -> tuple[str, bool]:
    """Name the innermost activity failure without exposing exception text.

    Returns the category and whether the failure is non-retryable: either the
    category is in the activity retry policy's non-retryable list or the
    innermost ``ApplicationError`` was raised with ``non_retryable=True``.
    """

    category: str | None = None
    flagged_non_retryable = False
    timed_out = False
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ApplicationError) and current.type:
            category = current.type
            flagged_non_retryable = current.non_retryable
        elif isinstance(current, ActivityTimeoutError):
            timed_out = True
        current = current.__cause__
    if category is None:
        return ("activity_timeout" if timed_out else "activity_failed"), False
    non_retryable = flagged_non_retryable or category in (
        NON_RETRYABLE_ERROR_TYPES or ()
    )
    return category, non_retryable


def _expiry_retry_backoff(failures: int) -> timedelta:
    # Cap the exponent before multiplying so a long outage cannot overflow.
    doublings = min(max(failures - 1, 0), 5)
    return min(
        EXPIRY_RETRY_INITIAL_BACKOFF * (1 << doublings),
        EXPIRY_RETRY_MAXIMUM_BACKOFF,
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
        self._expiry_failures = 0
        self._expiry_retry_at: datetime | None = None
        self._expiry_abandoned_for: tuple[UUID, datetime] | None = None

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
                and self._expiry_abandoned_for
                != (pending.approval_id, pending.approval_expires_at)
            ):
                remaining = pending.approval_expires_at - workflow.now()
                timeout_summary = "case approval expiry"
                if remaining <= timedelta(0):
                    retry_at = self._expiry_retry_at
                    if retry_at is None or retry_at <= workflow.now():
                        await self._expire_pending()
                        continue
                    remaining = retry_at - workflow.now()
                    timeout_summary = "case approval expiry retry"
                try:

                    def wake_changed(observed_version: int = observed) -> bool:
                        return (
                            self._wake_version != observed_version
                            or self._continue_requested
                        )

                    await workflow.wait_condition(
                        wake_changed,
                        timeout=remaining,
                        timeout_summary=timeout_summary,
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
                if not self._adopt_transition(transition):
                    workflow.logger.debug(
                        "update receipt not adopted: revision %d",
                        transition.after_revision,
                    )
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
        if (
            command.command_type is CaseCommandType.INGEST_CHANNEL_EVENT
            and transition.delivery_id is not None
        ):
            await workflow.execute_activity(
                CHANNEL_DELIVERY_ACTIVITY_NAME,
                ChannelDeliveryRequest(
                    case_id=command.case_id,
                    delivery_id=transition.delivery_id,
                    idempotency_key=str(transition.delivery_id),
                ),
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE,
                schedule_to_close_timeout=ACTIVITY_SCHEDULE_TO_CLOSE,
                retry_policy=ACTIVITY_RETRY_POLICY,
                activity_id=f"channel-delivery/{transition.delivery_id}",
            )
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
            try:
                transition = await self._execute_command(expiry_command)
                if transition.case_id != case_id:
                    raise ApplicationError(
                        "invalid activity result",
                        type="state_invalid",
                        non_retryable=True,
                    )
            except (ActivityError, ApplicationError) as error:
                # The expiry timer must never fail the run: a failed run cannot
                # be recreated under REJECT_DUPLICATE, so later Updates would
                # be lost for the whole Case.
                category, non_retryable = _expiry_failure_category(error)
                if non_retryable:
                    # The aggregate moved without this Workflow; the next
                    # Update carries the truth, so do not re-arm this timer.
                    self._expiry_abandoned_for = (
                        current.approval_id,
                        current.approval_expires_at,
                    )
                    workflow.logger.warning("approval expiry abandoned: %s", category)
                    return
                self._expiry_failures += 1
                self._expiry_retry_at = workflow.now() + _expiry_retry_backoff(
                    self._expiry_failures
                )
                workflow.logger.warning(
                    "approval expiry attempt %d failed: %s",
                    self._expiry_failures,
                    category,
                )
                return
            if not self._adopt_transition(transition):
                workflow.logger.debug(
                    "expiry receipt not adopted: revision %d",
                    transition.after_revision,
                )
            self._commands_in_run += 1
            self._continue_requested = (
                self._commands_in_run >= self._continue_as_new_after
            )
            self._wake_version += 1

    def _adopt_transition(self, transition: CaseTransitionRef) -> bool:
        """Replace the last transition only when the receipt is newer.

        Revision order alone decides. A replayed older command returns its
        stored receipt, and adopting it would roll the Workflow back and
        disarm a pending approval's expiry timer. ``deduplicated`` is not a
        rejection criterion: an activity retry after a committed but
        unreported first attempt also returns a ``deduplicated`` receipt,
        and that one is strictly newer and must be adopted.
        """

        current = self._last_transition
        if current is not None and transition.after_revision <= current.after_revision:
            return False
        self._last_transition = transition
        self._reset_expiry_backoff()
        return True

    def _reset_expiry_backoff(self) -> None:
        self._expiry_failures = 0
        self._expiry_retry_at = None
        self._expiry_abandoned_for = None

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
    "CHANNEL_DELIVERY_ACTIVITY_NAME",
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
