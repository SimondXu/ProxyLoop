"""Every adapter call on a 1.1 snapshot yields one 1.1 ModelTrace (P1 A-2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from proxyloop_agent_core import (
    CaseCoordinator,
    CoordinatorOutcome,
    CoordinatorStatus,
    FastAdapterResult,
    ModelCallUsage,
    RouteRequest,
    ScriptedFastAdapter,
    ScriptedSlowAdapter,
)
from proxyloop_api.app import _result_payload
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_contracts import (
    CaseContextSnapshot,
    DialogueAct,
    FastModelView,
    ModelResult,
    ModelTrace,
    RoutingOutcome,
    SlowWorkRequest,
    SlowWorkResult,
)
from proxyloop_contracts.contracts import CompletionClaim, ReasonerRequest
from proxyloop_openai_adapter import (
    FastModelOutput,
    OpenAICompatibleAdapter,
)
from proxyloop_openai_adapter.adapter import _token_count
from test_phase_04b_model_runtime import _slow_output
from test_strategy_basis_binding import _as_stored_1_0

T0 = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(minutes=2)


def _runtime() -> tuple[ThinAgentRuntime, CaseRuntimeState]:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: T0)
    runtime.create_case(occurred_at=T0)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return runtime, state


def _snapshot() -> CaseContextSnapshot:
    """A 1.1 snapshot with a current, bound strategy (Router: fast_now)."""

    _, state = _runtime()
    assert state.snapshot.schema_version == "1.1"
    assert state.snapshot.strategy is not None
    return state.snapshot


def _request(snapshot: CaseContextSnapshot, route: RoutingOutcome) -> RouteRequest:
    if route is RoutingOutcome.FAST_NOW:
        return RouteRequest(snapshot=snapshot, created_at=LATER)
    return RouteRequest(
        snapshot=snapshot,
        created_at=LATER,
        mandatory_slow_reason_codes=("provider_message",),
        bounded_acknowledgement_allowed=(
            route is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH
        ),
    )


class _Ticks:
    """An injected clock or monotonic source returning scripted values."""

    def __init__(self, *values: Any) -> None:
        self._values: Iterator[Any] = iter(values)
        self.reads = 0

    def __call__(self) -> Any:
        self.reads += 1
        return next(self._values)


def _advance(
    snapshot: CaseContextSnapshot,
    route: RoutingOutcome,
    *,
    fast: Any = None,
    slow: Any = None,
    clock: Any = None,
    monotonic: Any = None,
) -> CoordinatorOutcome:
    outcome = CaseCoordinator(
        snapshot=snapshot, clock=clock, monotonic=monotonic
    ).advance(_request(snapshot, route), fast=fast, slow=slow)
    assert outcome.route.outcome is route
    return outcome


def _assert_valid_1_1(trace: ModelTrace) -> None:
    assert trace.schema_version == "1.1"
    assert trace.contract_type == "model_trace"
    # Round-trips through the strict JSON contract.
    assert ModelTrace.model_validate_json(trace.model_dump_json()) == trace


@pytest.mark.parametrize(
    ("route", "roles"),
    [
        (RoutingOutcome.FAST_NOW, ("fast",)),
        (RoutingOutcome.SLOW_REFRESH, ("slow",)),
        # Slow is called first; the traces follow the call order.
        (RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH, ("slow", "fast")),
    ],
)
def test_one_trace_with_its_role_per_adapter_call(
    route: RoutingOutcome, roles: tuple[str, ...]
) -> None:
    snapshot = _snapshot()
    outcome = _advance(
        snapshot, route, fast=ScriptedFastAdapter(), slow=ScriptedSlowAdapter()
    )

    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert tuple(trace.role for trace in outcome.traces) == roles
    assert len({trace.trace_id for trace in outcome.traces}) == len(roles)
    for trace, audit in zip(outcome.traces, outcome.audits, strict=True):
        _assert_valid_1_1(trace)
        assert trace.role == audit.source
        assert trace.result is ModelResult.SUCCEEDED
        assert trace.reason_codes == audit.reason_codes
        assert trace.case_id == snapshot.case.case_id
        assert trace.input_pins == snapshot.pins
        # The scripted adapters expose a deterministic zero-token identity.
        assert trace.provider == "scripted"
        assert trace.input_tokens == trace.output_tokens == 0
        assert trace.safety_flags == ()
    slow_traces = [trace for trace in outcome.traces if trace.role == "slow"]
    fast_traces = [trace for trace in outcome.traces if trace.role == "fast"]
    if slow_traces:
        expected = CaseCoordinator.build_slow_request(
            snapshot,
            reason_code=outcome.route.reason_codes[0],
            created_at=LATER,
        )
        assert slow_traces[0].request_id == expected.request_id
        assert outcome.slow_result is not None
        assert slow_traces[0].output_ref == str(outcome.slow_result.result_id)
    if fast_traces:
        assert fast_traces[0].request_id is None
        assert outcome.fast_decision is not None
        assert fast_traces[0].output_ref == str(outcome.fast_decision.decision_id)


class _MismatchedSlow(ScriptedSlowAdapter):
    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return super().reason(request).model_copy(update={"request_id": uuid4()})


class _ActionPredatingSlow(ScriptedSlowAdapter):
    """Two proposals that both predate the result: one reason, reported twice."""

    def __init__(self, action: Any) -> None:
        self._action = action

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return (
            super()
            .reason(request)
            .model_copy(update={"action_proposals": (self._action, self._action)})
        )


class _StrategyMismatchFast(ScriptedFastAdapter):
    def decide(self, view: FastModelView) -> FastAdapterResult:
        result = super().decide(view)
        return FastAdapterResult(
            pins=result.pins,
            decision=result.decision.model_copy(update={"strategy_revision": 99}),
        )


def test_a_rejected_result_is_traced_with_its_reason_codes() -> None:
    snapshot = _snapshot()
    outcome = _advance(
        snapshot,
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=_StrategyMismatchFast(),
        slow=_MismatchedSlow(),
    )

    assert outcome.status is CoordinatorStatus.REJECTED
    assert outcome.slow_result is None and outcome.fast_decision is None
    slow_trace, fast_trace = outcome.traces
    for trace in outcome.traces:
        _assert_valid_1_1(trace)
        assert trace.result is ModelResult.REJECTED
    assert slow_trace.role == "slow"
    assert slow_trace.reason_codes == ("slow_request_mismatch",)
    assert fast_trace.role == "fast"
    assert fast_trace.reason_codes == ("fast_strategy_mismatch",)


def test_a_repeated_audit_reason_is_traced_once() -> None:
    runtime, state = _runtime()
    waiting = runtime.append_event(
        state.snapshot.case.case_id,
        content="Please review the current offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )
    action = waiting.snapshot.action_intents[0]
    snapshot = _snapshot()
    outcome = _advance(
        snapshot, RoutingOutcome.SLOW_REFRESH, slow=_ActionPredatingSlow(action)
    )

    (audit,) = outcome.audits
    assert audit.reason_codes.count("slow_action_predates_result") == 2
    (trace,) = outcome.traces
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == ("slow_action_predates_result",)


def test_a_1_0_snapshot_emits_no_trace() -> None:
    legacy = _as_stored_1_0(_runtime()[1]).snapshot
    assert legacy.schema_version == "1.0"
    clock = _Ticks()
    monotonic = _Ticks()

    outcome = _advance(
        legacy,
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=ScriptedFastAdapter(),
        slow=ScriptedSlowAdapter(),
        clock=clock,
        monotonic=monotonic,
    )

    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert len(outcome.audits) == 2
    assert outcome.traces == ()
    # The 1.0 (ML/evaluation) path does not read the injected sources.
    assert clock.reads == monotonic.reads == 0


def test_routes_without_an_adapter_call_emit_no_trace() -> None:
    snapshot = _snapshot()
    unavailable = _advance(snapshot, RoutingOutcome.SLOW_REFRESH)
    assert unavailable.status is CoordinatorStatus.SLOW_UNAVAILABLE
    assert unavailable.traces == ()

    # A request built on older pins is rerouted to the latest, never called.
    older = _as_stored_1_0(_runtime()[1]).snapshot
    assert older.pins != snapshot.pins
    stale = CaseCoordinator(snapshot=snapshot).advance(
        RouteRequest(snapshot=older, created_at=LATER),
        fast=ScriptedFastAdapter(),
        slow=ScriptedSlowAdapter(),
    )
    assert stale.status is CoordinatorStatus.REJECTED
    assert stale.traces == ()


def test_timestamps_and_latency_come_from_the_injected_sources() -> None:
    snapshot = _snapshot()
    started = LATER + timedelta(seconds=1)
    clock = _Ticks(
        started,
        started + timedelta(milliseconds=400),
        started + timedelta(seconds=1),
        started + timedelta(seconds=1, milliseconds=90),
    )
    monotonic = _Ticks(100.0, 100.4, 101.0, 101.09)

    outcome = _advance(
        snapshot,
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=ScriptedFastAdapter(),
        slow=ScriptedSlowAdapter(),
        clock=clock,
        monotonic=monotonic,
    )

    slow_trace, fast_trace = outcome.traces
    assert (slow_trace.started_at, slow_trace.completed_at) == (
        started,
        started + timedelta(milliseconds=400),
    )
    assert slow_trace.latency_ms == 400
    assert (fast_trace.started_at, fast_trace.completed_at) == (
        started + timedelta(seconds=1),
        started + timedelta(seconds=1, milliseconds=90),
    )
    assert fast_trace.latency_ms == 90
    assert clock.reads == monotonic.reads == 4


def test_without_injected_sources_the_trace_is_deterministic() -> None:
    def run() -> tuple[ModelTrace, ...]:
        return _advance(
            _snapshot(),
            RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
            fast=ScriptedFastAdapter(),
            slow=ScriptedSlowAdapter(),
        ).traces

    first = run()
    assert first == run()
    for trace in first:
        # No wall-clock read: the Route request time stands in for both ends.
        assert trace.started_at == trace.completed_at == LATER
        assert trace.latency_ms == 0


def _window_ms(trace: ModelTrace) -> float:
    return (trace.completed_at - trace.started_at) / timedelta(milliseconds=1)


def test_a_monotonic_source_without_a_clock_derives_the_window() -> None:
    outcome = _advance(
        _snapshot(),
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=ScriptedFastAdapter(),
        slow=ScriptedSlowAdapter(),
        monotonic=_Ticks(10.0, 10.3, 11.0, 11.05),
    )

    slow_trace, fast_trace = outcome.traces
    assert (slow_trace.latency_ms, fast_trace.latency_ms) == (300, 50)
    for trace in outcome.traces:
        assert trace.started_at == LATER
        assert _window_ms(trace) == trace.latency_ms


def test_a_clock_without_a_measurement_uses_the_window_width() -> None:
    started = LATER + timedelta(seconds=5)
    outcome = _advance(
        _snapshot(),
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=ScriptedFastAdapter(),
        slow=ScriptedSlowAdapter(),
        clock=_Ticks(
            started,
            started + timedelta(milliseconds=120),
            started + timedelta(seconds=1),
            started + timedelta(seconds=1, milliseconds=35),
        ),
    )

    slow_trace, fast_trace = outcome.traces
    assert (slow_trace.latency_ms, fast_trace.latency_ms) == (120, 35)
    for trace in outcome.traces:
        assert _window_ms(trace) == trace.latency_ms


class _BadUsageFast:
    """Reports usage the contract cannot hold (duck-typed, never validated)."""

    model_identity = ScriptedFastAdapter.model_identity

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, view: FastModelView) -> FastAdapterResult:
        raise AssertionError("the usage-reporting method is preferred")

    def decide_with_usage(self, view: FastModelView) -> tuple[FastAdapterResult, Any]:
        self.calls += 1
        usage = SimpleNamespace(input_tokens=-1, output_tokens=True, latency_ms="7")
        return ScriptedFastAdapter().decide(view), usage


def test_bad_reported_usage_never_fails_the_call() -> None:
    fast = _BadUsageFast()
    outcome = _advance(_snapshot(), RoutingOutcome.FAST_NOW, fast=fast)

    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.fast_decision is not None
    (trace,) = outcome.traces
    _assert_valid_1_1(trace)
    assert (trace.input_tokens, trace.output_tokens, trace.latency_ms) == (0, 0, 0)


@pytest.mark.parametrize(
    "fields",
    [
        {"input_tokens": -1},
        {"output_tokens": True},
        {"input_tokens": 1.5},
        {"latency_ms": -3},
        {"latency_ms": False},
    ],
)
def test_model_call_usage_rejects_non_counts(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must be a non-negative int"):
        ModelCallUsage(**fields)


@pytest.mark.parametrize(
    "reading",
    [datetime(2026, 8, 26, 12, 2), LATER.astimezone(timezone(timedelta(hours=2)))],
)
def test_a_non_utc_clock_is_refused_before_the_model_call(reading: datetime) -> None:
    fast = _BadUsageFast()
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="clock must return a timezone-aware UTC"):
        CaseCoordinator(snapshot=snapshot, clock=lambda: reading).advance(
            _request(snapshot, RoutingOutcome.FAST_NOW), fast=fast
        )
    assert fast.calls == 0


class _RaisingFast:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def decide(self, view: FastModelView) -> FastAdapterResult:
        self.calls += 1
        raise self.error


def test_an_adapter_that_raises_leaves_no_trace_and_propagates() -> None:
    error = RuntimeError("transport down")
    fast = _RaisingFast(error)
    with pytest.raises(RuntimeError) as raised:
        _advance(
            _snapshot(),
            RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
            fast=fast,
            slow=ScriptedSlowAdapter(),
        )
    assert raised.value is error
    assert fast.calls == 1


class _PlainFast:
    """A Fast adapter implementing none of the optional trace protocols."""

    def decide(self, view: FastModelView) -> FastAdapterResult:
        return ScriptedFastAdapter().decide(view)


def test_an_unidentified_adapter_is_named_by_its_class() -> None:
    (trace,) = _advance(_snapshot(), RoutingOutcome.FAST_NOW, fast=_PlainFast()).traces

    _assert_valid_1_1(trace)
    assert trace.provider == "unidentified"
    assert trace.model == "_PlainFast"
    assert trace.model_version == "unversioned"
    assert trace.adapter_version == "unversioned"
    assert trace.prompt_version == "unversioned"
    assert (trace.input_tokens, trace.output_tokens, trace.latency_ms) == (0, 0, 0)


@dataclass
class _Message:
    parsed: object


@dataclass
class _Choice:
    message: _Message


class _UsageResponse:
    def __init__(self, parsed: object, *, usage: object | None) -> None:
        self.model = "runtime-model"
        self.choices = [_Choice(_Message(parsed))]
        self.usage = usage


class _Completions:
    def __init__(self, *responses: object) -> None:
        self._responses = iter(responses)

    def parse(self, **kwargs: object) -> object:
        return next(self._responses)


def _bounded_fast_output() -> FastModelOutput:
    return FastModelOutput(
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="I am checking that and will update you.",
        action_intent=None,
    )


def test_openai_tokens_come_from_response_usage() -> None:
    completions = _Completions(
        _UsageResponse(
            _slow_output(),
            usage=SimpleNamespace(prompt_tokens=1_234, completion_tokens=56),
        ),
        # A response without usage records zero tokens rather than failing.
        _UsageResponse(_bounded_fast_output(), usage=None),
    )
    adapter = OpenAICompatibleAdapter(
        model="runtime-model",
        base_url="https://relay.example.invalid/v1",
        api_key="test-only",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        monotonic=_Ticks(5.0, 5.75, 9.0, 9.2),
    )

    outcome = _advance(
        _snapshot(),
        RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        fast=adapter,
        slow=adapter,
    )

    assert outcome.status is CoordinatorStatus.ACCEPTED
    slow_trace, fast_trace = outcome.traces
    for trace in outcome.traces:
        _assert_valid_1_1(trace)
        assert trace.provider == "relay.example.invalid"
        assert trace.model == "runtime-model"
        assert "test-only" not in trace.model_dump_json()
    assert (slow_trace.input_tokens, slow_trace.output_tokens) == (1_234, 56)
    assert (fast_trace.input_tokens, fast_trace.output_tokens) == (0, 0)
    # Latency is measured by the adapter around the model call; with no clock
    # injected the window is derived from it.
    assert slow_trace.latency_ms == 750
    assert fast_trace.latency_ms == 200
    for trace in outcome.traces:
        assert _window_ms(trace) == trace.latency_ms


def test_the_provider_is_only_the_host_and_no_secret_reaches_the_trace() -> None:
    secrets = ("alice-user", "pw-secret-123", "p-secret-789", "q-secret-456", "k-key")
    adapter = OpenAICompatibleAdapter(
        model="runtime-model",
        base_url=(
            "https://alice-user:pw-secret-123@Relay.Example.invalid:8443"
            "/v1/p-secret-789?api_key=q-secret-456"
        ),
        api_key="k-key",
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=_Completions(
                    _UsageResponse(_bounded_fast_output(), usage=None)
                )
            )
        ),
    )

    (trace,) = _advance(_snapshot(), RoutingOutcome.FAST_NOW, fast=adapter).traces

    assert trace.provider == "relay.example.invalid"
    dumped = trace.model_dump_json()
    assert "8443" not in dumped
    assert not any(secret in dumped for secret in secrets)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, 0), (False, 0), (-1, 0), ("5", 0), (5.0, 0), (None, 0), (7, 7)],
)
def test_token_count_accepts_only_non_negative_ints(
    value: object, expected: int
) -> None:
    assert _token_count(value) == expected


def _texts(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def test_no_trace_id_reaches_the_snapshot_views_or_browser_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    traces: list[ModelTrace] = []

    class _RecordingCoordinator(CaseCoordinator):
        def advance(self, *args: Any, **kwargs: Any) -> CoordinatorOutcome:
            outcome = super().advance(*args, **kwargs)
            traces.extend(outcome.traces)
            return outcome

    monkeypatch.setattr(runtime_module, "CaseCoordinator", _RecordingCoordinator)
    runtime = ThinAgentRuntime(InMemoryCaseRepository(), clock=lambda: T0)
    created = runtime.create_case(occurred_at=T0)
    waiting = runtime.append_event(
        created.snapshot.case.case_id,
        content="Please review the current offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )

    assert {trace.role for trace in traces} == {"fast", "slow", "judge"}
    trace_ids = {str(trace.trace_id) for trace in traces}
    for result in (created, waiting):
        snapshot = result.snapshot
        surfaces = (
            snapshot.model_dump_json(),
            CaseCoordinator.project_fast_view(snapshot).model_dump_json(),
            CaseCoordinator.build_slow_request(
                snapshot, reason_code="provider_message", created_at=LATER
            ).model_dump_json(),
            _texts(_result_payload(result)),
        )
        for surface in surfaces:
            assert "trace_id" not in surface
            assert not any(trace_id in surface for trace_id in trace_ids)
