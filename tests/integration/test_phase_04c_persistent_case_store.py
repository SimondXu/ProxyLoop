from __future__ import annotations

import importlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from proxyloop_api import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRuntimeState,
    InMemoryCaseRepository,
    PostgresCaseRepository,
    StorageUnavailableError,
    ThinAgentRuntime,
    runtime_from_environment,
)
from proxyloop_case_runtime import CaseCommand, CaseCommandType
from proxyloop_contracts import (
    CasePhase,
    CompletionOutcome,
    DialogueAct,
    EvidenceType,
    ModelTrace,
)
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)
from proxyloop_openai_adapter import (
    AcceptOfferCapabilityModelOutput,
    FastModelOutput,
    OpenAICompatibleAdapter,
    SlowModelOutput,
    StrategyModelOutput,
)
from psycopg.types.json import Jsonb

BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
TABLE = "proxyloop_case_runtime_states"
TRACES_TABLE = "proxyloop_model_traces"


class _FinalWriteFailureRepository(PostgresCaseRepository):
    def __init__(self, database_url: str) -> None:
        self.fail_final_write = True
        super().__init__(database_url)

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        if state.snapshot.completion_decision is not None and self.fail_final_write:
            self.fail_final_write = False
            raise CaseConflictError("injected final CAS conflict")
        return super().replace(
            case_id,
            expected_revision=expected_revision,
            state=state,
        )


@dataclass
class _Message:
    parsed: object | None
    refusal: str | None = None


@dataclass
class _Choice:
    message: _Message


class _Response:
    def __init__(self, parsed: object, *, model: str = "runtime-model") -> None:
        self.id = "response-1"
        self.model = model
        self.choices = [_Choice(_Message(parsed))]


class _FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return next(self.responses)


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def _slow_output() -> SlowModelOutput:
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Reduce the monthly bill safely.",
            current_subgoal="Review the current fictional Provider offer.",
            ranked_preference_positions=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=("Preserve hard constraints.",),
            fallback_outcomes=("Return control to the Consumer.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="Provider confirmation",
                ),
            ),
            escalation_conditions=("Material terms change.",),
            replan_conditions=("Planning basis changes.",),
        )
    )


def _slow_output_proposing_accept() -> SlowModelOutput:
    return _slow_output().model_copy(
        update={
            "next_capability": AcceptOfferCapabilityModelOutput(
                capability="accept_offer", offer_position=0
            )
        }
    )


def _fast_output() -> FastModelOutput:
    return FastModelOutput(
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="I am checking that and will update you.",
        action_intent=None,
    )


@pytest.fixture()
def repository() -> PostgresCaseRepository:
    database_url = os.environ.get("PROXYLOOP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROXYLOOP_TEST_DATABASE_URL is required")
    with psycopg.connect(database_url) as connection:
        if connection.info.dbname != "proxyloop_test":
            raise AssertionError("Postgres integration tests require proxyloop_test")
    repository = PostgresCaseRepository(database_url)
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute(f"TRUNCATE TABLE {TABLE}, {TRACES_TABLE}")
    return repository


def _clock(*values: datetime):
    values_iter = iter(values)
    last = values[-1]

    def now() -> datetime:
        nonlocal last
        last = next(values_iter, last)
        return last

    return now


def _waiting(runtime: ThinAgentRuntime) -> tuple[object, object]:
    runtime.create_case()
    result = runtime.append_event(CASE_ID, content="Review the offer.")
    assert result.approval is not None
    return result.snapshot, result.approval


def _assert_non_provider_fields_equal(
    expected: CaseRuntimeState,
    actual: CaseRuntimeState,
) -> None:
    # Derived from the dataclass so a field added later is compared too.
    for field in fields(CaseRuntimeState):
        if field.name == "provider":
            continue
        assert getattr(actual, field.name) == getattr(expected, field.name), field.name


def _in_memory_waiting() -> tuple[ThinAgentRuntime, CaseRuntimeState]:
    """An in-memory Case awaiting approval, reached through a command so that
    `transitions` and `last_fast_decision` are populated."""

    runtime = ThinAgentRuntime(
        InMemoryCaseRepository(),
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    created = runtime.create_case()
    runtime.apply_command(
        CaseCommand(
            command_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            case_id=CASE_ID,
            command_type=CaseCommandType.APPEND_EVENT,
            occurred_at=BASE_TIME + timedelta(minutes=1),
            expected_revision=created.snapshot.revision,
            content="Review the offer.",
            event_type="consumer_message",
        )
    )
    state = runtime.repository.get(CASE_ID)
    assert state is not None
    assert state.transitions
    assert state.last_fast_decision is not None
    return runtime, state


def _codec_round_trip(state: CaseRuntimeState) -> CaseRuntimeState:
    payload = json.loads(json.dumps(PostgresCaseRepository._encode_state(state)))
    return PostgresCaseRepository._decode_state(
        state.snapshot.case.case_id, state.snapshot.revision, payload
    )


@pytest.mark.parametrize(
    ("field", "other_value"),
    [("transitions", ()), ("last_fast_decision", None)],
)
def test_round_trip_helper_compares_every_non_provider_field(
    field: str, other_value: object
) -> None:
    # C-7: AC3 says every non-Provider field round-trips; the helper must notice
    # a difference in any of them, not only the execution fields.
    _, state = _in_memory_waiting()
    changed = replace(state, **{field: other_value})

    with pytest.raises(AssertionError):
        _assert_non_provider_fields_equal(state, changed)


def test_every_non_provider_field_survives_the_postgres_codec() -> None:
    # C-7 without a database: the write/read codec keeps every non-Provider
    # field, for a waiting Case and for the executed terminal Case.
    runtime, waiting = _in_memory_waiting()
    _assert_non_provider_fields_equal(waiting, _codec_round_trip(waiting))

    approval = waiting.snapshot.approval_requests[0]
    runtime.apply_command(
        CaseCommand(
            command_id=APPROVAL_COMMAND_ID,
            case_id=CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=BASE_TIME + timedelta(minutes=2),
            expected_revision=waiting.snapshot.revision,
            approval_id=approval.approval_id,
            decision="approved",
            expected_case_revision=approval.case_revision,
            expected_action_intent_revision=approval.action_intent_revision,
        )
    )
    terminal = runtime.repository.get(CASE_ID)
    assert terminal is not None
    assert terminal.execution_count == 1
    assert terminal.execution_source_pins is not None
    assert len(terminal.transitions) == len(waiting.transitions) + 1
    _assert_non_provider_fields_equal(terminal, _codec_round_trip(terminal))


def _terminal_state(repository: PostgresCaseRepository) -> CaseRuntimeState:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    runtime = ThinAgentRuntime(
        repository,
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    _waiting(runtime)
    waiting = repository.get(CASE_ID)
    assert waiting is not None
    approval = waiting.snapshot.approval_requests[0]
    runtime.approve(CASE_ID, approval.approval_id)
    final = PostgresCaseRepository(database_url).get(CASE_ID)
    assert final is not None
    assert final.snapshot.completion_decision is not None
    return final


def test_postgres_round_trips_runtime_state_and_reconstructs_provider(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(
        repository, clock=_clock(BASE_TIME, BASE_TIME + timedelta(minutes=1))
    )
    runtime.create_case()
    offered = repository.get(CASE_ID)
    assert offered is not None
    assert offered.provider.state.value == "offered"

    waiting_result = runtime.append_event(CASE_ID, content="Review the offer.")
    waiting_snapshot = waiting_result.snapshot
    waiting = repository.get(CASE_ID)
    assert waiting is not None
    assert waiting.snapshot == waiting_snapshot
    assert waiting.provider.state.value == "awaiting_approval"

    rejected_runtime = ThinAgentRuntime(
        repository, clock=_clock(BASE_TIME + timedelta(minutes=2))
    )
    rejected = rejected_runtime.approve(
        CASE_ID,
        waiting_snapshot.approval_requests[0].approval_id,
        decision="rejected",
    )
    rejected_state = repository.get(CASE_ID)
    assert rejected_state is not None
    assert rejected_state.snapshot == rejected.snapshot
    assert rejected_state.provider.state.value == "awaiting_approval"


def test_postgres_explicit_model_to_scripted_switch_continues_case(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    # PR-13: the model Slow proposes the accept, so the event opens approval.
    fake_transport = _FakeCompletions(
        [_Response(_slow_output_proposing_accept()), _Response(_fast_output())]
    )
    fake_adapter = OpenAICompatibleAdapter(
        model="runtime-model",
        base_url="https://example.invalid/v1",
        api_key="test-only",
        client=_FakeClient(fake_transport),
    )
    model_runtime = ThinAgentRuntime(
        repository,
        clock=_clock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
        fast=fake_adapter,
        slow=fake_adapter,
    )
    created = model_runtime.create_case()
    # The model-authored standing proposal (5-minute expiry) survives the row.
    stored = PostgresCaseRepository(database_url).get(CASE_ID)
    assert stored is not None
    assert stored.standing_proposal is not None
    assert stored.standing_proposal.expires_at == BASE_TIME + timedelta(minutes=5)
    waiting = model_runtime.append_event(CASE_ID, content="Review the offer.")
    assert created.snapshot.case.case_id == CASE_ID
    assert waiting.approval is not None
    assert model_runtime.adapter_mode == "model"
    assert model_runtime.storage_mode == "postgres"
    assert len(fake_transport.calls) == 2
    assert [call["model"] for call in fake_transport.calls] == [
        "runtime-model",
        "runtime-model",
    ]

    switched_runtime = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(minutes=2)),
    )
    persisted = switched_runtime.repository.get(CASE_ID)
    assert persisted is not None
    assert persisted.snapshot == waiting.snapshot
    assert switched_runtime.adapter_mode == "scripted"
    assert switched_runtime.storage_mode == "postgres"

    continued = switched_runtime.approve(
        CASE_ID,
        waiting.approval.approval_id,
        expected_revision=waiting.snapshot.revision,
    )
    assert continued.snapshot.completion_decision is not None
    assert continued.execution_count == 1


def test_postgres_readiness_probe_is_read_only_select_one(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    repository.check_readiness()
    with psycopg.connect(database_url) as connection:
        row = connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone()
    assert row == (0,)


def test_postgres_restart_reaches_terminal_once_and_repeats_without_write(
    repository: PostgresCaseRepository,
) -> None:
    runtime_a = ThinAgentRuntime(
        repository, clock=_clock(BASE_TIME, BASE_TIME + timedelta(minutes=1))
    )
    waiting_snapshot, approval = _waiting(runtime_a)
    repository_b = PostgresCaseRepository(os.environ["PROXYLOOP_TEST_DATABASE_URL"])
    runtime_b = ThinAgentRuntime(
        repository_b, clock=_clock(BASE_TIME + timedelta(minutes=2))
    )
    completed = runtime_b.approve(
        CASE_ID,
        approval.approval_id,
        expected_revision=waiting_snapshot.revision,
        expected_case_revision=approval.case_revision,
        expected_action_intent_revision=approval.action_intent_revision,
    )
    assert completed.execution_count == 1
    state = repository_b.get(CASE_ID)
    assert state is not None
    terminal_revision = state.snapshot.revision
    evidence = state.snapshot.evidence

    runtime_c = ThinAgentRuntime(
        PostgresCaseRepository(os.environ["PROXYLOOP_TEST_DATABASE_URL"]),
        clock=_clock(BASE_TIME + timedelta(minutes=3)),
    )
    repeated = runtime_c.approve(CASE_ID, approval.approval_id)
    after = runtime_c.repository.get(CASE_ID)
    assert after is not None
    _assert_non_provider_fields_equal(state, after)
    assert repeated.execution_count == 1
    assert after.snapshot.revision == terminal_revision
    assert after.execution_count == 1
    assert after.snapshot.evidence == evidence


def test_postgres_pending_claim_recovers_after_final_write_failure(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    failing = _FinalWriteFailureRepository(database_url)
    runtime_a = ThinAgentRuntime(
        failing,
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    waiting_snapshot, approval = _waiting(runtime_a)
    with pytest.raises(CaseConflictError, match="final CAS"):
        runtime_a.approve(
            CASE_ID,
            approval.approval_id,
            expected_revision=waiting_snapshot.revision,
        )

    persisted = repository.get(CASE_ID)
    assert persisted is not None
    assert persisted.snapshot.pending_execution is True
    assert persisted.provider.state.value == "awaiting_approval"
    fresh_pending = PostgresCaseRepository(database_url).get(CASE_ID)
    assert fresh_pending is not None
    _assert_non_provider_fields_equal(persisted, fresh_pending)
    assert fresh_pending.provider.state.value == "awaiting_approval"
    runtime_b = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(minutes=2)),
    )
    recovered = runtime_b.approve(CASE_ID, approval.approval_id)
    assert recovered.execution_count == 1
    final = repository.get(CASE_ID)
    assert final is not None
    assert final.snapshot.pending_execution is False
    assert final.execution_count == 1
    assert final.provider.state.value == "confirmed"
    assert (
        len(
            [
                item
                for item in final.snapshot.evidence
                if item.source_type.value == "confirmation"
            ]
        )
        == 1
    )


APPROVAL_COMMAND_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _failed_pinned_approval(
    database_url: str,
) -> tuple[ThinAgentRuntime, CaseCommand]:
    """Claim an approval whose final write fails once; return the exact command."""

    failing = _FinalWriteFailureRepository(database_url)
    runtime = ThinAgentRuntime(
        failing,
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    waiting_snapshot, approval = _waiting(runtime)
    command = CaseCommand(
        command_id=APPROVAL_COMMAND_ID,
        case_id=CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        expected_revision=waiting_snapshot.revision,
        approval_id=approval.approval_id,
        decision="approved",
        expected_case_revision=approval.case_revision,
        expected_action_intent_revision=approval.action_intent_revision,
    )
    with pytest.raises(CaseConflictError, match="final CAS"):
        runtime.apply_command(command)
    pending = PostgresCaseRepository(database_url).get(CASE_ID)
    assert pending is not None
    assert pending.snapshot.pending_execution is True
    assert pending.execution_count == 0
    assert pending.provider.state.value == "awaiting_approval"
    return runtime, command


def _assert_single_persisted_commit(database_url: str) -> CaseRuntimeState:
    stored = PostgresCaseRepository(database_url).get(CASE_ID)
    assert stored is not None
    assert stored.snapshot.pending_execution is False
    assert stored.execution_claim is None
    assert stored.execution_count == 1
    assert stored.provider.state.value == "confirmed"
    assert [item.value for item in stored.provider.state_history].count(
        "confirmed"
    ) == 1
    assert [item.source_type.value for item in stored.snapshot.evidence].count(
        "confirmation"
    ) == 1
    assert [item.source_type.value for item in stored.snapshot.evidence].count(
        "simulator_transition"
    ) == 1
    again = PostgresCaseRepository(database_url).get(CASE_ID)
    assert again is not None
    _assert_non_provider_fields_equal(stored, again)
    assert again.execution_claim == stored.execution_claim
    return stored


def test_postgres_pinned_same_command_retry_converges_on_same_instance(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    runtime, command = _failed_pinned_approval(database_url)
    pending = PostgresCaseRepository(database_url).get(CASE_ID)
    assert pending is not None

    retried = runtime.apply_command(command)
    assert retried.terminal is True
    assert retried.deduplicated is False
    assert retried.before_revision == command.expected_revision
    stored = _assert_single_persisted_commit(database_url)
    assert stored.snapshot.completion_decision is not None
    assert stored.snapshot.completion_decision.decision is CompletionOutcome.COMPLETE
    assert len(stored.transitions) == 1
    # The persisted claim record is what admitted the old pin above.
    assert pending.execution_claim is not None
    assert pending.execution_claim.command_id == APPROVAL_COMMAND_ID
    assert pending.execution_claim.before_revision == command.expected_revision

    duplicate = runtime.apply_command(command)
    assert duplicate.deduplicated is True
    assert duplicate.model_copy(update={"deduplicated": False}) == retried


def test_postgres_pinned_same_command_retry_converges_on_fresh_instance(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    _, command = _failed_pinned_approval(database_url)

    fresh = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(minutes=3)),
    )
    retried = fresh.apply_command(command)
    assert retried.terminal is True
    assert retried.deduplicated is False
    assert retried.before_revision == command.expected_revision
    stored = _assert_single_persisted_commit(database_url)
    assert stored.snapshot.completion_decision is not None
    assert stored.snapshot.completion_decision.decision is CompletionOutcome.COMPLETE

    later = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(minutes=4)),
    )
    duplicate = later.apply_command(command)
    assert duplicate.deduplicated is True
    assert duplicate.model_copy(update={"deduplicated": False}) == retried


def test_postgres_late_recovery_persists_complete_at_claim_time(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    _, command = _failed_pinned_approval(database_url)
    assert command.approval_id is not None

    late = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(hours=2)),
    )
    recovered = late.approve(CASE_ID, command.approval_id)
    assert recovered.execution_count == 1
    completion = recovered.snapshot.completion_decision
    assert completion is not None
    assert completion.decision is CompletionOutcome.COMPLETE
    assert "offer_expired" not in completion.reason_codes
    assert completion.evaluated_at == BASE_TIME + timedelta(minutes=2)
    assert recovered.snapshot.case.phase is CasePhase.COMPLETE

    stored = _assert_single_persisted_commit(database_url)
    assert stored.snapshot.completion_decision == completion
    assert stored.snapshot.case.phase is CasePhase.COMPLETE
    with pytest.raises(CaseConflictError, match="case is terminal"):
        late.append_event(CASE_ID, content="After completion.")


def test_postgres_rejects_pending_execution_count_tampering(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    failing = _FinalWriteFailureRepository(database_url)
    runtime = ThinAgentRuntime(
        failing,
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    _waiting(runtime)
    waiting = repository.get(CASE_ID)
    assert waiting is not None
    approval = waiting.snapshot.approval_requests[0]
    with pytest.raises(CaseConflictError, match="final CAS"):
        runtime.approve(CASE_ID, approval.approval_id)
    with psycopg.connect(database_url) as connection:
        payload = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s", (CASE_ID,)
        ).fetchone()
        assert payload is not None
        stored_payload = payload[0]
        stored_payload["execution_count"] = 1
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(stored_payload), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


def test_postgres_rejects_execution_metadata_on_non_executing_case(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(repository, clock=_clock(BASE_TIME))
    runtime.create_case()
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        payload = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s", (CASE_ID,)
        ).fetchone()
        assert payload is not None
        stored_payload = payload[0]
        stored_payload["execution_source_pins"] = stored_payload["snapshot"]["pins"]
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(stored_payload), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


def test_postgres_revision_cas_allows_only_one_cross_instance_claim(
    repository: PostgresCaseRepository,
) -> None:
    runtime_a = ThinAgentRuntime(
        repository, clock=_clock(BASE_TIME, BASE_TIME + timedelta(minutes=1))
    )
    waiting_snapshot, approval = _waiting(runtime_a)
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    runtime_b = ThinAgentRuntime(
        PostgresCaseRepository(database_url),
        clock=_clock(BASE_TIME + timedelta(minutes=2)),
    )
    barrier = Barrier(2)

    def approve(runtime: ThinAgentRuntime):
        barrier.wait()
        try:
            return runtime.approve(
                CASE_ID,
                approval.approval_id,
                expected_revision=waiting_snapshot.revision,
            )
        except CaseConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, (runtime_a, runtime_b)))
    assert sum(isinstance(result, CaseConflictError) for result in results) == 1
    final = repository.get(CASE_ID)
    assert final is not None
    assert final.execution_count == 1
    assert final.snapshot.completion_decision is not None


def test_postgres_conflicts_and_strict_payload_fail_closed(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(repository, clock=_clock(BASE_TIME))
    runtime.create_case()
    state = repository.get(CASE_ID)
    assert state is not None
    with pytest.raises(CaseConflictError, match="already exists"):
        repository.create(state)
    with pytest.raises(CaseConflictError, match="stale"):
        repository.replace(CASE_ID, expected_revision=1, state=state)
    with pytest.raises(CaseNotFoundError, match="not found"):
        repository.replace(
            UUID("22222222-2222-4222-8222-222222222222"),
            expected_revision=1,
            state=state,
        )

    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb({"storage_version": 4}), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="unsupported Case storage version"):
        repository.get(CASE_ID)


def test_postgres_rejects_relational_revision_tampering(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(repository, clock=_clock(BASE_TIME))
    runtime.create_case()
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        connection.execute(
            f"UPDATE {TABLE} SET revision = revision + 1 WHERE case_id = %s",
            (CASE_ID,),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid") as raised:
        repository.get(CASE_ID)
    assert str(raised.value) == "stored Case payload is invalid"
    assert "revision" not in str(raised.value)


def test_postgres_rejects_version_one_extra_payload_fields(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(repository, clock=_clock(BASE_TIME))
    runtime.create_case()
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb({"storage_version": 1, "unexpected": True}), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


def test_postgres_rejects_authoritative_completion_metadata_tampering(
    repository: PostgresCaseRepository,
) -> None:
    runtime = ThinAgentRuntime(
        repository,
        clock=_clock(
            BASE_TIME,
            BASE_TIME + timedelta(minutes=1),
            BASE_TIME + timedelta(minutes=2),
        ),
    )
    _waiting(runtime)
    approval = repository.get(CASE_ID)
    assert approval is not None
    approval_id = approval.snapshot.approval_requests[0].approval_id
    runtime.approve(
        CASE_ID,
        approval_id,
        expected_revision=approval.snapshot.revision,
    )
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s",
            (CASE_ID,),
        ).fetchone()
        assert row is not None
        payload = row[0]
        payload["snapshot"]["completion_decision"]["reason_codes"] = [
            "tampered_completion_metadata"
        ]
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(payload), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


def test_postgres_rejects_terminal_planning_basis_pin_tampering(
    repository: PostgresCaseRepository,
) -> None:
    _terminal_state(repository)
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s",
            (CASE_ID,),
        ).fetchone()
        assert row is not None
        payload = row[0]
        payload["execution_source_pins"]["planning_basis_fingerprint"] = "0" * 64
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(payload), CASE_ID),
        )
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


@pytest.mark.parametrize(
    "tamper",
    ["delete", "source_ref", "content_hash", "observed_at", "case_id", "media_type"],
)
def test_postgres_rejects_simulator_transition_evidence_tampering(
    repository: PostgresCaseRepository,
    tamper: str,
) -> None:
    final = _terminal_state(repository)
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        payload = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s", (CASE_ID,)
        ).fetchone()
        assert payload is not None
        stored_payload = payload[0]
        evidence = stored_payload["snapshot"]["evidence"]
        index = next(
            index
            for index, item in enumerate(evidence)
            if item["source_type"] == "simulator_transition"
        )
        if tamper == "delete":
            del evidence[index]
        elif tamper == "source_ref":
            evidence[index]["source_ref"] = "tampered-idempotency-key"
        elif tamper == "content_hash":
            evidence[index]["content_hash"] = "0" * 64
        elif tamper == "observed_at":
            evidence[index]["observed_at"] = "2026-08-24T12:02:01Z"
            evidence[index]["captured_at"] = "2026-08-24T12:02:01Z"
        elif tamper == "case_id":
            evidence[index]["case_id"] = "22222222-2222-4222-8222-222222222222"
        elif tamper == "media_type":
            evidence[index]["media_type"] = "text/plain"
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(stored_payload), CASE_ID),
        )
    assert final.provider.state.value == "confirmed"
    with pytest.raises(RuntimeError, match="stored Case payload is invalid"):
        repository.get(CASE_ID)


# -- the append-only model-trace log (R-12, R-13b) -------------------------------


def _logged_flow(repository: PostgresCaseRepository) -> tuple[ModelTrace, ...]:
    runtime = ThinAgentRuntime(
        repository, clock=_clock(BASE_TIME, BASE_TIME + timedelta(minutes=1))
    )
    _waiting(runtime)
    traces = repository.list_model_traces(CASE_ID)
    # PR-14: the Judge's trace follows the admitted Slow call and round-trips.
    assert [trace.role for trace in traces] == ["slow", "judge", "fast"]
    return traces


def _raw_row(database_url: str, case_id: UUID = CASE_ID) -> tuple[object, ...]:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"SELECT revision, payload::text, updated_at FROM {TABLE} "
            "WHERE case_id = %s",
            (case_id,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def test_postgres_trace_log_appends_in_order_without_touching_the_case(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    slow, judge, fast = _logged_flow(repository)
    before = _raw_row(database_url)

    # Indistinguishable calls are two rows; order is append order (I4, I10).
    repository.append_model_traces(CASE_ID, (fast, slow))
    repository.append_model_traces(CASE_ID, ())

    assert repository.list_model_traces(CASE_ID) == (slow, judge, fast, fast, slow)
    assert _raw_row(database_url) == before  # I5: revision and bytes unchanged
    other = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValueError, match="another Case"):
        repository.append_model_traces(other, (slow,))
    assert repository.list_model_traces(other) == ()


def test_postgres_trace_log_needs_no_case_row_and_survives_truncation(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    traces = _logged_flow(repository)
    # No foreign key: the Case table still truncates on its own.
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute(f"TRUNCATE TABLE {TABLE}")
    assert repository.get(CASE_ID) is None
    assert repository.list_model_traces(CASE_ID) == traces

    # A rejected create has no Case row; its traces are appended anyway.
    repository.append_model_traces(CASE_ID, traces)
    assert repository.get(CASE_ID) is None
    assert repository.list_model_traces(CASE_ID) == (*traces, *traces)


@pytest.mark.parametrize("tamper", ["foreign_case", "invalid_shape"])
def test_postgres_trace_log_fails_closed_on_a_tampered_trace(
    repository: PostgresCaseRepository, tamper: str
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    _logged_flow(repository)
    with psycopg.connect(database_url) as connection:
        if tamper == "foreign_case":
            # Consistently foreign: the trace's own validators still pass.
            foreign = Jsonb("22222222-2222-4222-8222-222222222222")
            connection.execute(
                f"UPDATE {TRACES_TABLE} SET trace = jsonb_set("
                "jsonb_set(trace, '{case_id}', %s), '{input_pins,case_id}', %s)",
                (foreign, foreign),
            )
        else:
            connection.execute(
                f"UPDATE {TRACES_TABLE} SET trace = %s", (Jsonb({"unexpected": 1}),)
            )
    with pytest.raises(RuntimeError, match="stored model trace is invalid"):
        repository.list_model_traces(CASE_ID)


def test_postgres_bootstrap_moves_v2_inline_traces_to_the_log_once(
    repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    traces = _logged_flow(repository)
    state = repository.get(CASE_ID)
    assert state is not None
    garbage_id = UUID("33333333-3333-4333-8333-333333333333")
    # Rebuild the row exactly as the version 2 codec wrote it, traces inline,
    # and start from an empty log.
    with psycopg.connect(database_url) as connection, connection.transaction():
        stored = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s", (CASE_ID,)
        ).fetchone()
        assert stored is not None
        v2 = {
            **stored[0],
            "storage_version": 2,
            "model_traces": [trace.model_dump(mode="json") for trace in traces],
        }
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(v2), CASE_ID),
        )
        # A version 2 row whose traces are not an array is left for read.
        connection.execute(
            f"INSERT INTO {TABLE} (case_id, revision, payload) VALUES (%s, 1, %s)",
            (garbage_id, Jsonb({"storage_version": 2, "model_traces": "invalid"})),
        )
        connection.execute(f"TRUNCATE TABLE {TRACES_TABLE}")
    revision, _, updated_at = _raw_row(database_url)
    with pytest.raises(RuntimeError, match="unsupported Case storage version"):
        repository.get(CASE_ID)

    upgraded = PostgresCaseRepository(database_url)

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"SELECT revision, payload, updated_at FROM {TABLE} WHERE case_id = %s",
            (CASE_ID,),
        ).fetchone()
    assert row is not None
    assert (row[0], row[2]) == (revision, updated_at)
    assert row[1]["storage_version"] == 3
    assert "model_traces" not in row[1]
    loaded = upgraded.get(CASE_ID)
    assert loaded is not None
    assert loaded.snapshot == state.snapshot
    assert upgraded.list_model_traces(CASE_ID) == traces
    with pytest.raises(RuntimeError, match="unsupported Case storage version"):
        upgraded.get(garbage_id)

    PostgresCaseRepository(database_url)
    assert upgraded.list_model_traces(CASE_ID) == traces  # no duplicates
    assert upgraded.list_model_traces(garbage_id) == ()


def test_postgres_bootstrap_migrates_a_v2_row_without_a_traces_key(
    repository: PostgresCaseRepository,
) -> None:
    # The version 2 envelope defaulted a missing ``model_traces`` to empty.
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    _logged_flow(repository)
    state = repository.get(CASE_ID)
    assert state is not None
    with psycopg.connect(database_url) as connection, connection.transaction():
        stored = connection.execute(
            f"SELECT payload FROM {TABLE} WHERE case_id = %s", (CASE_ID,)
        ).fetchone()
        assert stored is not None
        v2 = {**stored[0], "storage_version": 2}
        assert "model_traces" not in v2
        connection.execute(
            f"UPDATE {TABLE} SET payload = %s WHERE case_id = %s",
            (Jsonb(v2), CASE_ID),
        )
        connection.execute(f"TRUNCATE TABLE {TRACES_TABLE}")
    revision, _, updated_at = _raw_row(database_url)

    upgraded = PostgresCaseRepository(database_url)

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"SELECT revision, payload, updated_at FROM {TABLE} WHERE case_id = %s",
            (CASE_ID,),
        ).fetchone()
    assert row is not None
    assert (row[0], row[2]) == (revision, updated_at)
    assert row[1]["storage_version"] == 3
    assert "model_traces" not in row[1]
    loaded = upgraded.get(CASE_ID)
    assert loaded is not None
    assert loaded.snapshot == state.snapshot
    assert upgraded.list_model_traces(CASE_ID) == ()


def test_runtime_configuration_defaults_and_fails_closed() -> None:
    runtime = runtime_from_environment(environ={})
    assert isinstance(runtime.repository, InMemoryCaseRepository)
    with pytest.raises(ValueError, match="must be memory or postgres"):
        runtime_from_environment(environ={"PROXYLOOP_STORAGE_MODE": "invalid"})
    with pytest.raises(ValueError, match="requires PROXYLOOP_DATABASE_URL"):
        runtime_from_environment(environ={"PROXYLOOP_STORAGE_MODE": "postgres"})


def test_runtime_configuration_keeps_model_and_storage_selection_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("PROXYLOOP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROXYLOOP_TEST_DATABASE_URL is required")
    config_module = importlib.import_module("proxyloop_api.config")

    class NoDispatchAdapter:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(config_module, "OpenAICompatibleAdapter", NoDispatchAdapter)
    scripted = runtime_from_environment(
        mode="scripted",
        environ={
            "PROXYLOOP_STORAGE_MODE": "postgres",
            "PROXYLOOP_DATABASE_URL": database_url,
        },
    )
    assert isinstance(scripted.repository, PostgresCaseRepository)
    model = runtime_from_environment(
        mode="model",
        environ={
            "PROXYLOOP_STORAGE_MODE": "postgres",
            "PROXYLOOP_DATABASE_URL": database_url,
            "PROXYLOOP_MODEL_API_KEY": "test-only",
            "PROXYLOOP_MODEL_BASE_URL": "https://example.invalid/v1",
            "PROXYLOOP_MODEL_NAME": "test-model",
        },
    )
    assert isinstance(model.repository, PostgresCaseRepository)
    assert isinstance(model._fast, NoDispatchAdapter)
    assert model._slow is model._fast


def test_postgres_bootstrap_error_has_stable_public_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(_repository: PostgresCaseRepository) -> object:
        raise psycopg.OperationalError("password=secret raw driver details")

    monkeypatch.setattr(PostgresCaseRepository, "_connect", fail_connect)
    with pytest.raises(RuntimeError) as raised:
        PostgresCaseRepository("postgresql://user:secret@example.invalid/db")
    assert str(raised.value) == "PostgreSQL Case storage schema initialization failed"
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_postgres_operation_error_suppresses_driver_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(_repository: PostgresCaseRepository) -> object:
        raise psycopg.OperationalError("password=secret raw driver details")

    repository = object.__new__(PostgresCaseRepository)
    repository._database_url = "postgresql://user:secret@example.invalid/db"
    monkeypatch.setattr(PostgresCaseRepository, "_connect", fail_connect)
    with pytest.raises(RuntimeError) as raised:
        repository.get(CASE_ID)
    assert str(raised.value) == "PostgreSQL Case storage operation failed"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("operation", ["append", "list"])
def test_postgres_trace_log_error_suppresses_driver_cause(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    def fail_connect(_repository: PostgresCaseRepository) -> object:
        raise psycopg.OperationalError("password=secret raw driver details")

    memory = InMemoryCaseRepository()
    ThinAgentRuntime(memory, clock=_clock(BASE_TIME)).create_case()
    traces = memory.list_model_traces(CASE_ID)
    assert traces
    repository = object.__new__(PostgresCaseRepository)
    repository._database_url = "postgresql://user:secret@example.invalid/db"
    monkeypatch.setattr(PostgresCaseRepository, "_connect", fail_connect)
    with pytest.raises(StorageUnavailableError) as raised:
        if operation == "append":
            repository.append_model_traces(CASE_ID, traces)
        else:
            repository.list_model_traces(CASE_ID)
    assert str(raised.value) == "PostgreSQL model trace operation failed"
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_server_main_reports_storage_failure_without_driver_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server_module = importlib.import_module("proxyloop_api.server")

    def fail_runtime(*, mode: str | None = None) -> ThinAgentRuntime:
        del mode
        try:
            raise psycopg.OperationalError("password=secret raw driver details")
        except psycopg.OperationalError as exc:
            raise RuntimeError(
                "PostgreSQL Case storage schema initialization failed"
            ) from exc

    uvicorn_calls: list[object] = []
    monkeypatch.setattr(server_module, "runtime_from_environment", fail_runtime)
    monkeypatch.setattr(
        server_module.uvicorn,
        "run",
        lambda *args, **kwargs: uvicorn_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(sys, "argv", ["proxyloop-api"])
    with pytest.raises(SystemExit) as raised:
        server_module.main()
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert "PostgreSQL Case storage schema initialization failed" in captured.err
    assert "secret" not in captured.err
    assert "OperationalError" not in captured.err
    assert uvicorn_calls == []
