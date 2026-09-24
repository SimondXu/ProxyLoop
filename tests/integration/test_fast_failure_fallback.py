"""A typed Fast adapter failure becomes a FAILED trace plus the fallback (PR-9a)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from proxyloop_agent_core import (
    FAST_ADAPTER_FAILURE_CODES,
    CaseCoordinator,
    FastAdapterFailure,
    FastAdapterResult,
    ModelCallUsage,
    ModelIdentity,
    ObservationRefusal,
    RouteRequest,
    SafeObservation,
    ScriptedDialogueFastAdapter,
    ScriptedFastAdapter,
    fast_public_observation,
)
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    FAST_FALLBACK_TEXT,
    SCRIPTED_CASE_ID,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_contracts import (
    CaseContextSnapshot,
    EventActor,
    FastModelView,
    ModelResult,
    ModelTrace,
    RoutingOutcome,
)
from test_fast_dialogue_delivery import CREATE_CASE_REQUEST, SteppingClock

T0 = datetime(2035, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 8, 26, 12, 2, tzinfo=UTC)


class _FailingFast:
    """A Fast adapter whose every call raises one typed failure."""

    model_identity = ModelIdentity(
        provider="test",
        model="failing_fast",
        model_version="v1",
        adapter_version="v1",
        prompt_version="v1",
    )

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.calls = 0

    def decide(self, view: FastModelView) -> FastAdapterResult:
        self.calls += 1
        raise self.failure


class _ObservingFast:
    """Records the observation it is given and answers like scripted Fast."""

    def __init__(self) -> None:
        self.calls: list[tuple[FastModelView, SafeObservation]] = []
        self.plain_calls = 0

    def decide(self, view: FastModelView) -> FastAdapterResult:
        self.plain_calls += 1
        return ScriptedFastAdapter().decide(view)

    def decide_observed(
        self, view: FastModelView, observation: SafeObservation
    ) -> tuple[FastAdapterResult, ModelCallUsage]:
        self.calls.append((view, observation))
        return ScriptedFastAdapter().decide(view), ModelCallUsage(3, 4, 5)


def _client(runtime: ThinAgentRuntime) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
    )


def _post_turn(runtime: ThinAgentRuntime) -> tuple[int, dict[str, Any]]:
    async def scenario() -> tuple[int, dict[str, Any]]:
        async with _client(runtime) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            assert created.status_code == 201
            turn = await client.post(
                f"/cases/{SCRIPTED_CASE_ID}/events",
                json={
                    "content": "Please review the current offer.",
                    "expected_revision": created.json()["revision"],
                },
            )
            return turn.status_code, turn.json()

    return asyncio.run(scenario())


def _fast_traces(repository: InMemoryCaseRepository) -> list[ModelTrace]:
    return [
        trace
        for trace in repository.list_model_traces(SCRIPTED_CASE_ID)
        if trace.role == "fast"
    ]


def test_fast_adapter_failure_delivers_fallback_with_failed_trace() -> None:
    # F1: on main the failure escaped the command with no trace (PR-7's gap).
    repository = InMemoryCaseRepository()
    fast = _FailingFast(FastAdapterFailure("fast_adapter_timeout"))
    runtime = ThinAgentRuntime(repository, clock=SteppingClock(), fast=fast)

    status, body = _post_turn(runtime)

    assert status == 200
    assert "fast" not in body
    assert body["approval"]["decision"] == "pending"
    line = body["snapshot"]["visible_events"][-1]
    assert (line["actor"], line["event_type"], line["content"]) == (
        "system",
        "assistant_message",
        FAST_FALLBACK_TEXT,
    )
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.FAILED
    assert trace.reason_codes == ("fast_adapter_timeout",)
    assert trace.output_ref is None
    assert trace.output_schema_version == "none"
    assert (trace.input_tokens, trace.output_tokens) == (0, 0)
    assert trace.model == "failing_fast"
    assert ModelTrace.model_validate_json(trace.model_dump_json()) == trace
    assert fast.calls == 1


@pytest.mark.parametrize("code", sorted(FAST_ADAPTER_FAILURE_CODES))
def test_every_allow_listed_failure_applies_the_command(code: str) -> None:
    # AC2 at the Runtime, with a detail code and reported usage.
    repository = InMemoryCaseRepository()
    failure = FastAdapterFailure(
        code,
        detail_code="invalid_json",
        usage=ModelCallUsage(input_tokens=11, output_tokens=7, latency_ms=999),
    )
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_FailingFast(failure)
    )
    runtime.create_case(occurred_at=T0)

    result = runtime.append_event(SCRIPTED_CASE_ID, content="Please review.")

    assert result.fast_decision is None
    assert result.approval is not None
    line = result.snapshot.visible_events[-1]
    assert (line.actor, line.content) == (EventActor.SYSTEM, FAST_FALLBACK_TEXT)
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.FAILED
    assert trace.reason_codes == (code, "invalid_json")
    assert (trace.input_tokens, trace.output_tokens) == (11, 7)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.last_fast_decision is None


def test_an_unexpected_exception_still_propagates() -> None:
    # AC2, L6: only the typed failure is captured; nothing else is masked.
    error = RuntimeError("a bug, not a transport failure")
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_FailingFast(error)
    )
    runtime.create_case(occurred_at=T0)
    before = repository.get(SCRIPTED_CASE_ID)

    with pytest.raises(RuntimeError) as raised:
        runtime.append_event(SCRIPTED_CASE_ID, content="Please review.")

    assert raised.value is error
    assert repository.get(SCRIPTED_CASE_ID) is before
    assert _fast_traces(repository) == []


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        (("fast_adapter_exploded",), {}),
        (("fast_adapter_timeout",), {"detail_code": "free text detail"}),
        (("fast_adapter_timeout",), {"usage": object()}),
    ],
)
def test_failure_codes_outside_the_allow_lists_are_refused(
    args: tuple[str, ...], kwargs: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        FastAdapterFailure(*args, **kwargs)


def _snapshot() -> CaseContextSnapshot:
    repository = InMemoryCaseRepository()
    ThinAgentRuntime(repository, clock=lambda: LATER).create_case(
        occurred_at=LATER - timedelta(minutes=2)
    )
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state.snapshot


def _advance(
    fast: Any, *, capture: bool, snapshot: CaseContextSnapshot | None = None
) -> Any:
    snapshot = snapshot if snapshot is not None else _snapshot()
    outcome = CaseCoordinator(snapshot=snapshot, capture_fast_failures=capture).advance(
        RouteRequest(snapshot=snapshot, created_at=LATER), fast=fast
    )
    assert outcome.route.outcome is RoutingOutcome.FAST_NOW
    return outcome


def test_without_capture_a_typed_failure_propagates_as_on_main() -> None:
    # A15: the ML path (no gate, no capture) is unchanged.
    failure = FastAdapterFailure("fast_adapter_unavailable")
    fast = _FailingFast(failure)
    with pytest.raises(FastAdapterFailure) as raised:
        CaseCoordinator(snapshot=_snapshot()).advance(
            RouteRequest(snapshot=_snapshot(), created_at=LATER), fast=fast
        )
    assert raised.value is failure
    assert fast.calls == 1


def test_with_capture_the_outcome_reports_the_failure() -> None:
    outcome = _advance(
        _FailingFast(FastAdapterFailure("fast_adapter_busy")), capture=True
    )
    assert outcome.fast_failed is True
    assert outcome.fast_decision is None
    assert outcome.fast_disclosure_rejected is False
    (trace,) = outcome.traces
    assert (trace.role, trace.result, trace.reason_codes) == (
        "fast",
        ModelResult.FAILED,
        ("fast_adapter_busy",),
    )
    (audit,) = outcome.audits
    assert (audit.source, audit.accepted) == ("fast", False)


def test_the_observing_dispatch_uses_the_same_snapshot() -> None:
    # A16
    snapshot = _snapshot()
    fast = _ObservingFast()
    outcome = _advance(fast, capture=True, snapshot=snapshot)

    assert fast.plain_calls == 0
    ((view, observation),) = fast.calls
    assert observation == fast_public_observation(snapshot)
    assert view == CaseCoordinator.project_fast_view(snapshot)
    assert observation.case_id == str(view.case_id) == str(snapshot.case.case_id)
    assert observation.case_revision == view.pins.case_revision
    assert observation.constraint_set_revision == view.pins.constraint_set_revision
    (trace,) = outcome.traces
    assert trace.result is ModelResult.SUCCEEDED
    assert (trace.input_tokens, trace.output_tokens, trace.latency_ms) == (3, 4, 5)


def test_a_plain_adapter_never_gets_an_observation() -> None:
    # A16: dispatch is by protocol; the scripted default is untouched.
    outcome = _advance(ScriptedDialogueFastAdapter(), capture=True)
    (trace,) = outcome.traces
    assert trace.result is ModelResult.SUCCEEDED
    assert trace.model == "scripted_dialogue_fast"


def test_a_renderer_refusal_fails_without_calling_the_adapter() -> None:
    # A17: a snapshot with no offer cannot be rendered for the local model.
    snapshot = _snapshot()
    snapshot = snapshot.model_copy(update={"offers": ()})
    refusal = fast_public_observation(snapshot)
    assert isinstance(refusal, ObservationRefusal)
    assert refusal.reason_codes == ("fast_observation_offer_missing",)
    fast = _ObservingFast()

    outcome = _advance(fast, capture=True, snapshot=snapshot)

    assert fast.calls == [] and fast.plain_calls == 0
    assert outcome.fast_failed is True
    (trace,) = outcome.traces
    assert trace.result is ModelResult.FAILED
    assert trace.reason_codes == (
        "fast_input_unrenderable",
        "fast_observation_offer_missing",
    )
    with pytest.raises(FastAdapterFailure) as raised:
        _advance(fast, capture=False, snapshot=snapshot)
    assert raised.value.reason_code == "fast_input_unrenderable"


def test_the_runtime_captures_failures_at_the_single_coordinator_site() -> None:
    # A21: PR-7's guard (one ``.advance(``, no direct adapter call) holds.
    source = inspect.getsource(runtime_module)
    assert source.count(".advance(") == 1
    assert source.count("._coordinator(") == 1
    assert source.count("CaseCoordinator(") == 1
    assert source.count("capture_fast_failures=True") == 1
    assert source.count(".decide(") == 0
    assert source.count(".decide_observed(") == 0
