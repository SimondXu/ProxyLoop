"""Small FastAPI control-plane surface for the local thin runtime."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from proxyloop_contracts import Money
from proxyloop_openai_adapter import OpenAICompatibleAdapterError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .repository import CaseConflictError, CaseNotFoundError
from .runtime import ModelRuntimeError, RuntimeResult, ThinAgentRuntime


class EventCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    event_type: Literal["consumer_message"] = "consumer_message"
    expected_revision: int | None = Field(default=None, ge=1)


class ApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"] = "approved"
    expected_revision: int | None = Field(default=None, ge=1)
    expected_case_revision: int | None = Field(default=None, ge=1)
    expected_action_intent_revision: int | None = Field(default=None, ge=1)


class CreateCaseRequest(BaseModel):
    """API-local intake facts; the canonical Case remains Runtime-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)

    current_monthly_total: Money
    target_monthly_total: Money
    mobile_hotspot_required: Literal[True]
    device_financing_change_forbidden: Literal[True]

    @field_validator(
        "mobile_hotspot_required", "device_financing_change_forbidden", mode="before"
    )
    @classmethod
    def require_strict_true(cls, value: object) -> object:
        if type(value) is not bool or value is not True:
            raise ValueError("must be the boolean true")
        return value

    @model_validator(mode="after")
    def supports_fixed_offer(self) -> CreateCaseRequest:
        if self.current_monthly_total.currency != "USD":
            raise ValueError("current_monthly_total must use USD")
        if self.target_monthly_total.currency != "USD":
            raise ValueError("target_monthly_total must use USD")
        if self.current_monthly_total.amount_minor <= 7200:
            raise ValueError("current_monthly_total must be greater than 7200 cents")
        if self.target_monthly_total.amount_minor < 7200:
            raise ValueError("target_monthly_total must be at least 7200 cents")
        if (
            self.target_monthly_total.amount_minor
            >= self.current_monthly_total.amount_minor
        ):
            raise ValueError(
                "target_monthly_total must be less than current_monthly_total"
            )
        return self


def create_app(runtime: ThinAgentRuntime | None = None) -> FastAPI:
    service = runtime if runtime is not None else ThinAgentRuntime()
    api = FastAPI(title="ProxyLoop Thin Agent Runtime", version="0.0.0")

    @api.exception_handler(CaseNotFoundError)
    async def handle_not_found(_request: Any, exc: CaseNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @api.exception_handler(CaseConflictError)
    async def handle_conflict(_request: Any, exc: CaseConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @api.exception_handler(OpenAICompatibleAdapterError)
    async def handle_model_error(
        _request: Any, exc: OpenAICompatibleAdapterError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": f"model_{exc.kind.value}",
                    "message": "model operation failed safely",
                }
            },
        )

    @api.exception_handler(ModelRuntimeError)
    async def handle_model_runtime_error(
        _request: Any, exc: ModelRuntimeError
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "model_result_rejected",
                    "message": "model proposal was rejected safely",
                }
            },
        )

    @api.post("/cases", status_code=201)
    def create_case(command: CreateCaseRequest) -> dict[str, Any]:
        return _result_payload(
            service.create_case(
                current_monthly_total=command.current_monthly_total,
                target_monthly_total=command.target_monthly_total,
                mobile_hotspot_required=command.mobile_hotspot_required,
                device_financing_change_forbidden=command.device_financing_change_forbidden,
            )
        )

    @api.get("/cases/{case_id}")
    def get_case(case_id: UUID) -> dict[str, Any]:
        state = service.repository.get(case_id)
        if state is None:
            raise CaseNotFoundError("case not found")
        return _result_payload(
            RuntimeResult(
                snapshot=state.snapshot,
                route="terminal"
                if state.snapshot.completion_decision is not None
                else "current",
                approval=next(
                    iter(state.snapshot.approval_requests),
                    None,
                ),
                evidence=tuple(
                    evidence
                    for evidence in state.snapshot.evidence
                    if evidence.source_type.value
                    in {"simulator_transition", "confirmation"}
                ),
                execution_count=state.execution_count,
            )
        )

    @api.post("/cases/{case_id}/events")
    def append_event(
        command: EventCommand,
        case_id: UUID,
    ) -> dict[str, Any]:
        result = service.append_event(
            case_id,
            content=command.content,
            event_type=command.event_type,
            expected_revision=command.expected_revision,
        )
        return _result_payload(result)

    @api.post("/cases/{case_id}/approvals/{approval_id}")
    def decide_approval(
        command: ApprovalCommand,
        case_id: UUID,
        approval_id: UUID,
    ) -> dict[str, Any]:
        result = service.approve(
            case_id,
            approval_id,
            decision=command.decision,
            expected_revision=command.expected_revision,
            expected_case_revision=command.expected_case_revision,
            expected_action_intent_revision=command.expected_action_intent_revision,
        )
        return _result_payload(result)

    return api


def _result_payload(result: RuntimeResult) -> dict[str, Any]:
    snapshot = result.snapshot
    completion = snapshot.completion_decision
    completion_payload: dict[str, Any] = (
        completion.model_dump(mode="json")
        if completion is not None
        else {
            "decision": "not_done",
            "evidence_ids": [],
            "missing_evidence": ["verified_provider_confirmation"],
            "reason_codes": ["approval_or_execution_pending"],
        }
    )
    route = (
        result.route.outcome.value
        if hasattr(result.route, "outcome")
        else str(result.route)
    )
    approval = result.approval
    if approval is None:
        approval = next(iter(snapshot.approval_requests), None)
    evidence = result.evidence or tuple(
        item
        for item in snapshot.evidence
        if item.source_type.value in {"simulator_transition", "confirmation"}
    )
    payload: dict[str, Any] = {
        "case_id": str(snapshot.case.case_id),
        "case": snapshot.case.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
        "revision": snapshot.revision,
        "event_cursor": snapshot.event_cursor,
        "route": route,
        "approval": approval.model_dump(mode="json") if approval else None,
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "completion": completion_payload,
        "execution_count": result.execution_count,
    }
    if result.fast_decision is not None:
        payload["fast"] = result.fast_decision.model_dump(mode="json")
    return payload


app = create_app()


__all__ = [
    "ApprovalCommand",
    "CreateCaseRequest",
    "EventCommand",
    "app",
    "create_app",
]
