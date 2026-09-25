"""Slow's admitted proposal drives the intent (PR-13).

The Runtime compiles an Action Intent and an Approval Request only from the
Case's standing proposal: the capability proposal of the last admitted Slow
result, still admissible at the event time, naming an offer that
deterministic policy finds compliant. A Slow result that fails the A-3
coordinator admission check is rejected as a whole.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from proxyloop_agent_core import (
    FastAdapterResult,
    ScriptedDialogueFastAdapter,
    ScriptedProposingSlowAdapter,
    ScriptedSlowAdapter,
)
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    ASSISTANT_MESSAGE_EVENT_TYPE,
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ModelRuntimeError,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.postgres_repository import PostgresCaseRepository
from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    CapabilityArgument,
    CapabilityProposal,
    CapabilityReference,
    CasePhase,
    EventActor,
    FastModelView,
    ModelResult,
    Money,
    OfferReference,
    ProviderOffer,
    SlowWorkRequest,
    SlowWorkResult,
    StrategyPacket,
    material_terms_hash,
    offer_material_terms,
)
from test_phase_04b_model_runtime import (
    _adapter,
    _fast_output,
    _Response,
    _slow_output,
    _slow_output_proposing_accept,
)
from test_phase_04c_persistent_case_store import _assert_non_provider_fields_equal
from test_phase_06b1_channel_runtime import (
    BASE_TIME,
    _ChannelRepository,
    _create_command,
)
from test_r10_terminal_delivery_callback import (
    _callback,
    _CodecChannelRepository,
    _round_trip,
    _state,
)
from test_slow_refresh_strategy_expiry import _channel_command

T0 = datetime(2035, 1, 1, tzinfo=UTC)


class SteppingClock:
    """A UTC clock that advances one second per read."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _with_pair(
    request: SlowWorkRequest,
    base: SlowWorkResult,
    *,
    offer: ProviderOffer,
    action_type: ActionType = ActionType.ACCEPT_OFFER,
    capability_id: str = "simulator.accept_fictional_offer",
    version: str = "1.0",
    offer_argument: str | None = None,
    expires_at: datetime,
) -> SlowWorkResult:
    """``base`` plus one hand-built capability/action pair."""

    strategy: StrategyPacket | None = base.strategy_proposal
    assert strategy is not None
    terms = offer_material_terms(offer)
    action = ActionIntent(
        contract_type="action_intent",
        schema_version="1.0",
        revision=1,
        intent_id=UUID("11111111-1111-4111-8111-111111111111"),
        case_id=request.case_id,
        case_revision=request.pins.case_revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        constraint_set_revision=request.pins.constraint_set_revision,
        action_type=action_type,
        offer_ref=OfferReference(
            offer_id=offer.offer_id, offer_revision=offer.revision
        ),
        material_terms=terms,
        material_terms_hash=material_terms_hash(terms),
        approval_required=True,
        idempotency_key="test:pair",
        created_at=request.created_at,
        expires_at=expires_at,
    )
    capability = CapabilityProposal(
        proposal_id=UUID("22222222-2222-4222-8222-222222222222"),
        capability=CapabilityReference(
            namespace="simulator", capability_id=capability_id, version=version
        ),
        arguments=(
            CapabilityArgument(
                name="offer_id", value=offer_argument or str(offer.offer_id)
            ),
        ),
        created_at=request.created_at,
        expires_at=expires_at,
    )
    return SlowWorkResult.model_validate(
        {
            **dict(base),
            "capability_proposals": (capability,),
            "action_proposals": (action,),
        }
    )


class IncoherentProposalSlow(ScriptedSlowAdapter):
    """An END_INTERACTION action beside a capability outside the manifest."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return _with_pair(
            request,
            super().reason(request),
            offer=request.view.offers[0],
            action_type=ActionType.END_INTERACTION,
            capability_id="simulator.not_in_manifest",
            version="9.9",
            offer_argument="not-an-offer",
            expires_at=request.created_at + timedelta(minutes=5),
        )


class LongLivedProposalSlow(ScriptedSlowAdapter):
    """A coherent accept proposal that outlives the offer it names."""

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return _with_pair(
            request,
            super().reason(request),
            offer=request.view.offers[0],
            expires_at=request.created_at + timedelta(hours=3),
        )


# -- R1-R3: red on main -------------------------------------------------------


def test_slow_without_proposal_opens_no_approval() -> None:
    # R1 / criterion 1: a strategy-only Slow ("continue-dialogue").
    runtime = ThinAgentRuntime(clock=SteppingClock(), slow=ScriptedSlowAdapter())
    runtime.create_case(occurred_at=T0)

    result = runtime.append_event(
        SCRIPTED_CASE_ID, content="Please review the current offer."
    )

    assert result.approval is None
    assert result.snapshot.approval_requests == ()
    assert result.snapshot.action_intents == ()
    assert result.snapshot.case.phase is CasePhase.STRATEGY
    line = result.snapshot.visible_events[-1]
    assert (line.event_type, line.actor) == (
        ASSISTANT_MESSAGE_EVENT_TYPE,
        EventActor.SYSTEM,
    )
    assert (
        sum(
            event.event_type == ASSISTANT_MESSAGE_EVENT_TYPE
            for event in result.snapshot.visible_events
        )
        == 1
    )


def test_incoherent_slow_proposal_is_rejected_and_traced() -> None:
    # R2 / criterion 2: the result is refused as a whole; no Case is written.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), slow=IncoherentProposalSlow()
    )

    with pytest.raises(ModelRuntimeError) as raised:
        runtime.create_case(occurred_at=T0)

    assert raised.value.source == "slow"
    assert repository.get(SCRIPTED_CASE_ID) is None
    (trace,) = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert trace.role == "slow"
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == (
        "slow_proposal_capability_unsupported",
        "slow_proposal_offer_binding_mismatch",
        "slow_proposal_action_not_delegated",
    )
    assert trace.output_ref is not None


def test_model_slow_without_next_capability_opens_no_approval() -> None:
    # R3 / criterion 4: a model Slow that proposes nothing opens no approval.
    adapter, transport = _adapter(_Response(_slow_output()), _Response(_fast_output()))
    runtime = ThinAgentRuntime(fast=adapter, slow=adapter)

    created = runtime.create_case()
    result = runtime.append_event(
        created.snapshot.case.case_id, content="Please review the current offer."
    )

    assert result.approval is None
    assert result.snapshot.case.phase is CasePhase.STRATEGY
    assert result.snapshot.visible_events[-1].event_type == (
        ASSISTANT_MESSAGE_EVENT_TYPE
    )
    assert len(transport.calls) == 2


def test_model_slow_accept_proposal_opens_the_approval() -> None:
    # Criterion 4, the other direction: the compiled accept pair is admitted.
    adapter, _ = _adapter(
        _Response(_slow_output_proposing_accept()), _Response(_fast_output())
    )
    runtime = ThinAgentRuntime(fast=adapter, slow=adapter)

    created = runtime.create_case()
    result = runtime.append_event(
        created.snapshot.case.case_id, content="Please review the current offer."
    )

    assert result.approval is not None
    assert result.snapshot.case.phase is CasePhase.AWAITING_APPROVAL


# -- D1: the default scripted Runtime reproduces main --------------------------

# Consumer-event offsets and whether main opens the approval there: the offer
# lives 60 minutes and a strategy 30, so +31 minutes refreshes first.
OFFSETS = [
    (timedelta(seconds=1), True),
    (timedelta(minutes=29), True),
    (timedelta(minutes=31), True),
    (timedelta(minutes=59, seconds=59), True),
    (timedelta(minutes=60), False),
    (timedelta(minutes=61), False),
]


def _consumer_event_at(path: str, offset: timedelta) -> CaseRuntimeState:
    runtime = ThinAgentRuntime(clock=SteppingClock())
    at = T0 + offset
    if path == "direct":
        runtime.create_case(occurred_at=T0)
        runtime.append_event(
            SCRIPTED_CASE_ID, content="Please review the offer.", occurred_at=at
        )
    else:
        created = runtime.apply_command(
            CaseCommand(
                command_id=uuid4(),
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
                command_id=uuid4(),
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.APPEND_EVENT,
                occurred_at=at,
                expected_revision=created.after_revision,
                content="Please review the offer.",
                event_type="consumer_message",
            )
        )
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


@pytest.mark.parametrize("path", ["direct", "command"])
@pytest.mark.parametrize(("offset", "opens"), OFFSETS)
def test_the_default_runtime_opens_exactly_the_approvals_main_opens(
    path: str, offset: timedelta, opens: bool
) -> None:
    at = T0 + offset
    state = _consumer_event_at(path, offset)
    snapshot = state.snapshot
    (offer,) = snapshot.offers

    # Main's rule: approval iff the offer is compliant at the event time.
    compliant = not runtime_module.offer_compliance_violations_for_case(
        snapshot.case, offer, evaluated_at=at
    )
    assert compliant is opens
    assert snapshot.visible_events[-1].event_type == ASSISTANT_MESSAGE_EVENT_TYPE
    if opens:
        # The unchanged compiler, with main's arguments, gives the same bytes.
        intent, approval = runtime_module._build_approval(
            snapshot.case,
            snapshot.strategy,
            offer,
            requested_at=at,
            manifest=snapshot.capability_manifest,
        )
        assert snapshot.action_intents == (intent,)
        assert snapshot.approval_requests == (approval,)
        assert snapshot.case.phase is CasePhase.AWAITING_APPROVAL
        assert state.standing_proposal is None
    else:
        assert snapshot.action_intents == snapshot.approval_requests == ()
        assert snapshot.case.phase is CasePhase.STRATEGY


# -- D2: the standing proposal's lifecycle -------------------------------------


def _accepted(repository: _CodecChannelRepository, delivery_id: UUID) -> None:
    outbox = repository.get_outbox_record(delivery_id)
    assert outbox is not None
    repository.outbox[delivery_id] = replace(
        outbox, state="accepted", provider_message_id="local-provider-test"
    )


def test_every_non_refresh_transition_carries_the_standing_proposal() -> None:
    # Every write goes through the PostgreSQL codec (no database needed).
    repository = _CodecChannelRepository()
    now = [BASE_TIME]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    runtime.apply_command(_create_command())
    created = _state(repository)
    proposal = created.standing_proposal
    (offer,) = created.snapshot.offers
    assert proposal is not None
    assert proposal.expires_at == offer.expires_at

    # A channel ingest without a refresh.
    ingested = runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=5))
    )
    assert _state(repository).standing_proposal == proposal
    assert ingested.delivery_id is not None

    # A first delivery callback, its exact replay, and a second callback for
    # the same observation (the receipt-deduplicated write).
    _accepted(repository, ingested.delivery_id)
    callback = _callback(
        repository, ingested.delivery_id, _state(repository).snapshot.revision
    )
    runtime.apply_command(callback)
    assert _state(repository).standing_proposal == proposal
    revision = _state(repository).snapshot.revision
    assert runtime.apply_command(callback).deduplicated is True
    assert _state(repository).snapshot.revision == revision
    runtime.apply_command(_callback(repository, ingested.delivery_id, revision))
    assert _state(repository).standing_proposal == proposal

    # The consumer event that opens the approval consumes it.
    now[0] = BASE_TIME + timedelta(minutes=10)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    assert _state(repository).standing_proposal is None


def test_each_admitted_refresh_replaces_the_standing_proposal() -> None:
    repository = _CodecChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    first = _state(repository).standing_proposal
    assert first is not None

    # The strategy expired: the refresh's proposal replaces the first.
    runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=31))
    )
    second = _state(repository).standing_proposal
    assert second is not None
    assert second.proposal_id != first.proposal_id
    assert second.created_at == BASE_TIME + timedelta(minutes=31)

    # After the offer expired the refresh proposes nothing: replaced by None.
    runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=61))
    )
    assert _state(repository).standing_proposal is None


def test_a_case_with_a_decided_approval_holds_no_standing_proposal() -> None:
    repository = _CodecChannelRepository()
    now = [BASE_TIME + timedelta(minutes=5)]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    runtime.apply_command(_create_command())
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    runtime.approve(
        SCRIPTED_CASE_ID,
        waiting.approval.approval_id,
        decision="rejected",
        occurred_at=BASE_TIME + timedelta(minutes=6),
    )
    logged = len(repository.list_model_traces(SCRIPTED_CASE_ID))

    # The rejection changed the planning basis: the channel event refreshes,
    # and the admitted result's proposal is not installed beside the approval.
    runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=7))
    )

    slow, judge, _fast = repository.list_model_traces(SCRIPTED_CASE_ID)[logged:]
    assert (slow.role, slow.result) == ("slow", ModelResult.SUCCEEDED)
    assert judge.role == "judge"
    assert _state(repository).standing_proposal is None


def test_a_standing_proposal_cannot_sit_beside_an_approval() -> None:
    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    created = runtime.repository.get(SCRIPTED_CASE_ID)
    assert created is not None and created.standing_proposal is not None
    runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    waiting = runtime.repository.get(SCRIPTED_CASE_ID)
    assert waiting is not None and waiting.snapshot.approval_requests

    with pytest.raises(ValueError, match="standing proposal"):
        replace(waiting, standing_proposal=created.standing_proposal)


# -- D3: policy stays the authority --------------------------------------------


def test_a_proposal_outliving_its_offer_opens_no_approval() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), slow=LongLivedProposalSlow()
    )
    runtime.create_case(occurred_at=T0)

    # +61 minutes: the refresh admits a proposal for the (expired) offer.
    result = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Please review the offer.",
        occurred_at=T0 + timedelta(minutes=61),
    )

    assert [
        (trace.role, trace.result)
        for trace in repository.list_model_traces(SCRIPTED_CASE_ID)
    ] == [
        ("slow", ModelResult.SUCCEEDED),
        ("judge", ModelResult.SUCCEEDED),
        ("slow", ModelResult.SUCCEEDED),
        ("judge", ModelResult.SUCCEEDED),
        ("fast", ModelResult.SUCCEEDED),
    ]
    assert result.approval is None
    assert result.snapshot.case.phase is CasePhase.STRATEGY
    assert result.snapshot.visible_events[-1].event_type == (
        ASSISTANT_MESSAGE_EVENT_TYPE
    )
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    # Not consumed: only an approval consumes it.
    assert state.standing_proposal is not None
    assert state.standing_proposal.created_at == T0 + timedelta(minutes=61)


class _IncoherentOnRefreshSlow(ScriptedProposingSlowAdapter):
    """Coherent on create; an END_INTERACTION accept-capability pair after."""

    def __init__(self) -> None:
        self.calls = 0

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        self.calls += 1
        if self.calls == 1:
            return super().reason(request)
        return _with_pair(
            request,
            ScriptedSlowAdapter.reason(self, request),
            offer=request.view.offers[0],
            action_type=ActionType.END_INTERACTION,
            expires_at=request.created_at + timedelta(minutes=5),
        )


@pytest.mark.parametrize("path", ["append", "channel"])
def test_an_a3_rejected_refresh_fails_the_command_and_keeps_the_state(
    path: str,
) -> None:
    # M4: the A-3 check also guards a refresh; nothing of the result is used.
    repository = _CodecChannelRepository()
    runtime = ThinAgentRuntime(
        repository, clock=lambda: BASE_TIME, slow=_IncoherentOnRefreshSlow()
    )
    runtime.apply_command(_create_command())
    before = _state(repository)
    at = BASE_TIME + timedelta(minutes=31)  # the strategy expired
    if path == "append":
        command = CaseCommand(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.APPEND_EVENT,
            occurred_at=at,
            expected_revision=before.snapshot.revision,
            content="Is the offer ready?",
            event_type="consumer_message",
        )
    else:
        command = _channel_command(repository, at)

    with pytest.raises(ModelRuntimeError) as raised:
        runtime.apply_command(command)

    assert raised.value.source == "slow"
    after = _state(repository)
    assert after.snapshot == before.snapshot
    assert after.standing_proposal == before.standing_proposal
    trace = repository.list_model_traces(SCRIPTED_CASE_ID)[-1]
    assert (trace.role, trace.result) == ("slow", ModelResult.REJECTED)
    assert trace.reason_codes == (
        "slow_proposal_capability_action_mismatch",
        "slow_proposal_action_not_delegated",
    )
    if path == "channel":
        assert command.event_id is not None
        inbox = repository.get_inbox_receipt(command.event_id)
        assert inbox is not None and inbox.processing_state == "reserved"


# -- D4: identity and the single coordinator site ------------------------------


def test_the_default_slow_proposes_and_is_still_labelled_scripted() -> None:
    runtime = ThinAgentRuntime()

    assert isinstance(runtime._slow, ScriptedProposingSlowAdapter)
    assert runtime.adapter_mode == "scripted"
    source = inspect.getsource(runtime_module)
    assert source.count(".advance(") == 1
    assert source.count("CaseCoordinator(") == 1
    assert source.count("slow_proposal_check=slow_proposal_violations") == 1


# -- D5: the standing proposal is Runtime-local --------------------------------


def test_no_body_or_trace_carries_the_standing_proposal() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock())

    async def scenario() -> str:
        transport = httpx.ASGITransport(app=create_app(runtime))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            created = await client.post(
                "/cases",
                json={
                    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
                    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
                    "mobile_hotspot_required": True,
                    "device_financing_change_forbidden": True,
                },
            )
            assert created.status_code == 201
            read = await client.get(f"/cases/{SCRIPTED_CASE_ID}")
            return created.text + read.text

    bodies = asyncio.run(scenario())
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None and state.standing_proposal is not None
    traces = json.dumps(
        [
            trace.model_dump(mode="json")
            for trace in repository.list_model_traces(SCRIPTED_CASE_ID)
        ]
    )
    for text in (bodies, traces, state.snapshot.model_dump_json()):
        assert str(state.standing_proposal.proposal_id) not in text
        assert "standing" not in text


# -- The storage codec (no database) -------------------------------------------


def _created_state() -> CaseRuntimeState:
    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None and state.standing_proposal is not None
    return state


def _waiting_state() -> CaseRuntimeState:
    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None and state.snapshot.approval_requests
    return state


def _payload(state: CaseRuntimeState) -> dict[str, Any]:
    encoded: dict[str, Any] = json.loads(
        json.dumps(PostgresCaseRepository._encode_state(state))
    )
    return encoded


def _decode(state: CaseRuntimeState, payload: dict[str, Any]) -> CaseRuntimeState:
    return PostgresCaseRepository._decode_state(
        state.snapshot.case.case_id, state.snapshot.revision, payload
    )


def test_the_codec_round_trips_a_standing_proposal() -> None:
    created = _created_state()

    assert "standing_proposal" in _payload(created)
    _assert_non_provider_fields_equal(created, _round_trip(created))


def test_without_a_proposal_the_row_is_the_pre_pr13_document() -> None:
    waiting = _waiting_state()

    assert "standing_proposal" not in _payload(waiting)
    _assert_non_provider_fields_equal(waiting, _round_trip(waiting))


def test_a_pre_pr13_version_3_row_decodes_with_no_standing_proposal() -> None:
    created = _created_state()
    payload = _payload(created)
    del payload["standing_proposal"]

    decoded = _decode(created, payload)

    assert decoded.standing_proposal is None
    assert decoded.snapshot == created.snapshot


def _proposal_json(state: CaseRuntimeState) -> dict[str, Any]:
    proposal = _payload(state)["standing_proposal"]
    assert isinstance(proposal, dict)
    return proposal


def _beside_an_approval(payload: dict[str, Any], proposal: dict[str, Any]) -> None:
    payload["standing_proposal"] = proposal


def _unknown_capability(payload: dict[str, Any], proposal: dict[str, Any]) -> None:
    proposal["capability"]["capability_id"] = "simulator.unknown"
    payload["standing_proposal"] = proposal


def _foreign_offer(payload: dict[str, Any], proposal: dict[str, Any]) -> None:
    proposal["arguments"] = [{"name": "offer_id", "value": str(uuid4())}]
    payload["standing_proposal"] = proposal


@pytest.mark.parametrize(
    ("row", "edit"),
    [
        ("waiting", _beside_an_approval),
        ("created", _unknown_capability),
        ("created", _foreign_offer),
    ],
)
def test_the_codec_refuses_an_impossible_standing_proposal(row: str, edit: Any) -> None:
    created = _created_state()
    state = _waiting_state() if row == "waiting" else created
    payload = _payload(state)
    edit(payload, _proposal_json(created))

    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        _decode(state, payload)


def test_the_codec_refuses_to_write_a_foreign_offer_proposal() -> None:
    created = _created_state()
    assert created.standing_proposal is not None
    foreign = created.standing_proposal.model_copy(
        update={"arguments": (CapabilityArgument(name="offer_id", value="elsewhere"),)}
    )

    with pytest.raises(RuntimeError, match="failed storage validation"):
        PostgresCaseRepository._encode_state(
            replace(created, standing_proposal=foreign)
        )


# -- M-3: a replayed command is re-checked inside the Case lane -----------------


class _HeldFast(ScriptedDialogueFastAdapter):
    """Holds the first Fast call until released; later calls pass through."""

    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def decide(self, view: FastModelView) -> FastAdapterResult:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            assert self.release.wait(10)
        return super().decide(view)


class _WatchedRepository(InMemoryCaseRepository):
    """Signals when a watched thread first reads a Case."""

    def __init__(self) -> None:
        super().__init__()
        self.watched: threading.Thread | None = None
        self.read = threading.Event()

    def get(self, case_id: UUID) -> CaseRuntimeState | None:
        if threading.current_thread() is self.watched:
            self.read.set()
        return super().get(case_id)


def _unpinned_event(command_id: UUID, at: datetime) -> CaseCommand:
    # No expected_revision: the API allows it (EventCommand.expected_revision).
    return CaseCommand(
        command_id=command_id,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        occurred_at=at,
        content="Please review the offer.",
        event_type="consumer_message",
    )


def _consumer_turns(repository: InMemoryCaseRepository) -> tuple[int, int]:
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    events = state.snapshot.visible_events
    return (
        sum(event.event_type == "consumer_message" for event in events),
        sum(event.event_type == ASSISTANT_MESSAGE_EVENT_TYPE for event in events),
    )


@pytest.mark.parametrize(
    ("slow", "offset", "model_calls"),
    [
        # A Slow that proposes nothing: the turn applies without an approval.
        pytest.param(ScriptedSlowAdapter, timedelta(minutes=1), 1, id="dialogue"),
        # The default Slow after the offer expired: refresh (Slow, then its
        # Judge call), then no approval.
        pytest.param(
            ScriptedProposingSlowAdapter,
            timedelta(minutes=61),
            3,
            id="offer-expired",
        ),
    ],
)
def test_a_concurrent_retry_of_an_unpinned_event_applies_once(
    slow: type[ScriptedSlowAdapter], offset: timedelta, model_calls: int
) -> None:
    # The retry passes the receipt check before the first attempt writes,
    # then waits on the Case lane. No approval opens, so nothing else
    # refuses the second attempt.
    repository = _WatchedRepository()
    fast = _HeldFast()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=fast, slow=slow()
    )
    runtime.create_case(occurred_at=T0)
    created_traces = len(repository.list_model_traces(SCRIPTED_CASE_ID))
    command = _unpinned_event(uuid4(), T0 + offset)
    receipts: dict[str, Any] = {}

    def attempt(name: str) -> None:
        receipts[name] = runtime.apply_command(command)

    first = threading.Thread(target=attempt, args=("first",))
    first.start()
    assert fast.entered.wait(10)
    retry = threading.Thread(target=attempt, args=("retry",))
    repository.watched = retry
    retry.start()
    assert repository.read.wait(10)
    fast.release.set()
    first.join(10)
    retry.join(10)

    assert _consumer_turns(repository) == (1, 1)
    assert receipts["first"].deduplicated is False
    assert receipts["retry"] == receipts["first"].model_copy(
        update={"deduplicated": True}
    )
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert [t.command_id for t in state.transitions].count(command.command_id) == 1
    assert state.snapshot.approval_requests == ()
    # The retry made no model call: only the first attempt's are traced.
    traces = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert len(traces) == created_traces + model_calls
    assert fast.calls == 1


def test_a_retry_after_a_timeout_returns_the_stored_receipt() -> None:
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), slow=ScriptedSlowAdapter()
    )
    runtime.create_case(occurred_at=T0)
    command = _unpinned_event(uuid4(), T0 + timedelta(minutes=1))

    applied = runtime.apply_command(command)
    # The caller timed out and retries the identical command.
    replayed = runtime.apply_command(command)

    assert replayed == applied.model_copy(update={"deduplicated": True})
    assert _consumer_turns(repository) == (1, 1)


@pytest.mark.parametrize("decision", ["approved", "rejected", "expired"])
def test_the_lane_refuses_a_replayed_approval_command_without_a_write(
    decision: str,
) -> None:
    # What a raced retry reaches after apply_command's receipt check: the
    # decided approval refuses it before any model call or write, so
    # apply_command returns the stored receipt.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    approval = waiting.approval
    assert approval is not None
    command_id = uuid4()
    if decision == "expired":
        command = CaseCommand(
            command_id=command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.EXPIRE_APPROVAL,
            occurred_at=approval.expires_at,
            expected_revision=waiting.snapshot.revision,
            approval_id=approval.approval_id,
            approval_expires_at=approval.expires_at,
        )
    else:
        command = CaseCommand(
            command_id=command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=T0 + timedelta(minutes=2),
            approval_id=approval.approval_id,
            decision=decision,
        )
    applied = runtime.apply_command(command)
    before = repository.get(SCRIPTED_CASE_ID)
    traces = len(repository.list_model_traces(SCRIPTED_CASE_ID))

    with pytest.raises(runtime_module.CaseConflictError):
        if decision == "expired":
            runtime.expire_approval(
                SCRIPTED_CASE_ID,
                approval.approval_id,
                expected_revision=waiting.snapshot.revision,
                expires_at=approval.expires_at,
                command_id=command_id,
            )
        else:
            runtime.approve(
                SCRIPTED_CASE_ID,
                approval.approval_id,
                decision=decision,  # type: ignore[arg-type]
                occurred_at=T0 + timedelta(minutes=2),
                command_id=command_id,
            )

    assert repository.get(SCRIPTED_CASE_ID) is before
    assert len(repository.list_model_traces(SCRIPTED_CASE_ID)) == traces
    assert runtime.apply_command(command) == applied.model_copy(
        update={"deduplicated": True}
    )


def test_a_raced_create_with_the_same_command_applies_once() -> None:
    # Create has no lane: the repository's create uniqueness refuses the
    # second write and apply_command returns the stored receipt.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock())
    command = CaseCommand(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        occurred_at=T0,
        current_monthly_total=Money(amount_minor=9200, currency="USD"),
        target_monthly_total=Money(amount_minor=7500, currency="USD"),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )
    applied = runtime.apply_command(command)
    before = repository.get(SCRIPTED_CASE_ID)

    with pytest.raises(runtime_module.CaseConflictError):
        runtime.create_case(
            current_monthly_total=command.current_monthly_total,
            target_monthly_total=command.target_monthly_total,
            command_id=command.command_id,
            expected_case_id=SCRIPTED_CASE_ID,
            occurred_at=T0,
        )

    assert repository.get(SCRIPTED_CASE_ID) is before
    assert runtime.apply_command(command) == applied.model_copy(
        update={"deduplicated": True}
    )


class _WatchedChannelRepository(_ChannelRepository):
    """Signals when a watched thread has read its inbox reservation."""

    def __init__(self) -> None:
        super().__init__()
        self.watched: threading.Thread | None = None
        self.read = threading.Event()

    def get_inbox_receipt(self, event_id: UUID) -> Any:
        receipt = super().get_inbox_receipt(event_id)
        if threading.current_thread() is self.watched:
            self.read.set()
        return receipt


def test_a_concurrent_retry_of_a_channel_ingest_makes_no_model_call() -> None:
    # The retry reads the still-reserved inbox before the first attempt
    # writes, then waits on the Case lane; it must stop before the model.
    repository = _WatchedChannelRepository()
    fast = _HeldFast()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME, fast=fast)
    runtime.apply_command(_create_command())
    # Unpinned: a channel command may omit expected_revision.
    command = _channel_command(repository, BASE_TIME + timedelta(minutes=5)).model_copy(
        update={"expected_revision": None}
    )
    receipts: dict[str, Any] = {}

    def attempt(name: str) -> None:
        receipts[name] = runtime.apply_command(command)

    first = threading.Thread(target=attempt, args=("first",))
    first.start()
    assert fast.entered.wait(10)
    retry = threading.Thread(target=attempt, args=("retry",))
    repository.watched = retry
    retry.start()
    assert repository.read.wait(10)
    fast.release.set()
    first.join(10)
    retry.join(10)

    assert fast.calls == 1
    assert receipts["retry"] == receipts["first"].model_copy(
        update={"deduplicated": True}
    )
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert [t.command_id for t in state.transitions].count(command.command_id) == 1


class _HeldDeliveryRepository(_CodecChannelRepository):
    """Holds the first delivery write; signals when the retry read its inbox."""

    def __init__(self) -> None:
        super().__init__()
        self.watched: threading.Thread | None = None
        self.read = threading.Event()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.writes = 0

    def get_inbox_receipt(self, event_id: UUID) -> Any:
        receipt = super().get_inbox_receipt(event_id)
        if threading.current_thread() is self.watched:
            self.read.set()
        return receipt

    def replace_with_delivery_receipt(self, case_id: UUID, **kwargs: Any) -> Any:
        self.writes += 1
        if self.writes == 1:
            self.entered.set()
            assert self.release.wait(10)
        return super().replace_with_delivery_receipt(case_id, **kwargs)


def test_a_concurrent_retry_of_a_delivery_callback_records_once() -> None:
    repository = _HeldDeliveryRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    ingested = runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=5))
    )
    assert ingested.delivery_id is not None
    _accepted(repository, ingested.delivery_id)
    # Unpinned: a channel command may omit expected_revision.
    command = _callback(
        repository, ingested.delivery_id, _state(repository).snapshot.revision
    ).model_copy(update={"expected_revision": None})
    receipts: dict[str, Any] = {}

    def attempt(name: str) -> None:
        receipts[name] = runtime.apply_command(command)

    first = threading.Thread(target=attempt, args=("first",))
    first.start()
    assert repository.entered.wait(10)
    retry = threading.Thread(target=attempt, args=("retry",))
    repository.watched = retry
    retry.start()
    assert repository.read.wait(10)
    repository.release.set()
    first.join(10)
    retry.join(10)

    assert repository.writes == 1
    assert receipts["retry"] == receipts["first"].model_copy(
        update={"deduplicated": True}
    )
    state = _state(repository)
    assert [t.command_id for t in state.transitions].count(command.command_id) == 1


def test_two_first_callbacks_that_both_pass_the_relookup_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review re-check (scratch rev-pr13/delivery_race.py): the in-lane receipt
    # re-lookup and the first-callback write are separate lane entries. Both
    # unpinned callbacks find no receipt in the first, then take the second
    # one in turn; the later one must be a duplicate, not a second write.
    repository = _CodecChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    ingested = runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=5))
    )
    assert ingested.delivery_id is not None
    _accepted(repository, ingested.delivery_id)
    command = _callback(
        repository, ingested.delivery_id, _state(repository).snapshot.revision
    ).model_copy(update={"expected_revision": None})
    lane = runtime._lane
    barrier = threading.Barrier(2)
    entries: dict[int, int] = {}

    @contextmanager
    def held_lane(case_id: UUID) -> Iterator[None]:
        thread = threading.get_ident()
        entries[thread] = entries.get(thread, 0) + 1
        if entries[thread] == 2:  # about to enter the first-callback write
            barrier.wait(timeout=10)
        with lane(case_id):
            yield

    monkeypatch.setattr(runtime, "_lane", held_lane)
    results: dict[int, Any] = {}

    def attempt(index: int) -> None:
        try:
            results[index] = runtime.apply_command(command)
        except Exception as error:
            results[index] = error

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert sorted(entries.values()) == [2, 2]
    receipts = list(results.values())
    assert all(not isinstance(item, Exception) for item in receipts), receipts
    assert sorted(item.deduplicated for item in receipts) == [False, True]
    state = _state(repository)
    assert [t.command_id for t in state.transitions].count(command.command_id) == 1
