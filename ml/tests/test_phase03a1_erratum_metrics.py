from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from proxyloop_evaluation.models import (
    EpisodeEvaluationResultV2,
    EvaluationConditionV2,
    EvaluationSummaryV2,
    HostedCallEvidence,
    RunStatus,
)
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_MODEL,
    OpenAIFrontierAdapter,
)
from test_openai_frontier_adapter import _fast_output, _fast_view


def _episode(**updates: object) -> EpisodeEvaluationResultV2:
    values: dict[str, object] = {
        "episode_id": "r2-episode-1",
        "split": "development",
        "provider_split": "development",
        "safety": False,
        "route_outcomes": ("slow_refresh", "fast_now"),
        "adapter_status": "succeeded",
        "slow_json_valid": True,
        "slow_schema_valid": True,
        "slow_semantic_valid": True,
        "slow_canonical_valid": True,
        "fast_json_valid": True,
        "fast_schema_valid": True,
        "fast_canonical_valid": True,
        "fast_action_intent_null": True,
        "authorization_valid": True,
        "execution_valid": True,
        "provider_outcome_valid": True,
        "end_to_end_valid": True,
        "safe_noncompletion": False,
        "reference_match": True,
        "completed": True,
        "false_completion": False,
        "failure_codes": (),
        "leakage_violation_count": 0,
        "actual_cost_microusd": 0,
        "hosted_calls": (),
    }
    values.update(updates)
    return EpisodeEvaluationResultV2(**values)  # type: ignore[arg-type]


def test_stage_metrics_are_distinct_and_monotonic() -> None:
    semantic_failure = _episode(
        slow_semantic_valid=False,
        slow_canonical_valid=False,
        fast_json_valid=None,
        fast_schema_valid=None,
        fast_canonical_valid=None,
        fast_action_intent_null=None,
        authorization_valid=None,
        execution_valid=None,
        provider_outcome_valid=None,
        end_to_end_valid=False,
        completed=False,
        reference_match=None,
        failure_codes=("slow_semantic_invalid",),
    )

    assert semantic_failure.slow_json_valid is True
    assert semantic_failure.slow_schema_valid is True
    assert semantic_failure.slow_semantic_valid is False
    assert semantic_failure.end_to_end_valid is False

    with pytest.raises(ValueError, match=r"semantic.*schema"):
        _episode(slow_schema_valid=False, slow_semantic_valid=True)
    with pytest.raises(ValueError, match="end-to-end"):
        _episode(execution_valid=False, end_to_end_valid=True)
    with pytest.raises(ValueError, match="end-to-end"):
        _episode(authorization_valid=None, end_to_end_valid=True)


def test_summary_counts_each_stage_without_schema_conflation() -> None:
    rows = (
        _episode(),
        _episode(
            episode_id="r2-episode-2",
            slow_semantic_valid=False,
            slow_canonical_valid=False,
            fast_json_valid=None,
            fast_schema_valid=None,
            fast_canonical_valid=None,
            fast_action_intent_null=None,
            authorization_valid=None,
            execution_valid=None,
            provider_outcome_valid=None,
            end_to_end_valid=False,
            completed=False,
            reference_match=None,
            failure_codes=("slow_semantic_invalid",),
        ),
    )
    summary = EvaluationSummaryV2.from_episodes(
        condition=EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=2,
        model_call_count=2,
        episodes=rows,
        failure_slices={"slow_semantic_invalid": 1},
        model_provenance=(),
        prompt_provenance=(),
        hosted_max_cost_microusd=0,
    )

    assert summary.slow_json_valid_count == 2
    assert summary.slow_schema_valid_count == 2
    assert summary.slow_semantic_valid_count == 1
    assert summary.slow_canonical_valid_count == 1
    assert summary.end_to_end_valid_count == 1

    tampered = summary.model_dump(mode="python")
    tampered["input_tokens"] = 1
    with pytest.raises(ValueError, match="input token"):
        EvaluationSummaryV2.model_validate(tampered)


def test_reference_match_is_diagnostic_not_end_to_end_authority() -> None:
    row = _episode(reference_match=False, end_to_end_valid=True)

    assert row.reference_match is False
    assert row.end_to_end_valid is True


@dataclass
class _UsageDetails:
    reasoning_tokens: int = 7


@dataclass
class _Usage:
    prompt_tokens: int = 10
    completion_tokens: int = 20
    completion_tokens_details: _UsageDetails = field(default_factory=_UsageDetails)


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
    id: str = "resp-reasoning-r2"
    usage: _Usage = field(default_factory=_Usage)


@dataclass
class _Completions:
    response: _Response
    calls: list[dict[str, object]] = field(default_factory=list)

    def parse(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return self.response


def test_requested_reasoning_and_returned_tokens_are_bound_to_call_evidence() -> None:
    completions = _Completions(_Response(choices=[_Choice(_Message(_fast_output()))]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAIFrontierAdapter(
        client=client,
        reasoning_effort="high",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    adapter.decide(_fast_view())

    assert completions.calls[0]["reasoning_effort"] == "high"
    assert adapter.last_call is not None
    assert adapter.last_call.requested_reasoning_effort == "high"
    assert adapter.last_call.reasoning_tokens == 7
    evidence = HostedCallEvidence(
        status=adapter.last_call.status.value,
        requested_model=adapter.last_call.requested_model,
        response_model=adapter.last_call.response_model,
        response_model_version=adapter.last_call.response_model_version,
        response_id=adapter.last_call.response_id,
        requested_reasoning_effort=adapter.last_call.requested_reasoning_effort,
        reasoning_tokens=adapter.last_call.reasoning_tokens,
        prompt_fingerprint=adapter.last_call.prompt_fingerprint,
        schema_fingerprint=adapter.last_call.schema_fingerprint,
        input_tokens=adapter.last_call.input_tokens,
        output_tokens=adapter.last_call.output_tokens,
        latency_ms=adapter.last_call.latency_ms,
        estimated_cost_microusd=0,
        actual_cost_microusd=0,
    )
    assert evidence.requested_reasoning_effort == "high"
    assert evidence.reasoning_tokens == 7


def test_missing_reasoning_usage_is_explicit_none_not_zero() -> None:
    usage = _Usage()
    usage.completion_tokens_details = None  # type: ignore[assignment]
    completions = _Completions(
        _Response(choices=[_Choice(_Message(_fast_output()))], usage=usage)
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAIFrontierAdapter(
        client=client,
        reasoning_effort="medium",
        input_token_cap=100,
        max_output_tokens=100,
        call_cap=1,
        usd_ceiling=1.0,
    )

    adapter.decide(_fast_view())

    assert adapter.last_call is not None
    assert adapter.last_call.requested_reasoning_effort == "medium"
    assert adapter.last_call.reasoning_tokens is None
