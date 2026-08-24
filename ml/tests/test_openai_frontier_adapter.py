from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from proxyloop_contracts import (
    CapabilityManifest,
    ConsumerGoal,
    DelegatedAuthority,
    DialogueAct,
    EvidenceType,
    FastModelView,
    ModelInputPins,
    PlanningBasis,
    SlowReasonerView,
    SlowWorkRequest,
    StrategyPacket,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)
from proxyloop_evaluation.models import BaselineCondition
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    FRONTIER_BASE_URL,
    FRONTIER_MODEL,
    FastStructuredOutput,
    FrontierBudgetExceededError,
    FrontierCallStatus,
    FrontierProviderCallError,
    FrontierResponseValidationError,
    FrontierUnavailableError,
    OpenAIFrontierAdapter,
    build_fast_prompt,
    build_slow_prompt,
    estimate_frontier_cost,
)
from proxyloop_evaluation.qwen_mlx import QwenMLXAdapter
from proxyloop_evaluation.runner import _run_frontier_sequence, run_frontier_condition
from proxyloop_evaluation.slow_output import (
    CapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
)

from scripts.run_phase_03a1_harness import build_phase03a1_model_fixtures

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
STRATEGY_ID = UUID("99999999-9999-4999-8999-999999999999")


def _basis() -> PlanningBasis:
    components = {
        "goal_fingerprint": "1" * 64,
        "constraints_fingerprint": "2" * 64,
        "delegated_authority_fingerprint": "3" * 64,
        "verified_facts_fingerprint": "4" * 64,
        "material_offers_fingerprint": "5" * 64,
        "approval_state_fingerprint": "6" * 64,
        "provider_config_fingerprint": "7" * 64,
        "capability_manifest_fingerprint": "8" * 64,
    }
    return PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )


def _pins(*, event_cursor: int = 1) -> ModelInputPins:
    basis = _basis()
    return ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        case_revision=1,
        constraint_set_revision=1,
        fact_ledger_revision=1,
        strategy_id=STRATEGY_ID,
        strategy_revision=1,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=event_cursor,
        provider_config_ref="simulator.default",
        capability_manifest_version="sim-v1",
    )


def _strategy() -> StrategyPacket:
    # The adapter only needs a typed strategy identity for binding checks.  The
    # input model is deliberately constructed as a test seam; output models
    # remain fully validated by Pydantic.
    return StrategyPacket.model_construct(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=1,
        strategy_id=STRATEGY_ID,
        case_id=CASE_ID,
        case_revision=1,
        fact_ledger_revision=1,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        primary_objective="Reduce the recurring bill safely.",
        current_subgoal="Review the current offer.",
        hard_constraint_ids=(),
        ranked_preference_ids=(),
        allowed_disclosures=(),
        approval_required_disclosures=(),
        concession_ladder=("Preserve required features.",),
        fallback_outcomes=("Ask the consumer.",),
        required_completion_evidence=(),
        escalation_conditions=(),
        replan_conditions=(),
    )


def _fast_view() -> FastModelView:
    return FastModelView.model_construct(
        contract_type="fast_model_view",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        pins=_pins(),
        planning_basis=_basis(),
        goal=ConsumerGoal.model_construct(
            contract_type="consumer_goal",
            schema_version="1.0",
            revision=1,
            goal_id=UUID("44444444-4444-4444-8444-444444444444"),
            case_id=CASE_ID,
            created_at=NOW,
            updated_at=NOW,
            desired_outcome="Reduce the recurring bill safely.",
            target_monthly_total=None,
            required_features=(),
            forbidden_changes=(),
        ),
        constraints=(),
        verified_facts=(),
        strategy=_strategy(),
        recent_events=(),
        latest_provider_event=None,
        pending_slow_work=False,
        allowed_dialogue_acts=tuple(DialogueAct),
        allowed_disclosures=(),
    )


def _slow_request() -> SlowWorkRequest:
    pins = _pins()
    view = SlowReasonerView.model_construct(
        contract_type="slow_reasoner_view",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        pins=pins,
        planning_basis=_basis(),
        goal=_fast_view().goal,
        constraints=(),
        delegated_authority=DelegatedAuthority.model_construct(
            allowed_actions=(),
            approval_required_actions=(),
            allowed_disclosures=(),
        ),
        verified_facts=(),
        offers=(),
        approval_requests=(),
        strategy=_strategy(),
        recent_events=(),
        capability_manifest=CapabilityManifest.model_construct(
            contract_type="capability_manifest",
            schema_version="1.0",
            revision=1,
            namespace="simulator",
            manifest_version="sim-v1",
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
            capabilities=(),
        ),
        provider_config_ref="simulator.default",
        reason_code="case_initialized",
    )
    return SlowWorkRequest.model_construct(
        contract_type="slow_work_request",
        schema_version="1.0",
        revision=1,
        request_id=UUID("88888888-8888-4888-8888-888888888888"),
        case_id=CASE_ID,
        pins=pins,
        planning_basis=_basis(),
        view=view,
        reason_code="case_initialized",
        created_at=NOW,
    )


def _fast_output() -> FastStructuredOutput:
    return FastStructuredOutput(
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="Could you confirm the next step?",
        action_intent=None,
    )


def _slow_output() -> SlowModelOutput:
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Safely pursue the consumer goal.",
            current_subgoal="Handle the latest provider turn.",
            hard_constraint_ids=(),
            ranked_preference_ids=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=("Preserve hard constraints.",),
            fallback_outcomes=("Return control safely.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional Provider confirmation is required.",
                ),
            ),
            escalation_conditions=("Material terms change.",),
            replan_conditions=("Planning basis changes.",),
        ),
        capability_proposals=(),
    )


@dataclass
class _Usage:
    prompt_tokens: int = 10
    completion_tokens: int = 20


@dataclass
class _Message:
    parsed: object


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]
    model: str = f"{FRONTIER_MODEL}-2026-07-09"
    id: str = "resp-test-001"
    usage: _Usage = field(default_factory=_Usage)


@dataclass
class _Completions:
    response: _Response
    calls: list[dict[str, object]] = field(default_factory=list)

    def parse(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return self.response


@dataclass
class _Client:
    chat: SimpleNamespace


def _fake_client(parsed: object) -> _Client:
    completions = _Completions(_Response(choices=[_Choice(_Message(parsed))]))
    return _Client(SimpleNamespace(completions=completions))


@dataclass
class _QueuedCompletions:
    parsed_outputs: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    def parse(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return _Response(choices=[_Choice(_Message(self.parsed_outputs.pop(0)))])


@dataclass
class _QueuedClient:
    chat: SimpleNamespace


def _fixture_slow_output(*, capability_id: str) -> SlowModelOutput:
    fixture = build_phase03a1_model_fixtures()[0]
    hard_ids = tuple(
        item.constraint_id
        for item in fixture.snapshot.case.constraints
        if item.classification.value == "hard"
    )
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Safely pursue the consumer goal.",
            current_subgoal="Handle the latest fictional Provider turn.",
            hard_constraint_ids=hard_ids,
            ranked_preference_ids=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=("Preserve all hard constraints.",),
            fallback_outcomes=("Return control safely.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional Provider confirmation is required.",
                ),
            ),
            escalation_conditions=("Material terms change.",),
            replan_conditions=("Planning basis changes.",),
        ),
        capability_proposals=(
            CapabilityModelOutput(capability_id=capability_id, offer_id=None),
        ),
    )


def test_missing_credentials_is_typed_and_never_calls_or_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FRONTIER_API_KEY_ENV, raising=False)
    adapter = OpenAIFrontierAdapter(
        input_token_cap=10,
        max_output_tokens=10,
        call_cap=1,
        usd_ceiling=1.0,
    )

    with pytest.raises(FrontierUnavailableError) as exc_info:
        adapter.decide(_fast_view())

    assert exc_info.value.status is FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS
    assert adapter.last_call is not None
    assert adapter.last_call.status is FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS


def test_budget_is_rejected_before_fake_chat_call() -> None:
    fake = _fake_client({})
    adapter = OpenAIFrontierAdapter(
        client=fake,
        input_token_cap=10_000,
        max_output_tokens=10_000,
        call_cap=10,
        usd_ceiling=0.1,
    )

    with pytest.raises(FrontierBudgetExceededError) as exc_info:
        adapter.decide(_fast_view())

    assert exc_info.value.status is FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED
    assert fake.chat.completions.calls == []


def test_exact_conservative_budget_is_not_rejected_by_float_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FRONTIER_API_KEY_ENV, raising=False)
    estimate = estimate_frontier_cost(
        input_token_cap=8_192,
        output_token_cap=4_096,
        call_cap=32,
        usd_ceiling=3.670016,
    )
    adapter = OpenAIFrontierAdapter(
        input_token_cap=8_192,
        max_output_tokens=4_096,
        call_cap=32,
        usd_ceiling=estimate.maximum_cost_usd,
    )

    with pytest.raises(FrontierUnavailableError) as exc_info:
        adapter.decide(_fast_view())

    assert exc_info.value.status is FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS


def test_lazy_sdk_client_disables_retries_and_attempt_failure_is_auditable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    @dataclass
    class RaisingResponses:
        def parse(self, **_: object) -> object:
            raise TimeoutError("redacted")

    @dataclass
    class RaisingClient:
        chat: SimpleNamespace = field(
            default_factory=lambda: SimpleNamespace(completions=RaisingResponses())
        )

    def factory(**kwargs: object) -> RaisingClient:
        captured.update(kwargs)
        return RaisingClient()

    monkeypatch.setenv(FRONTIER_API_KEY_ENV, "test-only")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory))
    adapter = OpenAIFrontierAdapter(
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    with pytest.raises(FrontierProviderCallError) as exc_info:
        adapter.decide(_fast_view())

    assert captured == {
        "api_key": "test-only",
        "base_url": FRONTIER_BASE_URL,
        "max_retries": 0,
    }
    assert exc_info.value.status is FrontierCallStatus.FAILED_PROVIDER_CALL
    assert adapter.calls_started == 1
    assert adapter.last_call is not None
    assert adapter.last_call.actual_cost_usd is None
    assert adapter.last_call.status is FrontierCallStatus.FAILED_PROVIDER_CALL


def test_attempted_provider_failure_is_failed_not_not_run() -> None:
    fixture = build_phase03a1_model_fixtures()[0]

    @dataclass
    class RaisingResponses:
        def parse(self, **_: object) -> object:
            raise TimeoutError("redacted")

    @dataclass
    class RaisingClient:
        chat: SimpleNamespace = field(
            default_factory=lambda: SimpleNamespace(completions=RaisingResponses())
        )

    adapter = OpenAIFrontierAdapter(
        client=RaisingClient(),
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition(
        adapter,
        condition=BaselineCondition.FRONTIER_REFERENCE,
        fixtures=(fixture,),
    )

    assert summary.run_status.value == "failed"
    assert summary.model_call_count == 1
    assert summary.evaluated_episode_count == 1
    assert summary.cost_accounting_complete is False
    assert summary.episodes[0].hosted_calls[0].actual_cost_microusd is None
    assert "actual_cost_unknown" in summary.episodes[0].failure_codes


def test_unknown_cost_failure_aborts_the_second_hosted_condition() -> None:
    @dataclass
    class RaisingResponses:
        calls: int = 0

        def parse(self, **_: object) -> object:
            self.calls += 1
            raise TimeoutError("redacted")

    @dataclass
    class Client:
        chat: SimpleNamespace = field(
            default_factory=lambda: SimpleNamespace(completions=RaisingResponses())
        )

    first_client = Client()
    second_client = Client()
    first = OpenAIFrontierAdapter(
        client=first_client,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=32,
        usd_ceiling=1.0,
    )
    second = OpenAIFrontierAdapter(
        client=second_client,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=64,
        usd_ceiling=1.0,
    )

    fast_slow, reference = _run_frontier_sequence(
        first,
        second,
        qwen=QwenMLXAdapter(generator=lambda _: "{}"),
    )

    assert fast_slow.run_status.value == "failed"
    assert fast_slow.cost_accounting_complete is False
    assert reference.run_status.value == "not_run_budget_rejected"
    assert reference.model_call_count == 0
    assert first_client.chat.completions.calls == 1
    assert second_client.chat.completions.calls == 0


def test_prompt_builders_are_typed_and_do_not_include_evaluator_fields() -> None:
    fast = build_fast_prompt(_fast_view())
    slow = build_slow_prompt(_slow_request())
    serialized = json.dumps(
        {"fast": fast.messages, "slow": slow.messages},
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in ("expected_action", "family_id", "provider_split", "gold_label"):
        assert forbidden not in serialized
    assert fast.prompt_fingerprint
    assert fast.schema_fingerprint
    with pytest.raises(TypeError):
        build_fast_prompt({"expected_action": "accept_offer"})  # type: ignore[arg-type]


def test_fake_valid_fast_response_records_model_usage_and_cost() -> None:
    view = _fast_view()
    fake = _fake_client(_fast_output())
    adapter = OpenAIFrontierAdapter(
        client=fake,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    result = adapter.decide(view)

    assert result.pins == view.pins
    assert result.decision.action_intent is None
    assert fake.chat.completions.calls[0]["model"] == FRONTIER_MODEL
    assert fake.chat.completions.calls[0]["response_format"] is FastStructuredOutput
    assert adapter.last_call is not None
    assert adapter.last_call.response_model == f"{FRONTIER_MODEL}-2026-07-09"
    assert adapter.last_call.response_model_version == (f"{FRONTIER_MODEL}-2026-07-09")
    assert adapter.last_call.input_tokens == 10
    assert adapter.last_call.output_tokens == 20
    assert adapter.last_call.actual_cost_usd == pytest.approx(0.00044)
    assert adapter.last_structured_output is not None
    assert '"action_intent":null' in adapter.last_structured_output


def test_fake_valid_slow_response_compiles_current_request_binding() -> None:
    request = _slow_request()
    fake = _fake_client(_slow_output())
    adapter = OpenAIFrontierAdapter(
        client=fake,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    result = adapter.reason(request)

    assert result.request_id == request.request_id
    assert result.pins == request.pins
    assert result.planning_basis == request.planning_basis
    assert result.strategy_proposal is not None
    assert fake.chat.completions.calls[0]["response_format"] is SlowModelOutput


def test_fast_action_intent_and_slow_invented_reference_are_rejected() -> None:
    view = _fast_view()
    invalid_fields = _fast_output().model_dump(mode="python")
    invalid_fields.pop("action_intent")
    invalid = FastStructuredOutput.model_construct(
        **invalid_fields,
        action_intent=object(),
    )
    fast_adapter = OpenAIFrontierAdapter(
        client=_fake_client(invalid),
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )
    with pytest.raises(FrontierResponseValidationError) as fast_error:
        fast_adapter.decide(view)
    assert fast_error.value.status is FrontierCallStatus.FAILED_INVALID_RESPONSE

    request = _slow_request()
    invalid_strategy = _slow_output().strategy.model_copy(
        update={"hard_constraint_ids": (UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),)}
    )
    invalid_slow = SlowModelOutput(
        strategy=invalid_strategy,
        capability_proposals=(),
    )
    slow_adapter = OpenAIFrontierAdapter(
        client=_fake_client(invalid_slow),
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )
    with pytest.raises(FrontierResponseValidationError) as slow_error:
        slow_adapter.reason(request)
    assert slow_error.value.status is FrontierCallStatus.FAILED_INVALID_RESPONSE


def test_cost_estimator_uses_frozen_rates_and_call_cap() -> None:
    estimate = estimate_frontier_cost(
        input_token_cap=1_000,
        output_token_cap=500,
        call_cap=3,
        usd_ceiling=1.0,
    )
    assert estimate.per_call_cost_usd == pytest.approx(0.014)
    assert estimate.maximum_cost_usd == pytest.approx(0.042)


def test_frontier_reference_runner_uses_typed_slow_then_fast_and_executor() -> None:
    fixture = build_phase03a1_model_fixtures()[0]
    assert fixture.reference_capability_id == "simulator.request_replan"
    completions = _QueuedCompletions(
        [
            _fixture_slow_output(
                capability_id=fixture.reference_capability_id,
            ),
            _fast_output(),
        ]
    )
    fake = _QueuedClient(SimpleNamespace(completions=completions))
    adapter = OpenAIFrontierAdapter(
        client=fake,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=2,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition(
        adapter,
        condition=BaselineCondition.FRONTIER_REFERENCE,
        fixtures=(fixture,),
    )

    assert summary.run_status.value == "succeeded"
    assert summary.model_call_count == 2
    assert summary.valid_outcome_count == 1
    assert summary.false_completion_count == 0
    assert summary.actual_cost_microusd == 880
    assert summary.episodes[0].route_outcomes == ("slow_refresh", "fast_now")
    assert summary.episodes[0].failure_codes == ()
    assert summary.episodes[0].raw_output_excerpt is not None
    assert '"slow"' in summary.episodes[0].raw_output_excerpt
    assert '"fast"' in summary.episodes[0].raw_output_excerpt
    assert [call["response_format"] for call in fake.chat.completions.calls] == [
        SlowModelOutput,
        FastStructuredOutput,
    ]


def test_frontier_failure_slices_include_reference_safety_and_route() -> None:
    fixture = build_phase03a1_model_fixtures()[0]
    completions = _QueuedCompletions(
        [
            _fixture_slow_output(capability_id="simulator.decline"),
            _fast_output(),
        ]
    )
    fake = _QueuedClient(SimpleNamespace(completions=completions))
    adapter = OpenAIFrontierAdapter(
        client=fake,
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=2,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition(
        adapter,
        condition=BaselineCondition.FRONTIER_REFERENCE,
        fixtures=(fixture,),
    )

    code = "capability_reference_mismatch"
    assert summary.failure_slices[code] == 1
    safety = str(fixture.safety_only).lower()
    assert summary.failure_slices[f"safety:{safety}:{code}"] == 1
    assert summary.failure_slices[f"route:slow_refresh:{code}"] == 1
    assert summary.failure_slices[f"route:fast_now:{code}"] == 1
