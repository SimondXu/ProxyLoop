"""Small FastAPI control-plane surface for the local thin runtime."""

from __future__ import annotations

from contextlib import suppress
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommandType,
    CaseConflictError,
    CaseNotFoundError,
    CaseTransitionRef,
    ModelRuntimeError,
    RuntimeResult,
    StorageUnavailableError,
    ThinAgentRuntime,
)
from proxyloop_contracts import Money
from proxyloop_openai_adapter import OpenAICompatibleAdapterError
from proxyloop_workflow_worker import (
    CaseCommandRequest,
    TemporalDispatchError,
    TemporalReadinessResult,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .operations import (
    CORRELATION_ID_HEADER,
    JsonLoggingOperationRecorder,
    OperationRecord,
    OperationRecorder,
)
from .readiness import check_readiness, liveness_payload, readiness_payload


class TemporalCommandClient(Protocol):
    async def apply_command(self, command: CaseCommandRequest) -> CaseTransitionRef: ...

    async def check_readiness(self) -> TemporalReadinessResult: ...


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


def create_app(
    runtime: ThinAgentRuntime | None = None,
    *,
    recorder: OperationRecorder | None = None,
    temporal_client: TemporalCommandClient | None = None,
) -> FastAPI:
    service = runtime if runtime is not None else ThinAgentRuntime()
    operation_recorder = (
        recorder if recorder is not None else JsonLoggingOperationRecorder()
    )
    api = FastAPI(title="ProxyLoop Thin Agent Runtime", version="0.0.0")

    @api.middleware("http")
    async def observe_operation(request: Request, call_next: Any) -> Any:
        request.state.correlation_id = str(uuid4())
        started = perf_counter()
        response: Any = None
        try:
            response = await call_next(request)
        except Exception:
            request.state.operation_error_category = "internal_error"
            response = _internal_error_response()
        finally:
            if response is not None:
                response.headers[CORRELATION_ID_HEADER] = request.state.correlation_id
            _record_operation_safely(
                request,
                service,
                operation_recorder,
                status=response.status_code if response is not None else 500,
                latency_ms=(perf_counter() - started) * 1000,
            )
        return response

    @api.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> Response:
        request.state.operation_error_category = "request_invalid"
        return await request_validation_exception_handler(request, exc)

    @api.exception_handler(CaseNotFoundError)
    async def handle_not_found(
        request: Request, exc: CaseNotFoundError
    ) -> JSONResponse:
        request.state.operation_error_category = "case_not_found"
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @api.exception_handler(CaseConflictError)
    async def handle_conflict(request: Request, exc: CaseConflictError) -> JSONResponse:
        request.state.operation_error_category = _conflict_category(exc)
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @api.exception_handler(StorageUnavailableError)
    async def handle_storage_unavailable(
        request: Request, _exc: StorageUnavailableError
    ) -> JSONResponse:
        request.state.operation_error_category = "storage_unavailable"
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "storage_unavailable",
                    "message": "storage dependency unavailable",
                }
            },
        )

    @api.exception_handler(OpenAICompatibleAdapterError)
    async def handle_model_error(
        request: Request, exc: OpenAICompatibleAdapterError
    ) -> JSONResponse:
        request.state.operation_error_category = f"model_{exc.kind.value}"
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
        request: Request, exc: ModelRuntimeError
    ) -> JSONResponse:
        del exc
        request.state.operation_error_category = "model_result_rejected"
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "model_result_rejected",
                    "message": "model proposal was rejected safely",
                }
            },
        )

    @api.exception_handler(TemporalDispatchError)
    async def handle_temporal_error(
        request: Request, exc: TemporalDispatchError
    ) -> JSONResponse:
        category = exc.category
        request.state.operation_error_category = category
        if category == "case_not_found":
            return JSONResponse(status_code=404, content={"detail": "case not found"})
        if category in {"case_conflict", "approval_expired"}:
            return JSONResponse(status_code=409, content={"detail": category})
        if category == "invalid_command":
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": category, "message": "command rejected"}},
            )
        if category == "state_invalid":
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": category,
                        "message": "stored Case state failed validation",
                    }
                },
            )
        if category == "model_path":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": {
                        "code": category,
                        "message": "model execution is unavailable in Temporal mode",
                    }
                },
            )
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "temporal_unavailable",
                    "message": "orchestration dependency unavailable",
                }
            },
        )

    @api.get("/health/live")
    def health_live(request: Request) -> dict[str, object]:
        request.state.operation_name = "health_live"
        payload = liveness_payload(service)
        if temporal_client is not None:
            payload["orchestration_mode"] = "temporal"
        return payload

    @api.get("/health/ready")
    async def health_ready(request: Request) -> JSONResponse:
        request.state.operation_name = "health_ready"
        result = check_readiness(service)
        if not result.ready:
            request.state.operation_error_category = result.error_category
            return JSONResponse(
                status_code=503,
                content=readiness_payload(service, result),
            )
        payload = readiness_payload(service, result)
        if temporal_client is None:
            return JSONResponse(status_code=200, content=payload)
        temporal_result = await temporal_client.check_readiness()
        payload["orchestration_mode"] = "temporal"
        payload["dependency"] = temporal_result.dependency
        if not temporal_result.ready:
            request.state.operation_error_category = temporal_result.error_category
            payload.update(
                {
                    "status": "unavailable",
                    "ready": False,
                    "detail": {
                        "code": "dependency_not_ready",
                        "message": "configured dependency is not ready",
                    },
                }
            )
            return JSONResponse(status_code=503, content=payload)
        return JSONResponse(status_code=200, content=payload)

    @api.post("/cases", status_code=201)
    async def create_case(
        request: Request, command: CreateCaseRequest
    ) -> dict[str, Any]:
        if temporal_client is None:
            result = service.create_case(
                current_monthly_total=command.current_monthly_total,
                target_monthly_total=command.target_monthly_total,
                mobile_hotspot_required=command.mobile_hotspot_required,
                device_financing_change_forbidden=(
                    command.device_financing_change_forbidden
                ),
            )
        else:
            transition = await temporal_client.apply_command(
                CaseCommandRequest(
                    command_id=_command_id(request),
                    case_id=SCRIPTED_CASE_ID,
                    command_type=CaseCommandType.CREATE_CASE,
                    current_monthly_total=command.current_monthly_total,
                    target_monthly_total=command.target_monthly_total,
                    mobile_hotspot_required=command.mobile_hotspot_required,
                    device_financing_change_forbidden=(
                        command.device_financing_change_forbidden
                    ),
                )
            )
            result = service.current_result(SCRIPTED_CASE_ID, transition=transition)
        _annotate_result(request, result)
        return _result_payload(result)

    @api.get("/cases/{case_id}")
    def get_case(request: Request, case_id: UUID) -> dict[str, Any]:
        state = service.repository.get(case_id)
        if state is None:
            raise CaseNotFoundError("case not found")
        result = RuntimeResult(
            snapshot=state.snapshot,
            route="terminal"
            if state.snapshot.completion_decision is not None
            else "current",
            approval=next(iter(state.snapshot.approval_requests), None),
            evidence=tuple(
                evidence
                for evidence in state.snapshot.evidence
                if evidence.source_type.value
                in {"simulator_transition", "confirmation"}
            ),
            execution_count=state.execution_count,
        )
        _annotate_result(request, result)
        return _result_payload(result)

    @api.post("/cases/{case_id}/events")
    async def append_event(
        request: Request,
        command: EventCommand,
        case_id: UUID,
    ) -> dict[str, Any]:
        if temporal_client is None:
            result = service.append_event(
                case_id,
                content=command.content,
                event_type=command.event_type,
                expected_revision=command.expected_revision,
            )
        else:
            transition = await temporal_client.apply_command(
                CaseCommandRequest(
                    command_id=_command_id(request),
                    case_id=case_id,
                    command_type=CaseCommandType.APPEND_EVENT,
                    content=command.content,
                    event_type=command.event_type,
                    expected_revision=command.expected_revision,
                )
            )
            result = service.current_result(case_id, transition=transition)
        _annotate_result(request, result)
        return _result_payload(result)

    @api.post("/cases/{case_id}/approvals/{approval_id}")
    async def decide_approval(
        request: Request,
        command: ApprovalCommand,
        case_id: UUID,
        approval_id: UUID,
    ) -> dict[str, Any]:
        if temporal_client is None:
            result = service.approve(
                case_id,
                approval_id,
                decision=command.decision,
                expected_revision=command.expected_revision,
                expected_case_revision=command.expected_case_revision,
                expected_action_intent_revision=(
                    command.expected_action_intent_revision
                ),
            )
        else:
            transition = await temporal_client.apply_command(
                CaseCommandRequest(
                    command_id=_command_id(request),
                    case_id=case_id,
                    command_type=CaseCommandType.DECIDE_APPROVAL,
                    approval_id=approval_id,
                    decision=command.decision,
                    expected_revision=command.expected_revision,
                    expected_case_revision=command.expected_case_revision,
                    expected_action_intent_revision=(
                        command.expected_action_intent_revision
                    ),
                )
            )
            result = service.current_result(case_id, transition=transition)
        _annotate_result(request, result)
        return _result_payload(result)

    api.state.operation_recorder = operation_recorder
    api.state.orchestration_mode = (
        "temporal" if temporal_client is not None else "direct"
    )
    return api


def _command_id(request: Request) -> UUID:
    value = request.headers.get("Idempotency-Key")
    if value is None:
        return uuid4()
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise TemporalDispatchError("invalid_command") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise TemporalDispatchError("invalid_command")
    return parsed


def _annotate_result(request: Request, result: RuntimeResult) -> None:
    snapshot = result.snapshot
    request.state.case_id = str(snapshot.case.case_id)
    request.state.revision = snapshot.revision
    request.state.deterministic_route = _route_value(result.route)
    request.state.policy_outcome = _policy_outcome(snapshot)
    request.state.approval_outcome = _approval_outcome(snapshot)
    request.state.execution_outcome = (
        "pending"
        if snapshot.pending_execution
        else "completed"
        if result.execution_count > 0
        else "none"
    )
    request.state.verifier_outcome = (
        snapshot.completion_decision.decision.value
        if snapshot.completion_decision is not None
        else "not_done"
    )


def _operation_record(
    request: Request,
    runtime: ThinAgentRuntime,
    *,
    status: int,
    latency_ms: float,
) -> OperationRecord:
    route = request.scope.get("route")
    route_template = getattr(route, "path", None)
    if not isinstance(route_template, str):
        route_template = "<unmatched>"
    operation = getattr(request.state, "operation_name", None) or (
        getattr(route, "name", None) if route_template != "<unmatched>" else None
    )
    if operation is None:
        operation = "<unmatched>"
    path_case_id = (
        request.path_params.get("case_id") if route_template != "<unmatched>" else None
    )
    case_id = getattr(request.state, "case_id", None) or (
        str(path_case_id) if path_case_id is not None else None
    )
    return OperationRecord(
        correlation_id=request.state.correlation_id,
        operation=str(operation),
        route=str(route_template),
        case_id=_safe_case_id(case_id),
        revision=getattr(request.state, "revision", None),
        deterministic_route=getattr(request.state, "deterministic_route", None),
        adapter_mode=runtime.adapter_mode,
        storage_mode=runtime.storage_mode,
        policy_outcome=getattr(request.state, "policy_outcome", None),
        approval_outcome=getattr(request.state, "approval_outcome", None),
        execution_outcome=getattr(request.state, "execution_outcome", None),
        verifier_outcome=getattr(request.state, "verifier_outcome", None),
        error_category=getattr(request.state, "operation_error_category", "none"),
        status=status,
        latency_ms=max(0.0, latency_ms),
    )


def _record_operation_safely(
    request: Request,
    runtime: ThinAgentRuntime,
    recorder: OperationRecorder,
    *,
    status: int,
    latency_ms: float,
) -> None:
    record = _operation_record(
        request,
        runtime,
        status=status,
        latency_ms=latency_ms,
    )
    try:
        recorder.record(record)
    except Exception:
        with suppress(Exception):
            JsonLoggingOperationRecorder().record(record)


def _internal_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "internal operation failed safely",
            }
        },
    )


def _safe_case_id(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _route_value(route: object) -> str:
    outcome = getattr(route, "outcome", None)
    return str(getattr(outcome, "value", route))


def _approval_outcome(snapshot: Any) -> str:
    if not snapshot.approval_requests:
        return "none"
    return str(snapshot.approval_requests[0].decision.value)


def _policy_outcome(snapshot: Any) -> str:
    if snapshot.approval_requests:
        decision = snapshot.approval_requests[0].decision.value
        if decision == "pending":
            return "approval_required"
        if decision == "approved":
            return "allowed"
        return "rejected"
    if snapshot.action_intents:
        return "allowed"
    return "none"


def _conflict_category(exc: CaseConflictError) -> str:
    return "stale_cas" if "stale" in str(exc) else "case_conflict"


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
