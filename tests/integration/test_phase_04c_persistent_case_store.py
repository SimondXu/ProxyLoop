from __future__ import annotations

import importlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
    ThinAgentRuntime,
    runtime_from_environment,
)
from proxyloop_contracts import DialogueAct, EvidenceType
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)
from proxyloop_openai_adapter import (
    FastModelOutput,
    OpenAICompatibleAdapter,
    SlowModelOutput,
    StrategyModelOutput,
)
from psycopg.types.json import Jsonb

BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
TABLE = "proxyloop_case_runtime_states"


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
        connection.execute(f"TRUNCATE TABLE {TABLE}")
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
    assert actual.snapshot == expected.snapshot
    assert actual.events == expected.events
    assert actual.execution_count == expected.execution_count
    assert actual.execution_source_pins == expected.execution_source_pins
    assert actual.execution_intent == expected.execution_intent
    assert actual.execution_approval == expected.execution_approval
    assert actual.execution_proposal == expected.execution_proposal


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
    fake_transport = _FakeCompletions(
        [_Response(_slow_output()), _Response(_fast_output())]
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
            (Jsonb({"storage_version": 2}), CASE_ID),
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
