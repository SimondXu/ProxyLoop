from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import psycopg
import pytest
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    CaseRepository,
    CaseRuntimeState,
    InMemoryCaseRepository,
    PostgresCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_contracts import ApprovalDecision, EventActor, Money

BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
CREATE_COMMAND_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EVENT_COMMAND_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
APPROVAL_COMMAND_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
EXPIRY_COMMAND_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _runtime(
    repository: CaseRepository,
    now: datetime,
) -> ThinAgentRuntime:
    return ThinAgentRuntime(repository, clock=lambda: now)


def _create_command() -> CaseCommand:
    return CaseCommand(
        command_id=CREATE_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        occurred_at=BASE_TIME,
        current_monthly_total=Money(amount_minor=9200, currency="USD"),
        target_monthly_total=Money(amount_minor=7500, currency="USD"),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


def _event_command() -> CaseCommand:
    return CaseCommand(
        command_id=EVENT_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        occurred_at=BASE_TIME + timedelta(minutes=1),
        expected_revision=2,
        content="Review the fictional offer.",
        event_type="consumer_message",
    )


def test_case_command_rejects_non_utc_and_cross_command_fields() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        CaseCommand(
            **{
                **_event_command().model_dump(),
                "occurred_at": datetime.fromisoformat("2026-08-26T08:01:00-04:00"),
            }
        )
    with pytest.raises(ValueError, match="another command"):
        CaseCommand(
            **{
                **_event_command().model_dump(),
                "approval_id": UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            }
        )


def test_command_receipts_deduplicate_full_scripted_flow() -> None:
    repository = InMemoryCaseRepository()
    created = _runtime(repository, BASE_TIME).apply_command(_create_command())
    duplicate_create = _runtime(repository, BASE_TIME).apply_command(_create_command())
    assert created.after_revision == 2
    assert duplicate_create.model_copy(update={"deduplicated": False}) == created
    assert duplicate_create.deduplicated is True

    event = _runtime(repository, BASE_TIME + timedelta(minutes=1)).apply_command(
        _event_command()
    )
    duplicate_event = _runtime(
        repository, BASE_TIME + timedelta(minutes=1)
    ).apply_command(_event_command())
    assert event.after_revision == 4
    assert event.approval_id is not None
    assert event.approval_expires_at is not None
    assert duplicate_event.model_copy(update={"deduplicated": False}) == event

    event_result = _runtime(
        repository, BASE_TIME + timedelta(minutes=1)
    ).current_result(SCRIPTED_CASE_ID, transition=event)
    assert event_result.fast_decision is not None
    approval_command = CaseCommand(
        command_id=APPROVAL_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        expected_revision=event.after_revision,
        approval_id=event.approval_id,
        decision="approved",
        expected_case_revision=1,
        expected_action_intent_revision=1,
    )
    approved = _runtime(repository, BASE_TIME + timedelta(minutes=2)).apply_command(
        approval_command
    )
    duplicate_approval = _runtime(
        repository, BASE_TIME + timedelta(minutes=2)
    ).apply_command(approval_command)
    assert approved.after_revision == 6
    assert approved.terminal is True
    assert duplicate_approval.model_copy(update={"deduplicated": False}) == approved

    final = repository.get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.execution_count == 1
    assert len(final.transitions) == 3
    assert (
        len(
            [
                item
                for item in final.snapshot.evidence
                if item.source_type.value in {"simulator_transition", "confirmation"}
            ]
        )
        == 2
    )


def test_same_command_id_with_different_semantics_fails_before_mutation() -> None:
    repository = InMemoryCaseRepository()
    runtime = _runtime(repository, BASE_TIME)
    runtime.apply_command(_create_command())

    changed_body = _create_command().model_copy(
        update={
            "target_monthly_total": Money(amount_minor=7400, currency="USD"),
        }
    )
    with pytest.raises(CaseConflictError, match="different command"):
        runtime.apply_command(changed_body)

    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert len(state.transitions) == 1
    assert state.snapshot.revision == 2

    changed_type = _event_command().model_copy(update={"command_id": CREATE_COMMAND_ID})
    with pytest.raises(CaseConflictError, match="different command"):
        runtime.apply_command(changed_type)

    state_after_type_mismatch = repository.get(SCRIPTED_CASE_ID)
    assert state_after_type_mismatch is not None
    assert state_after_type_mismatch.snapshot.revision == 2
    assert len(state_after_type_mismatch.transitions) == 1


def test_legacy_receipt_is_decodable_but_not_reusable() -> None:
    repository = InMemoryCaseRepository()
    runtime = _runtime(repository, BASE_TIME)
    runtime.apply_command(_create_command())
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    legacy = CaseRuntimeState(
        snapshot=state.snapshot,
        events=state.events,
        provider=state.provider,
        execution_count=state.execution_count,
        transitions=(
            state.transitions[0].model_copy(update={"command_fingerprint": None}),
        ),
    )
    repository.replace(
        SCRIPTED_CASE_ID,
        expected_revision=state.snapshot.revision,
        state=legacy,
    )

    with pytest.raises(CaseConflictError, match="legacy command receipt"):
        runtime.apply_command(_create_command())


def test_expiry_command_writes_canonical_system_transition_once() -> None:
    repository = InMemoryCaseRepository()
    _runtime(repository, BASE_TIME).apply_command(_create_command())
    waiting = _runtime(repository, BASE_TIME + timedelta(minutes=1)).apply_command(
        _event_command()
    )
    assert waiting.approval_id is not None
    assert waiting.approval_expires_at is not None
    expiry = CaseCommand(
        command_id=EXPIRY_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.EXPIRE_APPROVAL,
        occurred_at=waiting.approval_expires_at,
        expected_revision=waiting.after_revision,
        approval_id=waiting.approval_id,
        approval_expires_at=waiting.approval_expires_at,
    )
    expired = _runtime(repository, waiting.approval_expires_at).apply_command(expiry)
    duplicate = _runtime(repository, waiting.approval_expires_at).apply_command(expiry)
    assert duplicate.model_copy(update={"deduplicated": False}) == expired

    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    approval = state.snapshot.approval_requests[0]
    event = state.snapshot.visible_events[-1]
    assert approval.decision is ApprovalDecision.EXPIRED
    assert approval.decided_at == approval.expires_at
    assert event.actor is EventActor.SYSTEM
    assert event.event_type == "approval_expired"
    assert state.execution_count == 0
    assert state.snapshot.pending_execution is False
    assert not any(
        item.source_type.value in {"simulator_transition", "confirmation"}
        for item in state.snapshot.evidence
    )


@pytest.fixture()
def postgres_repository() -> PostgresCaseRepository:
    database_url = os.environ.get("PROXYLOOP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROXYLOOP_TEST_DATABASE_URL is required")
    with psycopg.connect(database_url) as connection:
        if connection.info.dbname != "proxyloop_test":
            raise AssertionError("Postgres integration tests require proxyloop_test")
    repository = PostgresCaseRepository(database_url)
    with psycopg.connect(database_url) as connection, connection.transaction():
        connection.execute("TRUNCATE TABLE proxyloop_case_runtime_states")
    return repository


def test_postgres_receipt_deduplicates_across_runtime_instances(
    postgres_repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    created = _runtime(postgres_repository, BASE_TIME).apply_command(_create_command())
    duplicate = _runtime(PostgresCaseRepository(database_url), BASE_TIME).apply_command(
        _create_command()
    )
    assert duplicate.model_copy(update={"deduplicated": False}) == created

    waiting = _runtime(
        PostgresCaseRepository(database_url), BASE_TIME + timedelta(minutes=1)
    ).apply_command(_event_command())
    assert waiting.approval_id is not None
    approval_command = CaseCommand(
        command_id=APPROVAL_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        expected_revision=waiting.after_revision,
        approval_id=waiting.approval_id,
        decision="approved",
        expected_case_revision=1,
        expected_action_intent_revision=1,
    )
    completed = _runtime(
        PostgresCaseRepository(database_url), BASE_TIME + timedelta(minutes=2)
    ).apply_command(approval_command)
    duplicate_callback = _runtime(
        PostgresCaseRepository(database_url), BASE_TIME + timedelta(minutes=3)
    ).apply_command(approval_command)
    assert duplicate_callback.model_copy(update={"deduplicated": False}) == completed

    final = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert final is not None
    assert final.execution_count == 1
    assert len(final.transitions) == 3
    assert (
        len(
            [
                item
                for item in final.snapshot.evidence
                if item.source_type.value in {"simulator_transition", "confirmation"}
            ]
        )
        == 2
    )


def test_postgres_approval_and_expiry_race_has_one_cas_winner(
    postgres_repository: PostgresCaseRepository,
) -> None:
    database_url = os.environ["PROXYLOOP_TEST_DATABASE_URL"]
    _runtime(postgres_repository, BASE_TIME).apply_command(_create_command())
    waiting = _runtime(
        PostgresCaseRepository(database_url), BASE_TIME + timedelta(minutes=1)
    ).apply_command(_event_command())
    assert waiting.approval_id is not None
    assert waiting.approval_expires_at is not None
    approval = CaseCommand(
        command_id=APPROVAL_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.DECIDE_APPROVAL,
        occurred_at=waiting.approval_expires_at - timedelta(microseconds=1),
        expected_revision=waiting.after_revision,
        approval_id=waiting.approval_id,
        decision="approved",
    )
    expiry = CaseCommand(
        command_id=EXPIRY_COMMAND_ID,
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.EXPIRE_APPROVAL,
        occurred_at=waiting.approval_expires_at,
        expected_revision=waiting.after_revision,
        approval_id=waiting.approval_id,
        approval_expires_at=waiting.approval_expires_at,
    )
    barrier = Barrier(2)

    def apply(command: CaseCommand) -> str:
        runtime = ThinAgentRuntime(PostgresCaseRepository(database_url))
        barrier.wait()
        try:
            runtime.apply_command(command)
        except CaseConflictError:
            return "conflict"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(apply, (approval, expiry)))

    assert sorted(outcomes) == ["applied", "conflict"]
    state = PostgresCaseRepository(database_url).get(SCRIPTED_CASE_ID)
    assert state is not None
    decision = state.snapshot.approval_requests[0].decision
    assert decision in {ApprovalDecision.APPROVED, ApprovalDecision.EXPIRED}
    assert state.execution_count == (1 if decision is ApprovalDecision.APPROVED else 0)
    assert len(state.transitions) == 3
