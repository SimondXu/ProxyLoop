"""The canonical execution claim and model traces are persisted (1.1 PR4, R-12).

The PostgreSQL codec is exercised without a database: a repository below
stores every state as the exact jsonb payload the PostgreSQL repository
writes and decodes it on every read. Model traces live in the repository's
append-only log, never in the Case state (``storage_version`` 3).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from proxyloop_agent_core import (
    CaseCoordinator,
    CoordinatorOutcome,
    FastAdapterResult,
    RouteRequest,
    ScriptedFastAdapter,
)
from proxyloop_agent_core.interfaces import FastAdapter, SlowAdapter
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    CaseRuntimeState,
    ChannelConflictError,
    InMemoryCaseRepository,
    ModelRuntimeError,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.commands import semantic_command_fingerprint
from proxyloop_case_runtime.postgres_repository import PostgresCaseRepository
from proxyloop_connectors import BINDING_REF, CHANNEL_KIND, LocalMailboxEventKind
from proxyloop_contracts import (
    ActionType,
    CasePhase,
    EvidenceType,
    ExecutionClaim,
    ModelResult,
    ModelTrace,
)
from test_phase_05a_case_runtime import (
    APPROVAL_COMMAND_ID,
    BASE_TIME,
    _create_command,
    _event_command,
    _runtime,
)
from test_phase_06b1_channel_runtime import _ChannelRepository, _message_event
from test_slow_refresh_strategy_expiry import _channel_command
from test_strategy_basis_binding import _as_stored_1_0, _ClaimCrashRepository

INVALID = "stored Case payload is invalid"


# -- the PostgreSQL payload, without a database ---------------------------------


def _encode(state: CaseRuntimeState) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        json.dumps(PostgresCaseRepository._encode_state(state))
    )
    return payload


def _decode(payload: dict[str, Any]) -> CaseRuntimeState:
    snapshot = payload["snapshot"]
    return PostgresCaseRepository._decode_state(
        UUID(snapshot["case"]["case_id"]), snapshot["revision"], payload
    )


class _PayloadRepository(InMemoryCaseRepository):
    """Keep each Case as its PostgreSQL jsonb payload; decode on every read."""

    def __init__(self) -> None:
        super().__init__()
        self.payloads: dict[UUID, dict[str, Any]] = {}

    def load(self, payload: dict[str, Any]) -> None:
        state = _decode(payload)
        super().create(state)
        self.payloads[state.snapshot.case.case_id] = payload

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        created = super().create(state)
        self.payloads[state.snapshot.case.case_id] = _encode(state)
        return created

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        updated = super().replace(
            case_id, expected_revision=expected_revision, state=state
        )
        self.payloads[case_id] = _encode(state)
        return updated

    def get(self, case_id: UUID) -> CaseRuntimeState | None:
        payload = self.payloads.get(case_id)
        return None if payload is None else _decode(payload)


def _json(value: Any) -> Any:
    return None if value is None else value.model_dump(mode="json")


def _v1_payload(state: CaseRuntimeState) -> dict[str, Any]:
    """Build the ``storage_version`` 1 row exactly as the pre-1.1 codec wrote it."""

    claim = state.execution_claim
    return {
        "storage_version": 1,
        "snapshot": state.snapshot.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in state.events],
        "execution_count": state.execution_count,
        "execution_source_pins": _json(state.execution_source_pins),
        "execution_intent": _json(state.execution_intent),
        "execution_approval": _json(state.execution_approval),
        "execution_proposal": _json(state.execution_proposal),
        "transitions": [item.model_dump(mode="json") for item in state.transitions],
        "last_fast_decision": _json(state.last_fast_decision),
        "execution_claim": (
            None
            if claim is None
            else {
                "approval_id": str(claim.approval_id),
                "before_revision": claim.before_revision,
                "claimed_at": claim.claimed_at.isoformat().replace("+00:00", "Z"),
                "command_id": (
                    None if claim.command_id is None else str(claim.command_id)
                ),
                "command_fingerprint": claim.command_fingerprint,
            }
        ),
    }


# -- a pending claim, as a crash after the claim write leaves it ---------------


def _approval_command(after_revision: int, approval_id: UUID | None) -> CaseCommand:
    return CaseCommand(
        command_id=APPROVAL_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        expected_revision=after_revision,
        approval_id=approval_id,
        decision="approved",
        expected_case_revision=1,
        expected_action_intent_revision=1,
    )


def _pending_claim() -> tuple[CaseRuntimeState, CaseCommand, int]:
    # The claim write lands and the process dies before the Provider commit.
    repository = _ClaimCrashRepository()
    _runtime(repository, BASE_TIME).apply_command(_create_command())
    event = _runtime(repository, BASE_TIME + timedelta(minutes=1)).apply_command(
        _event_command()
    )
    command = _approval_command(event.after_revision, event.approval_id)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _runtime(repository, BASE_TIME + timedelta(minutes=2)).apply_command(command)
    pending = repository.get(SCRIPTED_CASE_ID)
    assert pending is not None
    assert pending.snapshot.pending_execution
    return pending, command, event.after_revision


def _expected_claim(
    state: CaseRuntimeState, command: CaseCommand, before_revision: int
) -> ExecutionClaim:
    intent = state.execution_intent
    assert intent is not None
    assert command.approval_id is not None
    return ExecutionClaim(
        contract_type="execution_claim",
        schema_version="1.1",
        revision=1,
        case_id=SCRIPTED_CASE_ID,
        approval_id=command.approval_id,
        action_intent_id=intent.intent_id,
        idempotency_key=intent.idempotency_key,
        before_revision=before_revision,
        claimed_at=command.occurred_at,
        command_id=command.command_id,
        command_fingerprint=semantic_command_fingerprint(command),
    )


# -- storage_version 1 rows load, upgrade, and are rewritten as version 3 -------


@pytest.mark.parametrize("stored_as_1_0", [False, True], ids=["snap-1.1", "snap-1.0"])
def test_a_v1_row_with_a_pending_claim_upgrades_completes_and_writes_v3(
    stored_as_1_0: bool,
) -> None:
    pending, command, before_revision = _pending_claim()
    if stored_as_1_0:
        pending = _as_stored_1_0(pending)
    row = _v1_payload(pending)

    upgraded = _decode(row)

    expected = _expected_claim(pending, command, before_revision)
    assert upgraded.execution_claim == expected
    assert upgraded.snapshot == pending.snapshot
    rewritten = _encode(upgraded)
    assert rewritten["storage_version"] == 3
    assert "model_traces" not in rewritten
    assert (
        ExecutionClaim.model_validate_json(json.dumps(rewritten["execution_claim"]))
        == expected
    )
    reloaded = _decode(rewritten)
    assert reloaded == replace(upgraded, provider=reloaded.provider)

    repository = _PayloadRepository()
    repository.load(row)
    retried = _runtime(repository, BASE_TIME + timedelta(minutes=3)).apply_command(
        command
    )

    assert retried.terminal is True
    assert retried.deduplicated is False
    assert retried.before_revision == before_revision
    stored = repository.payloads[SCRIPTED_CASE_ID]
    assert stored["storage_version"] == 3
    assert stored["execution_claim"] is None
    assert "model_traces" not in stored
    final = _decode(stored)
    assert final.snapshot.case.phase is CasePhase.COMPLETE
    assert final.snapshot.schema_version == ("1.0" if stored_as_1_0 else "1.1")
    assert final.execution_count == 1
    assert [item.source_type for item in final.snapshot.evidence].count(
        EvidenceType.CONFIRMATION
    ) == 1
    duplicate = _runtime(repository, BASE_TIME + timedelta(minutes=4)).apply_command(
        command
    )
    assert duplicate.deduplicated is True
    assert duplicate.model_copy(update={"deduplicated": False}) == retried


def test_v1_rows_without_a_claim_load_and_rewrite_as_v3() -> None:
    repository = InMemoryCaseRepository()
    _runtime(repository, BASE_TIME).apply_command(_create_command())
    created = repository.get(SCRIPTED_CASE_ID)
    _runtime(repository, BASE_TIME + timedelta(minutes=1)).apply_command(
        _event_command()
    )
    waiting = repository.get(SCRIPTED_CASE_ID)
    assert created is not None
    assert waiting is not None

    for state in (created, waiting):
        loaded = _decode(_v1_payload(state))
        assert loaded.execution_claim is None
        assert loaded.snapshot == state.snapshot
        assert loaded.transitions == state.transitions
        rewritten = _encode(loaded)
        assert rewritten["storage_version"] == 3
        assert "model_traces" not in rewritten
        assert rewritten["execution_claim"] is None
        assert _decode(rewritten).snapshot == state.snapshot


def test_stored_rows_fail_closed_on_shapes_they_never_had() -> None:
    pending, _, _ = _pending_claim()
    row = _v1_payload(pending)

    for tampered in (
        # A version 1 row never carried traces or a canonical claim.
        {**row, "model_traces": []},
        {**row, "execution_claim": _encode(pending)["execution_claim"]},
        # A command id without its fingerprint cannot become a canonical claim.
        {
            **row,
            "execution_claim": {**row["execution_claim"], "command_fingerprint": None},
        },
        # A pending row still requires its claim.
        {**row, "execution_claim": None},
        {**_encode(pending), "execution_claim": None},
        # A version 3 row carries no traces: they live in the trace log.
        {**_encode(pending), "model_traces": []},
    ):
        with pytest.raises(RuntimeError, match=INVALID):
            _decode(tampered)
    # Version 2 rows are moved to version 3 at bootstrap, never decoded.
    for version in (2, 4):
        with pytest.raises(RuntimeError, match="unsupported Case storage version"):
            _decode({**_encode(pending), "storage_version": version})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", "22222222-2222-4222-8222-222222222222"),
        ("action_intent_id", "33333333-3333-4333-8333-333333333333"),
        ("idempotency_key", "accept:another-intent"),
        ("approval_id", "44444444-4444-4444-8444-444444444444"),
    ],
)
def test_a_v3_claim_must_bind_the_pending_execution(field: str, value: str) -> None:
    pending, _, _ = _pending_claim()
    payload = _encode(pending)
    payload["execution_claim"][field] = value

    with pytest.raises(RuntimeError, match=INVALID):
        _decode(payload)


def test_the_claim_is_present_exactly_while_execution_is_pending() -> None:
    pending, _, _ = _pending_claim()
    assert isinstance(pending.execution_claim, ExecutionClaim)
    with pytest.raises(ValueError, match="execution claim must be present"):
        replace(pending, execution_claim=None)

    repository = InMemoryCaseRepository()
    _runtime(repository, BASE_TIME).apply_command(_create_command())
    idle = repository.get(SCRIPTED_CASE_ID)
    assert idle is not None
    with pytest.raises(ValueError, match="execution claim must be present"):
        replace(idle, execution_claim=pending.execution_claim)


# -- model traces live in an append-only log, never in the Case state -----------


@pytest.fixture
def issued(monkeypatch: pytest.MonkeyPatch) -> list[ModelTrace]:
    """Record every trace the coordinator (PR3) returns to the runtime."""

    traces: list[ModelTrace] = []

    class _RecordingCoordinator(CaseCoordinator):
        def advance(
            self,
            request: RouteRequest,
            *,
            fast: FastAdapter | None = None,
            slow: SlowAdapter | None = None,
        ) -> CoordinatorOutcome:
            outcome = super().advance(request, fast=fast, slow=slow)
            traces.extend(outcome.traces)
            return outcome

    monkeypatch.setattr(runtime_module, "CaseCoordinator", _RecordingCoordinator)
    return traces


def _assert_not_projected(state: CaseRuntimeState, traces: list[ModelTrace]) -> None:
    public = json.dumps(
        [
            state.snapshot.model_dump(mode="json"),
            [item.model_dump(mode="json") for item in state.transitions],
            [item.model_dump(mode="json") for item in state.events],
        ]
    )
    assert "model_traces" not in public
    for trace in traces:
        assert str(trace.trace_id) not in public


def test_the_log_holds_every_issued_trace_across_the_direct_flow(
    issued: list[ModelTrace],
) -> None:
    repository = _PayloadRepository()
    clock = BASE_TIME
    runtime = ThinAgentRuntime(repository, clock=lambda: clock)

    runtime.apply_command(_create_command())
    assert [trace.role for trace in issued] == ["slow"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)

    clock = BASE_TIME + timedelta(minutes=1)
    event = runtime.apply_command(_event_command())
    assert [trace.role for trace in issued] == ["slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)

    clock = BASE_TIME + timedelta(minutes=2)
    runtime.apply_command(_approval_command(event.after_revision, event.approval_id))

    final = repository.get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.snapshot.case.phase is CasePhase.COMPLETE
    assert [trace.role for trace in issued] == ["slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)
    stored = repository.payloads[SCRIPTED_CASE_ID]
    assert stored["storage_version"] == 3
    assert "model_traces" not in stored
    _assert_not_projected(final, issued)


def test_the_log_holds_every_issued_trace_across_the_channel_flow(
    issued: list[ModelTrace],
) -> None:
    repository = _ChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    # After the strategy lifetime, the event refreshes Slow and then runs Fast.
    applied = runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=31))
    )
    assert applied.delivery_id is not None
    assert [trace.role for trace in issued] == ["slow", "slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)
    accepted = repository.get_outbox_record(applied.delivery_id)
    assert accepted is not None
    repository.outbox[applied.delivery_id] = replace(
        accepted, state="accepted", provider_message_id="local-provider-test"
    )

    def callback(expected_revision: int) -> CaseCommand:
        event = _message_event(uuid4(), kind=LocalMailboxEventKind.DELIVERY)
        inbox = repository.reserve_channel_event(event, received_at=BASE_TIME)
        return CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
            occurred_at=BASE_TIME,
            expected_revision=expected_revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=event.event_id,
            delivery_id=applied.delivery_id,
            provider_message_id="local-provider-test",
            delivery_status="delivered",
            artifact_hash=hashlib.sha256(b"artifact").hexdigest(),
            payload_hash=event.raw_payload_hash,
        )

    first = runtime.apply_command(callback(applied.after_revision))
    runtime.apply_command(callback(first.after_revision))  # an exact duplicate

    # A callback runs no model, so it logs nothing.
    assert [trace.role for trace in issued] == ["slow", "slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    _assert_not_projected(stored, issued)


def test_persisted_traces_share_the_case_time_base(
    issued: list[ModelTrace], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each trace starts at the time of the Case event whose route ran the
    # model and lasts the measured latency (a fake perf counter: 0.25 s per
    # call), so a persisted trace never needs a second clock to be placed.
    # Only the runtime's measurement source is replaced, not the process-wide
    # ``time.perf_counter``; the coordinator reads it before and after a call.
    ticks = iter(range(1_000))
    monkeypatch.setattr(
        runtime_module, "time", SimpleNamespace(perf_counter=lambda: next(ticks) / 4)
    )
    repository = _PayloadRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    runtime.apply_command(_event_command())

    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    logged = repository.list_model_traces(SCRIPTED_CASE_ID)
    assert [trace.role for trace in logged] == ["slow", "fast"]
    assert logged == tuple(issued)
    event_times = {event.occurred_at for event in stored.events}
    for trace in logged:
        assert trace.started_at in event_times
        assert trace.latency_ms == 250
        assert trace.completed_at == trace.started_at + timedelta(milliseconds=250)


class _StalePinsFast(ScriptedFastAdapter):
    """Echo the pins of the view before the triggering event."""

    def decide(self, view: Any) -> FastAdapterResult:
        result = super().decide(view)
        stale = result.pins.model_copy(
            update={"event_cursor": result.pins.event_cursor - 1}
        )
        return FastAdapterResult(pins=stale, decision=result.decision)


class _OffScriptFast(ScriptedFastAdapter):
    """An accepted decision whose text is not the bounded channel reply."""

    def decide(self, view: Any) -> FastAdapterResult:
        result = super().decide(view)
        decision = result.decision.model_copy(
            update={"response_text": "Could you confirm the next step?"}
        )
        return FastAdapterResult(pins=result.pins, decision=decision)


def test_a_rejected_fast_result_is_traced(issued: list[ModelTrace]) -> None:
    repository = _PayloadRepository()
    runtime = ThinAgentRuntime(
        repository, clock=lambda: BASE_TIME, fast=_StalePinsFast()
    )
    runtime.apply_command(_create_command())
    before = repository.get(SCRIPTED_CASE_ID)
    assert before is not None

    with pytest.raises(ModelRuntimeError) as raised:
        runtime.apply_command(_event_command())

    assert raised.value.source == "fast"
    assert [trace.role for trace in issued] == ["slow", "fast"]
    rejected = issued[-1]
    assert rejected.result is ModelResult.REJECTED
    assert rejected.reason_codes
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)
    after = repository.get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot == before.snapshot
    assert after.events == before.events
    assert after.transitions == before.transitions


def _without_send_message(repository: _ChannelRepository) -> None:
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    case = state.snapshot.case
    authority = case.delegated_authority.model_copy(
        update={
            "allowed_actions": tuple(
                action
                for action in case.delegated_authority.allowed_actions
                if action is not ActionType.SEND_MESSAGE
            )
        }
    )
    snapshot = state.snapshot.model_copy(
        update={"case": case.model_copy(update={"delegated_authority": authority})}
    )
    repository.replace(
        SCRIPTED_CASE_ID,
        expected_revision=snapshot.revision,
        state=replace(state, snapshot=snapshot),
    )


@pytest.mark.parametrize("refusal", ["response_text", "unauthorized_send"])
def test_a_channel_refusal_keeps_its_accepted_traces(
    issued: list[ModelTrace], refusal: str
) -> None:
    repository = _ChannelRepository()
    fast = _OffScriptFast() if refusal == "response_text" else ScriptedFastAdapter()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME, fast=fast)
    runtime.apply_command(_create_command())
    if refusal == "unauthorized_send":
        _without_send_message(repository)
    before = repository.get(SCRIPTED_CASE_ID)
    assert before is not None
    # After the strategy lifetime, the event refreshes Slow and then runs Fast.
    command = _channel_command(repository, BASE_TIME + timedelta(minutes=31))

    with pytest.raises((ModelRuntimeError, ChannelConflictError)) as raised:
        runtime.apply_command(command)

    if refusal == "response_text":
        assert isinstance(raised.value, ModelRuntimeError)
        assert raised.value.source == "fast"
    else:
        assert str(raised.value) == "channel send is not authorized"
    assert [trace.role for trace in issued] == ["slow", "slow", "fast"]
    assert {trace.result for trace in issued} == {ModelResult.SUCCEEDED}
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)
    after = repository.get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot == before.snapshot
    assert after.transitions == before.transitions
    assert repository.outbox == {}
    assert command.event_id is not None
    inbox = repository.get_inbox_receipt(command.event_id)
    assert inbox is not None
    assert inbox.processing_state == "reserved"


def test_the_append_event_rollback_keeps_its_traces(
    issued: list[ModelTrace], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The in-memory store hands the Runtime its stored Provider, so only this
    # Case's Provider refuses (the codec replays ``await_approval`` itself).
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    before = repository.get(SCRIPTED_CASE_ID)
    assert before is not None

    def refuse(intent: object) -> None:
        raise RuntimeError("simulated Provider refusal")

    monkeypatch.setattr(before.provider, "await_approval", refuse)
    with pytest.raises(RuntimeError, match="simulated Provider refusal"):
        runtime.apply_command(_event_command())

    after = repository.get(SCRIPTED_CASE_ID)
    assert after is not None
    assert after.snapshot == before.snapshot
    assert after.transitions == before.transitions
    assert [trace.role for trace in issued] == ["slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)


def test_a_compare_and_swap_loser_keeps_its_traces(
    issued: list[ModelTrace],
) -> None:
    class _LosingRepository(_PayloadRepository):
        def replace(
            self,
            case_id: UUID,
            *,
            expected_revision: int,
            state: CaseRuntimeState,
        ) -> CaseRuntimeState:
            raise CaseConflictError("case snapshot revision is stale")

    repository = _LosingRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())

    with pytest.raises(CaseConflictError):
        runtime.apply_command(_event_command())

    assert [trace.role for trace in issued] == ["slow", "fast"]
    assert repository.list_model_traces(SCRIPTED_CASE_ID) == tuple(issued)


def test_the_runtime_calls_the_coordinator_only_through_advance() -> None:
    # I6 source guard: ``_advance`` is the Runtime's single coordinator call,
    # so a new path cannot run a model without logging its traces.
    source = inspect.getsource(runtime_module)
    assert source.count(".advance(") == 1
    assert "self._coordinator(request.snapshot).advance(" in source


def _unconnected_postgres(monkeypatch: pytest.MonkeyPatch) -> PostgresCaseRepository:
    """A PostgreSQL repository that fails the test if it opens a connection."""

    repository = PostgresCaseRepository.__new__(PostgresCaseRepository)

    def connect() -> Any:
        raise AssertionError("the append must not open a connection")

    monkeypatch.setattr(repository, "_connect", connect)
    return repository


@pytest.mark.parametrize("adapter", ["memory", "postgres"])
def test_a_trace_append_is_for_one_case_and_empty_is_a_no_op(
    issued: list[ModelTrace], monkeypatch: pytest.MonkeyPatch, adapter: str
) -> None:
    memory = InMemoryCaseRepository()
    ThinAgentRuntime(memory, clock=lambda: BASE_TIME).apply_command(_create_command())
    (trace,) = issued
    foreign = trace.model_copy(
        update={"case_id": UUID("22222222-2222-4222-8222-222222222222")}
    )
    repository: InMemoryCaseRepository | PostgresCaseRepository = (
        memory if adapter == "memory" else _unconnected_postgres(monkeypatch)
    )

    with pytest.raises(ValueError, match="model trace references another Case"):
        repository.append_model_traces(SCRIPTED_CASE_ID, (trace, foreign))
    repository.append_model_traces(SCRIPTED_CASE_ID, ())

    # All or nothing: the valid trace in the refused append was not written.
    assert memory.list_model_traces(SCRIPTED_CASE_ID) == (trace,)


def test_the_browser_projection_never_carries_a_trace(
    issued: list[ModelTrace],
) -> None:
    asyncio.run(_browser_flow(issued))


async def _browser_flow(issued: list[ModelTrace]) -> None:
    runtime = ThinAgentRuntime()
    bodies: list[str] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
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
        case_id = created.json()["case_id"]
        turn = await client.post(
            f"/cases/{case_id}/events",
            json={
                "content": "Please review the current offer.",
                "expected_revision": created.json()["revision"],
            },
        )
        assert turn.status_code == 200
        approval = turn.json()["approval"]
        approved = await client.post(
            f"/cases/{case_id}/approvals/{approval['approval_id']}",
            json={
                "decision": "approved",
                "expected_revision": turn.json()["revision"],
                "expected_case_revision": approval["case_revision"],
                "expected_action_intent_revision": approval["action_intent_revision"],
            },
        )
        assert approved.status_code == 200
        read = await client.get(f"/cases/{case_id}")
        assert read.status_code == 200
        bodies = [item.text for item in (created, turn, approved, read)]

    state = runtime.repository.get(UUID(case_id))
    assert state is not None
    assert len(issued) >= 2
    assert runtime.repository.list_model_traces(UUID(case_id)) == tuple(issued)
    _assert_not_projected(state, issued)
    for body in bodies:
        assert "model_traces" not in body
        for trace in issued:
            assert str(trace.trace_id) not in body
