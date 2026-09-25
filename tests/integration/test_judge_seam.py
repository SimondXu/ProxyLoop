"""The Stage 2 Judge seam (PR-14).

The Judge reviews every Slow result the coordinator admitted, on the Runtime
coordinator only. Its verdict is advisory (accept or revise, never block): a
binding ``revise`` retries a feedback-capable Slow once, in process and off
the contract, and a rejected retry, a failed Judge call, or a non-binding
verdict leaves the first admitted result. Every Judge call is a
``role=judge`` trace appended with the run's other traces.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from proxyloop_agent_core import (
    CaseCoordinator,
    CoordinatorOutcome,
    CoordinatorStatus,
    ModelCallUsage,
    RouteRequest,
    ScriptedFastAdapter,
    ScriptedProposingSlowAdapter,
    ScriptedSlowAdapter,
    slow_proposal_violations,
)
from proxyloop_agent_core.judge import (
    JUDGE_ADAPTER_FAILURE_CODES,
    JUDGE_REVISE_CODES,
    JUDGE_VERDICT_VERSION,
    FeedbackReasoningSlowAdapter,
    JudgeAdapterFailure,
    JudgeVerdict,
    ScriptedJudgeAdapter,
)
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.turn_split import fast_slow_split
from proxyloop_contracts import (
    CaseContextSnapshot,
    CasePhase,
    ModelResult,
    ModelTrace,
    Money,
    RoutingOutcome,
    SlowWorkRequest,
    SlowWorkResult,
)
from test_phase_04c_persistent_case_store import _assert_non_provider_fields_equal
from test_slow_driven_intent import IncoherentProposalSlow

T0 = datetime(2035, 1, 1, tzinfo=UTC)
LATER = T0 + timedelta(minutes=2)
GIVE_UP = "judge_premature_give_up"


class SteppingClock:
    """A UTC clock that advances one second per read."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


# -- test doubles --------------------------------------------------------------


@dataclass
class StubJudge:
    """A Judge with a fixed verdict, failure, or binding error."""

    verdict: str = "accept"
    failure: str | None = None
    error: Exception | None = None
    result_id: UUID | None = None
    request_id: UUID | None = None
    calls: list[tuple[SlowWorkRequest, SlowWorkResult]] = field(default_factory=list)

    def judge(self, request: SlowWorkRequest, result: SlowWorkResult) -> JudgeVerdict:
        self.calls.append((request, result))
        if self.error is not None:
            raise self.error
        if self.failure is not None:
            raise JudgeAdapterFailure(self.failure)
        return JudgeVerdict(
            verdict=self.verdict,  # type: ignore[arg-type]
            request_id=self.request_id or request.request_id,
            result_id=self.result_id or result.result_id,
            reason_codes=(GIVE_UP,) if self.verdict == "revise" else (),
        )


class GivingUpSlow(ScriptedProposingSlowAdapter):
    """Proposes nothing at first; proposes the accept when given feedback."""

    def __init__(self) -> None:
        self.requests: list[SlowWorkRequest] = []
        self.feedback: list[tuple[SlowWorkRequest, JudgeVerdict]] = []

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        self.requests.append(request)
        return ScriptedSlowAdapter.reason(self, request)

    def reason_with_feedback(
        self, request: SlowWorkRequest, verdict: JudgeVerdict
    ) -> tuple[SlowWorkResult, ModelCallUsage]:
        self.feedback.append((request, verdict))
        return self.retried(request), ModelCallUsage()

    def retried(self, request: SlowWorkRequest) -> SlowWorkResult:
        return ScriptedProposingSlowAdapter.reason(self, request)


class GivingUpAgainSlow(GivingUpSlow):
    """The retry proposes nothing either; the Judge is not asked again."""

    def retried(self, request: SlowWorkRequest) -> SlowWorkResult:
        return ScriptedSlowAdapter.reason(self, request)


class IncoherentRetrySlow(GivingUpSlow):
    """The retry fails the A-3 admission check."""

    def retried(self, request: SlowWorkRequest) -> SlowWorkResult:
        return IncoherentProposalSlow().reason(request)


class RaisingRetrySlow(GivingUpSlow):
    def retried(self, request: SlowWorkRequest) -> SlowWorkResult:
        raise RuntimeError("retry transport broke")


# -- helpers -------------------------------------------------------------------


def _snapshot() -> CaseContextSnapshot:
    """A 1.1 Case snapshot at T0 with a live offer and a current strategy."""

    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state.snapshot


def _refresh(
    snapshot: CaseContextSnapshot,
    *,
    slow: object,
    judge: object | None,
    fast: object | None = None,
    bounded: bool = False,
) -> CoordinatorOutcome:
    """One Runtime-shaped coordinator run on a mandatory Slow refresh."""

    coordinator = CaseCoordinator(
        snapshot=snapshot,
        slow_proposal_check=slow_proposal_violations,
        judge=judge,  # type: ignore[arg-type]
    )
    return coordinator.advance(
        RouteRequest(
            snapshot=snapshot,
            created_at=LATER,
            mandatory_slow_reason_codes=("provider_message",),
            bounded_acknowledgement_allowed=bounded,
        ),
        fast=fast,  # type: ignore[arg-type]
        slow=slow,  # type: ignore[arg-type]
    )


def _slow_request(snapshot: CaseContextSnapshot, at: datetime) -> SlowWorkRequest:
    return CaseCoordinator.build_slow_request(
        snapshot, reason_code="provider_message", created_at=at
    )


def _roles(traces: tuple[ModelTrace, ...]) -> list[str | None]:
    return [trace.role for trace in traces]


def _assert_audits_pair_with_traces(outcome: CoordinatorOutcome) -> None:
    assert len(outcome.audits) == len(outcome.traces)
    for audit, trace in zip(outcome.audits, outcome.traces, strict=True):
        assert audit.source == trace.role
        assert audit.reason_codes == trace.reason_codes


# -- R1: the Runtime judges each admitted Slow result ---------------------------


def test_runtime_judges_each_admitted_slow_result() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock())
    runtime.create_case(occurred_at=T0)

    slow, judge = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert (slow.role, slow.result) == ("slow", ModelResult.SUCCEEDED)
    assert judge.role == "judge"
    assert judge.result is ModelResult.SUCCEEDED
    assert judge.reason_codes == ("judge_accept",)
    assert (judge.provider, judge.model) == ("scripted", "scripted_judge")
    assert judge.request_id == slow.request_id
    assert judge.input_pins == slow.input_pins
    assert judge.output_ref is None
    assert judge.output_schema_version == JUDGE_VERDICT_VERSION
    assert judge.input_schema_version == "1.0"
    assert judge.input_tokens == judge.output_tokens == 0


# -- R2-R4: the retry flow ------------------------------------------------------


def test_revise_retries_slow_once_with_the_verdict_in_process() -> None:
    snapshot = _snapshot()
    slow = GivingUpSlow()
    judge = StubJudge(verdict="revise")

    outcome = _refresh(snapshot, slow=slow, judge=judge)

    assert _roles(outcome.traces) == ["slow", "judge", "slow"]
    assert [trace.result for trace in outcome.traces] == [ModelResult.SUCCEEDED] * 3
    assert outcome.traces[1].reason_codes == ("judge_revise", GIVE_UP)
    _assert_audits_pair_with_traces(outcome)
    # One Judge call; the retry received the verdict and the very same request.
    assert len(judge.calls) == 1
    ((request, verdict),) = slow.feedback
    (first_request,) = slow.requests
    assert request is first_request
    assert verdict.verdict == "revise"
    assert verdict.reason_codes == (GIVE_UP,)
    # The retry's result is used: it carries the proposal the first lacked.
    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.slow_result is not None
    assert len(outcome.slow_result.capability_proposals) == 1
    assert outcome.traces[2].request_id == outcome.traces[0].request_id


def test_a_rejected_retry_falls_back_to_the_first_admitted_result() -> None:
    snapshot = _snapshot()
    slow = IncoherentRetrySlow()

    outcome = _refresh(snapshot, slow=slow, judge=StubJudge(verdict="revise"))

    assert _roles(outcome.traces) == ["slow", "judge", "slow"]
    retry = outcome.traces[2]
    assert retry.result is ModelResult.REJECTED
    assert retry.reason_codes is not None
    assert all(code.startswith("slow_proposal_") for code in retry.reason_codes)
    _assert_audits_pair_with_traces(outcome)
    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


@pytest.mark.parametrize("code", sorted(JUDGE_ADAPTER_FAILURE_CODES))
def test_a_typed_judge_failure_is_traced_failed_and_never_blocks(code: str) -> None:
    snapshot = _snapshot()
    slow = GivingUpSlow()

    outcome = _refresh(snapshot, slow=slow, judge=StubJudge(failure=code))

    assert _roles(outcome.traces) == ["slow", "judge"]
    judge = outcome.traces[1]
    assert judge.result is ModelResult.FAILED
    assert judge.reason_codes == (code,)
    assert judge.output_schema_version == "none"
    assert judge.output_ref is None
    _assert_audits_pair_with_traces(outcome)
    assert slow.feedback == []
    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


# -- the coordinator ------------------------------------------------------------


@pytest.mark.parametrize(
    ("binding", "code"),
    [
        ("result", "judge_verdict_result_mismatch"),
        ("request", "judge_verdict_request_mismatch"),
    ],
)
def test_a_non_binding_verdict_is_rejected_and_the_first_result_used(
    binding: str, code: str
) -> None:
    snapshot = _snapshot()
    slow = GivingUpSlow()
    judge = StubJudge(
        verdict="revise",
        result_id=uuid4() if binding == "result" else None,
        request_id=uuid4() if binding == "request" else None,
    )

    outcome = _refresh(snapshot, slow=slow, judge=judge)

    assert _roles(outcome.traces) == ["slow", "judge"]
    assert outcome.traces[1].result is ModelResult.REJECTED
    assert outcome.traces[1].reason_codes == (code,)
    _assert_audits_pair_with_traces(outcome)
    assert slow.feedback == []
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


class NotAVerdictJudge:
    """A Judge whose adapter returns something that is not a verdict."""

    def judge(self, request: SlowWorkRequest, result: SlowWorkResult) -> object:
        return {"verdict": "revise"}


def test_a_return_that_is_not_a_verdict_is_rejected_and_the_first_result_used() -> None:
    # Review M1: recorded like a non-binding verdict, never raised.
    snapshot = _snapshot()
    slow = GivingUpSlow()

    outcome = _refresh(snapshot, slow=slow, judge=NotAVerdictJudge())

    assert _roles(outcome.traces) == ["slow", "judge"]
    judge = outcome.traces[1]
    assert (judge.result, judge.reason_codes) == (
        ModelResult.REJECTED,
        ("judge_verdict_invalid",),
    )
    assert judge.output_schema_version == JUDGE_VERDICT_VERSION
    _assert_audits_pair_with_traces(outcome)
    assert slow.feedback == []
    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


def test_a_revise_without_the_feedback_protocol_does_not_retry() -> None:
    # Root answer 3: the revise is traced and the first result is used.
    snapshot = _snapshot()
    slow = ScriptedSlowAdapter()
    assert not isinstance(slow, FeedbackReasoningSlowAdapter)

    outcome = _refresh(snapshot, slow=slow, judge=ScriptedJudgeAdapter())

    assert _roles(outcome.traces) == ["slow", "judge"]
    assert outcome.traces[1].reason_codes == ("judge_revise", GIVE_UP)
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


def test_the_retry_is_final_and_the_judge_is_asked_once() -> None:
    snapshot = _snapshot()
    judge = StubJudge(verdict="revise")

    outcome = _refresh(snapshot, slow=GivingUpAgainSlow(), judge=judge)

    assert _roles(outcome.traces) == ["slow", "judge", "slow"]
    assert len(judge.calls) == 1
    assert outcome.traces[2].result is ModelResult.SUCCEEDED
    assert outcome.slow_result is not None
    assert outcome.slow_result.capability_proposals == ()


def test_an_unadmitted_slow_result_is_not_judged() -> None:
    snapshot = _snapshot()
    judge = StubJudge()

    outcome = _refresh(snapshot, slow=IncoherentProposalSlow(), judge=judge)

    assert judge.calls == []
    assert _roles(outcome.traces) == ["slow"]
    assert outcome.traces[0].result is ModelResult.REJECTED
    assert outcome.slow_result is None


def test_the_bounded_route_traces_slow_judge_then_fast() -> None:
    snapshot = _snapshot()

    outcome = _refresh(
        snapshot,
        slow=ScriptedProposingSlowAdapter(),
        judge=ScriptedJudgeAdapter(),
        fast=ScriptedFastAdapter(),
        bounded=True,
    )

    assert outcome.route.outcome is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH
    assert _roles(outcome.traces) == ["slow", "judge", "fast"]
    _assert_audits_pair_with_traces(outcome)


def test_an_untyped_judge_exception_propagates() -> None:
    snapshot = _snapshot()
    with pytest.raises(ZeroDivisionError):
        _refresh(
            snapshot,
            slow=ScriptedProposingSlowAdapter(),
            judge=StubJudge(error=ZeroDivisionError()),
        )


def test_an_exception_from_the_retry_propagates() -> None:
    # Root answer 4: a known limit; the run's traces are lost with it.
    snapshot = _snapshot()
    with pytest.raises(RuntimeError, match="retry transport broke"):
        _refresh(snapshot, slow=RaisingRetrySlow(), judge=StubJudge(verdict="revise"))


def test_a_coordinator_without_a_judge_is_unchanged() -> None:
    # JG2: the ML and bare coordinators never judge.
    snapshot = _snapshot()
    outcome = CaseCoordinator(snapshot=snapshot).advance(
        RouteRequest(
            snapshot=snapshot,
            created_at=LATER,
            mandatory_slow_reason_codes=("provider_message",),
        ),
        slow=ScriptedSlowAdapter(),
    )
    assert _roles(outcome.traces) == ["slow"]


# -- the scripted Judge and the verdict types ------------------------------------


def test_the_scripted_judge_accepts_a_result_with_a_proposal() -> None:
    request = _slow_request(_snapshot(), LATER)
    result = ScriptedProposingSlowAdapter().reason(request)
    verdict = ScriptedJudgeAdapter().judge(request, result)
    assert verdict == JudgeVerdict("accept", request.request_id, result.result_id)


def test_the_scripted_judge_revises_a_premature_give_up() -> None:
    request = _slow_request(_snapshot(), LATER)
    result = ScriptedSlowAdapter().reason(request)
    judge = ScriptedJudgeAdapter()
    verdict = judge.judge(request, result)
    assert verdict == JudgeVerdict(
        "revise", request.request_id, result.result_id, (GIVE_UP,)
    )
    # A pure function of its input.
    assert judge.judge(request, result) == verdict


def test_the_scripted_judge_accepts_when_no_offer_is_live() -> None:
    snapshot = _snapshot()
    expiry = snapshot.offers[0].expires_at
    request = _slow_request(snapshot, expiry)
    result = ScriptedSlowAdapter().reason(request)
    assert ScriptedJudgeAdapter().judge(request, result).verdict == "accept"


def test_the_scripted_judge_accepts_without_an_accept_capability() -> None:
    request = _slow_request(_snapshot(), LATER)
    result = ScriptedSlowAdapter().reason(request)
    manifest = request.view.capability_manifest.model_copy(update={"capabilities": ()})
    view = request.view.model_copy(update={"capability_manifest": manifest})
    stripped = request.model_copy(update={"view": view})
    assert ScriptedJudgeAdapter().judge(stripped, result).verdict == "accept"


@pytest.mark.parametrize(
    ("verdict", "codes"),
    [
        ("block", ()),
        ("accept", (GIVE_UP,)),
        ("revise", ()),
        ("revise", ("judge_arithmetic_error",)),
        ("revise", (GIVE_UP, GIVE_UP)),
    ],
)
def test_an_ill_formed_verdict_is_refused(verdict: str, codes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        JudgeVerdict(verdict, uuid4(), uuid4(), codes)  # type: ignore[arg-type]


def test_the_revise_vocabulary_is_one_closed_code() -> None:
    assert sorted(JUDGE_REVISE_CODES) == [GIVE_UP]


def test_a_judge_failure_code_must_be_allow_listed() -> None:
    with pytest.raises(ValueError):
        JudgeAdapterFailure("judge_adapter_mood")
    failure = JudgeAdapterFailure("judge_adapter_timeout")
    assert failure.reason_codes == ("judge_adapter_timeout",)


# -- the Runtime ----------------------------------------------------------------


def _command_flow(runtime: ThinAgentRuntime) -> CaseRuntimeState:
    created = runtime.apply_command(
        CaseCommand(
            command_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.CREATE_CASE,
            occurred_at=T0,
            current_monthly_total=Money(amount_minor=9200, currency="USD"),
            target_monthly_total=Money(amount_minor=7500, currency="USD"),
            mobile_hotspot_required=True,
            device_financing_change_forbidden=True,
        )
    )
    runtime.apply_command(
        CaseCommand(
            command_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.APPEND_EVENT,
            occurred_at=T0 + timedelta(minutes=31),
            expected_revision=created.after_revision,
            content="Please review the offer.",
            event_type="consumer_message",
        )
    )
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


def _direct_flow(runtime: ThinAgentRuntime) -> CaseRuntimeState:
    runtime.create_case(occurred_at=T0)
    runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Please review the offer.",
        occurred_at=T0 + timedelta(minutes=31),
    )
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


@pytest.mark.parametrize("flow", [_direct_flow, _command_flow])
@pytest.mark.parametrize(
    "stub",
    [
        {"verdict": "revise"},
        {"failure": "judge_adapter_unavailable"},
        {"result_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")},
    ],
    ids=["always_revise", "always_fails", "never_binds"],
)
def test_the_judge_changes_no_state_on_the_default_slow(
    flow: object, stub: dict[str, object]
) -> None:
    # JG9: without a feedback-capable Slow the Judge cannot change a decision;
    # the event at +31 minutes refreshes, so create and refresh are judged.
    judge = StubJudge(**stub)  # type: ignore[arg-type]
    default_runtime = ThinAgentRuntime(clock=SteppingClock())
    judged_runtime = ThinAgentRuntime(clock=SteppingClock(), judge=judge)
    expected = flow(default_runtime)  # type: ignore[operator]
    actual = flow(judged_runtime)  # type: ignore[operator]

    _assert_non_provider_fields_equal(expected, actual)
    assert actual.provider.state == expected.provider.state
    assert actual.snapshot.case.phase is CasePhase.AWAITING_APPROVAL
    assert len(judge.calls) == 2

    def shape(runtime: ThinAgentRuntime) -> list[tuple[object, ...]]:
        return [
            (trace.role, trace.result)
            for trace in runtime.repository.list_model_traces(SCRIPTED_CASE_ID)
        ]

    assert shape(default_runtime) == [
        ("slow", ModelResult.SUCCEEDED),
        ("judge", ModelResult.SUCCEEDED),
        ("slow", ModelResult.SUCCEEDED),
        ("judge", ModelResult.SUCCEEDED),
        ("fast", ModelResult.SUCCEEDED),
    ]
    assert [role for role, _ in shape(judged_runtime)] == [
        "slow",
        "judge",
        "slow",
        "judge",
        "fast",
    ]


def test_a_retried_proposal_opens_the_approval_end_to_end() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock(), slow=GivingUpSlow())

    runtime.create_case(occurred_at=T0)
    assert _roles(repository.list_model_traces(SCRIPTED_CASE_ID)) == [
        "slow",
        "judge",
        "slow",
    ]
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None and state.standing_proposal is not None

    result = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Please review the offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )
    assert result.approval is not None
    assert result.snapshot.case.phase is CasePhase.AWAITING_APPROVAL


def test_a_rejected_retry_leaves_the_dialogue_going_end_to_end() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), slow=IncoherentRetrySlow()
    )

    runtime.create_case(occurred_at=T0)
    traces = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert [(trace.role, trace.result) for trace in traces] == [
        ("slow", ModelResult.SUCCEEDED),
        ("judge", ModelResult.SUCCEEDED),
        ("slow", ModelResult.REJECTED),
    ]
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None and state.standing_proposal is None

    result = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Please review the offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )
    assert result.approval is None
    assert result.snapshot.case.phase is CasePhase.STRATEGY


def test_a_repeated_create_after_an_unretried_revise_splits_cleanly() -> None:
    # Review I1 (the reviewer's repro): a Slow without the feedback protocol
    # is revised and not retried; the repeated create's judged Slow call is a
    # new attempt, not a retry.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), slow=ScriptedSlowAdapter()
    )
    runtime.create_case(occurred_at=T0)
    with pytest.raises(CaseConflictError):
        runtime.create_case(occurred_at=T0)

    traces = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert [(trace.role, trace.reason_codes) for trace in traces] == [
        ("slow", ("slow_result_current",)),
        ("judge", ("judge_revise", GIVE_UP)),
        ("slow", ("slow_result_current",)),
        ("judge", ("judge_revise", GIVE_UP)),
    ]
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    split = fast_slow_split(traces, state)
    (turn,) = split["turns"]
    assert (turn["slow_calls"], turn["judge_calls"], turn["slow_retry"]) == (
        1,
        1,
        None,
    )
    assert split["aggregates"]["unapplied_model_calls"] == 1
    assert split["aggregates"]["unapplied_judge_calls_by_result"]["succeeded"] == 1


def test_the_runtime_wires_the_judge_only_through_its_coordinator() -> None:
    # G1: PR-7's G8 guard, extended to the Judge.
    source = inspect.getsource(runtime_module)
    assert source.count(".advance(") == 1
    assert source.count("._coordinator(") == 1
    assert source.count("CaseCoordinator(") == 1
    assert source.count("judge=self._judge") == 1
    for call in (".judge(", ".reason_with_feedback(", ".decide(", ".reason("):
        assert source.count(call) == 0, call
    assert "verdict" not in source.lower()
    # Review M2: the Judge's codes live in the outcome's audits and traces.
    # The Runtime never reads the audits and touches the traces only in
    # ``_advance``, to append them to the log.
    assert source.count(".audits") == 0
    assert source.count(".traces") == 2
    assert "if outcome.traces:\n            self.repository.append_model_traces(" in (
        source
    )
