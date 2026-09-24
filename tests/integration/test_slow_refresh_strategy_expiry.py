"""The event paths refresh an expired strategy through Slow (P1 B2-3, B2-5)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from proxyloop_agent_core import ScriptedSlowAdapter
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    InMemoryCaseRepository,
    ModelRuntimeError,
    ThinAgentRuntime,
)
from proxyloop_connectors import BINDING_REF, CHANNEL_KIND
from proxyloop_contracts import (
    ApprovalDecision,
    CasePhase,
    CompletionOutcome,
    ModelResult,
    ModelTrace,
    SlowWorkRequest,
    SlowWorkResult,
)
from test_phase_06b1_channel_runtime import (
    BASE_TIME,
    _ChannelRepository,
    _create_command,
    _message_event,
)

T0 = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _CountingSlow(ScriptedSlowAdapter):
    def __init__(self) -> None:
        self.reason_codes: list[str] = []

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        self.reason_codes.append(request.reason_code)
        return super().reason(request)


class _SameRevisionSlow(_CountingSlow):
    """Return the installed strategy's (id, revision) on a refresh."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        result = super().reason(request)
        prior = request.view.strategy
        if prior is None or result.strategy_proposal is None:
            return result
        strategy = result.strategy_proposal.model_copy(
            update={"strategy_id": prior.strategy_id, "revision": prior.revision}
        )
        return result.model_copy(update={"strategy_proposal": strategy})


class _RegressedRevisionSlow(_CountingSlow):
    """Return a lower revision of the installed strategy once it is past 1."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        result = super().reason(request)
        prior = request.view.strategy
        if prior is None or prior.revision < 2 or result.strategy_proposal is None:
            return result
        strategy = result.strategy_proposal.model_copy(
            update={"strategy_id": prior.strategy_id, "revision": prior.revision - 1}
        )
        return result.model_copy(update={"strategy_proposal": strategy})


class _ExpiredStrategySlow(_CountingSlow):
    """Return an already expired strategy on a refresh."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        result = super().reason(request)
        if request.view.strategy is None or result.strategy_proposal is None:
            return result
        strategy = result.strategy_proposal.model_copy(
            update={"expires_at": request.created_at}
        )
        return result.model_copy(update={"strategy_proposal": strategy})


def _created(
    slow: ScriptedSlowAdapter | None = None,
) -> tuple[ThinAgentRuntime, InMemoryCaseRepository, _Clock]:
    repository = InMemoryCaseRepository()
    clock = _Clock(T0)
    runtime = ThinAgentRuntime(repository, clock=clock, slow=slow)
    runtime.create_case(occurred_at=T0)
    return runtime, repository, clock


def test_t1_consumer_message_after_expiry_refreshes_the_strategy() -> None:
    runtime, repository, clock = _created()
    stale = runtime.current_result(SCRIPTED_CASE_ID).snapshot.strategy
    assert stale is not None
    at = T0 + timedelta(minutes=31)
    clock.now = at

    result = runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")

    strategy = result.snapshot.strategy
    assert strategy is not None
    assert (strategy.strategy_id, strategy.revision) != (
        stale.strategy_id,
        stale.revision,
    )
    assert strategy.revision == stale.revision + 1
    assert strategy.created_at == at
    assert strategy.expires_at > at
    approval = result.approval
    assert approval is not None
    assert approval.decision is ApprovalDecision.PENDING
    assert (approval.strategy_id, approval.strategy_revision) == (
        strategy.strategy_id,
        strategy.revision,
    )
    (intent,) = result.snapshot.action_intents
    assert (intent.strategy_id, intent.strategy_revision) == (
        strategy.strategy_id,
        strategy.revision,
    )
    assert result.fast_decision is not None
    assert result.fast_decision.strategy_revision == strategy.revision
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    assert stored.snapshot == result.snapshot
    assert result.snapshot.revision == 5


def test_t2_refreshed_approval_executes_once_and_completes() -> None:
    runtime, _, clock = _created()
    clock.now = T0 + timedelta(minutes=31)
    pending = runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")
    assert pending.approval is not None
    clock.now = T0 + timedelta(minutes=40)

    result = runtime.approve(SCRIPTED_CASE_ID, pending.approval.approval_id)

    assert result.execution_count == 1
    assert result.snapshot.case.phase is CasePhase.COMPLETE
    assert result.snapshot.completion_decision is not None
    assert result.snapshot.completion_decision.decision is CompletionOutcome.COMPLETE


def test_t3_expired_strategy_does_not_gate_a_current_approval() -> None:
    slow = _CountingSlow()
    runtime, _, clock = _created(slow)
    clock.now = T0 + timedelta(minutes=10)
    pending = runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")
    assert pending.approval is not None
    strategy = pending.snapshot.strategy
    assert strategy is not None
    clock.now = T0 + timedelta(minutes=45)
    assert strategy.expires_at <= clock.now

    result = runtime.approve(SCRIPTED_CASE_ID, pending.approval.approval_id)

    assert result.execution_count == 1
    assert result.snapshot.case.phase is CasePhase.COMPLETE
    assert result.snapshot.strategy == strategy
    assert slow.reason_codes == ["case_initialization"]


def _channel_created(
    slow: ScriptedSlowAdapter | None = None,
) -> tuple[ThinAgentRuntime, _ChannelRepository]:
    repository = _ChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME, slow=slow)
    runtime.apply_command(_create_command())
    return runtime, repository


def _channel_command(
    repository: _ChannelRepository,
    at: datetime,
) -> CaseCommand:
    event = replace(_message_event(uuid4()), occurred_at=at, fixture_timestamp=at)
    inbox = repository.reserve_channel_event(event, received_at=at)
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    return CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
        occurred_at=event.occurred_at,
        expected_revision=stored.snapshot.revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=event.event_id,
        content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
        payload_hash=event.raw_payload_hash,
    )


def test_t4_channel_event_after_expiry_refreshes_and_pins_the_outbox() -> None:
    runtime, repository = _channel_created()
    stale = runtime.current_result(SCRIPTED_CASE_ID).snapshot.strategy
    assert stale is not None
    at = BASE_TIME + timedelta(minutes=31)
    command = _channel_command(repository, at)

    applied = runtime.apply_command(command)

    assert applied.delivery_id is not None
    assert applied.after_revision == 4
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    strategy = stored.snapshot.strategy
    assert strategy is not None
    assert (strategy.strategy_id, strategy.revision) != (
        stale.strategy_id,
        stale.revision,
    )
    assert strategy.created_at == at
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    assert (outbox.source_strategy_id, outbox.source_strategy_revision) == (
        strategy.strategy_id,
        strategy.revision,
    )
    assert command.event_id is not None
    inbox = repository.get_inbox_receipt(command.event_id)
    assert inbox is not None
    assert inbox.processing_state == "applied"


def _logged(
    repository: InMemoryCaseRepository,
) -> tuple[ModelTrace, ...]:
    return repository.list_model_traces(SCRIPTED_CASE_ID)


def _assert_channel_refusal_persisted_no_case_state(
    runtime: ThinAgentRuntime,
    repository: _ChannelRepository,
    command: CaseCommand,
    before_revision: int,
    before_outbox_count: int,
) -> None:
    logged = len(_logged(repository))
    with pytest.raises(ModelRuntimeError) as raised:
        runtime.apply_command(command)
    assert raised.value.source == "slow"
    # The refused refresh's Slow trace is kept; the Case state is not changed.
    assert [trace.role for trace in _logged(repository)[logged:]] == ["slow"]
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    assert stored.snapshot.revision == before_revision
    assert len(repository.outbox) == before_outbox_count
    assert command.event_id is not None
    inbox = repository.get_inbox_receipt(command.event_id)
    assert inbox is not None
    assert inbox.processing_state == "reserved"


@pytest.mark.parametrize("slow", [_SameRevisionSlow, _ExpiredStrategySlow])
def test_t5_channel_rejected_slow_refresh_persists_no_case_state(
    slow: type[_CountingSlow],
) -> None:
    adapter = slow()
    runtime, repository = _channel_created(adapter)
    command = _channel_command(repository, BASE_TIME + timedelta(minutes=31))

    _assert_channel_refusal_persisted_no_case_state(
        runtime, repository, command, before_revision=2, before_outbox_count=0
    )
    assert adapter.reason_codes == ["case_initialization", "strategy_expired"]


def test_t5_channel_rejects_a_same_id_revision_regression() -> None:
    adapter = _RegressedRevisionSlow()
    runtime, repository = _channel_created(adapter)
    runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=31))
    )
    refreshed = repository.get(SCRIPTED_CASE_ID)
    assert refreshed is not None
    assert refreshed.snapshot.strategy is not None
    assert refreshed.snapshot.strategy.revision == 2
    command = _channel_command(repository, BASE_TIME + timedelta(minutes=62))

    _assert_channel_refusal_persisted_no_case_state(
        runtime,
        repository,
        command,
        before_revision=refreshed.snapshot.revision,
        before_outbox_count=1,
    )
    assert adapter.reason_codes == [
        "case_initialization",
        "strategy_expired",
        "strategy_expired",
    ]


def test_t6_channel_event_with_current_strategy_makes_no_slow_call() -> None:
    adapter = _CountingSlow()
    runtime, repository = _channel_created(adapter)
    created = runtime.current_result(SCRIPTED_CASE_ID).snapshot

    applied = runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=10))
    )

    assert adapter.reason_codes == ["case_initialization"]
    assert applied.after_revision == created.revision + 1
    assert applied.delivery_id is not None
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    assert created.strategy is not None
    assert outbox.source_strategy_revision == created.strategy.revision


@pytest.mark.parametrize("slow", [_SameRevisionSlow, _ExpiredStrategySlow])
def test_t5_rejected_slow_refresh_persists_no_case_state(
    slow: type[_CountingSlow],
) -> None:
    # R2: the refused refresh is traced even though no Case state is written.
    adapter = slow()
    runtime, repository, clock = _created(adapter)
    before = repository.get(SCRIPTED_CASE_ID)
    assert before is not None
    created_traces = _logged(repository)
    assert [trace.role for trace in created_traces] == ["slow"]
    clock.now = T0 + timedelta(minutes=31)

    with pytest.raises(ModelRuntimeError) as raised:
        runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")

    assert raised.value.source == "slow"
    assert adapter.reason_codes == ["case_initialization", "strategy_expired"]
    after = repository.get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot.revision == before.snapshot.revision
    assert after.snapshot == before.snapshot
    logged = _logged(repository)
    assert logged[:1] == created_traces
    assert [trace.role for trace in logged] == ["slow", "slow"]
    # I11: ``result`` is the coordinator's verdict. A same-revision refresh
    # passes the coordinator and is refused by the Runtime afterwards.
    expected = (
        ModelResult.SUCCEEDED if slow is _SameRevisionSlow else ModelResult.REJECTED
    )
    assert logged[1].result is expected


def test_t6_current_strategy_makes_no_slow_call() -> None:
    slow = _CountingSlow()
    runtime, _, clock = _created(slow)
    created = runtime.current_result(SCRIPTED_CASE_ID).snapshot
    clock.now = T0 + timedelta(minutes=10)

    result = runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")

    assert slow.reason_codes == ["case_initialization"]
    assert result.snapshot.strategy == created.strategy
    assert result.snapshot.revision == created.revision + 2
    assert result.fast_decision is not None
    assert result.approval is not None
    assert result.approval.strategy_revision == 1
