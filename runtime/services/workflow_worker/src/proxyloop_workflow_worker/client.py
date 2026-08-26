"""Client adapter for CaseWorkflow Update and Update-with-Start calls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from proxyloop_case_runtime.commands import (
    CaseCommand,
    CaseCommandType,
    CaseTransitionRef,
)
from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter

from .config import TemporalSettings, temporal_settings_from_environment
from .models import CaseCommandRequest, CaseWorkflowInput
from .readiness import TemporalReadinessResult, check_temporal_readiness
from .workflow import (
    UPDATE_NAME,
    CaseWorkflow,
    update_id_for_command,
    workflow_id_for_case,
)


class TemporalDispatchError(RuntimeError):
    """Stable redacted transport/domain failure returned to API adapters."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class TemporalCaseClient:
    """Small transport adapter used by the API's explicit Temporal mode."""

    def __init__(self, client: Client, settings: TemporalSettings) -> None:
        self.client = client
        self.settings = settings

    @classmethod
    async def connect(
        cls,
        settings: TemporalSettings | None = None,
    ) -> TemporalCaseClient:
        selected = settings or temporal_settings_from_environment()
        client = await Client.connect(
            selected.target_host,
            namespace=selected.namespace,
            data_converter=pydantic_data_converter,
        )
        return cls(client, selected)

    @staticmethod
    def workflow_id(case_id: UUID) -> str:
        return workflow_id_for_case(case_id)

    async def apply_command(
        self,
        command: CaseCommand | CaseCommandRequest,
    ) -> CaseTransitionRef:
        """Apply a command, using Update-with-Start only for creation."""

        request = _command_request(command)
        workflow_id = workflow_id_for_case(request.case_id)
        update_id = update_id_for_command(request.command_id)
        try:
            if request.command_type is CaseCommandType.CREATE_CASE:
                # A fresh operation is required for every Update-with-Start call.
                start_operation = WithStartWorkflowOperation(
                    CaseWorkflow.run,
                    CaseWorkflowInput(
                        case_id=request.case_id,
                        continue_as_new_after=self.settings.continue_as_new_after,
                    ),
                    id=workflow_id,
                    task_queue=self.settings.task_queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
                result = await self.client.execute_update_with_start_workflow(
                    UPDATE_NAME,
                    request,
                    id=update_id,
                    result_type=CaseTransitionRef,
                    start_workflow_operation=start_operation,
                )
            else:
                handle = self.client.get_workflow_handle(workflow_id)
                result = await handle.execute_update(
                    UPDATE_NAME,
                    request,
                    id=update_id,
                    result_type=CaseTransitionRef,
                )
            return _transition(result)
        except TemporalDispatchError:
            raise
        except Exception as exc:
            raise TemporalDispatchError(_failure_category(exc)) from exc

    async def check_readiness(self) -> TemporalReadinessResult:
        return await check_temporal_readiness(self.client)


def _command_request(
    command: CaseCommand | CaseCommandRequest,
) -> CaseCommandRequest:
    if isinstance(command, CaseCommandRequest):
        return command
    if isinstance(command, CaseCommand):
        return CaseCommandRequest.from_command(command)
    raise TypeError("command must be a CaseCommand or CaseCommandRequest")


def _transition(value: Any) -> CaseTransitionRef:
    if isinstance(value, CaseTransitionRef):
        return value
    try:
        return CaseTransitionRef.model_validate(value)
    except Exception as exc:
        raise TemporalDispatchError("state_invalid") from exc


def _failure_category(exc: BaseException) -> str:
    """Extract only an allowlisted Temporal ApplicationError category."""

    allowed = {
        "invalid_command",
        "case_not_found",
        "case_conflict",
        "approval_expired",
        "state_invalid",
        "model_path",
    }
    current: BaseException | None = exc
    while current is not None:
        error_type = getattr(current, "type", None)
        if isinstance(error_type, str) and error_type in allowed:
            return error_type
        current = current.__cause__ or current.__context__
    return "temporal_unavailable"


__all__ = ["TemporalCaseClient", "TemporalDispatchError"]
