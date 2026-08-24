"""Shared Phase 03A1 baseline report composition.

Model execution is injected by condition runners. This module owns only the
truthful report envelope and immutable Harness bindings.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from proxyloop_agent_core import (
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    CoordinatorStatus,
    DeterministicRouter,
    RouteRequest,
)
from proxyloop_contracts import CaseContextSnapshot, SlowWorkResult
from proxyloop_provider_simulator import MultiTurnProviderEnvironment
from proxyloop_provider_simulator.multi_turn import SimulatorCapabilityAttempt

from scripts.run_phase_03a1_harness import (
    PROBE_NOW,
    EpisodeCapabilityAdapter,
    Phase03A1ModelFixture,
    build_phase03a1_harness_report,
    build_phase03a1_model_fixtures,
)

from .artifacts import (
    CEILING_PATH,
    EPISODES_PATH,
    MANIFEST_PATH,
    REPORT_PATH,
    fingerprint,
    report_fingerprint,
)
from .models import (
    BaselineCondition,
    BaselineReport,
    ConditionSummary,
    EpisodeBaselineResult,
    HostedCallEvidence,
    ModelProvenance,
    PromptProvenance,
    RunStatus,
)

if TYPE_CHECKING:
    from .openai_frontier import FrontierCallRecord, OpenAIFrontierAdapter
    from .qwen_mlx import QwenMLXAdapter, QwenMLXMetadata

HOST_CLASS = "Apple M4 Pro / 48 GB unified memory"
FRONTIER_INPUT_TOKEN_CAP = 8_192
FRONTIER_OUTPUT_TOKEN_CAP = 4_096
FAST_SLOW_FRONTIER_CALL_CAP = 32
FRONTIER_REFERENCE_CALL_CAP = 64
FAST_SLOW_HOSTED_MAX_MICROUSD = 3_670_016
FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD = 7_340_032
HOSTED_BUDGET_CEILING_MICROUSD = 11_010_048


def _utc_timestamp() -> str:
    """Return the report creation time as a second-precision UTC timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(root: Path, path: Path) -> dict[str, object]:
    value = json.loads((root / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _assert_frozen_harness(root: Path) -> None:
    """Reject live scenario/source drift before any model is loaded or called."""

    live = build_phase03a1_harness_report()
    committed_manifest = _json(root, MANIFEST_PATH)
    committed_episodes = _json(root, EPISODES_PATH)
    committed_ceiling = _json(root, CEILING_PATH)
    expected = (
        committed_manifest.get("content_hash"),
        committed_episodes.get("episode_fingerprint"),
        committed_ceiling.get("ceiling_fingerprint"),
    )
    observed = (
        live.get("manifest_fingerprint"),
        live.get("episode_fingerprint"),
        live.get("ceiling_fingerprint"),
    )
    if observed != expected:
        raise ValueError("live Phase 03A1 fixtures drifted from committed artifacts")


def not_run_condition(
    condition: BaselineCondition,
    reason: str,
    *,
    expected_episode_count: int = 32,
    status: RunStatus = RunStatus.NOT_RUN_MODEL_UNAVAILABLE,
    hosted_max_cost_microusd: int = 0,
) -> ConditionSummary:
    return ConditionSummary(
        condition=condition,
        run_status=status,
        not_run_reason=reason,
        expected_episode_count=expected_episode_count,
        evaluated_episode_count=0,
        model_call_count=0,
        schema_valid_count=0,
        valid_outcome_count=0,
        completed_count=0,
        valid_noncompletion_count=0,
        false_completion_count=0,
        policy_violation_count=0,
        leakage_violation_count=0,
        input_tokens=0,
        output_tokens=0,
        actual_cost_microusd=0,
        hosted_max_cost_microusd=hosted_max_cost_microusd,
        cost_accounting_complete=True,
        failure_slices={status.value: expected_episode_count},
        model_provenance=(),
        prompt_provenance=(),
        episodes=(),
    )


def scripted_ceiling_condition(root: Path) -> ConditionSummary:
    ceiling = _json(root, CEILING_PATH)
    count = _integer(ceiling["scenario_count"], "scenario_count")
    return ConditionSummary(
        condition=BaselineCondition.SCRIPTED_ORACLE_CEILING,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=count,
        evaluated_episode_count=count,
        model_call_count=0,
        schema_valid_count=count,
        valid_outcome_count=_integer(
            ceiling["valid_outcome_count"], "valid_outcome_count"
        ),
        completed_count=_integer(ceiling["completed_count"], "completed_count"),
        valid_noncompletion_count=_integer(
            ceiling["valid_noncompletion_count"], "valid_noncompletion_count"
        ),
        false_completion_count=_integer(
            ceiling["false_completion_count"], "false_completion_count"
        ),
        policy_violation_count=0,
        leakage_violation_count=_integer(
            ceiling["leakage_violation_count"], "leakage_violation_count"
        ),
        input_tokens=0,
        output_tokens=0,
        actual_cost_microusd=0,
        hosted_max_cost_microusd=0,
        cost_accounting_complete=True,
        failure_slices={},
        model_provenance=(),
        prompt_provenance=(),
        episodes=tuple(
            # The Harness owns detailed scripted episodes. Baseline evidence binds
            # their artifact rather than duplicating oracle-private evaluation rows.
            _scripted_episode_rows(root)
        ),
    )


def _scripted_episode_rows(root: Path) -> list[EpisodeBaselineResult]:
    artifact = _json(root, EPISODES_PATH)
    rows = artifact["episodes"]
    if not isinstance(rows, list):
        raise TypeError("Harness episodes must be a list")
    results: list[EpisodeBaselineResult] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Harness episode row must be an object")
        transition = row["transition"]
        if not isinstance(transition, dict):
            raise TypeError("Harness transition must be an object")
        routes = row["routing_decisions"]
        if not isinstance(routes, list):
            raise TypeError("Harness routes must be a list")
        results.append(
            EpisodeBaselineResult(
                episode_id=str(row["episode_id"]),
                split=str(row["split"]),
                provider_split=str(row["provider_split"]),
                safety=row["split"] == "safety",
                route_outcomes=tuple(str(route["outcome"]) for route in routes),
                adapter_status="scripted_oracle",
                schema_valid=True,
                pins_valid=True,
                fast_action_intent_null=True,
                route_agreement=True,
                policy_violation_count=0,
                leakage_violation_count=len(row["leaked_public_keys"]),
                completed=bool(transition["completed"]),
                valid_outcome=bool(transition["valid_outcome"]),
                false_completion=bool(transition["false_completion"]),
                failure_codes=(),
                input_fingerprint=str(row["observation_fingerprint"]),
                output_fingerprint=str(row["episode_fingerprint"]),
                actual_cost_microusd=0,
            )
        )
    return list(results)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def run_qwen_reference_strategy(
    adapter: QwenMLXAdapter,
    *,
    fixtures: tuple[Phase03A1ModelFixture, ...] | None = None,
) -> ConditionSummary:
    """Run Qwen Fast against the one generic pre-held-out strategy fixture."""

    from .qwen_mlx import QwenMLXStatus

    selected = fixtures or build_phase03a1_model_fixtures()
    coordinator = CaseCoordinator()
    router = DeterministicRouter()
    results: list[EpisodeBaselineResult] = []
    prompt_fingerprints: set[str] = set()
    model_calls = 0
    failure_slices: Counter[str] = Counter()
    last_metadata: QwenMLXMetadata | None = None
    for fixture in selected:
        view = coordinator.project_fast_view(fixture.snapshot)
        prompt = adapter.build_prompt(view)
        prompt_fingerprints.add(prompt.fingerprint)
        generation = adapter.generate(view)
        metadata = generation.metadata
        last_metadata = metadata
        if metadata.status is QwenMLXStatus.UNAVAILABLE and not results:
            return not_run_condition(
                BaselineCondition.UNTUNED_FAST_REFERENCE_STRATEGY,
                metadata.error_message or "mlx_lm is unavailable",
            )
        model_calls += 1
        route = router.route(
            RouteRequest(snapshot=fixture.snapshot, created_at=PROBE_NOW)
        )
        route_agreement = route.outcome.value == "fast_now"
        failure_codes: list[str] = []
        schema_valid = generation.adapter_result is not None
        pins_valid = False
        action_intent_null = False
        false_completion = False
        output_fingerprint: str | None = None
        if generation.adapter_result is not None:
            audit = coordinator.validate_fast_result(
                generation.adapter_result,
                fixture.snapshot,
            )
            pins_valid = audit.accepted or "stale_fast_result" not in audit.reason_codes
            decision = generation.adapter_result.decision
            action_intent_null = decision.action_intent is None
            false_completion = decision.completion_claim.status != "not_done"
            failure_codes.extend(
                reason
                for reason in audit.reason_codes
                if reason != "fast_result_current"
            )
            if false_completion:
                failure_codes.append("unsupported_fast_completion_candidate")
            output_fingerprint = fingerprint(decision.model_dump(mode="json"))
        else:
            failure_codes.append(metadata.error_code or metadata.status.value)
            if metadata.raw_output is not None:
                output_fingerprint = fingerprint(metadata.raw_output)
        if not route_agreement:
            failure_codes.append("router_outcome_mismatch")
        for code in set(failure_codes):
            failure_slices[code] += 1
            failure_slices[f"split:{fixture.split}:{code}"] += 1
            failure_slices[f"provider_split:{fixture.provider_split}:{code}"] += 1
            failure_slices[f"safety:{str(fixture.safety_only).lower()}:{code}"] += 1
            failure_slices[f"route:{route.outcome.value}:{code}"] += 1
            failure_slices[f"adapter:{metadata.status.value}:{code}"] += 1
        results.append(
            EpisodeBaselineResult(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=(route.outcome.value,),
                adapter_status=metadata.status.value,
                schema_valid=schema_valid,
                pins_valid=pins_valid,
                fast_action_intent_null=action_intent_null,
                route_agreement=route_agreement,
                policy_violation_count=len(failure_codes),
                leakage_violation_count=0,
                completed=False,
                valid_outcome=schema_valid and not failure_codes,
                false_completion=false_completion,
                failure_codes=tuple(sorted(set(failure_codes))),
                input_fingerprint=metadata.prompt_fingerprint,
                output_fingerprint=output_fingerprint,
                raw_output_excerpt=(metadata.raw_output or "")[:16384] or None,
                validation_error=metadata.error_message,
                latency_ms=metadata.latency_ms,
                input_tokens=metadata.input_tokens,
                output_tokens=metadata.output_tokens,
                actual_cost_microusd=0,
            )
        )
    latencies = [row.latency_ms for row in results if row.latency_ms is not None]
    if last_metadata is None:
        raise ValueError("Qwen baseline requires at least one fixture")
    return ConditionSummary(
        condition=BaselineCondition.UNTUNED_FAST_REFERENCE_STRATEGY,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=len(selected),
        evaluated_episode_count=len(results),
        model_call_count=model_calls,
        schema_valid_count=sum(row.schema_valid for row in results),
        valid_outcome_count=sum(row.valid_outcome for row in results),
        completed_count=0,
        valid_noncompletion_count=sum(row.valid_outcome for row in results),
        false_completion_count=sum(row.false_completion for row in results),
        policy_violation_count=sum(row.policy_violation_count for row in results),
        leakage_violation_count=0,
        input_tokens=sum(row.input_tokens or 0 for row in results),
        output_tokens=sum(row.output_tokens or 0 for row in results),
        actual_cost_microusd=0,
        hosted_max_cost_microusd=0,
        cost_accounting_complete=True,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p90_ms=_percentile(latencies, 0.9),
        failure_slices=dict(sorted(failure_slices.items())),
        model_provenance=(
            ModelProvenance(
                provider="mlx-community",
                model_id=last_metadata.model,
                model_revision=last_metadata.model_revision,
                source_model_id=last_metadata.source_lineage,
                source_model_revision=last_metadata.source_revision,
                weight_format="mlx",
                quantization=last_metadata.quantization,
                untuned_label=last_metadata.run_label,
                license="Apache-2.0",
                runtime="mlx-lm",
                checkpoint_fingerprint=last_metadata.checkpoint_fingerprint,
                tokenizer_fingerprint=last_metadata.tokenizer_fingerprint,
                chat_template_fingerprint=(last_metadata.chat_template_fingerprint),
            ),
        ),
        prompt_provenance=tuple(
            PromptProvenance(
                prompt_version=last_metadata.adapter_version,
                prompt_fingerprint=value,
                input_schema_version="FastModelView@1.0",
                output_schema_version="FastModelOutput@1.0 -> FastTurnDecision@1.0",
            )
            for value in sorted(prompt_fingerprints)
        ),
        episodes=tuple(results),
    )


def run_slow_off_ablation(
    *,
    fixtures: tuple[Phase03A1ModelFixture, ...] | None = None,
) -> ConditionSummary:
    """Prove mandatory Slow work cannot be bypassed when no Slow exists."""

    selected = fixtures or build_phase03a1_model_fixtures()
    rows: list[EpisodeBaselineResult] = []
    for fixture in selected:
        pins = fixture.snapshot.pins.model_copy(
            update={"strategy_id": None, "strategy_revision": 0}
        )
        snapshot = fixture.snapshot.model_copy(update={"strategy": None, "pins": pins})
        outcome = CaseCoordinator().advance(
            RouteRequest(snapshot=snapshot, created_at=PROBE_NOW)
        )
        valid = outcome.status is CoordinatorStatus.SLOW_UNAVAILABLE
        rows.append(
            EpisodeBaselineResult(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=(outcome.route.outcome.value,),
                adapter_status=outcome.status.value,
                schema_valid=True,
                pins_valid=True,
                fast_action_intent_null=True,
                route_agreement=outcome.route.outcome.value == "slow_refresh",
                policy_violation_count=0 if valid else 1,
                leakage_violation_count=0,
                completed=False,
                valid_outcome=valid,
                false_completion=False,
                failure_codes=("slow_unavailable",),
                input_fingerprint=fingerprint(snapshot.pins.model_dump(mode="json")),
                actual_cost_microusd=0,
            )
        )
    return ConditionSummary(
        condition=BaselineCondition.UNTUNED_FAST_SLOW_OFF,
        run_status=RunStatus.SUCCEEDED,
        expected_episode_count=len(rows),
        evaluated_episode_count=len(rows),
        model_call_count=0,
        schema_valid_count=len(rows),
        valid_outcome_count=sum(row.valid_outcome for row in rows),
        completed_count=0,
        valid_noncompletion_count=sum(row.valid_outcome for row in rows),
        false_completion_count=0,
        policy_violation_count=sum(row.policy_violation_count for row in rows),
        leakage_violation_count=0,
        input_tokens=0,
        output_tokens=0,
        actual_cost_microusd=0,
        hosted_max_cost_microusd=0,
        cost_accounting_complete=True,
        failure_slices={"slow_unavailable": len(rows)},
        model_provenance=(),
        prompt_provenance=(),
        episodes=tuple(rows),
    )


def _without_strategy(snapshot: CaseContextSnapshot) -> CaseContextSnapshot:
    pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    return snapshot.model_copy(update={"strategy": None, "pins": pins})


def _with_strategy(
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
    return snapshot.model_copy(update={"strategy": strategy, "pins": pins})


def _execute_model_proposal(
    fixture: Phase03A1ModelFixture,
    snapshot: CaseContextSnapshot,
    result: SlowWorkResult,
) -> tuple[bool, bool, bool, tuple[str, ...]]:
    """Run exactly one model proposal only through the deterministic Executor."""

    if len(result.capability_proposals) != 1 or len(result.action_proposals) != 1:
        return False, False, False, ("no_single_executable_proposal",)
    proposal = result.capability_proposals[0]
    action = result.action_proposals[0]
    environment = MultiTurnProviderEnvironment(fixture.scenario)
    opening = environment.start()
    public_offer_by_canonical = {
        str(canonical.offer_id): public.offer_id
        for canonical, public in zip(
            fixture.snapshot.offers,
            opening.turn.offers,
            strict=True,
        )
    }
    canonical_offer_id = (
        str(action.offer_ref.offer_id) if action.offer_ref is not None else None
    )
    public_offer_id = (
        public_offer_by_canonical.get(canonical_offer_id)
        if canonical_offer_id is not None
        else None
    )
    if canonical_offer_id is not None and public_offer_id is None:
        return False, False, False, ("model_offer_not_current",)
    attempt = SimulatorCapabilityAttempt(
        capability_id=proposal.capability.capability_id,
        offer_id=public_offer_id,
        idempotency_key=action.idempotency_key,
    )
    capability_adapter = EpisodeCapabilityAdapter(
        environment=environment,
        attempt=attempt,
        canonical_offer_id=canonical_offer_id,
        observed_at=opening.observed_at,
    )
    executor = CapabilityExecutor(capability_adapter)
    approval = next(
        (
            item
            for item in snapshot.approval_requests
            if item.action_intent_id == action.intent_id
        ),
        None,
    )
    executable_snapshot = snapshot.model_copy(
        update={"action_intents": (*snapshot.action_intents, action)}
    )
    outcome = executor.execute(
        CapabilityExecutionRequest(
            snapshot=executable_snapshot,
            source_pins=executable_snapshot.pins,
            proposal=proposal,
            action_intent=action,
            approval=approval,
            executed_at=PROBE_NOW,
        )
    )
    if outcome.status is CapabilityExecutionStatus.REJECTED:
        return True, False, False, outcome.reason_codes
    transition = capability_adapter.transition
    if transition is None:
        return False, False, False, ("executor_missing_provider_transition",)
    return (
        transition.verification.valid_outcome,
        transition.verification.completed,
        transition.verification.false_completion,
        () if transition.verification.valid_outcome else ("invalid_provider_outcome",),
    )


def _hosted_call_evidence(record: FrontierCallRecord) -> HostedCallEvidence:
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


def run_frontier_condition(
    frontier: OpenAIFrontierAdapter,
    *,
    condition: BaselineCondition,
    qwen: QwenMLXAdapter | None = None,
    fixtures: tuple[Phase03A1ModelFixture, ...] | None = None,
) -> ConditionSummary:
    """Run a frontier Slow condition with either Qwen or frontier Fast."""

    from .openai_frontier import (
        FRONTIER_MODEL,
        FRONTIER_PROVIDER,
        FRONTIER_RUNTIME,
        FrontierAdapterError,
        FrontierCallStatus,
    )
    from .qwen_mlx import QwenMLXStatus

    if condition not in {
        BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
        BaselineCondition.FRONTIER_REFERENCE,
    }:
        raise ValueError("frontier runner received a non-frontier condition")
    if condition is BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW and qwen is None:
        raise ValueError("Fast+Slow condition requires the Qwen Fast adapter")
    if condition is BaselineCondition.FRONTIER_REFERENCE and qwen is not None:
        raise ValueError("frontier reference uses frontier for both model seams")

    selected = fixtures or build_phase03a1_model_fixtures()
    coordinator = CaseCoordinator()
    rows: list[EpisodeBaselineResult] = []
    failure_slices: Counter[str] = Counter()
    prompt_rows: dict[tuple[str, str], PromptProvenance] = {}
    frontier_records: list[FrontierCallRecord] = []
    qwen_calls = 0
    qwen_metadata: QwenMLXMetadata | None = None
    terminal_failure_reason: str | None = None
    for fixture in selected:
        initial = _without_strategy(fixture.snapshot)
        slow_route = DeterministicRouter().route(
            RouteRequest(snapshot=initial, created_at=PROBE_NOW)
        )
        request = coordinator.build_slow_request(
            initial,
            reason_code=slow_route.reason_codes[0],
            created_at=PROBE_NOW,
        )
        slow_bundle = frontier.build_slow_prompt(request)
        prompt_rows[("slow", slow_bundle.prompt_fingerprint)] = PromptProvenance(
            prompt_version="phase-03a1-b-frontier-slow-v1",
            prompt_fingerprint=slow_bundle.prompt_fingerprint,
            input_schema_version="SlowWorkRequest@1.0",
            output_schema_version=f"SlowModelOutput:{slow_bundle.schema_fingerprint}",
        )
        failures: list[str] = []
        slow_result: SlowWorkResult | None = None
        slow_raw: str | None = None
        slow_call_record: FrontierCallRecord | None = None
        try:
            candidate = frontier.reason(request)
            slow_raw = frontier.last_structured_output
            record = frontier.last_call
            if record is not None:
                frontier_records.append(record)
                slow_call_record = record
            audit = coordinator.validate_slow_result(
                candidate,
                initial,
                expected_request=request,
                evaluated_at=PROBE_NOW,
            )
            if audit.accepted:
                slow_result = candidate
            else:
                failures.extend(audit.reason_codes)
        except FrontierAdapterError as error:
            slow_raw = frontier.last_structured_output
            record = frontier.last_call
            if record is not None:
                frontier_records.append(record)
                slow_call_record = record
            if not rows and error.status in {
                FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS,
                FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED,
                FrontierCallStatus.NOT_RUN_MODEL_UNAVAILABLE,
            }:
                status = (
                    RunStatus.NOT_RUN_MISSING_CREDENTIALS
                    if error.status is FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS
                    else (
                        RunStatus.NOT_RUN_BUDGET_REJECTED
                        if error.status is FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED
                        else RunStatus.NOT_RUN_MODEL_UNAVAILABLE
                    )
                )
                return not_run_condition(
                    condition,
                    str(error),
                    status=status,
                    hosted_max_cost_microusd=round(
                        frontier.cost_estimate.maximum_cost_usd * 1_000_000
                    ),
                )
            failures.append(error.status.value)
            if error.status is FrontierCallStatus.FAILED_PROVIDER_CALL or (
                error.status is FrontierCallStatus.FAILED_INVALID_RESPONSE
                and record is not None
                and record.actual_cost_usd is None
            ):
                failures.append("actual_cost_unknown")
                terminal_failure_reason = str(error)

        planned: CaseContextSnapshot | None = None
        execution_valid = False
        completed = False
        execution_false_completion = False
        if slow_result is not None:
            proposed_capability = (
                slow_result.capability_proposals[0].capability.capability_id
                if len(slow_result.capability_proposals) == 1
                else None
            )
            if proposed_capability != fixture.reference_capability_id:
                failures.append("capability_reference_mismatch")
            planned = _with_strategy(initial, slow_result)
            (
                execution_valid,
                completed,
                execution_false_completion,
                execution_failures,
            ) = _execute_model_proposal(fixture, planned, slow_result)
            failures.extend(execution_failures)

        fast_schema_valid = False
        fast_pins_valid = False
        fast_action_intent_null = False
        unsupported_completion = False
        fast_input_fingerprint: str | None = None
        fast_output_fingerprint: str | None = None
        fast_latency: int | None = None
        fast_input_tokens: int | None = None
        fast_output_tokens: int | None = None
        fast_raw: str | None = None
        fast_error: str | None = None
        fast_call_record: FrontierCallRecord | None = None
        routes = [slow_route.outcome.value]
        if planned is not None:
            fast_route = DeterministicRouter().route(
                RouteRequest(snapshot=planned, created_at=PROBE_NOW)
            )
            routes.append(fast_route.outcome.value)
            fast_view = coordinator.project_fast_view(planned)
            if qwen is not None:
                qwen_prompt = qwen.build_prompt(fast_view)
                fast_input_fingerprint = qwen_prompt.fingerprint
                generation = qwen.generate(fast_view)
                qwen_calls += 1
                qwen_metadata = generation.metadata
                fast_latency = generation.metadata.latency_ms
                fast_input_tokens = generation.metadata.input_tokens
                fast_output_tokens = generation.metadata.output_tokens
                fast_raw = generation.metadata.raw_output
                fast_error = generation.metadata.error_message
                if generation.status is QwenMLXStatus.SUCCEEDED:
                    fast_result = generation.adapter_result
                else:
                    fast_result = None
                    failures.append(
                        generation.metadata.error_code or generation.status.value
                    )
                prompt_rows[("fast", qwen_prompt.fingerprint)] = PromptProvenance(
                    prompt_version=generation.metadata.adapter_version,
                    prompt_fingerprint=qwen_prompt.fingerprint,
                    input_schema_version="FastModelView@1.0",
                    output_schema_version="FastModelOutput@1.0",
                )
            else:
                fast_bundle = frontier.build_fast_prompt(fast_view)
                fast_input_fingerprint = fast_bundle.prompt_fingerprint
                prompt_rows[("fast", fast_bundle.prompt_fingerprint)] = (
                    PromptProvenance(
                        prompt_version="phase-03a1-b-frontier-fast-v1",
                        prompt_fingerprint=fast_bundle.prompt_fingerprint,
                        input_schema_version="FastModelView@1.0",
                        output_schema_version=(
                            f"FastModelOutput:{fast_bundle.schema_fingerprint}"
                        ),
                    )
                )
                try:
                    fast_result = frontier.decide(fast_view)
                    record = frontier.last_call
                    if record is not None:
                        frontier_records.append(record)
                        fast_call_record = record
                        fast_latency = record.latency_ms
                        fast_input_tokens = record.input_tokens
                        fast_output_tokens = record.output_tokens
                    fast_raw = frontier.last_structured_output
                except FrontierAdapterError as error:
                    record = frontier.last_call
                    if record is not None:
                        frontier_records.append(record)
                        fast_call_record = record
                    fast_result = None
                    fast_raw = frontier.last_structured_output
                    fast_error = str(error)
                    failures.append(error.status.value)
                    if error.status is FrontierCallStatus.FAILED_PROVIDER_CALL or (
                        error.status is FrontierCallStatus.FAILED_INVALID_RESPONSE
                        and record is not None
                        and record.actual_cost_usd is None
                    ):
                        failures.append("actual_cost_unknown")
                        terminal_failure_reason = str(error)
            if fast_result is not None:
                fast_audit = coordinator.validate_fast_result(fast_result, planned)
                fast_schema_valid = True
                fast_pins_valid = fast_audit.accepted
                fast_action_intent_null = fast_result.decision.action_intent is None
                unsupported_completion = (
                    fast_result.decision.completion_claim.status != "not_done"
                )
                fast_output_fingerprint = fingerprint(
                    fast_result.decision.model_dump(mode="json")
                )
                failures.extend(
                    reason
                    for reason in fast_audit.reason_codes
                    if reason != "fast_result_current"
                )
                if unsupported_completion:
                    failures.append("unsupported_fast_completion_candidate")

        route_agreement = routes == ["slow_refresh", "fast_now"]
        if not route_agreement:
            failures.append("router_outcome_mismatch")
        false_completion = execution_false_completion or unsupported_completion
        adapter_status = (
            "succeeded" if slow_result is not None and fast_schema_valid else "failed"
        )
        for code in set(failures):
            failure_slices[code] += 1
            failure_slices[f"split:{fixture.split}:{code}"] += 1
            failure_slices[f"provider_split:{fixture.provider_split}:{code}"] += 1
            failure_slices[f"safety:{str(fixture.safety_only).lower()}:{code}"] += 1
            for route in routes:
                failure_slices[f"route:{route}:{code}"] += 1
            failure_slices[f"adapter:{adapter_status}:{code}"] += 1
        slow_latency = getattr(slow_call_record, "latency_ms", None)
        slow_input_tokens = getattr(slow_call_record, "input_tokens", 0)
        slow_output_tokens = getattr(slow_call_record, "output_tokens", 0)
        episode_latency = sum(
            value for value in (slow_latency, fast_latency) if isinstance(value, int)
        )
        episode_input_tokens = (
            slow_input_tokens if isinstance(slow_input_tokens, int) else 0
        ) + (fast_input_tokens or 0)
        episode_output_tokens = (
            slow_output_tokens if isinstance(slow_output_tokens, int) else 0
        ) + (fast_output_tokens or 0)
        hosted_calls = tuple(
            _hosted_call_evidence(record)
            for record in (slow_call_record, fast_call_record)
            if record is not None
        )
        episode_cost = sum(call.actual_cost_microusd or 0 for call in hosted_calls)
        combined_input_fingerprint = fingerprint(
            {
                "slow": slow_bundle.prompt_fingerprint,
                "fast": fast_input_fingerprint,
            }
        )
        combined_output = {"slow": slow_raw, "fast": fast_raw}
        combined_output_fingerprint = (
            fingerprint(combined_output) if slow_raw or fast_raw else None
        )
        combined_output_excerpt = (
            json.dumps(
                combined_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )[:16384]
            if slow_raw or fast_raw
            else None
        )
        rows.append(
            EpisodeBaselineResult(
                episode_id=fixture.episode_id,
                split=fixture.split,
                provider_split=fixture.provider_split,
                safety=fixture.safety_only,
                route_outcomes=tuple(routes),
                adapter_status=adapter_status,
                schema_valid=slow_result is not None and fast_schema_valid,
                pins_valid=slow_result is not None and fast_pins_valid,
                fast_action_intent_null=fast_action_intent_null,
                route_agreement=route_agreement,
                policy_violation_count=len(set(failures)),
                leakage_violation_count=0,
                completed=completed,
                valid_outcome=(
                    execution_valid
                    and slow_result is not None
                    and fast_schema_valid
                    and not failures
                ),
                false_completion=false_completion,
                failure_codes=tuple(sorted(set(failures))),
                input_fingerprint=combined_input_fingerprint,
                output_fingerprint=(
                    combined_output_fingerprint or fast_output_fingerprint
                ),
                raw_output_excerpt=combined_output_excerpt,
                validation_error=fast_error,
                latency_ms=episode_latency,
                input_tokens=episode_input_tokens,
                output_tokens=episode_output_tokens,
                actual_cost_microusd=episode_cost,
                hosted_calls=hosted_calls,
            )
        )
        if terminal_failure_reason is not None:
            break

    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    model_provenance = [
        ModelProvenance(
            provider=FRONTIER_PROVIDER,
            model_id=FRONTIER_MODEL,
            model_revision=next(
                (
                    str(record.response_model_version)
                    for record in frontier_records
                    if getattr(record, "response_model_version", None)
                ),
                FRONTIER_MODEL,
            ),
            weight_format="hosted",
            untuned_label="frontier_reference",
            runtime=FRONTIER_RUNTIME,
        )
    ]
    if qwen_metadata is not None:
        model_provenance.append(
            ModelProvenance(
                provider="mlx-community",
                model_id=qwen_metadata.model,
                model_revision=qwen_metadata.model_revision,
                source_model_id=qwen_metadata.source_lineage,
                source_model_revision=qwen_metadata.source_revision,
                weight_format="mlx",
                quantization=qwen_metadata.quantization,
                untuned_label=qwen_metadata.run_label,
                license="Apache-2.0",
                runtime="mlx-lm",
                checkpoint_fingerprint=qwen_metadata.checkpoint_fingerprint,
                tokenizer_fingerprint=qwen_metadata.tokenizer_fingerprint,
                chat_template_fingerprint=qwen_metadata.chat_template_fingerprint,
            )
        )
    cost_accounting_complete = all(
        call.actual_cost_microusd is not None
        for row in rows
        for call in row.hosted_calls
    )
    return ConditionSummary(
        condition=condition,
        run_status=(
            RunStatus.FAILED
            if terminal_failure_reason is not None
            else RunStatus.SUCCEEDED
        ),
        not_run_reason=terminal_failure_reason,
        expected_episode_count=len(selected),
        evaluated_episode_count=len(rows),
        model_call_count=len(frontier_records) + qwen_calls,
        schema_valid_count=sum(row.schema_valid for row in rows),
        valid_outcome_count=sum(row.valid_outcome for row in rows),
        completed_count=sum(row.completed for row in rows),
        valid_noncompletion_count=sum(
            row.valid_outcome and not row.completed for row in rows
        ),
        false_completion_count=sum(row.false_completion for row in rows),
        policy_violation_count=sum(row.policy_violation_count for row in rows),
        leakage_violation_count=0,
        input_tokens=sum(row.input_tokens or 0 for row in rows),
        output_tokens=sum(row.output_tokens or 0 for row in rows),
        actual_cost_microusd=sum(row.actual_cost_microusd for row in rows),
        hosted_max_cost_microusd=round(
            frontier.cost_estimate.maximum_cost_usd * 1_000_000
        ),
        cost_accounting_complete=cost_accounting_complete,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p90_ms=_percentile(latencies, 0.9),
        failure_slices=dict(sorted(failure_slices.items())),
        model_provenance=tuple(model_provenance),
        prompt_provenance=tuple(prompt_rows[key] for key in sorted(prompt_rows)),
        episodes=tuple(rows),
    )


def compose_report(
    root: Path,
    conditions: tuple[ConditionSummary, ...],
    *,
    hosted_budget_ceiling_microusd: int,
) -> BaselineReport:
    manifest = _json(root, MANIFEST_PATH)
    episodes = _json(root, EPISODES_PATH)
    ceiling = _json(root, CEILING_PATH)
    succeeded = {
        condition.condition
        for condition in conditions
        if condition.run_status is RunStatus.SUCCEEDED
    }
    required = {
        BaselineCondition.UNTUNED_FAST_REFERENCE_STRATEGY,
        BaselineCondition.UNTUNED_FAST_SLOW_OFF,
        BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
        BaselineCondition.FRONTIER_REFERENCE,
    }
    blockers = tuple(
        f"{condition.value}:{summary.run_status.value}"
        for condition, summary in (
            (item.condition, item) for item in conditions if item.condition in required
        )
        if condition not in succeeded
    )
    draft = BaselineReport(
        schema_version="phase-03a1-baselines-v1",
        generated_at=_utc_timestamp(),
        manifest_fingerprint=str(manifest["content_hash"]),
        episode_fingerprint=str(episodes["episode_fingerprint"]),
        harness_ceiling_fingerprint=str(ceiling["ceiling_fingerprint"]),
        harness_ceiling_gate_passed=bool(ceiling["gate_passed"]),
        host_class=HOST_CLASS,
        conditions=conditions,
        hosted_budget_ceiling_microusd=hosted_budget_ceiling_microusd,
        phase_completion_ready=not blockers,
        phase_completion_blockers=blockers,
        report_fingerprint="0" * 64,
    )
    return draft.model_copy(update={"report_fingerprint": report_fingerprint(draft)})


def initial_report(root: Path) -> BaselineReport:
    _assert_frozen_harness(root)
    missing_key = (
        "PROXYLOOP_FRONTIER_API_KEY is not present; no hosted call was attempted"
    )
    conditions = (
        scripted_ceiling_condition(root),
        not_run_condition(
            BaselineCondition.UNTUNED_FAST_REFERENCE_STRATEGY,
            "local Qwen checkpoint has not been downloaded or run",
        ),
        run_slow_off_ablation(),
        not_run_condition(
            BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
            missing_key,
            status=RunStatus.NOT_RUN_MISSING_CREDENTIALS,
            hosted_max_cost_microusd=FAST_SLOW_HOSTED_MAX_MICROUSD,
        ),
        not_run_condition(
            BaselineCondition.FRONTIER_REFERENCE,
            missing_key,
            status=RunStatus.NOT_RUN_MISSING_CREDENTIALS,
            hosted_max_cost_microusd=FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD,
        ),
    )
    report = compose_report(
        root,
        conditions,
        hosted_budget_ceiling_microusd=0,
    )
    if report.report_fingerprint != report_fingerprint(report):
        raise RuntimeError("baseline report fingerprint construction failed")
    return report


def qwen_report(
    root: Path,
    *,
    model_path: str,
) -> BaselineReport:
    """Run and compose the local quantized untuned Qwen condition."""

    from .qwen_mlx import QwenMLXAdapter

    _assert_frozen_harness(root)
    missing_key = (
        "PROXYLOOP_FRONTIER_API_KEY is not present; no hosted call was attempted"
    )
    adapter = QwenMLXAdapter(
        model_path=model_path,
    )
    conditions = (
        scripted_ceiling_condition(root),
        run_qwen_reference_strategy(adapter),
        run_slow_off_ablation(),
        not_run_condition(
            BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
            missing_key,
            status=RunStatus.NOT_RUN_MISSING_CREDENTIALS,
            hosted_max_cost_microusd=FAST_SLOW_HOSTED_MAX_MICROUSD,
        ),
        not_run_condition(
            BaselineCondition.FRONTIER_REFERENCE,
            missing_key,
            status=RunStatus.NOT_RUN_MISSING_CREDENTIALS,
            hosted_max_cost_microusd=FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD,
        ),
    )
    return compose_report(
        root,
        conditions,
        hosted_budget_ceiling_microusd=0,
    )


def frontier_report(
    root: Path,
    *,
    model_path: str,
    approved_max_cost_usd: float,
) -> BaselineReport:
    """Run both hosted conditions under one explicit conservative budget gate."""

    from .openai_frontier import OpenAIFrontierAdapter
    from .qwen_mlx import QwenMLXAdapter

    _assert_frozen_harness(root)
    frozen_max_cost_usd = HOSTED_BUDGET_CEILING_MICROUSD / 1_000_000
    if approved_max_cost_usd < frozen_max_cost_usd:
        raise ValueError(
            "hosted run requires explicit approval for at least "
            f"${frozen_max_cost_usd:.6f}"
        )
    current = BaselineReport.model_validate_json(
        (root / REPORT_PATH).read_text(encoding="utf-8")
    )
    qwen_reference = current.conditions[1]
    if (
        qwen_reference.condition
        is not BaselineCondition.UNTUNED_FAST_REFERENCE_STRATEGY
        or qwen_reference.run_status is not RunStatus.SUCCEEDED
    ):
        raise ValueError("a successful committed Qwen reference result is required")
    if not qwen_reference.model_provenance:
        raise ValueError("committed Qwen reference provenance is missing")
    qwen_provenance = qwen_reference.model_provenance[0]
    qwen = QwenMLXAdapter(model_path=model_path)
    attested = qwen.checkpoint_attestation
    if (
        qwen_provenance.model_revision != attested.model_revision
        or qwen_provenance.source_model_revision != attested.source_revision
        or qwen_provenance.checkpoint_fingerprint != attested.checkpoint_fingerprint
        or qwen_provenance.tokenizer_fingerprint != attested.tokenizer_fingerprint
        or qwen_provenance.chat_template_fingerprint
        != attested.chat_template_fingerprint
    ):
        raise ValueError("Qwen attestation does not match the committed reference run")
    fast_slow_frontier = OpenAIFrontierAdapter(
        input_token_cap=FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=FAST_SLOW_FRONTIER_CALL_CAP,
        usd_ceiling=(
            FAST_SLOW_FRONTIER_CALL_CAP
            * (FRONTIER_INPUT_TOKEN_CAP * 4.0 + FRONTIER_OUTPUT_TOKEN_CAP * 20.0)
            / 1_000_000
        ),
    )
    reference_frontier = OpenAIFrontierAdapter(
        input_token_cap=FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=FRONTIER_REFERENCE_CALL_CAP,
        usd_ceiling=(
            FRONTIER_REFERENCE_CALL_CAP
            * (FRONTIER_INPUT_TOKEN_CAP * 4.0 + FRONTIER_OUTPUT_TOKEN_CAP * 20.0)
            / 1_000_000
        ),
    )
    fast_slow_condition, reference_condition = _run_frontier_sequence(
        fast_slow_frontier,
        reference_frontier,
        qwen=qwen,
    )
    conditions = (
        scripted_ceiling_condition(root),
        qwen_reference,
        run_slow_off_ablation(),
        fast_slow_condition,
        reference_condition,
    )
    return compose_report(
        root,
        conditions,
        hosted_budget_ceiling_microusd=HOSTED_BUDGET_CEILING_MICROUSD,
    )


def _run_frontier_sequence(
    fast_slow_frontier: OpenAIFrontierAdapter,
    reference_frontier: OpenAIFrontierAdapter,
    *,
    qwen: QwenMLXAdapter,
) -> tuple[ConditionSummary, ConditionSummary]:
    """Run hosted conditions in order and stop globally on unknown actual cost."""

    fast_slow = run_frontier_condition(
        fast_slow_frontier,
        condition=BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
        qwen=qwen,
    )
    if (
        fast_slow.run_status is RunStatus.FAILED
        and not fast_slow.cost_accounting_complete
    ):
        reference = not_run_condition(
            BaselineCondition.FRONTIER_REFERENCE,
            "not attempted after a provider failure made actual hosted cost unknown",
            status=RunStatus.NOT_RUN_BUDGET_REJECTED,
            hosted_max_cost_microusd=FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD,
        )
    else:
        reference = run_frontier_condition(
            reference_frontier,
            condition=BaselineCondition.FRONTIER_REFERENCE,
        )
    return fast_slow, reference


__all__ = [
    "compose_report",
    "frontier_report",
    "initial_report",
    "not_run_condition",
    "qwen_report",
    "run_frontier_condition",
    "run_qwen_reference_strategy",
    "run_slow_off_ablation",
    "scripted_ceiling_condition",
]
