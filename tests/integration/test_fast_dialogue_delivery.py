"""Fast dialogue reaches the Case as a gated assistant message (PR-8 Stage 1a)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from proxyloop_agent_core import (
    BOUNDED_FAST_STATUS_TEXT,
    SCRIPTED_DIALOGUE_LINES,
    FastAdapterResult,
    ScriptedFastAdapter,
)
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    ASSISTANT_MESSAGE_EVENT_TYPE,
    FAST_FALLBACK_TEXT,
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    InMemoryCaseRepository,
    ModelRuntimeError,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_connectors import BINDING_REF, CHANNEL_KIND
from proxyloop_contracts import DialogueAct, EventActor, FastModelView, ModelResult
from proxyloop_contracts.contracts import CompletionClaim
from test_phase_05a_temporal_api import FakeTemporalCaseClient
from test_phase_06b1_channel_runtime import (
    _ChannelRepository,
    _create_command,
    _message_event,
)

T0 = datetime(2035, 1, 1, tzinfo=UTC)
CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
LEAKY_TEXT = "Deal accepted: your target is $61.00 and I signed you up."


class SteppingClock:
    """A UTC clock that advances one second per read."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class LeakyFast:
    """A Fast adapter whose valid decision carries text the gate must withhold."""

    def __init__(
        self, text: str = LEAKY_TEXT, *, stale: bool = False, **update: Any
    ) -> None:
        self._inner = ScriptedFastAdapter()
        self.text = text
        self._update = {"response_text": text, **update}
        self._stale = stale

    def decide(self, view: FastModelView) -> FastAdapterResult:
        result = self._inner.decide(view)
        pins = (
            result.pins.model_copy(update={"event_cursor": 0})
            if self._stale
            else result.pins
        )
        return FastAdapterResult(
            pins=pins, decision=result.decision.model_copy(update=self._update)
        )


def _client(runtime: ThinAgentRuntime, mode: str = "direct") -> httpx.AsyncClient:
    app = (
        create_app(runtime)
        if mode == "direct"
        else create_app(runtime, temporal_client=FakeTemporalCaseClient(runtime))
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _fast_traces(repository: InMemoryCaseRepository) -> list[Any]:
    return [
        trace
        for trace in repository.list_model_traces(SCRIPTED_CASE_ID)
        if trace.role == "fast"
    ]


def test_scripted_dialogue_line_is_a_visible_event() -> None:
    # D1
    runtime = ThinAgentRuntime(clock=SteppingClock())
    created = runtime.create_case(occurred_at=T0)
    trigger_cursor = created.snapshot.event_cursor + 1

    result = runtime.append_event(
        SCRIPTED_CASE_ID, content="Please review the current offer."
    )

    events = result.snapshot.visible_events
    trigger, line = events[-2], events[-1]
    assert (trigger.event_cursor, trigger.actor, trigger.event_type) == (
        trigger_cursor,
        EventActor.CONSUMER,
        "consumer_message",
    )
    assert (line.event_cursor, line.actor, line.event_type) == (
        trigger_cursor + 1,
        EventActor.SYSTEM,
        "assistant_message",
    )
    assert line.occurred_at == trigger.occurred_at
    assert result.snapshot.event_cursor == trigger_cursor + 1


def test_gate_withholds_undisclosed_text_and_delivers_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # D2
    caplog.set_level(logging.DEBUG)
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock(), fast=LeakyFast())

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], str]:
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
            read = await client.get(f"/cases/{SCRIPTED_CASE_ID}")
            return turn.json(), read.json(), turn.text + read.text

    body = asyncio.run(scenario())
    turn, read, raw = body
    assert "fast" not in turn
    assert turn["route"] == "wait_for_approval"
    assert turn["approval"]["decision"] == "pending"
    line = turn["snapshot"]["visible_events"][-1]
    assert (line["actor"], line["event_type"], line["content"]) == (
        "system",
        "assistant_message",
        "I am checking that and will update you.",
    )
    assert read["snapshot"]["visible_events"] == turn["snapshot"]["visible_events"]

    fast = _fast_traces(repository)
    assert len(fast) == 1
    assert fast[0].result is ModelResult.REJECTED
    assert fast[0].reason_codes == (
        "fast_gate_commitment",
        "fast_gate_completion",
        "fast_gate_number_not_allowed",
    )

    # The withheld text is stored and emitted nowhere (I4).
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.last_fast_decision is None
    for surface in (
        raw,
        repr(state),
        repr(repository.list_model_traces(SCRIPTED_CASE_ID)),
        caplog.text,
    ):
        assert "$61" not in surface
        assert "signed you up" not in surface


@pytest.mark.parametrize("mode", ["direct", "temporal"])
def test_every_consumer_event_is_followed_by_one_scripted_line(mode: str) -> None:
    # AC1, I1, I6: visible on GET in direct and (fake) Temporal mode.
    runtime = ThinAgentRuntime(clock=SteppingClock())

    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        async with _client(runtime, mode) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            assert created.status_code == 201
            turn = await client.post(
                f"/cases/{SCRIPTED_CASE_ID}/events",
                json={
                    "content": "Please review the current offer.",
                    "expected_revision": created.json()["revision"],
                },
            )
            assert turn.status_code == 200
            read = await client.get(f"/cases/{SCRIPTED_CASE_ID}")
            assert read.status_code == 200
            return turn.json(), read.json()

    turn, read = asyncio.run(scenario())
    events = read["snapshot"]["visible_events"]
    assert [(item["actor"], item["event_type"]) for item in events] == [
        ("provider", "provider_offer"),
        ("consumer", "consumer_message"),
        ("system", "assistant_message"),
    ]
    line = events[-1]
    assert line["content"] == SCRIPTED_DIALOGUE_LINES[0]
    assert line["event_cursor"] == events[-2]["event_cursor"] + 1
    assert line["occurred_at"] == events[-2]["occurred_at"]
    assert read["event_cursor"] == line["event_cursor"]
    assert turn["revision"] == read["revision"]
    # The per-command echo equals the delivered line (I1).
    assert turn["fast"]["response_text"] == line["content"]


def test_each_applied_turn_gets_exactly_one_line_in_order() -> None:
    # I6 over several turns (after the offer expired, so no approval blocks
    # them): the lines follow SCRIPTED_DIALOGUE_LINES, then the last repeats.
    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    for minute in (61, 62, 63, 64, 65):
        runtime.append_event(
            SCRIPTED_CASE_ID,
            content="Another question.",
            occurred_at=T0 + timedelta(minutes=minute),
        )
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    events = state.snapshot.visible_events
    assert state.events == events
    consumer = [item for item in events if item.actor is EventActor.CONSUMER]
    lines = [item for item in events if item.event_type == "assistant_message"]
    assert len(lines) == len(consumer) == 5
    assert [item.content for item in lines] == [
        *SCRIPTED_DIALOGUE_LINES,
        SCRIPTED_DIALOGUE_LINES[-1],
    ]
    for trigger, line in zip(consumer, lines, strict=True):
        assert line.event_cursor == trigger.event_cursor + 1
        assert line.occurred_at == trigger.occurred_at
        assert line.actor is EventActor.SYSTEM


@pytest.mark.parametrize(
    ("fast", "code"),
    [
        (LeakyFast("They offered $61."), "fast_gate_number_not_allowed"),
        (LeakyFast("I accept it for you."), "fast_gate_commitment"),
        (LeakyFast("Your plan has been switched."), "fast_gate_completion"),
        (
            LeakyFast(
                "Checking.",
                completion_claim=CompletionClaim(
                    status="candidate", evidence_message_ids=()
                ),
            ),
            "fast_gate_completion",
        ),
        (LeakyFast("I am the account holder."), "fast_gate_authority"),
        (
            LeakyFast("Checking.", dialogue_act=DialogueAct.CONFIRM),
            "fast_gate_dialogue_act",
        ),
        (LeakyFast("Visit www.example.test now."), "fast_gate_identifier_or_link"),
        (LeakyFast("x" * 601), "fast_gate_text_too_long"),
    ],
)
def test_a_gate_reject_delivers_the_fallback_and_applies(
    fast: LeakyFast, code: str
) -> None:
    # AC2, I3, I4 at the Runtime.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock(), fast=fast)
    runtime.create_case(occurred_at=T0)
    result = runtime.append_event(SCRIPTED_CASE_ID, content="Please review.")

    assert result.fast_decision is None
    assert result.approval is not None
    line = result.snapshot.visible_events[-1]
    assert (line.actor, line.event_type, line.content) == (
        EventActor.SYSTEM,
        ASSISTANT_MESSAGE_EVENT_TYPE,
        FAST_FALLBACK_TEXT,
    )
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == (code,)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.last_fast_decision is None
    if fast.text != "Checking.":
        assert fast.text not in repr(state)
        assert fast.text not in repr(repository.list_model_traces(SCRIPTED_CASE_ID))


def test_a_validation_reject_is_unchanged() -> None:
    # D3, AC3: content-free 409, no state change, the trace is kept.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=LeakyFast("Checking.", stale=True)
    )

    async def scenario() -> tuple[int, Any]:
        async with _client(runtime) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            before = repository.get(SCRIPTED_CASE_ID)
            response = await client.post(
                f"/cases/{SCRIPTED_CASE_ID}/events",
                json={
                    "content": "Please review the current offer.",
                    "expected_revision": created.json()["revision"],
                },
            )
            assert repository.get(SCRIPTED_CASE_ID) is before
            return response.status_code, response.json()

    status, body = asyncio.run(scenario())
    assert status == 409
    assert body == {
        "detail": {
            "code": "model_result_rejected",
            "message": "model proposal was rejected safely",
        }
    }
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes is not None
    assert "stale_fast_result" in trace.reason_codes
    with pytest.raises(ModelRuntimeError):
        runtime.append_event(SCRIPTED_CASE_ID, content="Again.")


def test_a_deduplicated_replay_makes_no_new_trace() -> None:
    # D4
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock())
    created = runtime.apply_command(_create_command())
    command = CaseCommand(
        command_id=uuid4(),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        occurred_at=datetime(2026, 8, 26, 12, 1, tzinfo=UTC),
        expected_revision=created.after_revision,
        content="Please review the current offer.",
        event_type="consumer_message",
    )
    first = runtime.apply_command(command)
    traces = repository.list_model_traces(SCRIPTED_CASE_ID)
    replay = runtime.apply_command(command)
    assert replay.deduplicated is True
    assert replay.model_copy(update={"deduplicated": False}) == first
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == traces
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert first.event_cursor == state.snapshot.event_cursor
    assert state.snapshot.visible_events[-1].event_type == "assistant_message"


def test_channel_ingest_keeps_the_constant_body_and_adds_no_line() -> None:
    # D5, AC4, I7
    repository = _ChannelRepository()
    base = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime = ThinAgentRuntime(repository, clock=lambda: base)
    runtime.apply_command(_create_command())
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=base)
    applied = runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
            occurred_at=event.occurred_at,
            expected_revision=2,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=event.event_id,
            content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
            payload_hash=event.raw_payload_hash,
        )
    )
    assert applied.delivery_id is not None
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    assert outbox.body == BOUNDED_FAST_STATUS_TEXT
    assert (
        outbox.body_hash
        == hashlib.sha256(BOUNDED_FAST_STATUS_TEXT.encode()).hexdigest()
    )
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert [item.event_type for item in state.snapshot.visible_events] == [
        "provider_offer",
        "provider_message",
    ]
    (trace,) = _fast_traces(repository)
    assert trace.model == "scripted_dialogue_fast"
    assert trace.result is ModelResult.SUCCEEDED


def test_assistant_message_cannot_be_appended_by_a_caller() -> None:
    # D7, I11
    runtime = ThinAgentRuntime(clock=SteppingClock())
    runtime.create_case(occurred_at=T0)
    before = runtime.repository.get(SCRIPTED_CASE_ID)
    with pytest.raises(ValueError, match="Runtime-authored"):
        runtime.append_event(
            SCRIPTED_CASE_ID,
            content="Forged line.",
            event_type=ASSISTANT_MESSAGE_EVENT_TYPE,
        )
    assert runtime.repository.get(SCRIPTED_CASE_ID) is before


def test_the_default_runtime_is_scripted() -> None:
    # D8
    assert ThinAgentRuntime().adapter_mode == "scripted"
    assert ThinAgentRuntime(fast=ScriptedFastAdapter()).adapter_mode == "scripted"
    assert ThinAgentRuntime(fast=LeakyFast()).adapter_mode == "model"


def test_the_gate_is_wired_at_the_single_coordinator_site() -> None:
    # D9: PR-7's single ``.advance(`` guard still holds with the gate added.
    source = inspect.getsource(runtime_module)
    assert source.count(".advance(") == 1
    assert source.count("CaseCoordinator(") == 1
    assert source.count("fast_gate=fast_disclosure_violations") == 1


def test_an_invisible_character_bypass_is_withheld_end_to_end() -> None:
    # Review B1: zero-width spaces inside "accepted" and "finalized" used to
    # pass every phrase rule and be stored as the assistant line.
    text = (
        "I a\N{ZERO WIDTH SPACE}ccepted the offer and it is "
        "fin\N{ZERO WIDTH SPACE}alized for you."
    )
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=SteppingClock(), fast=LeakyFast(text))
    runtime.create_case(occurred_at=T0)
    result = runtime.append_event(SCRIPTED_CASE_ID, content="Please review.")

    assert result.fast_decision is None
    assert result.snapshot.visible_events[-1].content == FAST_FALLBACK_TEXT
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == ("fast_gate_non_ascii_text",)
    assert "ccepted" not in repr(repository.get(SCRIPTED_CASE_ID))


def test_a_gate_reject_on_the_channel_path_fails_closed() -> None:
    # Review M6, I7: a channel turn has no fallback; nothing is sent.
    repository = _ChannelRepository()
    base = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime = ThinAgentRuntime(
        repository, clock=lambda: base, fast=LeakyFast("I accept the offer.")
    )
    runtime.apply_command(_create_command())
    before = repository.get(SCRIPTED_CASE_ID)
    event = _message_event(uuid4())
    inbox = repository.reserve_channel_event(event, received_at=base)
    with pytest.raises(ModelRuntimeError):
        runtime.apply_command(
            CaseCommand(
                schema_version="phase-06b1-v1",
                command_id=inbox.command_id,
                case_id=SCRIPTED_CASE_ID,
                command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
                occurred_at=event.occurred_at,
                expected_revision=2,
                channel_kind=CHANNEL_KIND,
                binding_ref=BINDING_REF,
                event_id=event.event_id,
                content_hash=hashlib.sha256(event.content.encode()).hexdigest(),
                payload_hash=event.raw_payload_hash,
            )
        )
    assert repository.get(SCRIPTED_CASE_ID) is before
    assert repository.outbox == {}
    assert repository.inbox[event.event_id].processing_state == "reserved"
    (trace,) = _fast_traces(repository)
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == ("fast_gate_commitment",)
