"""A delivery callback on a COMPLETE Case survives the PostgreSQL codec (R-10).

The 06B1 contract appends a Provider-event Evidence and advances the revision
when a delivery callback lands on a terminal Case. The repository below runs
every write through the PostgreSQL codec without a database, so the terminal
storage rule is exercised exactly as the PostgreSQL repository applies it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseRuntimeState,
    DeliveryReceiptRecord,
    OutboxRecord,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.postgres_repository import PostgresCaseRepository
from proxyloop_connectors import BINDING_REF, CHANNEL_KIND, LocalMailboxEventKind
from proxyloop_contracts import (
    CasePhase,
    EventActor,
    Evidence,
    EvidenceType,
    VisibleCaseEvent,
)
from test_phase_06b1_channel_runtime import (
    BASE_TIME,
    _ChannelRepository,
    _create_command,
    _message_event,
)
from test_strategy_basis_binding import _as_stored_1_0

REJECTED = "Case state failed storage validation"
UNPAIRED = "terminal Case callback events do not match their Evidence"
ARTIFACT_HASH = hashlib.sha256(b"artifact").hexdigest()
CALLBACK_CONTENT = {
    "delivered": "The fictional Provider delivered the local reply.",
    "bounced": "The fictional Provider bounced the local reply.",
}


def _round_trip(state: CaseRuntimeState) -> CaseRuntimeState:
    payload: dict[str, Any] = json.loads(
        json.dumps(PostgresCaseRepository._encode_state(state))
    )
    return PostgresCaseRepository._decode_state(
        state.snapshot.case.case_id, state.snapshot.revision, payload
    )


class _CodecChannelRepository(_ChannelRepository):
    """The 06B1 channel seam, with every Case write through the codec."""

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        return super().create(_round_trip(state))

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        return super().replace(
            case_id, expected_revision=expected_revision, state=_round_trip(state)
        )

    def replace_with_channel_outbox(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        outbox: OutboxRecord,
        inbox_event_id: UUID,
    ) -> CaseRuntimeState:
        return super().replace_with_channel_outbox(
            case_id,
            expected_revision=expected_revision,
            state=_round_trip(state),
            outbox=outbox,
            inbox_event_id=inbox_event_id,
        )

    def replace_with_delivery_receipt(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
        inbox_event_id: UUID,
        receipt: DeliveryReceiptRecord,
        outbox_state: str,
    ) -> CaseRuntimeState:
        return super().replace_with_delivery_receipt(
            case_id,
            expected_revision=expected_revision,
            state=_round_trip(state),
            inbox_event_id=inbox_event_id,
            receipt=receipt,
            outbox_state=outbox_state,
        )


def _state(repository: _CodecChannelRepository) -> CaseRuntimeState:
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


def _completed(repository: _CodecChannelRepository) -> tuple[ThinAgentRuntime, UUID]:
    """Send one channel reply, then approve and complete the Case."""

    runtime, delivery_ids = _completed_with_replies(repository, replies=1)
    return runtime, delivery_ids[0]


def _completed_with_replies(
    repository: _CodecChannelRepository,
    *,
    replies: int,
    delivered_before_approval: bool = False,
) -> tuple[ThinAgentRuntime, list[UUID]]:
    """Send channel replies, then approve and complete the Case.

    With ``delivered_before_approval`` the first reply's delivery callback
    lands while the Case is still open, before the approval decision.
    """

    now = [BASE_TIME]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    runtime.apply_command(_create_command())
    delivery_ids: list[UUID] = []
    for _ in range(replies):
        event = _message_event(uuid4())
        inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
        applied = runtime.apply_command(
            CaseCommand(
                schema_version="phase-06b1-v1",
                command_id=inbox.command_id,
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
                occurred_at=event.occurred_at,
                expected_revision=_state(repository).snapshot.revision,
                channel_kind=CHANNEL_KIND,
                binding_ref=BINDING_REF,
                event_id=event.event_id,
                content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
                payload_hash=event.raw_payload_hash,
            )
        )
        assert applied.delivery_id is not None
        accepted = repository.get_outbox_record(applied.delivery_id)
        assert accepted is not None
        repository.outbox[applied.delivery_id] = replace(
            accepted, state="accepted", provider_message_id="local-provider-test"
        )
        delivery_ids.append(applied.delivery_id)
    if delivered_before_approval:
        runtime.apply_command(
            _callback(
                repository,
                delivery_ids[0],
                _state(repository).snapshot.revision,
            )
        )
    now[0] = BASE_TIME + timedelta(minutes=1)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    completed = runtime.apply_command(
        CaseCommand(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=BASE_TIME + timedelta(minutes=2),
            expected_revision=waiting.snapshot.revision,
            approval_id=waiting.approval.approval_id,
            decision="approved",
        )
    )
    assert completed.terminal is True
    assert _state(repository).snapshot.case.phase is CasePhase.COMPLETE
    return runtime, delivery_ids


def _callback(
    repository: _CodecChannelRepository,
    delivery_id: UUID,
    expected_revision: int,
    delivery_status: str = "delivered",
) -> CaseCommand:
    delivery_event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
    inbox = repository.reserve_channel_event(delivery_event, received_at=BASE_TIME)
    return CaseCommand(
        schema_version="phase-06b1-v1",
        command_id=inbox.command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
        occurred_at=BASE_TIME,
        expected_revision=expected_revision,
        channel_kind=CHANNEL_KIND,
        binding_ref=BINDING_REF,
        event_id=delivery_event.event_id,
        delivery_id=delivery_id,
        provider_message_id="local-provider-test",
        delivery_status=delivery_status,
        artifact_hash=ARTIFACT_HASH,
        payload_hash=delivery_event.raw_payload_hash,
    )


def _delivered_after_complete() -> CaseRuntimeState:
    repository = _CodecChannelRepository()
    runtime, delivery_id = _completed(repository)
    before = _state(repository)
    runtime.apply_command(_callback(repository, delivery_id, before.snapshot.revision))
    return _state(repository)


@pytest.mark.parametrize("delivery_status", ["delivered", "bounced"])
def test_first_callback_after_complete_is_stored(delivery_status: str) -> None:
    repository = _CodecChannelRepository()
    runtime, delivery_id = _completed(repository)
    before = _state(repository)
    assert before.snapshot.schema_version == "1.1"
    assert before.snapshot.completion_receipt is not None

    delivered = runtime.apply_command(
        _callback(repository, delivery_id, before.snapshot.revision, delivery_status)
    )

    assert delivered.after_revision == before.snapshot.revision + 1
    assert delivered.delivery_status == delivery_status
    after = _state(repository)
    assert after.snapshot.revision == before.snapshot.revision + 1
    assert after.snapshot.schema_version == "1.1"
    assert after.snapshot.case.phase is CasePhase.COMPLETE
    assert after.snapshot.completion_decision == before.snapshot.completion_decision
    assert after.snapshot.completion_receipt == before.snapshot.completion_receipt
    assert after.execution_source_pins == before.execution_source_pins
    assert after.execution_count == 1
    new_event = after.snapshot.visible_events[-1]
    assert new_event.event_type == "provider_event"
    assert new_event.actor is EventActor.PROVIDER
    assert new_event.content == CALLBACK_CONTENT[delivery_status]
    assert new_event.event_cursor == before.snapshot.event_cursor + 1
    evidence = after.snapshot.evidence[-1]
    assert evidence.source_type is EvidenceType.PROVIDER_EVENT
    assert evidence.source_ref == "local-provider-test"
    assert evidence.content_hash == ARTIFACT_HASH
    assert evidence.observed_at == new_event.occurred_at
    assert after.snapshot.evidence[:-1] == before.snapshot.evidence
    assert len(repository.receipts) == 1

    # A replayed observation of the same delivery is written again as a
    # transition only; the terminal rule still accepts the stored Case.
    replayed = runtime.apply_command(
        _callback(repository, delivery_id, after.snapshot.revision, delivery_status)
    )
    assert replayed.after_revision == after.snapshot.revision
    assert _state(repository).snapshot == after.snapshot
    assert len(repository.receipts) == 1


def test_a_stored_1_0_complete_case_stays_1_0_after_a_callback() -> None:
    repository = _CodecChannelRepository()
    _, delivery_id = _completed(repository)
    completed = _state(repository)
    legacy = _as_stored_1_0(completed)
    repository.replace(
        SCRIPTED_CASE_ID, expected_revision=completed.snapshot.revision, state=legacy
    )
    stored = _state(repository)
    assert stored.snapshot.schema_version == "1.0"
    assert stored.snapshot.completion_receipt is None
    resumed = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)

    delivered = resumed.apply_command(
        _callback(repository, delivery_id, stored.snapshot.revision)
    )

    assert delivered.after_revision == stored.snapshot.revision + 1
    after = _state(repository)
    assert after.snapshot.schema_version == "1.0"
    assert after.snapshot.completion_receipt is None
    assert after.snapshot.completion_decision == stored.snapshot.completion_decision
    assert after.execution_source_pins == stored.execution_source_pins
    assert (
        after.snapshot.planning_basis.planning_basis_fingerprint
        == stored.snapshot.planning_basis.planning_basis_fingerprint
    )


@pytest.mark.parametrize("offset", [1, -1])
def test_a_tampered_source_pin_cursor_is_rejected(offset: int) -> None:
    after = _delivered_after_complete()
    pins = after.execution_source_pins
    assert pins is not None
    tampered = replace(
        after,
        execution_source_pins=pins.model_copy(
            update={"event_cursor": pins.event_cursor + offset}
        ),
    )
    with pytest.raises(RuntimeError, match=REJECTED):
        PostgresCaseRepository._encode_state(tampered)


def _rebuilt(
    state: CaseRuntimeState,
    *,
    events: tuple[VisibleCaseEvent, ...] | None = None,
    evidence: tuple[Evidence, ...] | None = None,
) -> CaseRuntimeState:
    snapshot = state.snapshot
    events = snapshot.visible_events if events is None else events
    rebuilt = runtime_module._snapshot(
        case=snapshot.case,
        ledger=snapshot.fact_ledger,
        strategy=snapshot.strategy,
        offers=snapshot.offers,
        action_intents=snapshot.action_intents,
        approvals=snapshot.approval_requests,
        evidence=snapshot.evidence if evidence is None else evidence,
        completion=snapshot.completion_decision,
        events=events,
        snapshot_revision=snapshot.revision,
        phase=snapshot.case.phase,
        manifest=snapshot.capability_manifest,
        receipt=snapshot.completion_receipt,
        schema_version=snapshot.schema_version,
    )
    return replace(state, snapshot=rebuilt, events=events)


def _with_last_event(state: CaseRuntimeState, **changes: Any) -> CaseRuntimeState:
    snapshot = state.snapshot
    last = snapshot.visible_events[-1]
    event = runtime_module._event(
        snapshot.case.case_id,
        cursor=last.event_cursor,
        occurred_at=last.occurred_at,
        **{
            "event_type": last.event_type,
            "content": last.content,
            "seed": "r10-forged",
            "actor": last.actor,
            **changes,
        },
    )
    return _rebuilt(state, events=(*snapshot.visible_events[:-1], event))


def test_a_rebuilt_callback_event_is_still_accepted() -> None:
    """Control for the forgeries below: only the event itself differs."""

    after = _delivered_after_complete()
    PostgresCaseRepository._encode_state(_with_last_event(after))


@pytest.mark.parametrize(
    "changes",
    [
        {
            "event_type": "consumer_message",
            "content": "Please also cancel my other line.",
            "actor": EventActor.CONSUMER,
        },
        {"content": "The fictional Provider applied a different offer."},
        {"event_type": "provider_message"},
    ],
    ids=["consumer-message", "provider-event-other-content", "provider-message"],
)
def test_a_non_delivery_event_after_the_approval_is_rejected(
    changes: dict[str, Any],
) -> None:
    after = _delivered_after_complete()
    with pytest.raises(RuntimeError, match=REJECTED):
        PostgresCaseRepository._encode_state(_with_last_event(after, **changes))


# R-18: each callback event after the approval cursor is paired, in order,
# with the Provider-event Evidence appended with it after the execution.


def _assert_unpaired(state: CaseRuntimeState) -> None:
    """The codec rejects ``state`` because of the pairing rule itself."""

    with pytest.raises(RuntimeError, match=REJECTED) as raised:
        PostgresCaseRepository._encode_state(state)
    assert raised.value.__suppress_context__ is True
    assert str(raised.value.__context__) == UNPAIRED


def _forged_callback_event(state: CaseRuntimeState) -> VisibleCaseEvent:
    last = state.snapshot.visible_events[-1]
    return runtime_module._event(
        state.snapshot.case.case_id,
        cursor=last.event_cursor + 1,
        occurred_at=last.occurred_at,
        event_type="provider_event",
        content=CALLBACK_CONTENT["delivered"],
        seed="r18-forged",
        actor=EventActor.PROVIDER,
    )


@pytest.mark.parametrize("delivery_status", ["delivered", "bounced"])
def test_two_callbacks_after_complete_are_stored(delivery_status: str) -> None:
    repository = _CodecChannelRepository()
    runtime, delivery_ids = _completed_with_replies(repository, replies=2)
    for delivery_id, status in zip(
        delivery_ids, ["delivered", delivery_status], strict=True
    ):
        runtime.apply_command(
            _callback(
                repository,
                delivery_id,
                _state(repository).snapshot.revision,
                status,
            )
        )

    after = _state(repository)
    assert [event.content for event in after.snapshot.visible_events[-2:]] == [
        CALLBACK_CONTENT["delivered"],
        CALLBACK_CONTENT[delivery_status],
    ]
    assert [item.source_type for item in after.snapshot.evidence[-2:]] == [
        EvidenceType.PROVIDER_EVENT,
        EvidenceType.PROVIDER_EVENT,
    ]
    assert _round_trip(after).snapshot == after.snapshot


def test_a_callback_before_approval_and_one_after_complete_are_stored() -> None:
    repository = _CodecChannelRepository()
    runtime, delivery_ids = _completed_with_replies(
        repository, replies=2, delivered_before_approval=True
    )
    completed = _state(repository)
    assert [
        item.source_type is EvidenceType.PROVIDER_EVENT
        for item in completed.snapshot.evidence
    ].count(True) == 1

    runtime.apply_command(
        _callback(repository, delivery_ids[1], completed.snapshot.revision, "bounced")
    )

    after = _state(repository)
    assert after.snapshot.revision == completed.snapshot.revision + 1
    assert _round_trip(after).snapshot == after.snapshot


def test_a_forged_callback_event_without_evidence_is_rejected() -> None:
    after = _delivered_after_complete()
    forged = _rebuilt(
        after,
        events=(*after.snapshot.visible_events, _forged_callback_event(after)),
    )
    _assert_unpaired(forged)


def test_a_forged_callback_event_on_a_completed_case_is_rejected() -> None:
    repository = _CodecChannelRepository()
    _completed(repository)
    completed = _state(repository)
    forged = _rebuilt(
        completed,
        events=(
            *completed.snapshot.visible_events,
            _forged_callback_event(completed),
        ),
    )
    _assert_unpaired(forged)


def test_a_deleted_callback_event_whose_evidence_remains_is_rejected() -> None:
    after = _delivered_after_complete()
    forged = _rebuilt(after, events=after.snapshot.visible_events[:-1])
    _assert_unpaired(forged)


def test_provider_event_evidence_without_a_callback_event_is_rejected() -> None:
    after = _delivered_after_complete()
    extra = after.snapshot.evidence[-1].model_copy(update={"evidence_id": uuid4()})
    forged = _rebuilt(after, evidence=(*after.snapshot.evidence, extra))
    _assert_unpaired(forged)


def test_a_callback_evidence_at_another_time_is_rejected() -> None:
    after = _delivered_after_complete()
    last = after.snapshot.evidence[-1]
    shifted = last.model_copy(
        update={
            "observed_at": last.observed_at + timedelta(seconds=1),
            "captured_at": last.captured_at + timedelta(seconds=1),
        }
    )
    forged = _rebuilt(after, evidence=(*after.snapshot.evidence[:-1], shifted))
    _assert_unpaired(forged)


# Evidence requires captured_at >= observed_at, so observed_at moves earlier.
@pytest.mark.parametrize(
    ("field", "seconds"), [("observed_at", -1), ("captured_at", 1)]
)
def test_a_callback_evidence_with_one_shifted_time_is_rejected(
    field: str, seconds: int
) -> None:
    after = _delivered_after_complete()
    last = after.snapshot.evidence[-1]
    shifted = last.model_copy(
        update={field: getattr(last, field) + timedelta(seconds=seconds)}
    )
    _assert_unpaired(_rebuilt(after, evidence=(*after.snapshot.evidence[:-1], shifted)))


def test_a_callback_evidence_moved_before_the_confirmation_is_rejected() -> None:
    after = _delivered_after_complete()
    *earlier, callback = after.snapshot.evidence
    confirmation = next(
        index
        for index, item in enumerate(earlier)
        if item.source_type is EvidenceType.CONFIRMATION
    )
    moved = (*earlier[:confirmation], callback, *earlier[confirmation:])
    _assert_unpaired(_rebuilt(after, evidence=moved))


def test_an_exact_duplicate_of_a_callback_pair_is_rejected() -> None:
    after = _delivered_after_complete()
    event = after.snapshot.visible_events[-1]
    duplicate = event.model_copy(update={"event_cursor": event.event_cursor + 1})
    _assert_unpaired(
        _rebuilt(
            after,
            events=(*after.snapshot.visible_events, duplicate),
            evidence=(*after.snapshot.evidence, after.snapshot.evidence[-1]),
        )
    )
