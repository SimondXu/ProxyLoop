"""The canonical execution claim and model traces are persisted (1.1 PR4).

The PostgreSQL codec is exercised without a database: a repository below
stores every state as the exact jsonb payload the PostgreSQL repository
writes and decodes it on every read.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from proxyloop_agent_core import CaseCoordinator, CoordinatorOutcome, RouteRequest
from proxyloop_agent_core.interfaces import FastAdapter, SlowAdapter
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.commands import semantic_command_fingerprint
from proxyloop_case_runtime.postgres_repository import PostgresCaseRepository
from proxyloop_contracts import (
    CasePhase,
    EvidenceType,
    ExecutionClaim,
    ModelTrace,
)
from test_phase_05a_case_runtime import (
    APPROVAL_COMMAND_ID,
    BASE_TIME,
    _create_command,
    _event_command,
    _runtime,
)
from test_phase_06b1_channel_runtime import _ChannelRepository
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


# -- storage_version 1 rows load, upgrade, and are rewritten as version 2 -------


@pytest.mark.parametrize("stored_as_1_0", [False, True], ids=["snap-1.1", "snap-1.0"])
def test_a_v1_row_with_a_pending_claim_upgrades_completes_and_writes_v2(
    stored_as_1_0: bool,
) -> None:
    pending, command, before_revision = _pending_claim()
    if stored_as_1_0:
        pending = _as_stored_1_0(pending)
    row = _v1_payload(pending)

    upgraded = _decode(row)

    expected = _expected_claim(pending, command, before_revision)
    assert upgraded.execution_claim == expected
    assert upgraded.model_traces == ()
    assert upgraded.snapshot == pending.snapshot
    rewritten = _encode(upgraded)
    assert rewritten["storage_version"] == 2
    assert rewritten["model_traces"] == []
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
    assert stored["storage_version"] == 2
    assert stored["execution_claim"] is None
    assert stored["model_traces"] == []
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


def test_v1_rows_without_a_claim_load_and_rewrite_as_v2() -> None:
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
        assert loaded.model_traces == ()
        assert loaded.snapshot == state.snapshot
        assert loaded.transitions == state.transitions
        rewritten = _encode(loaded)
        assert rewritten["storage_version"] == 2
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
    ):
        with pytest.raises(RuntimeError, match=INVALID):
            _decode(tampered)
    with pytest.raises(RuntimeError, match="unsupported Case storage version"):
        _decode({**_encode(pending), "storage_version": 3})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", "22222222-2222-4222-8222-222222222222"),
        ("action_intent_id", "33333333-3333-4333-8333-333333333333"),
        ("idempotency_key", "accept:another-intent"),
        ("approval_id", "44444444-4444-4444-8444-444444444444"),
    ],
)
def test_a_v2_claim_must_bind_the_pending_execution(field: str, value: str) -> None:
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


# -- model traces ride in the same state write and never leave runtime state ----


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


class _RecordingRepository(_PayloadRepository):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[CaseRuntimeState] = []

    def create(self, state: CaseRuntimeState) -> CaseRuntimeState:
        self.writes.append(state)
        return super().create(state)

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        self.writes.append(state)
        return super().replace(
            case_id, expected_revision=expected_revision, state=state
        )


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


def test_traces_are_appended_in_the_same_write_and_survive_completion(
    issued: list[ModelTrace],
) -> None:
    repository = _RecordingRepository()
    clock = BASE_TIME
    runtime = ThinAgentRuntime(repository, clock=lambda: clock)

    runtime.apply_command(_create_command())
    assert [write.model_traces for write in repository.writes] == [tuple(issued)]
    assert [trace.role for trace in issued] == ["slow"]

    clock = BASE_TIME + timedelta(minutes=1)
    before = len(repository.writes)
    event = runtime.apply_command(_event_command())
    (event_write,) = repository.writes[before:]
    assert event_write.snapshot.revision == event.after_revision
    assert event_write.model_traces == tuple(issued)
    assert [trace.role for trace in issued] == ["slow", "fast"]

    clock = BASE_TIME + timedelta(minutes=2)
    runtime.apply_command(_approval_command(event.after_revision, event.approval_id))
    claim_write, final_write = repository.writes[before + 1 :]
    assert claim_write.snapshot.pending_execution
    assert claim_write.execution_claim is not None
    assert final_write.snapshot.case.phase is CasePhase.COMPLETE
    assert final_write.model_traces == claim_write.model_traces == tuple(issued)

    stored = repository.payloads[SCRIPTED_CASE_ID]
    assert stored["storage_version"] == 2
    assert [item["trace_id"] for item in stored["model_traces"]] == [
        str(trace.trace_id) for trace in issued
    ]
    final = repository.get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.model_traces == tuple(issued)
    _assert_not_projected(final, issued)
    foreign = json.loads(json.dumps(stored))
    foreign["model_traces"][0]["case_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(RuntimeError, match=INVALID):
        _decode(foreign)


def test_persisted_traces_share_the_case_time_base(
    issued: list[ModelTrace], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each trace starts at the time of the Case event whose route ran the
    # model and lasts the measured latency (a fake perf counter: 0.25 s per
    # call), so a persisted trace never needs a second clock to be placed.
    ticks = iter(range(1_000))
    monkeypatch.setattr(runtime_module.time, "perf_counter", lambda: next(ticks) / 4)
    repository = _RecordingRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    runtime.apply_command(_event_command())

    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    assert [trace.role for trace in stored.model_traces] == ["slow", "fast"]
    assert stored.model_traces == tuple(issued)
    event_times = {event.occurred_at for event in stored.events}
    for trace in stored.model_traces:
        assert trace.started_at in event_times
        assert trace.latency_ms == 250
        assert trace.completed_at == trace.started_at + timedelta(milliseconds=250)


class _RecordingChannelRepository(_ChannelRepository):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[CaseRuntimeState] = []

    def replace_with_channel_outbox(self, *args: Any, **kwargs: Any) -> Any:
        self.writes.append(kwargs["state"])
        return super().replace_with_channel_outbox(*args, **kwargs)


def test_a_channel_event_writes_its_refresh_and_fast_traces_once(
    issued: list[ModelTrace],
) -> None:
    repository = _RecordingChannelRepository()
    runtime = ThinAgentRuntime(repository, clock=lambda: BASE_TIME)
    runtime.apply_command(_create_command())
    created = repository.get(SCRIPTED_CASE_ID)
    assert created is not None
    assert created.model_traces == tuple(issued)

    # After the strategy lifetime, the event refreshes Slow and then runs Fast.
    runtime.apply_command(
        _channel_command(repository, BASE_TIME + timedelta(minutes=31))
    )

    assert [trace.role for trace in issued] == ["slow", "slow", "fast"]
    (write,) = repository.writes
    assert write.model_traces == tuple(issued)
    stored = repository.get(SCRIPTED_CASE_ID)
    assert stored is not None
    assert stored.model_traces == tuple(issued)
    _assert_not_projected(stored, issued)


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
    assert state.model_traces == tuple(issued)
    for body in bodies:
        assert "model_traces" not in body
        for trace in issued:
            assert str(trace.trace_id) not in body
