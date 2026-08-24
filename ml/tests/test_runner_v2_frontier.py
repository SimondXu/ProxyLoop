from __future__ import annotations

from types import SimpleNamespace

from proxyloop_contracts import EvidenceType
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_evaluation.fresh_fixtures import build_fresh_phase03a1_bundle
from proxyloop_evaluation.models import (
    EvaluationConditionV2,
    EvaluationSummaryV2,
    RunStatus,
)
from proxyloop_evaluation.openai_frontier import OpenAIFrontierAdapter
from proxyloop_evaluation.qwen_mlx import QwenMLXAdapter, QwenMLXUnavailableError
from proxyloop_evaluation.replay_v2 import replay_condition_v2
from proxyloop_evaluation.runner_v2 import (
    initial_report_v2,
    run_frontier_condition_v2,
    run_qwen_reference_strategy_v2,
    run_slow_off_v2,
)
from proxyloop_evaluation.slow_output import (
    NonOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
)
from test_openai_frontier_adapter import (
    _fast_output,
    _QueuedClient,
    _QueuedCompletions,
)


def _slow_output(
    capability: str, *, preference_positions: tuple[int, ...] = ()
) -> SlowModelOutput:
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Safely pursue the Consumer goal.",
            current_subgoal="Choose one current capability.",
            ranked_preference_positions=preference_positions,
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=("Preserve constraints.",),
            fallback_outcomes=("Return control safely.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional confirmation is required.",
                ),
            ),
            escalation_conditions=("Terms change.",),
            replan_conditions=("Basis changes.",),
        ),
        next_capability=NonOfferCapabilityModelOutput(capability=capability),
    )


def test_frontier_r2_records_each_stage_and_high_reasoning() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    capability = fixture.reference_capability_id.removeprefix("simulator.")
    queued = _QueuedCompletions([_slow_output(capability), _fast_output()])
    adapter = OpenAIFrontierAdapter(
        client=_QueuedClient(SimpleNamespace(completions=queued)),
        reasoning_effort="high",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=2,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition_v2(
        adapter,
        condition=EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
        fixtures=(fixture,),
    )

    assert summary.slow_json_valid_count == 1
    assert summary.slow_schema_valid_count == 1
    assert summary.slow_semantic_valid_count == 1
    assert summary.slow_canonical_valid_count == 1
    assert summary.fast_json_valid_count == 1
    assert summary.fast_schema_valid_count == 1
    assert summary.fast_canonical_valid_count == 1
    assert summary.authorization_valid_count == 1
    assert summary.execution_valid_count == 1
    assert summary.provider_outcome_valid_count == 1
    assert summary.end_to_end_valid_count == 1
    assert summary.episodes[0].reference_match is True
    assert {
        call.requested_reasoning_effort for call in summary.episodes[0].hosted_calls
    } == {"high"}
    assert replay_condition_v2(summary, fixtures=(fixture,)) == ()

    tampered_row = summary.episodes[0].model_copy(
        update={
            "slow_semantic_valid": False,
            "slow_canonical_valid": False,
            "end_to_end_valid": False,
        }
    )
    tampered = EvaluationSummaryV2.from_episodes(
        condition=summary.condition,
        run_status=summary.run_status,
        expected_episode_count=1,
        model_call_count=summary.model_call_count,
        episodes=(tampered_row,),
        failure_slices=summary.failure_slices,
        model_provenance=summary.model_provenance,
        prompt_provenance=summary.prompt_provenance,
        hosted_max_cost_microusd=summary.hosted_max_cost_microusd,
    )
    assert "semantic replay mismatch" in replay_condition_v2(
        tampered, fixtures=(fixture,)
    )


def test_semantic_failure_does_not_erase_json_or_schema_validity() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    capability = fixture.reference_capability_id.removeprefix("simulator.")
    queued = _QueuedCompletions([_slow_output(capability, preference_positions=(0,))])
    adapter = OpenAIFrontierAdapter(
        client=_QueuedClient(SimpleNamespace(completions=queued)),
        reasoning_effort="medium",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition_v2(
        adapter,
        condition=EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        fixtures=(fixture,),
    )

    row = summary.episodes[0]
    assert row.slow_json_valid is True
    assert row.slow_schema_valid is True
    assert row.slow_semantic_valid is False
    assert row.slow_canonical_valid is False
    assert row.fast_json_valid is None
    assert summary.model_call_count == 1
    assert "slow_semantic_invalid" in row.failure_codes


def test_qwen_fast_plus_frontier_slow_uses_only_one_hosted_call() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    capability = fixture.reference_capability_id.removeprefix("simulator.")
    queued = _QueuedCompletions([_slow_output(capability)])
    adapter = OpenAIFrontierAdapter(
        client=_QueuedClient(SimpleNamespace(completions=queued)),
        reasoning_effort="high",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )
    qwen = QwenMLXAdapter(generator=lambda _: _fast_output().model_dump_json())

    summary = run_frontier_condition_v2(
        adapter,
        condition=EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
        fixtures=(fixture,),
        qwen=qwen,
    )

    assert summary.model_call_count == 2
    assert summary.end_to_end_valid_count == 1
    assert len(summary.episodes[0].hosted_calls) == 1
    assert summary.episodes[0].fast_canonical_valid is True
    assert replay_condition_v2(summary, fixtures=(fixture,)) == ()


def test_local_qwen_and_slow_off_conditions_are_semantically_replayable() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    qwen = QwenMLXAdapter(generator=lambda _: _fast_output().model_dump_json())

    qwen_summary = run_qwen_reference_strategy_v2(qwen, (fixture,))
    slow_off = run_slow_off_v2((fixture,))

    assert replay_condition_v2(qwen_summary, fixtures=(fixture,)) == ()
    assert replay_condition_v2(slow_off, fixtures=(fixture,)) == ()


def test_local_qwen_unavailable_is_truthful_not_run_without_usage() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]

    def unavailable(_: str) -> str:
        raise QwenMLXUnavailableError("mlx_unavailable", "Metal is unavailable")

    summary = run_qwen_reference_strategy_v2(
        QwenMLXAdapter(generator=unavailable),
        (fixture,),
    )

    assert summary.run_status is RunStatus.NOT_RUN_MODEL_UNAVAILABLE
    assert summary.not_run_reason == "Metal is unavailable"
    assert summary.evaluated_episode_count == 0
    assert summary.model_call_count == 0
    assert summary.episodes == ()


def test_local_qwen_runtime_error_is_terminal_failed_not_success() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]

    def broken(_: str) -> str:
        raise RuntimeError("generation crashed")

    summary = run_qwen_reference_strategy_v2(
        QwenMLXAdapter(generator=broken),
        (fixture,),
    )

    assert summary.run_status is RunStatus.FAILED
    assert summary.not_run_reason == "generation crashed"
    assert summary.evaluated_episode_count == 1
    assert summary.model_call_count == 1
    assert summary.episodes[0].adapter_status == "error"


def test_terminal_provider_failure_is_not_a_router_mismatch() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]

    class FailingCompletions:
        def create(self, **_: object) -> object:
            raise RuntimeError("provider unavailable")

    adapter = OpenAIFrontierAdapter(
        client=_QueuedClient(SimpleNamespace(completions=FailingCompletions())),
        reasoning_effort="medium",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    summary = run_frontier_condition_v2(
        adapter,
        condition=EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        fixtures=(fixture,),
        qwen=QwenMLXAdapter(generator=lambda _: _fast_output().model_dump_json()),
    )

    assert summary.run_status is RunStatus.FAILED
    assert summary.episodes[0].route_outcomes == ("slow_refresh",)
    assert summary.episodes[0].route_agreement is True
    assert "failed_provider_call" in summary.episodes[0].failure_codes
    assert "router_outcome_mismatch" not in summary.episodes[0].failure_codes


def test_reasoning_effort_mismatch_is_rejected_before_dispatch() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    queued = _QueuedCompletions([])
    adapter = OpenAIFrontierAdapter(
        client=_QueuedClient(SimpleNamespace(completions=queued)),
        reasoning_effort="high",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    import pytest

    with pytest.raises(ValueError, match="requires reasoning_effort=medium"):
        run_frontier_condition_v2(
            adapter,
            condition=EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
            fixtures=(fixture,),
        )

    assert queued.calls == []


def test_initial_r2_report_is_complete_and_truthfully_not_dispatched() -> None:
    bundle = build_fresh_phase03a1_bundle()

    report = initial_report_v2(bundle.fixtures, host_class="test")

    assert tuple(item.condition for item in report.conditions) == tuple(
        EvaluationConditionV2
    )
    assert report.conditions[0].end_to_end_valid_count == 32
    assert all(
        item.run_status.value.startswith("not_run") for item in report.conditions[1:]
    )
    assert report.phase_completion_ready is False
