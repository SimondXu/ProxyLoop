"""Phase 03A1-E execution seam with exact approval continuation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from proxyloop_agent_core import (
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    DeterministicRouter,
    PreparedSimulatorExecution,
    RouteRequest,
)
from proxyloop_contracts import (
    ActionIntent,
    ApprovalDecision,
    ApprovalRequest,
    CaseContextSnapshot,
    EventActor,
    Evidence,
    EvidenceType,
    SlowWorkResult,
    VisibleCaseEvent,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_provider_simulator import MultiTurnProviderEnvironment
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnTransition,
    SimulatorCapabilityAttempt,
)

from .fresh_fixtures import (
    FRESH_PHASE03A1_OBSERVED_AT,
    FreshPhase03A1ModelFixture,
)
from .models import (
    EpisodeEvaluationResultV2,
    EvaluationConditionV2,
    EvaluationReportV2,
    EvaluationSummaryV2,
    HostedCallEvidence,
    ModelProvenance,
    PromptProvenance,
    RunStatus,
)
from .slow_output import (
    AcceptOfferCapabilityModelOutput,
    NonOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)


@dataclass(frozen=True, slots=True)
class ExecutionEvaluationV2:
    route_outcomes: tuple[str, ...]
    approval_bound: bool | None
    authorization_valid: bool | None
    execution_valid: bool | None
    provider_outcome_valid: bool | None
    completed: bool
    false_completion: bool
    duplicate_reused: bool
    provider_mutation_count: int
    failure_codes: tuple[str, ...]
    next_snapshot: CaseContextSnapshot


class _FrontierRecordLike(Protocol):
    @property
    def response_model_version(self) -> str | None: ...


def snapshot_without_strategy(snapshot: CaseContextSnapshot) -> CaseContextSnapshot:
    pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    return CaseContextSnapshot.model_validate(
        snapshot.model_copy(update={"strategy": None, "pins": pins}).model_dump(
            mode="python"
        )
    )


def snapshot_with_strategy(
    snapshot: CaseContextSnapshot,
    result: SlowWorkResult,
) -> CaseContextSnapshot:
    strategy = result.strategy_proposal
    if strategy is None:
        raise ValueError("accepted Slow output did not propose a strategy")
    pins = snapshot.pins.model_copy(
        update={
            "strategy_id": strategy.strategy_id,
            "strategy_revision": strategy.revision,
        }
    )
    return CaseContextSnapshot.model_validate(
        snapshot.model_copy(update={"strategy": strategy, "pins": pins}).model_dump(
            mode="python"
        )
    )


def execute_model_proposal_r2(
    fixture: FreshPhase03A1ModelFixture,
    snapshot: CaseContextSnapshot,
    result: SlowWorkResult,
) -> ExecutionEvaluationV2:
    """Execute one inert proposal through approval, policy, and Executor only."""

    if not result.capability_proposals and not result.action_proposals:
        return ExecutionEvaluationV2(
            route_outcomes=(),
            approval_bound=None,
            authorization_valid=None,
            execution_valid=None,
            provider_outcome_valid=None,
            completed=False,
            false_completion=False,
            duplicate_reused=False,
            provider_mutation_count=0,
            failure_codes=("no_capability_proposal",),
            next_snapshot=snapshot,
        )
    if len(result.capability_proposals) != 1 or len(result.action_proposals) != 1:
        return ExecutionEvaluationV2(
            route_outcomes=(),
            approval_bound=False,
            authorization_valid=False,
            execution_valid=False,
            provider_outcome_valid=None,
            completed=False,
            false_completion=False,
            duplicate_reused=False,
            provider_mutation_count=0,
            failure_codes=("one_capability_per_turn_violated",),
            next_snapshot=snapshot,
        )

    proposal = result.capability_proposals[0]
    action = result.action_proposals[0]
    environment = MultiTurnProviderEnvironment(fixture.scenario)
    opening = environment.start()
    canonical_to_public = {
        str(canonical.offer_id): public.offer_id
        for canonical, public in zip(snapshot.offers, opening.turn.offers, strict=True)
    }
    canonical_offer_id = (
        str(action.offer_ref.offer_id) if action.offer_ref is not None else None
    )
    public_offer_id = (
        canonical_to_public.get(canonical_offer_id)
        if canonical_offer_id is not None
        else None
    )
    if canonical_offer_id is not None and public_offer_id is None:
        return ExecutionEvaluationV2(
            route_outcomes=(),
            approval_bound=False,
            authorization_valid=False,
            execution_valid=False,
            provider_outcome_valid=None,
            completed=False,
            false_completion=False,
            duplicate_reused=False,
            provider_mutation_count=0,
            failure_codes=("model_offer_not_current",),
            next_snapshot=snapshot,
        )

    attempt = SimulatorCapabilityAttempt(
        capability_id=proposal.capability.capability_id,
        offer_id=public_offer_id,
        idempotency_key=action.idempotency_key,
    )
    executed_at = FRESH_PHASE03A1_OBSERVED_AT + timedelta(minutes=2)
    adapter = _R2CapabilityAdapter(
        environment=environment,
        attempt=attempt,
        canonical_offer_id=canonical_offer_id,
        case_id=snapshot.case.case_id,
        observed_at=opening.observed_at,
        captured_at=executed_at,
    )
    executor = CapabilityExecutor(adapter)
    executable_snapshot = _rebind_snapshot(
        snapshot,
        action_intents=(*snapshot.action_intents, action),
        approval_requests=(),
    )
    approval: ApprovalRequest | None = None
    route_outcomes: list[str] = []
    approval_bound: bool | None = None
    if action.approval_required:
        pending = _pending_approval(action)
        pending_snapshot = _rebind_snapshot(
            executable_snapshot,
            action_intents=executable_snapshot.action_intents,
            approval_requests=(pending,),
        )
        pending_route = DeterministicRouter().route(
            RouteRequest(
                snapshot=pending_snapshot,
                created_at=FRESH_PHASE03A1_OBSERVED_AT + timedelta(seconds=31),
            )
        )
        route_outcomes.append(pending_route.outcome.value)
        if pending_route.outcome.value != "wait_for_approval":
            return ExecutionEvaluationV2(
                route_outcomes=tuple(route_outcomes),
                approval_bound=False,
                authorization_valid=False,
                execution_valid=False,
                provider_outcome_valid=None,
                completed=False,
                false_completion=False,
                duplicate_reused=False,
                provider_mutation_count=0,
                failure_codes=("approval_wait_route_mismatch",),
                next_snapshot=pending_snapshot,
            )
        approval_decided_at = FRESH_PHASE03A1_OBSERVED_AT + timedelta(minutes=1)
        approval = pending.model_copy(
            update={
                "revision": pending.revision + 1,
                "decision": ApprovalDecision.APPROVED,
                "decided_at": approval_decided_at,
            }
        )
        event = VisibleCaseEvent(
            contract_type="visible_case_event",
            schema_version="1.0",
            revision=1,
            event_id=_stable_uuid4(f"approval-event:{approval.approval_id}"),
            case_id=snapshot.case.case_id,
            event_cursor=pending_snapshot.event_cursor + 1,
            occurred_at=approval_decided_at,
            actor=EventActor.CONSUMER,
            event_type="approval_decision",
            content="Consumer approved the pending fictional action.",
        )
        executable_snapshot = _rebind_snapshot(
            pending_snapshot,
            action_intents=pending_snapshot.action_intents,
            approval_requests=(approval,),
            visible_events=(*pending_snapshot.visible_events, event),
        )
        resumed = DeterministicRouter().route(
            RouteRequest(
                snapshot=executable_snapshot,
                created_at=approval_decided_at,
                triggering_event=event,
            )
        )
        route_outcomes.append(resumed.outcome.value)
        approval_bound = approval.action_intent_id == action.intent_id

    request = CapabilityExecutionRequest(
        snapshot=executable_snapshot,
        source_pins=executable_snapshot.pins,
        proposal=proposal,
        action_intent=action,
        approval=approval,
        executed_at=executed_at,
    )
    outcome = executor.execute(request)
    if outcome.status is CapabilityExecutionStatus.REJECTED:
        return ExecutionEvaluationV2(
            route_outcomes=tuple(route_outcomes),
            approval_bound=approval_bound,
            authorization_valid=False,
            execution_valid=False,
            provider_outcome_valid=None,
            completed=False,
            false_completion=False,
            duplicate_reused=False,
            provider_mutation_count=environment.provider_mutation_count,
            failure_codes=outcome.reason_codes,
            next_snapshot=executable_snapshot,
        )
    duplicate = executor.execute(request)
    duplicate_reused = (
        duplicate.status is CapabilityExecutionStatus.REUSED
        and duplicate.evidence == outcome.evidence
    )
    transition = adapter.transition
    if transition is None:
        return ExecutionEvaluationV2(
            route_outcomes=tuple(route_outcomes),
            approval_bound=approval_bound,
            authorization_valid=True,
            execution_valid=False,
            provider_outcome_valid=None,
            completed=False,
            false_completion=False,
            duplicate_reused=duplicate_reused,
            provider_mutation_count=environment.provider_mutation_count,
            failure_codes=("executor_missing_provider_transition",),
            next_snapshot=executable_snapshot,
        )
    failures: list[str] = []
    if not duplicate_reused or adapter.commits != 1:
        failures.append("duplicate_execution_not_idempotent")
    if not transition.verification.valid_outcome:
        failures.append("invalid_provider_outcome")
    return ExecutionEvaluationV2(
        route_outcomes=tuple(route_outcomes),
        approval_bound=approval_bound,
        authorization_valid=True,
        execution_valid=True,
        provider_outcome_valid=transition.verification.valid_outcome,
        completed=transition.verification.completed,
        false_completion=transition.verification.false_completion,
        duplicate_reused=duplicate_reused,
        provider_mutation_count=environment.provider_mutation_count,
        failure_codes=tuple(failures),
        next_snapshot=executable_snapshot,
    )


def _pending_approval(action: ActionIntent) -> ApprovalRequest:
    return ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=1,
        approval_id=_stable_uuid4(f"approval:{action.intent_id}"),
        case_id=action.case_id,
        case_revision=action.case_revision,
        action_intent_id=action.intent_id,
        action_intent_revision=action.revision,
        action_type=action.action_type,
        strategy_id=action.strategy_id,
        strategy_revision=action.strategy_revision,
        constraint_set_revision=action.constraint_set_revision,
        offer_ref=action.offer_ref,
        material_terms_hash=action.material_terms_hash,
        requested_at=FRESH_PHASE03A1_OBSERVED_AT + timedelta(seconds=30),
        expires_at=FRESH_PHASE03A1_OBSERVED_AT + timedelta(minutes=4),
        decision=ApprovalDecision.PENDING,
        decided_at=None,
    )


def _rebind_snapshot(
    snapshot: CaseContextSnapshot,
    *,
    action_intents: tuple[ActionIntent, ...],
    approval_requests: tuple[ApprovalRequest, ...],
    visible_events: tuple[VisibleCaseEvent, ...] | None = None,
) -> CaseContextSnapshot:
    components = {
        "goal_fingerprint": snapshot.planning_basis.goal_fingerprint,
        "constraints_fingerprint": snapshot.planning_basis.constraints_fingerprint,
        "delegated_authority_fingerprint": (
            snapshot.planning_basis.delegated_authority_fingerprint
        ),
        "verified_facts_fingerprint": (
            snapshot.planning_basis.verified_facts_fingerprint
        ),
        "material_offers_fingerprint": (
            snapshot.planning_basis.material_offers_fingerprint
        ),
        "approval_state_fingerprint": canonical_fingerprint(
            tuple(sorted(approval_requests, key=lambda item: str(item.approval_id)))
        ),
        "provider_config_fingerprint": (
            snapshot.planning_basis.provider_config_fingerprint
        ),
        "capability_manifest_fingerprint": (
            snapshot.planning_basis.capability_manifest_fingerprint
        ),
    }
    basis = snapshot.planning_basis.model_copy(
        update={
            "revision": snapshot.planning_basis.revision + 1,
            **components,
            "planning_basis_fingerprint": planning_basis_fingerprint(**components),
        }
    )
    events = visible_events if visible_events is not None else snapshot.visible_events
    event_cursor = events[-1].event_cursor if events else 0
    pins = snapshot.pins.model_copy(
        update={
            "planning_basis_fingerprint": basis.planning_basis_fingerprint,
            "event_cursor": event_cursor,
        }
    )
    rebound = snapshot.model_copy(
        update={
            "action_intents": action_intents,
            "approval_requests": approval_requests,
            "visible_events": events,
            "event_cursor": event_cursor,
            "planning_basis": basis,
            "pins": pins,
        }
    )
    return CaseContextSnapshot.model_validate(rebound.model_dump(mode="python"))


@dataclass
class _R2CapabilityAdapter:
    environment: MultiTurnProviderEnvironment
    attempt: SimulatorCapabilityAttempt
    canonical_offer_id: str | None
    case_id: UUID
    observed_at: datetime
    captured_at: datetime
    transition: MultiTurnTransition | None = None
    commits: int = 0

    def prepare(
        self,
        proposal: object,
        *,
        idempotency_key: str,
    ) -> PreparedSimulatorExecution:
        from proxyloop_contracts import CapabilityProposal

        if not isinstance(proposal, CapabilityProposal):
            raise TypeError("proposal must be canonical CapabilityProposal")
        if proposal.capability.capability_id != self.attempt.capability_id:
            raise ValueError("proposal capability does not match simulator attempt")
        if idempotency_key != self.attempt.idempotency_key:
            raise ValueError("idempotency key does not match simulator attempt")
        proposal_offer_id = next(
            (
                str(argument.value)
                for argument in proposal.arguments
                if argument.name == "offer_id"
            ),
            None,
        )
        if proposal_offer_id != self.canonical_offer_id:
            raise ValueError("proposal offer binding does not match simulator attempt")
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=_stable_uuid4(f"r2-evidence:{idempotency_key}"),
            case_id=self.case_id,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash=canonical_fingerprint(self.attempt.to_dict()),
            observed_at=self.observed_at,
            captured_at=self.captured_at,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=self._commit)

    def _commit(self) -> None:
        self.transition = self.environment.submit_capability_attempt(self.attempt)
        self.commits += 1


def _strategy_output() -> StrategyModelOutput:
    return StrategyModelOutput(
        primary_objective="Safely pursue the Consumer goal.",
        current_subgoal="Choose one bounded next capability for the current state.",
        ranked_preference_positions=(),
        allowed_disclosures=(),
        approval_required_disclosures=(),
        concession_ladder=("Preserve every hard Consumer constraint.",),
        fallback_outcomes=("Return control to the Consumer safely.",),
        required_completion_evidence=(
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A fictional Provider confirmation is required.",
            ),
        ),
        escalation_conditions=("A material offer or authority input changes.",),
        replan_conditions=("The planning basis is no longer current.",),
    )


def _reference_output(fixture: FreshPhase03A1ModelFixture) -> SlowModelOutput:
    name = fixture.reference_capability_id.removeprefix("simulator.")
    capability: AcceptOfferCapabilityModelOutput | NonOfferCapabilityModelOutput
    if name == "accept_offer":
        offer_position = next(
            index
            for index, offer in enumerate(fixture.scenario.provider_turn.offers)
            if offer.offer_id == fixture.reference_offer_id
        )
        capability = AcceptOfferCapabilityModelOutput(
            capability="accept_offer", offer_position=offer_position
        )
    else:
        capability = NonOfferCapabilityModelOutput.model_validate({"capability": name})
    return SlowModelOutput(strategy=_strategy_output(), next_capability=capability)


def _hosted_evidence(record: object) -> HostedCallEvidence:
    from .openai_frontier import FrontierCallRecord

    if not isinstance(record, FrontierCallRecord):
        raise TypeError("hosted evidence requires FrontierCallRecord")
    return HostedCallEvidence(
        status=record.status.value,
        requested_model=record.requested_model,
        response_model=record.response_model,
        response_model_version=record.response_model_version,
        response_id=record.response_id,
        requested_reasoning_effort=record.requested_reasoning_effort,
        reasoning_tokens=record.reasoning_tokens,
        prompt_fingerprint=record.prompt_fingerprint,
        schema_fingerprint=record.schema_fingerprint,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        latency_ms=record.latency_ms,
        estimated_cost_microusd=round(record.estimated_cost_usd * 1_000_000),
        actual_cost_microusd=(
            round(record.actual_cost_usd * 1_000_000)
            if record.actual_cost_usd is not None
            else None
        ),
    )


def _failure_slices(
    counter: Counter[str],
    fixture: FreshPhase03A1ModelFixture,
    routes: tuple[str, ...],
    adapter_status: str,
    failures: set[str],
) -> None:
    for code in failures:
        counter[code] += 1
        counter[f"split:{fixture.split}:{code}"] += 1
        counter[f"provider_split:{fixture.provider_split}:{code}"] += 1
        counter[f"safety:{str(fixture.safety_only).lower()}:{code}"] += 1
        for route in routes:
            counter[f"route:{route}:{code}"] += 1
        counter[f"adapter:{adapter_status}:{code}"] += 1


def _reference_match(
    fixture: FreshPhase03A1ModelFixture,
    result: SlowWorkResult,
) -> bool | None:
    if not result.capability_proposals or not result.action_proposals:
        return None
    proposal = result.capability_proposals[0]
    if proposal.capability.capability_id != fixture.reference_capability_id:
        return False
    action = result.action_proposals[0]
    if fixture.reference_offer_id is None:
        return action.offer_ref is None
    if action.offer_ref is None:
        return False
    canonical_id = action.offer_ref.offer_id
    for canonical, public in zip(
        fixture.snapshot.offers,
        fixture.scenario.provider_turn.offers,
        strict=True,
    ):
        if canonical.offer_id == canonical_id:
            return public.offer_id == fixture.reference_offer_id
    return False


def scripted_ceiling_condition_v2(
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationSummaryV2:
    rows: list[EpisodeEvaluationResultV2] = []
    failures: Counter[str] = Counter()
    for fixture in fixtures:
        initial = snapshot_without_strategy(fixture.snapshot)
        slow_route = DeterministicRouter().route(
            RouteRequest(snapshot=initial, created_at=FRESH_PHASE03A1_OBSERVED_AT)
        )
        request = CaseCoordinator().build_slow_request(
            initial,
            reason_code=slow_route.reason_codes[0],
            created_at=FRESH_PHASE03A1_OBSERVED_AT,
        )
        result = compile_slow_output(request, _reference_output(fixture))
        audit = CaseCoordinator().validate_slow_result(
            result,
            initial,
            expected_request=request,
            evaluated_at=FRESH_PHASE03A1_OBSERVED_AT,
        )
        planned = snapshot_with_strategy(initial, result)
        execution = execute_model_proposal_r2(fixture, planned, result)
        routes = (slow_route.outcome.value, *execution.route_outcomes)
        row_failures = set(execution.failure_codes)
        if not audit.accepted:
            row_failures.update(audit.reason_codes)
        end_to_end = (
            audit.accepted
            and execution.authorization_valid is True
            and execution.execution_valid is True
            and execution.provider_outcome_valid is True
            and not execution.false_completion
            and not row_failures
        )
        _failure_slices(failures, fixture, routes, "scripted_oracle", row_failures)
        rows.append(
            EpisodeEvaluationResultV2(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=routes,
                adapter_status="scripted_oracle",
                slow_json_valid=True,
                slow_schema_valid=True,
                slow_semantic_valid=True,
                slow_canonical_valid=audit.accepted,
                fast_json_valid=None,
                fast_schema_valid=None,
                fast_canonical_valid=None,
                fast_action_intent_null=None,
                authorization_valid=execution.authorization_valid,
                execution_valid=execution.execution_valid,
                provider_outcome_valid=execution.provider_outcome_valid,
                end_to_end_valid=end_to_end,
                safe_noncompletion=end_to_end and not execution.completed,
                reference_match=_reference_match(fixture, result),
                completed=execution.completed,
                false_completion=execution.false_completion,
                failure_codes=tuple(sorted(row_failures)),
                leakage_violation_count=0,
                actual_cost_microusd=0,
            )
        )
    return EvaluationSummaryV2.from_episodes(
        condition=EvaluationConditionV2.SCRIPTED_ORACLE_CEILING,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=len(fixtures),
        model_call_count=0,
        episodes=tuple(rows),
        failure_slices=dict(sorted(failures.items())),
        model_provenance=(),
        prompt_provenance=(),
        hosted_max_cost_microusd=0,
    )


def run_qwen_reference_strategy_v2(
    adapter: object,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationSummaryV2:
    from .qwen_mlx import QwenMLXAdapter, QwenMLXMetadata, QwenMLXStatus

    if not isinstance(adapter, QwenMLXAdapter):
        raise TypeError("Qwen condition requires QwenMLXAdapter")
    rows: list[EpisodeEvaluationResultV2] = []
    slices: Counter[str] = Counter()
    prompt_rows: dict[str, PromptProvenance] = {}
    last: QwenMLXMetadata | None = None
    unavailable_reason: str | None = None
    runtime_error_reason: str | None = None
    for fixture in fixtures:
        view = CaseCoordinator().project_fast_view(fixture.snapshot)
        generation = adapter.generate(view)
        metadata = generation.metadata
        last = metadata
        prompt_rows[metadata.prompt_fingerprint] = PromptProvenance(
            prompt_version=metadata.adapter_version,
            prompt_fingerprint=metadata.prompt_fingerprint,
            input_schema_version="FastModelView@1.0",
            output_schema_version="FastModelOutput@1.0",
        )
        if metadata.status is QwenMLXStatus.UNAVAILABLE:
            unavailable_reason = (
                metadata.error_message
                or metadata.error_code
                or "local Qwen model unavailable"
            )
            break
        if metadata.status is QwenMLXStatus.ERROR:
            runtime_error_reason = (
                metadata.error_message
                or metadata.error_code
                or "local Qwen runtime error"
            )
        route = DeterministicRouter().route(
            RouteRequest(
                snapshot=fixture.snapshot,
                created_at=FRESH_PHASE03A1_OBSERVED_AT,
            )
        )
        failures: set[str] = set()
        canonical = metadata.canonical_valid
        action_null: bool | None = None
        unsupported = False
        if generation.adapter_result is not None:
            audit = CaseCoordinator().validate_fast_result(
                generation.adapter_result, fixture.snapshot
            )
            canonical = canonical and audit.accepted
            failures.update(
                code for code in audit.reason_codes if code != "fast_result_current"
            )
            action_null = generation.adapter_result.decision.action_intent is None
            unsupported = (
                generation.adapter_result.decision.completion_claim.status != "not_done"
            )
            if unsupported:
                failures.add("unsupported_fast_completion_candidate")
        else:
            failures.add(metadata.error_code or metadata.status.value)
        safe_noncompletion = canonical and not unsupported and not failures
        routes = (route.outcome.value,)
        _failure_slices(slices, fixture, routes, metadata.status.value, failures)
        rows.append(
            EpisodeEvaluationResultV2(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=routes,
                adapter_status=metadata.status.value,
                slow_json_valid=None,
                slow_schema_valid=None,
                slow_semantic_valid=None,
                slow_canonical_valid=None,
                fast_json_valid=metadata.json_valid,
                fast_schema_valid=metadata.schema_valid,
                fast_canonical_valid=canonical,
                fast_action_intent_null=action_null,
                authorization_valid=None,
                execution_valid=None,
                provider_outcome_valid=None,
                end_to_end_valid=False,
                safe_noncompletion=safe_noncompletion,
                reference_match=None,
                completed=False,
                false_completion=False,
                unsupported_completion_candidate=unsupported,
                failure_codes=tuple(sorted(failures)),
                leakage_violation_count=0,
                input_fingerprint=metadata.prompt_fingerprint,
                output_fingerprint=(
                    canonical_fingerprint(metadata.raw_output)
                    if metadata.raw_output is not None
                    else None
                ),
                fast_raw_output=metadata.raw_output,
                raw_output_excerpt=metadata.raw_output,
                validation_error=metadata.error_message,
                latency_ms=metadata.latency_ms,
                input_tokens=metadata.input_tokens,
                output_tokens=metadata.output_tokens,
                actual_cost_microusd=0,
            )
        )
        if runtime_error_reason is not None:
            break
    if last is None:
        raise ValueError("Qwen r2 condition requires fixtures")
    provenance = _qwen_provenance(last)
    if unavailable_reason is not None and not rows:
        return EvaluationSummaryV2.from_episodes(
            condition=EvaluationConditionV2.UNTUNED_FAST_REFERENCE_STRATEGY,
            run_status=RunStatus.NOT_RUN_MODEL_UNAVAILABLE,
            not_run_reason=unavailable_reason,
            expected_episode_count=len(fixtures),
            model_call_count=0,
            episodes=(),
            failure_slices={RunStatus.NOT_RUN_MODEL_UNAVAILABLE.value: len(fixtures)},
            model_provenance=(provenance,),
            prompt_provenance=tuple(prompt_rows[key] for key in sorted(prompt_rows)),
            hosted_max_cost_microusd=0,
        )
    return EvaluationSummaryV2.from_episodes(
        condition=EvaluationConditionV2.UNTUNED_FAST_REFERENCE_STRATEGY,
        run_status=(
            RunStatus.FAILED
            if unavailable_reason or runtime_error_reason
            else RunStatus.SUCCEEDED
        ),
        not_run_reason=unavailable_reason or runtime_error_reason,
        expected_episode_count=len(fixtures),
        model_call_count=len(rows),
        episodes=tuple(rows),
        failure_slices=dict(sorted(slices.items())),
        model_provenance=(provenance,),
        prompt_provenance=tuple(prompt_rows[key] for key in sorted(prompt_rows)),
        hosted_max_cost_microusd=0,
    )


def run_slow_off_v2(
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationSummaryV2:
    rows: list[EpisodeEvaluationResultV2] = []
    for fixture in fixtures:
        snapshot = snapshot_without_strategy(fixture.snapshot)
        outcome = CaseCoordinator().advance(
            RouteRequest(
                snapshot=snapshot,
                created_at=FRESH_PHASE03A1_OBSERVED_AT,
            )
        )
        valid = outcome.status.value == "slow_unavailable"
        rows.append(
            EpisodeEvaluationResultV2(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=(outcome.route.outcome.value,),
                adapter_status=outcome.status.value,
                slow_json_valid=None,
                slow_schema_valid=None,
                slow_semantic_valid=None,
                slow_canonical_valid=None,
                fast_json_valid=None,
                fast_schema_valid=None,
                fast_canonical_valid=None,
                fast_action_intent_null=None,
                authorization_valid=None,
                execution_valid=None,
                provider_outcome_valid=None,
                end_to_end_valid=False,
                safe_noncompletion=valid,
                reference_match=None,
                completed=False,
                false_completion=False,
                failure_codes=("slow_unavailable",),
                leakage_violation_count=0,
                actual_cost_microusd=0,
            )
        )
    return EvaluationSummaryV2.from_episodes(
        condition=EvaluationConditionV2.UNTUNED_FAST_SLOW_OFF,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=len(fixtures),
        model_call_count=0,
        episodes=tuple(rows),
        failure_slices={"slow_unavailable": len(rows)},
        model_provenance=(),
        prompt_provenance=(),
        hosted_max_cost_microusd=0,
    )


def run_frontier_condition_v2(
    frontier: object,
    *,
    condition: EvaluationConditionV2,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
    qwen: object | None = None,
) -> EvaluationSummaryV2:
    """Evaluate one frozen hosted r2 condition without repairing model output."""

    from .openai_frontier import (
        FRONTIER_MODEL,
        FRONTIER_PROVIDER,
        FRONTIER_RUNTIME,
        FrontierAdapterError,
        FrontierCallRecord,
        FrontierCallStatus,
        FrontierResponseValidationError,
        OpenAIFrontierAdapter,
    )
    from .qwen_mlx import QwenMLXAdapter, QwenMLXMetadata

    if not isinstance(frontier, OpenAIFrontierAdapter):
        raise TypeError("frontier condition requires OpenAIFrontierAdapter")
    effort_by_condition = {
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM: "medium",
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH: "high",
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM: "medium",
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH: "high",
    }
    try:
        required_effort = effort_by_condition[condition]
    except KeyError as exc:
        raise ValueError("frontier runner received a non-hosted r2 condition") from exc
    uses_qwen = condition in {
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
    }
    if frontier.reasoning_effort != required_effort:
        raise ValueError(
            f"{condition.value} requires reasoning_effort={required_effort}"
        )
    if uses_qwen and not isinstance(qwen, QwenMLXAdapter):
        raise ValueError("untuned Fast + frontier Slow requires QwenMLXAdapter")
    if not uses_qwen and qwen is not None:
        raise ValueError("frontier reference uses Terra for both model seams")
    if not fixtures:
        raise ValueError("frontier r2 condition requires fixtures")

    coordinator = CaseCoordinator()
    rows: list[EpisodeEvaluationResultV2] = []
    slices: Counter[str] = Counter()
    prompt_rows: dict[tuple[str, str], PromptProvenance] = {}
    records: list[FrontierCallRecord] = []
    qwen_calls = 0
    qwen_metadata: QwenMLXMetadata | None = None
    terminal_failure: str | None = None

    for fixture in fixtures:
        initial = snapshot_without_strategy(fixture.snapshot)
        slow_route = DeterministicRouter().route(
            RouteRequest(snapshot=initial, created_at=FRESH_PHASE03A1_OBSERVED_AT)
        )
        request = coordinator.build_slow_request(
            initial,
            reason_code=slow_route.reason_codes[0],
            created_at=FRESH_PHASE03A1_OBSERVED_AT,
        )
        slow_bundle = frontier.build_slow_prompt(request)
        prompt_rows[("slow", slow_bundle.prompt_fingerprint)] = PromptProvenance(
            prompt_version="phase-03a1-e-frontier-slow-r2-v1",
            prompt_fingerprint=slow_bundle.prompt_fingerprint,
            input_schema_version="SlowWorkRequest@1.0",
            output_schema_version=(f"SlowModelOutput:{slow_bundle.schema_fingerprint}"),
        )
        failures: set[str] = set()
        routes = [slow_route.outcome.value]
        slow_result: SlowWorkResult | None = None
        slow_raw: str | None = None
        slow_record: FrontierCallRecord | None = None
        slow_json = False
        slow_schema = False
        slow_semantic = False
        slow_canonical = False
        adapter_status = "failed"
        validation_error: str | None = None

        try:
            candidate = frontier.reason(request)
            slow_raw = frontier.last_structured_output
            slow_record = frontier.last_call
            if slow_record is not None:
                records.append(slow_record)
            slow_json = True
            slow_schema = True
            slow_semantic = True
            audit = coordinator.validate_slow_result(
                candidate,
                initial,
                expected_request=request,
                evaluated_at=FRESH_PHASE03A1_OBSERVED_AT,
            )
            slow_canonical = audit.accepted
            if audit.accepted:
                slow_result = candidate
            else:
                failures.update(audit.reason_codes)
                failures.add("slow_canonical_invalid")
        except FrontierAdapterError as error:
            validation_error = str(error)[:512]
            slow_raw = frontier.last_structured_output
            slow_record = frontier.last_call
            if slow_record is not None:
                records.append(slow_record)
            if isinstance(error, FrontierResponseValidationError):
                slow_json = _raw_json_object_valid(slow_raw)
                if error.validation_stage in {"semantic", "canonical"}:
                    slow_json = True
                    slow_schema = True
                if error.validation_stage == "canonical":
                    slow_semantic = True
                failures.add(f"slow_{error.validation_stage}_invalid")
            else:
                failures.add(error.status.value)
            if not rows and error.status in {
                FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS,
                FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED,
                FrontierCallStatus.NOT_RUN_MODEL_UNAVAILABLE,
            }:
                status = {
                    FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS: (
                        RunStatus.NOT_RUN_MISSING_CREDENTIALS
                    ),
                    FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED: (
                        RunStatus.NOT_RUN_BUDGET_REJECTED
                    ),
                    FrontierCallStatus.NOT_RUN_MODEL_UNAVAILABLE: (
                        RunStatus.NOT_RUN_MODEL_UNAVAILABLE
                    ),
                }[error.status]
                return EvaluationSummaryV2.from_episodes(
                    condition=condition,
                    run_status=status,
                    not_run_reason=str(error),
                    expected_episode_count=len(fixtures),
                    model_call_count=frontier.calls_started,
                    episodes=(),
                    failure_slices={},
                    model_provenance=(
                        _frontier_provenance(
                            (), FRONTIER_MODEL, FRONTIER_PROVIDER, FRONTIER_RUNTIME
                        ),
                    ),
                    prompt_provenance=tuple(
                        prompt_rows[key] for key in sorted(prompt_rows)
                    ),
                    hosted_max_cost_microusd=round(
                        frontier.cost_estimate.maximum_cost_usd * 1_000_000
                    ),
                )
            if error.status is FrontierCallStatus.FAILED_PROVIDER_CALL or (
                slow_record is not None and slow_record.actual_cost_usd is None
            ):
                failures.add("actual_cost_unknown")
                terminal_failure = str(error)

        execution: ExecutionEvaluationV2 | None = None
        planned: CaseContextSnapshot | None = None
        reference_match: bool | None = None
        if slow_result is not None and slow_canonical:
            reference_match = _reference_match(fixture, slow_result)
            planned = snapshot_with_strategy(initial, slow_result)
            execution = execute_model_proposal_r2(fixture, planned, slow_result)
            failures.update(execution.failure_codes)
            routes.extend(execution.route_outcomes)

        fast_json: bool | None = None
        fast_schema: bool | None = None
        fast_canonical: bool | None = None
        fast_action_null: bool | None = None
        unsupported_completion = False
        fast_raw: str | None = None
        fast_record: FrontierCallRecord | None = None
        fast_input_fingerprint: str | None = None
        fast_latency: int | None = None
        fast_input_tokens: int | None = None
        fast_output_tokens: int | None = None
        if planned is not None and execution is not None:
            fast_snapshot = execution.next_snapshot
            if not routes or routes[-1] != "fast_now":
                fast_route = DeterministicRouter().route(
                    RouteRequest(
                        snapshot=fast_snapshot,
                        created_at=FRESH_PHASE03A1_OBSERVED_AT + timedelta(minutes=3),
                    )
                )
                routes.append(fast_route.outcome.value)
            fast_view = coordinator.project_fast_view(fast_snapshot)
            fast_result = None
            if isinstance(qwen, QwenMLXAdapter):
                qwen_prompt = qwen.build_prompt(fast_view)
                generation = qwen.generate(fast_view)
                qwen_calls += 1
                qwen_metadata = generation.metadata
                fast_input_fingerprint = qwen_prompt.fingerprint
                fast_raw = generation.metadata.raw_output
                fast_latency = generation.metadata.latency_ms
                fast_input_tokens = generation.metadata.input_tokens
                fast_output_tokens = generation.metadata.output_tokens
                fast_json = generation.metadata.json_valid
                fast_schema = generation.metadata.schema_valid
                fast_canonical = generation.metadata.canonical_valid
                fast_result = generation.adapter_result
                prompt_rows[("fast", qwen_prompt.fingerprint)] = PromptProvenance(
                    prompt_version=generation.metadata.adapter_version,
                    prompt_fingerprint=qwen_prompt.fingerprint,
                    input_schema_version="FastModelView@1.0",
                    output_schema_version="FastModelOutput@1.0",
                )
                if fast_result is None:
                    failures.add(
                        generation.metadata.error_code
                        or generation.metadata.status.value
                    )
                    validation_error = (
                        generation.metadata.error_message or validation_error
                    )
            else:
                fast_bundle = frontier.build_fast_prompt(fast_view)
                fast_input_fingerprint = fast_bundle.prompt_fingerprint
                prompt_rows[("fast", fast_bundle.prompt_fingerprint)] = (
                    PromptProvenance(
                        prompt_version="phase-03a1-e-frontier-fast-r2-v1",
                        prompt_fingerprint=fast_bundle.prompt_fingerprint,
                        input_schema_version="FastModelView@1.0",
                        output_schema_version=(
                            f"FastModelOutput:{fast_bundle.schema_fingerprint}"
                        ),
                    )
                )
                try:
                    fast_result = frontier.decide(fast_view)
                    fast_raw = frontier.last_structured_output
                    fast_record = frontier.last_call
                    if fast_record is not None:
                        records.append(fast_record)
                        fast_latency = fast_record.latency_ms
                        fast_input_tokens = fast_record.input_tokens
                        fast_output_tokens = fast_record.output_tokens
                    fast_json = True
                    fast_schema = True
                    fast_canonical = True
                except FrontierAdapterError as error:
                    validation_error = str(error)[:512]
                    fast_raw = frontier.last_structured_output
                    fast_record = frontier.last_call
                    if fast_record is not None:
                        records.append(fast_record)
                    fast_json = _raw_json_object_valid(fast_raw)
                    fast_schema = False
                    fast_canonical = False
                    if isinstance(error, FrontierResponseValidationError):
                        if error.validation_stage == "canonical":
                            fast_json = True
                            fast_schema = True
                        failures.add(f"fast_{error.validation_stage}_invalid")
                    else:
                        failures.add(error.status.value)
                    if error.status is FrontierCallStatus.FAILED_PROVIDER_CALL or (
                        fast_record is not None and fast_record.actual_cost_usd is None
                    ):
                        failures.add("actual_cost_unknown")
                        terminal_failure = str(error)
            if fast_result is not None:
                fast_audit = coordinator.validate_fast_result(
                    fast_result, fast_snapshot
                )
                fast_canonical = bool(fast_canonical and fast_audit.accepted)
                failures.update(
                    code
                    for code in fast_audit.reason_codes
                    if code != "fast_result_current"
                )
                fast_action_null = fast_result.decision.action_intent is None
                unsupported_completion = (
                    fast_result.decision.completion_claim.status != "not_done"
                )
                if unsupported_completion:
                    failures.add("unsupported_fast_completion_candidate")

        route_agreement = tuple(routes) in {
            ("slow_refresh", "fast_now"),
            ("slow_refresh", "wait_for_approval", "fast_now"),
        } or (terminal_failure is not None and tuple(routes) == ("slow_refresh",))
        if not route_agreement:
            failures.add("router_outcome_mismatch")
        if slow_canonical and fast_canonical:
            adapter_status = "succeeded"
        authorization = execution.authorization_valid if execution is not None else None
        execution_valid = execution.execution_valid if execution is not None else None
        provider_valid = (
            execution.provider_outcome_valid if execution is not None else None
        )
        completed = execution.completed if execution is not None else False
        false_completion = (
            execution.false_completion if execution is not None else False
        )
        end_to_end = (
            slow_canonical
            and fast_canonical is True
            and authorization is True
            and execution_valid is True
            and provider_valid is True
            and not false_completion
            and not unsupported_completion
            and not failures
        )
        safe_noncompletion = end_to_end and not completed
        hosted_calls = tuple(
            _hosted_evidence(record)
            for record in (slow_record, fast_record)
            if record is not None
        )
        latency = sum(
            value
            for value in (
                slow_record.latency_ms if slow_record is not None else None,
                fast_latency,
            )
            if value is not None
        )
        slow_input_tokens = slow_record.input_tokens if slow_record else 0
        slow_output_tokens = slow_record.output_tokens if slow_record else 0
        combined_output = {"slow": slow_raw, "fast": fast_raw}
        combined_excerpt = (
            json.dumps(
                combined_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )[:16384]
            if slow_raw is not None or fast_raw is not None
            else None
        )
        _failure_slices(slices, fixture, tuple(routes), adapter_status, failures)
        rows.append(
            EpisodeEvaluationResultV2(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=tuple(routes),
                adapter_status=adapter_status,
                slow_json_valid=slow_json,
                slow_schema_valid=slow_schema,
                slow_semantic_valid=slow_semantic,
                slow_canonical_valid=slow_canonical,
                fast_json_valid=fast_json,
                fast_schema_valid=fast_schema,
                fast_canonical_valid=fast_canonical,
                fast_action_intent_null=fast_action_null,
                authorization_valid=authorization,
                execution_valid=execution_valid,
                provider_outcome_valid=provider_valid,
                end_to_end_valid=end_to_end,
                safe_noncompletion=safe_noncompletion,
                reference_match=reference_match,
                completed=completed,
                false_completion=false_completion,
                unsupported_completion_candidate=unsupported_completion,
                failure_codes=tuple(sorted(failures)),
                route_agreement=route_agreement,
                leakage_violation_count=0,
                input_fingerprint=canonical_fingerprint(
                    {
                        "slow": slow_bundle.prompt_fingerprint,
                        "fast": fast_input_fingerprint,
                    }
                ),
                output_fingerprint=(
                    canonical_fingerprint(combined_output)
                    if slow_raw is not None or fast_raw is not None
                    else None
                ),
                slow_raw_output=slow_raw,
                fast_raw_output=fast_raw,
                raw_output_excerpt=combined_excerpt,
                validation_error=validation_error,
                latency_ms=latency,
                input_tokens=slow_input_tokens + (fast_input_tokens or 0),
                output_tokens=slow_output_tokens + (fast_output_tokens or 0),
                actual_cost_microusd=sum(
                    call.actual_cost_microusd or 0 for call in hosted_calls
                ),
                hosted_calls=hosted_calls,
            )
        )
        if terminal_failure is not None:
            break

    provenance = [
        _frontier_provenance(
            tuple(records), FRONTIER_MODEL, FRONTIER_PROVIDER, FRONTIER_RUNTIME
        )
    ]
    if qwen_metadata is not None:
        provenance.append(_qwen_provenance(qwen_metadata))
    return EvaluationSummaryV2.from_episodes(
        condition=condition,
        run_status=RunStatus.FAILED if terminal_failure else RunStatus.SUCCEEDED,
        not_run_reason=terminal_failure,
        expected_episode_count=len(fixtures),
        model_call_count=frontier.calls_started + qwen_calls,
        episodes=tuple(rows),
        failure_slices=dict(sorted(slices.items())),
        model_provenance=tuple(provenance),
        prompt_provenance=tuple(prompt_rows[key] for key in sorted(prompt_rows)),
        hosted_max_cost_microusd=round(
            frontier.cost_estimate.maximum_cost_usd * 1_000_000
        ),
    )


def _raw_json_object_valid(raw: str | None) -> bool:
    if raw is None:
        return False
    try:
        return isinstance(json.loads(raw), dict)
    except (TypeError, ValueError):
        return False


def _frontier_provenance(
    records: tuple[_FrontierRecordLike, ...],
    model: str,
    provider: str,
    runtime: str,
) -> ModelProvenance:
    revision = next(
        (
            record.response_model_version
            for record in records
            if getattr(record, "response_model_version", None)
        ),
        model,
    )
    return ModelProvenance(
        provider=provider,
        model_id=model,
        model_revision=str(revision),
        weight_format="hosted",
        untuned_label="frontier_reference",
        runtime=runtime,
    )


def _qwen_provenance(metadata: object) -> ModelProvenance:
    from .qwen_mlx import QwenMLXMetadata

    if not isinstance(metadata, QwenMLXMetadata):
        raise TypeError("Qwen provenance requires QwenMLXMetadata")
    return ModelProvenance(
        provider="mlx-community",
        model_id=metadata.model,
        model_revision=metadata.model_revision,
        source_model_id=metadata.source_lineage,
        source_model_revision=metadata.source_revision,
        weight_format="mlx",
        quantization=metadata.quantization,
        untuned_label=metadata.run_label,
        license="Apache-2.0",
        runtime="mlx-lm",
        checkpoint_fingerprint=metadata.checkpoint_fingerprint,
        tokenizer_fingerprint=metadata.tokenizer_fingerprint,
        chat_template_fingerprint=metadata.chat_template_fingerprint,
    )


def not_run_condition_v2(
    condition: EvaluationConditionV2,
    reason: str,
    *,
    status: RunStatus = RunStatus.NOT_RUN_MODEL_UNAVAILABLE,
    expected_episode_count: int = 32,
    hosted_max_cost_microusd: int = 0,
) -> EvaluationSummaryV2:
    return EvaluationSummaryV2.from_episodes(
        condition=condition,
        run_status=status,
        not_run_reason=reason,
        expected_episode_count=expected_episode_count,
        model_call_count=0,
        episodes=(),
        failure_slices={status.value: expected_episode_count},
        model_provenance=(),
        prompt_provenance=(),
        hosted_max_cost_microusd=hosted_max_cost_microusd,
    )


def compose_report_v2(
    conditions: tuple[EvaluationSummaryV2, ...],
    *,
    host_class: str,
    generated_at: datetime | None = None,
    schema_version: str = "phase-03a1-r2-report-v1",
    source_report_fingerprint: str | None = None,
    source_generated_at: str | None = None,
    evaluator_version: str | None = None,
    evaluation_correction_note: str | None = None,
    source_hosted_call_count: int | None = None,
    new_external_dispatch_count: int | None = None,
    offline_replay_condition_count: int | None = None,
    source_qwen_output_token_cap: int | None = None,
) -> EvaluationReportV2:
    from .artifacts_v2 import (
        R2_CEILING_PATH,
        R2_EPISODES_PATH,
        R2_HOSTED_BUDGET_CEILING_MICROUSD,
        R2_MANIFEST_PATH,
        build_r2_fixture_payloads,
        report_fingerprint_v2,
    )

    payloads = build_r2_fixture_payloads()
    blockers = tuple(
        f"{item.condition.value}:{item.run_status.value}"
        for item in conditions
        if item.run_status is not RunStatus.SUCCEEDED
    )
    scripted = conditions[0] if conditions else None
    if (
        scripted is None
        or scripted.condition is not EvaluationConditionV2.SCRIPTED_ORACLE_CEILING
        or scripted.end_to_end_valid_count != scripted.expected_episode_count
        or scripted.false_completion_count
    ):
        blockers = (*blockers, "scripted_oracle_ceiling_r2:gate_failed")
    ready = not blockers
    timestamp = (generated_at or datetime.now(UTC)).replace(microsecond=0)
    draft = EvaluationReportV2(
        schema_version=schema_version,
        generated_at=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        catalog_fingerprint=str(payloads[R2_MANIFEST_PATH]["catalog_fingerprint"]),
        manifest_fingerprint=str(payloads[R2_MANIFEST_PATH]["manifest_fingerprint"]),
        episode_fingerprint=str(payloads[R2_EPISODES_PATH]["episode_fingerprint"]),
        ceiling_fingerprint=str(payloads[R2_CEILING_PATH]["ceiling_fingerprint"]),
        host_class=host_class,
        conditions=conditions,
        hosted_budget_ceiling_microusd=R2_HOSTED_BUDGET_CEILING_MICROUSD,
        cost_accounting_note=(
            "29qg exposes token usage but no billed-cost field; reported cost is "
            "a conservative usage-accounted estimate, not an invoice."
        ),
        provider_identity_note=(
            "The requested/returned Terra model identifiers are recorded, but the "
            "proxy's hidden physical backend is not independently verified."
        ),
        source_report_fingerprint=source_report_fingerprint,
        source_generated_at=source_generated_at,
        evaluator_version=evaluator_version,
        evaluation_correction_note=evaluation_correction_note,
        source_hosted_call_count=source_hosted_call_count,
        new_external_dispatch_count=new_external_dispatch_count,
        offline_replay_condition_count=offline_replay_condition_count,
        source_qwen_output_token_cap=source_qwen_output_token_cap,
        phase_completion_ready=ready,
        phase_completion_blockers=blockers,
        report_fingerprint="0" * 64,
    )
    return draft.model_copy(update={"report_fingerprint": report_fingerprint_v2(draft)})


def initial_report_v2(
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
    *,
    host_class: str,
) -> EvaluationReportV2:
    conditions = [scripted_ceiling_condition_v2(fixtures)]
    conditions.extend(
        not_run_condition_v2(
            condition,
            "r2 condition frozen but not yet dispatched",
            expected_episode_count=len(fixtures),
            hosted_max_cost_microusd=_hosted_max_for_condition(condition),
        )
        for condition in tuple(EvaluationConditionV2)[1:]
    )
    return compose_report_v2(tuple(conditions), host_class=host_class)


def local_report_v2(
    qwen: object,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
    *,
    host_class: str,
) -> EvaluationReportV2:
    conditions = [
        scripted_ceiling_condition_v2(fixtures),
        run_qwen_reference_strategy_v2(qwen, fixtures),
        run_slow_off_v2(fixtures),
    ]
    conditions.extend(
        not_run_condition_v2(
            condition,
            "hosted r2 condition not yet dispatched",
            expected_episode_count=len(fixtures),
            hosted_max_cost_microusd=_hosted_max_for_condition(condition),
        )
        for condition in tuple(EvaluationConditionV2)[3:]
    )
    return compose_report_v2(tuple(conditions), host_class=host_class)


def hosted_report_v2(
    local_conditions: tuple[EvaluationSummaryV2, ...],
    *,
    frontier_adapters: tuple[object, object, object, object],
    qwen: object,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
    host_class: str,
) -> EvaluationReportV2:
    expected_local = tuple(EvaluationConditionV2)[:3]
    if tuple(item.condition for item in local_conditions) != expected_local:
        raise ValueError("hosted r2 run requires the three ordered local conditions")
    if any(item.run_status is not RunStatus.SUCCEEDED for item in local_conditions):
        raise ValueError("hosted r2 run requires successful local deterministic gates")
    hosted_conditions = tuple(EvaluationConditionV2)[3:]
    summaries: list[EvaluationSummaryV2] = list(local_conditions)
    abort_reason: str | None = None
    for condition, adapter in zip(hosted_conditions, frontier_adapters, strict=True):
        if abort_reason is not None:
            summaries.append(
                not_run_condition_v2(
                    condition,
                    abort_reason,
                    status=RunStatus.NOT_RUN_BUDGET_REJECTED,
                    expected_episode_count=len(fixtures),
                    hosted_max_cost_microusd=_hosted_max_for_condition(condition),
                )
            )
            continue
        summary = run_frontier_condition_v2(
            adapter,
            condition=condition,
            fixtures=fixtures,
            qwen=(
                qwen
                if condition
                in {
                    EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
                    EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
                }
                else None
            ),
        )
        summaries.append(summary)
        if (
            summary.run_status is RunStatus.FAILED
            and not summary.cost_accounting_complete
        ):
            abort_reason = (
                "not attempted after a provider failure made actual hosted cost unknown"
            )
    return compose_report_v2(tuple(summaries), host_class=host_class)


def load_report_v2(root: Path) -> EvaluationReportV2:
    from .artifacts_v2 import R2_REPORT_PATH

    return EvaluationReportV2.model_validate_json(
        (root / R2_REPORT_PATH).read_text(encoding="utf-8")
    )


def _hosted_max_for_condition(condition: EvaluationConditionV2) -> int:
    from .artifacts_v2 import (
        R2_FAST_SLOW_MAX_MICROUSD,
        R2_REFERENCE_MAX_MICROUSD,
    )

    if condition in {
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
    }:
        return R2_FAST_SLOW_MAX_MICROUSD
    if condition in {
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
    }:
        return R2_REFERENCE_MAX_MICROUSD
    return 0


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = [
    "ExecutionEvaluationV2",
    "compose_report_v2",
    "execute_model_proposal_r2",
    "hosted_report_v2",
    "initial_report_v2",
    "load_report_v2",
    "local_report_v2",
    "not_run_condition_v2",
    "run_frontier_condition_v2",
    "run_qwen_reference_strategy_v2",
    "run_slow_off_v2",
    "scripted_ceiling_condition_v2",
    "snapshot_with_strategy",
    "snapshot_without_strategy",
]
