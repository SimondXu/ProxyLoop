from __future__ import annotations

from proxyloop_agent_core import CaseCoordinator, DeterministicRouter, RouteRequest
from proxyloop_contracts import EvidenceType
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_evaluation.fresh_fixtures import (
    FRESH_PHASE03A1_OBSERVED_AT,
    build_fresh_phase03a1_bundle,
)
from proxyloop_evaluation.runner_v2 import (
    execute_model_proposal_r2,
    scripted_ceiling_condition_v2,
    snapshot_with_strategy,
    snapshot_without_strategy,
)
from proxyloop_evaluation.slow_output import (
    AcceptOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)


def _strategy() -> StrategyModelOutput:
    return StrategyModelOutput(
        primary_objective="Safely reduce the recurring bill.",
        current_subgoal="Choose the next bounded simulator capability.",
        ranked_preference_positions=(),
        allowed_disclosures=(),
        approval_required_disclosures=(),
        concession_ladder=("Preserve every hard constraint.",),
        fallback_outcomes=("Return control safely.",),
        required_completion_evidence=(
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A fictional Provider confirmation is required.",
            ),
        ),
        escalation_conditions=("Material terms change.",),
        replan_conditions=("Planning basis changes.",),
    )


def test_accept_offer_uses_exact_pending_then_approved_continuation() -> None:
    fixture = next(
        item
        for item in build_fresh_phase03a1_bundle().fixtures
        if item.reference_capability_id == "simulator.accept_offer"
    )
    initial = snapshot_without_strategy(fixture.snapshot)
    route = DeterministicRouter().route(
        RouteRequest(snapshot=initial, created_at=FRESH_PHASE03A1_OBSERVED_AT)
    )
    request = CaseCoordinator().build_slow_request(
        initial,
        reason_code=route.reason_codes[0],
        created_at=FRESH_PHASE03A1_OBSERVED_AT,
    )
    result = compile_slow_output(
        request,
        SlowModelOutput(
            strategy=_strategy(),
            next_capability=AcceptOfferCapabilityModelOutput(
                capability="accept_offer",
                offer_position=0,
            ),
        ),
    )
    planned = snapshot_with_strategy(initial, result)

    execution = execute_model_proposal_r2(fixture, planned, result)

    assert execution.route_outcomes == ("wait_for_approval", "fast_now")
    assert execution.approval_bound is True
    assert execution.authorization_valid is True
    assert execution.execution_valid is True
    assert execution.provider_outcome_valid is True
    assert execution.duplicate_reused is True
    assert execution.provider_mutation_count == 1
    assert execution.failure_codes == ()


def test_no_capability_is_attributed_without_execution_or_fake_success() -> None:
    fixture = build_fresh_phase03a1_bundle().fixtures[0]
    initial = snapshot_without_strategy(fixture.snapshot)
    route = DeterministicRouter().route(
        RouteRequest(snapshot=initial, created_at=FRESH_PHASE03A1_OBSERVED_AT)
    )
    request = CaseCoordinator().build_slow_request(
        initial,
        reason_code=route.reason_codes[0],
        created_at=FRESH_PHASE03A1_OBSERVED_AT,
    )
    result = compile_slow_output(
        request,
        SlowModelOutput(strategy=_strategy(), next_capability=None),
    )
    planned = snapshot_with_strategy(initial, result)

    execution = execute_model_proposal_r2(fixture, planned, result)

    assert execution.authorization_valid is None
    assert execution.execution_valid is None
    assert execution.provider_outcome_valid is None
    assert execution.completed is False
    assert execution.failure_codes == ("no_capability_proposal",)


def test_scripted_r2_ceiling_accepts_safe_noncompletion_without_fake_mutation() -> None:
    summary = scripted_ceiling_condition_v2(build_fresh_phase03a1_bundle().fixtures)

    assert summary.end_to_end_valid_count == 32
    assert summary.execution_valid_count == 32
    assert summary.provider_outcome_valid_count == 32
    assert summary.false_completion_count == 0
