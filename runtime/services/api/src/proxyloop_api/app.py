"""Small FastAPI control-plane surface for the local thin runtime."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from proxyloop_case_runtime import (
    CHANNEL_COMMAND_SCHEMA_VERSION,
    SCRIPTED_CASE_ID,
    CaseCommandType,
    CaseConflictError,
    CaseNotFoundError,
    CaseTransitionRef,
    ChannelConflictError,
    ChannelDependencyUnavailableError,
    ModelRuntimeError,
    RuntimeResult,
    StorageUnavailableError,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    SCHEMA_VERSION,
    LocalMailboxEventKind,
    LocalMailboxVerificationError,
    verify_local_mailbox_event,
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

    @api.exception_handler(ChannelDependencyUnavailableError)
    async def handle_channel_dependency_unavailable(
        request: Request, _exc: ChannelDependencyUnavailableError
    ) -> JSONResponse:
        request.state.operation_error_category = "channel_dependency_unavailable"
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "channel_dependency_unavailable",
                    "message": "channel dependency unavailable",
                }
            },
        )

    @api.exception_handler(ChannelConflictError)
    async def handle_channel_conflict(
        request: Request, exc: ChannelConflictError
    ) -> JSONResponse:
        category = _channel_conflict_category(exc)
        request.state.operation_error_category = category
        status = 422 if category in {"stale_unknown_event", "unknown_binding"} else 409
        return JSONResponse(
            status_code=status,
            content={
                "detail": {
                    "code": category,
                    "message": _channel_failure_message(category),
                }
            },
        )

    @api.exception_handler(LocalMailboxVerificationError)
    async def handle_channel_verification(
        request: Request, exc: LocalMailboxVerificationError
    ) -> JSONResponse:
        category = exc.category
        if category not in {
            "invalid_fixture_authenticity",
            "stale_unknown_event",
            "malformed_channel_event",
            "unknown_binding",
        }:
            category = "invalid_fixture_authenticity"
        request.state.operation_error_category = category
        status = 401 if category == "invalid_fixture_authenticity" else 422
        return JSONResponse(
            status_code=status,
            content={"detail": {"code": category, "message": "channel event rejected"}},
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
        if category in {
            "channel_replay_mismatch",
            "channel_conflict",
        }:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": {
                        "code": category,
                        "message": _channel_failure_message(category),
                    }
                },
            )
        if category in {"stale_unknown_event", "unknown_binding"}:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": category,
                        "message": _channel_failure_message(category),
                    }
                },
            )
        if category == "channel_dependency_unavailable":
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": category,
                        "message": "channel dependency unavailable",
                    }
                },
            )
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

    @api.post("/channels/local_mailbox/events")
    async def local_mailbox_event(request: Request) -> dict[str, Any]:
        """Accept only the synthetic raw-byte mailbox fixture."""

        request.state.operation_name = "local_mailbox_event"
        received_at = datetime.now(UTC)
        raw_bytes = await request.body()
        event = verify_local_mailbox_event(
            raw_bytes,
            request.headers,
            received_at,
            require_fresh=False,
        )
        request.state.channel_kind = "local_mailbox"
        request.state.channel_event_kind = event.kind.value
        if temporal_client is None:
            raise ChannelDependencyUnavailableError(
                "local mailbox requires the explicit Temporal mode"
            )
        repository = getattr(service, "repository", None)
        reserve = getattr(repository, "reserve_channel_event", None)
        if not callable(reserve):
            raise ChannelDependencyUnavailableError(
                "local mailbox requires PostgreSQL channel persistence"
            )
        inbox = reserve(event, received_at=received_at)
        request.state.case_id = str(inbox.case_id)
        state = service.repository.get(inbox.case_id)
        if state is None:
            raise CaseNotFoundError("case not found")
        prior = next(
            (item for item in state.transitions if item.command_id == inbox.command_id),
            None,
        )
        if (
            inbox.deduplicated
            and inbox.processing_state == "applied"
            and prior is not None
        ):
            request.state.revision = prior.after_revision
            request.state.delivery_state = prior.delivery_status
            return _channel_result_payload(
                event, prior.model_copy(update={"deduplicated": True})
            )
        if event.kind is LocalMailboxEventKind.PROVIDER_MESSAGE:
            command_type = CaseCommandType.INGEST_CHANNEL_EVENT
        else:
            command_type = CaseCommandType.RECORD_CHANNEL_DELIVERY
        command_values: dict[str, Any] = {
            "schema_version": CHANNEL_COMMAND_SCHEMA_VERSION,
            "command_id": inbox.command_id,
            "case_id": inbox.case_id,
            "command_type": command_type,
            "expected_revision": state.snapshot.revision,
            "channel_occurred_at": event.occurred_at,
            "channel_kind": "local_mailbox",
            "binding_ref": event.binding_ref,
            "event_id": event.event_id,
        }
        if event.kind is LocalMailboxEventKind.PROVIDER_MESSAGE:
            if event.content is None:
                raise LocalMailboxVerificationError("malformed_channel_event")
            command_values.update(
                {
                    "content_hash": hashlib.sha256(
                        event.content.encode("utf-8")
                    ).hexdigest(),
                    "payload_hash": event.raw_payload_hash,
                }
            )
        else:
            if (
                event.delivery_id is None
                or event.provider_message_id is None
                or event.delivery_status is None
            ):
                raise LocalMailboxVerificationError("malformed_channel_event")
            command_values.update(
                {
                    "delivery_id": event.delivery_id,
                    "provider_message_id": event.provider_message_id,
                    "delivery_status": event.delivery_status,
                    "artifact_hash": event.raw_payload_hash,
                    "payload_hash": event.raw_payload_hash,
                }
            )
        transition = await temporal_client.apply_command(
            CaseCommandRequest(**command_values)
        )
        request.state.revision = transition.after_revision
        request.state.delivery_state = transition.delivery_status
        return _channel_result_payload(event, transition)

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
        channel_kind=getattr(request.state, "channel_kind", None),
        channel_event_kind=getattr(request.state, "channel_event_kind", None),
        delivery_state=getattr(request.state, "delivery_state", None),
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


def _channel_conflict_category(exc: BaseException) -> str:
    """Convert known channel details into a stable, redacted category."""

    value = str(exc).lower()
    if "channel_replay_mismatch" in value or "replay mismatch" in value:
        return "channel_replay_mismatch"
    if "stale_unknown_event" in value or "stale unknown event" in value:
        return "stale_unknown_event"
    if "unknown_binding" in value or "unknown binding" in value:
        return "unknown_binding"
    return "channel_conflict"


def _channel_failure_message(category: str) -> str:
    if category in {"stale_unknown_event", "unknown_binding"}:
        return "channel event rejected"
    if category == "channel_replay_mismatch":
        return "channel event replay rejected"
    return "channel conflict"


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
        "snapshot": _browser_snapshot_payload(snapshot),
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


def _browser_snapshot_payload(snapshot: Any) -> dict[str, Any]:
    """Project the canonical snapshot without exposing local-mailbox material."""

    payload = cast(dict[str, Any], snapshot.model_dump(mode="json"))
    payload["visible_events"] = [
        event
        for event in payload["visible_events"]
        if not _is_channel_visible_event(event)
    ]
    payload["evidence"] = [
        evidence
        for evidence in payload["evidence"]
        if not _is_channel_evidence(evidence)
    ]
    return payload


def _is_channel_visible_event(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return value.get("actor") == "provider" and value.get("event_type") in {
        "provider_message",
        "provider_event",
    }


def _is_channel_evidence(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    source_type = value.get("source_type")
    source_ref = value.get("source_ref")
    if source_type == "provider_message":
        return _is_uuid4_reference(source_ref)
    return source_type == "provider_event"


def _is_uuid4_reference(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _channel_result_payload(
    event: Any,
    transition: CaseTransitionRef,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(event.event_id),
        "command_id": str(transition.command_id),
        "case_id": str(transition.case_id),
        "revision": transition.after_revision,
        "event_cursor": transition.event_cursor,
        "deduplicated": transition.deduplicated,
        "delivery_id": str(transition.delivery_id)
        if transition.delivery_id is not None
        else None,
        "delivery_status": transition.delivery_status,
    }


app = create_app()


__all__ = [
    "ApprovalCommand",
    "CreateCaseRequest",
    "EventCommand",
    "app",
    "create_app",
]
