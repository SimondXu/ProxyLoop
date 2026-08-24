"""Independent offline replay checks for committed Phase 03A1 model evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from proxyloop_agent_core import CaseCoordinator, DeterministicRouter, RouteRequest
from proxyloop_contracts import CaseContextSnapshot

from scripts.run_phase_03a1_harness import (
    PROBE_NOW,
    build_phase03a1_harness_report,
    build_phase03a1_model_fixtures,
)

from .fast_output import FastModelOutput, compile_fast_output
from .legacy_slow_output import (
    LegacySlowModelOutput,
    build_legacy_slow_prompt,
    compile_legacy_slow_output,
)
from .models import BaselineCondition, BaselineReport, RunStatus
from .openai_frontier import (
    FRONTIER_MODEL,
    FrontierCallStatus,
    build_fast_prompt,
)
from .qwen_mlx import (
    QWEN_CHAT_TEMPLATE_FINGERPRINT,
    QWEN_CHECKPOINT_FINGERPRINT,
    QWEN_MLX_MODEL,
    QWEN_MODEL_REVISION,
    QWEN_SOURCE_REVISION,
    QWEN_TOKENIZER_FINGERPRINT,
    QwenMLXAdapter,
)


def _fingerprint(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _without_strategy(snapshot: CaseContextSnapshot) -> CaseContextSnapshot:
    pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    return snapshot.model_copy(update={"strategy": None, "pins": pins})


def _with_strategy(
    snapshot: CaseContextSnapshot, result: object
) -> CaseContextSnapshot:
    from proxyloop_contracts import SlowWorkResult

    if not isinstance(result, SlowWorkResult) or result.strategy_proposal is None:
        raise ValueError("replay Slow result has no strategy")
    strategy = result.strategy_proposal
    pins = snapshot.pins.model_copy(
        update={
            "strategy_id": strategy.strategy_id,
            "strategy_revision": strategy.revision,
        }
    )
    return snapshot.model_copy(update={"strategy": strategy, "pins": pins})


def replay_report(
    root: Path,
    report: BaselineReport,
    *,
    manifest: dict[str, object],
    episodes: dict[str, object],
    ceiling: dict[str, object],
) -> tuple[str, ...]:
    """Rebuild frozen inputs/prompts and recompile recorded semantic outputs."""

    del root
    errors: list[str] = []
    live = build_phase03a1_harness_report()
    observed = (
        live.get("manifest_fingerprint"),
        live.get("episode_fingerprint"),
        live.get("ceiling_fingerprint"),
    )
    expected = (
        manifest.get("content_hash"),
        episodes.get("episode_fingerprint"),
        ceiling.get("ceiling_fingerprint"),
    )
    if observed != expected:
        errors.append("live evaluation fixtures drifted from committed Harness inputs")
        return tuple(errors)

    fixtures = {
        fixture.episode_id: fixture for fixture in build_phase03a1_model_fixtures()
    }
    errors.extend(_replay_qwen(report, fixtures))
    errors.extend(_replay_frontier(report, fixtures))
    return tuple(errors)


def _replay_qwen(
    report: BaselineReport,
    fixtures: Mapping[str, object],
) -> list[str]:
    from scripts.run_phase_03a1_harness import Phase03A1ModelFixture

    errors: list[str] = []
    condition = report.conditions[1]
    if condition.run_status is not RunStatus.SUCCEEDED:
        return errors
    expected_provenance = (
        QWEN_MLX_MODEL,
        QWEN_MODEL_REVISION,
        QWEN_SOURCE_REVISION,
        QWEN_CHECKPOINT_FINGERPRINT,
        QWEN_TOKENIZER_FINGERPRINT,
        QWEN_CHAT_TEMPLATE_FINGERPRINT,
    )
    if len(condition.model_provenance) != 1:
        errors.append("Qwen replay requires exactly one model provenance record")
    else:
        provenance = condition.model_provenance[0]
        observed_provenance = (
            provenance.model_id,
            provenance.model_revision,
            provenance.source_model_revision,
            provenance.checkpoint_fingerprint,
            provenance.tokenizer_fingerprint,
            provenance.chat_template_fingerprint,
        )
        if observed_provenance != expected_provenance:
            errors.append("Qwen provenance does not match frozen file attestations")

    adapter = QwenMLXAdapter(generator=lambda _: "{}")
    prompt_fingerprints: set[str] = set()
    for row in condition.episodes:
        fixture = fixtures.get(row.episode_id)
        if not isinstance(fixture, Phase03A1ModelFixture):
            errors.append(f"{row.episode_id}: Qwen fixture is missing")
            continue
        view = CaseCoordinator().project_fast_view(fixture.snapshot)
        prompt = adapter.build_prompt(view)
        prompt_fingerprints.add(prompt.fingerprint)
        if row.input_fingerprint != prompt.fingerprint:
            errors.append(f"{row.episode_id}: Qwen prompt fingerprint mismatch")
        route = DeterministicRouter().route(
            RouteRequest(snapshot=fixture.snapshot, created_at=PROBE_NOW)
        )
        if row.route_outcomes != (route.outcome.value,):
            errors.append(f"{row.episode_id}: Qwen route replay mismatch")
        raw = row.raw_output_excerpt
        if raw is None:
            errors.append(f"{row.episode_id}: Qwen semantic output is missing")
            continue
        if row.schema_valid:
            try:
                semantic = FastModelOutput.model_validate_json(raw)
                decision = compile_fast_output(view, semantic)
            except Exception as error:
                errors.append(
                    f"{row.episode_id}: recorded Qwen output does not recompile: "
                    f"{type(error).__name__}"
                )
                continue
            if row.output_fingerprint != _fingerprint(decision.model_dump(mode="json")):
                errors.append(f"{row.episode_id}: Qwen output fingerprint mismatch")
            replay_false_completion = semantic.completion_claim.status != "not_done"
            if row.false_completion != replay_false_completion:
                errors.append(f"{row.episode_id}: Qwen completion replay mismatch")
            if not row.fast_action_intent_null or semantic.action_intent is not None:
                errors.append(f"{row.episode_id}: Qwen action_intent replay mismatch")
        elif row.output_fingerprint != _fingerprint(raw):
            errors.append(f"{row.episode_id}: invalid Qwen output fingerprint mismatch")

    recorded_prompts = {item.prompt_fingerprint for item in condition.prompt_provenance}
    if recorded_prompts != prompt_fingerprints:
        errors.append("Qwen prompt provenance set does not match replayed prompts")
    return errors


def _replay_frontier(
    report: BaselineReport,
    fixtures: Mapping[str, object],
) -> list[str]:
    from scripts.run_phase_03a1_harness import Phase03A1ModelFixture

    errors: list[str] = []
    response_ids: set[str] = set()
    qwen_prompt_builder = QwenMLXAdapter(generator=lambda _: "{}")
    for condition in report.conditions[3:]:
        if condition.run_status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            continue
        hosted_call_count = 0
        qwen_call_count = 0
        unknown_cost_failure_count = 0
        prompt_fingerprints: set[str] = set()
        for row_index, row in enumerate(condition.episodes):
            fixture = fixtures.get(row.episode_id)
            if not isinstance(fixture, Phase03A1ModelFixture):
                errors.append(f"{row.episode_id}: frontier fixture is missing")
                continue
            hosted_call_count += len(row.hosted_calls)
            for call in row.hosted_calls:
                prompt_fingerprints.add(call.prompt_fingerprint)
                unknown_cost_failure = call.actual_cost_microusd is None and (
                    call.status
                    in {
                        FrontierCallStatus.FAILED_PROVIDER_CALL.value,
                        FrontierCallStatus.FAILED_INVALID_RESPONSE.value,
                    }
                )
                if unknown_cost_failure:
                    unknown_cost_failure_count += 1
                    if (
                        call.status == FrontierCallStatus.FAILED_PROVIDER_CALL.value
                        and any(
                            value is not None
                            for value in (
                                call.response_model,
                                call.response_model_version,
                                call.response_id,
                            )
                        )
                    ):
                        errors.append(
                            f"{row.episode_id}: failed provider response metadata "
                            "must be absent"
                        )
                    if call.input_tokens != 0 or call.output_tokens != 0:
                        errors.append(
                            f"{row.episode_id}: failed provider usage must be zero"
                        )
                    continue
                if call.response_id is None or call.response_id in response_ids:
                    errors.append(
                        f"{row.episode_id}: hosted response id is missing/duplicate"
                    )
                else:
                    response_ids.add(call.response_id)
                if call.response_model is None or not (
                    call.response_model == FRONTIER_MODEL
                    or call.response_model.startswith(f"{FRONTIER_MODEL}-")
                ):
                    errors.append(f"{row.episode_id}: hosted response model drift")
                if call.input_tokens is None or call.output_tokens is None:
                    errors.append(f"{row.episode_id}: hosted usage is incomplete")
                else:
                    expected_cost = call.input_tokens * 4 + call.output_tokens * 20
                    if call.actual_cost_microusd != expected_cost:
                        errors.append(f"{row.episode_id}: hosted cost replay mismatch")

            initial = _without_strategy(fixture.snapshot)
            coordinator = CaseCoordinator()
            slow_route = DeterministicRouter().route(
                RouteRequest(snapshot=initial, created_at=PROBE_NOW)
            )
            request = coordinator.build_slow_request(
                initial,
                reason_code=slow_route.reason_codes[0],
                created_at=PROBE_NOW,
            )
            slow_prompt = build_legacy_slow_prompt(request)
            if not row.hosted_calls or (
                row.hosted_calls[0].prompt_fingerprint != slow_prompt.prompt_fingerprint
            ):
                errors.append(f"{row.episode_id}: frontier Slow prompt mismatch")
            elif (
                row.hosted_calls[0].schema_fingerprint != slow_prompt.schema_fingerprint
            ):
                errors.append(f"{row.episode_id}: frontier Slow schema mismatch")

            failed_calls = tuple(
                call
                for call in row.hosted_calls
                if call.actual_cost_microusd is None
                and call.status
                in {
                    FrontierCallStatus.FAILED_PROVIDER_CALL.value,
                    FrontierCallStatus.FAILED_INVALID_RESPONSE.value,
                }
            )
            if failed_calls:
                if condition.run_status is not RunStatus.FAILED:
                    errors.append(
                        f"{row.episode_id}: provider failure requires failed condition"
                    )
                if row_index != len(condition.episodes) - 1:
                    errors.append(
                        f"{row.episode_id}: provider failure must be the final attempt"
                    )
                if (
                    len(failed_calls) != 1
                    or "actual_cost_unknown" not in row.failure_codes
                ):
                    errors.append(
                        f"{row.episode_id}: provider failure evidence is incomplete"
                    )
                if row.actual_cost_microusd != sum(
                    call.actual_cost_microusd or 0 for call in row.hosted_calls
                ):
                    errors.append(
                        f"{row.episode_id}: attempted-call cost evidence mismatch"
                    )

            failed_at_slow = bool(row.hosted_calls) and (
                row.hosted_calls[0].actual_cost_microusd is None
                and row.hosted_calls[0].status
                in {
                    FrontierCallStatus.FAILED_PROVIDER_CALL.value,
                    FrontierCallStatus.FAILED_INVALID_RESPONSE.value,
                }
            )
            if failed_at_slow:
                if len(row.hosted_calls) != 1:
                    errors.append(
                        f"{row.episode_id}: calls continued after failed Slow attempt"
                    )
                expected_input = _fingerprint(
                    {"slow": slow_prompt.prompt_fingerprint, "fast": None}
                )
                if row.input_fingerprint != expected_input:
                    errors.append(
                        f"{row.episode_id}: failed Slow prompt fingerprint mismatch"
                    )
                if (
                    row.raw_output_excerpt is not None
                    or row.output_fingerprint is not None
                ):
                    errors.append(
                        f"{row.episode_id}: failed Slow attempt cannot claim output"
                    )
                continue
            raw = row.raw_output_excerpt
            if raw is None:
                errors.append(f"{row.episode_id}: frontier semantic output is missing")
                continue
            try:
                combined = json.loads(raw)
            except json.JSONDecodeError:
                errors.append(f"{row.episode_id}: frontier output envelope is invalid")
                continue
            if not isinstance(combined, dict):
                errors.append(
                    f"{row.episode_id}: frontier output envelope is not an object"
                )
                continue
            slow_raw = combined.get("slow")
            fast_raw = combined.get("fast")
            if not isinstance(slow_raw, str):
                errors.append(
                    f"{row.episode_id}: frontier Slow semantic output missing"
                )
                continue
            if row.output_fingerprint != _fingerprint(
                {"slow": slow_raw, "fast": fast_raw}
            ):
                errors.append(f"{row.episode_id}: frontier output fingerprint mismatch")
            try:
                slow_semantic = LegacySlowModelOutput.model_validate_json(slow_raw)
                slow_result = compile_legacy_slow_output(request, slow_semantic)
                planned = _with_strategy(initial, slow_result)
            except Exception as error:
                if row.schema_valid:
                    errors.append(
                        f"{row.episode_id}: recorded Slow output does not recompile: "
                        f"{type(error).__name__}"
                    )
                continue
            view = coordinator.project_fast_view(planned)
            if condition.condition is BaselineCondition.FRONTIER_REFERENCE:
                fast_prompt = build_fast_prompt(view)
                fast_prompt_fingerprint = fast_prompt.prompt_fingerprint
                if len(row.hosted_calls) != 2 or (
                    row.hosted_calls[1].prompt_fingerprint != fast_prompt_fingerprint
                ):
                    errors.append(f"{row.episode_id}: frontier Fast prompt mismatch")
                elif (
                    row.hosted_calls[1].schema_fingerprint
                    != fast_prompt.schema_fingerprint
                ):
                    errors.append(f"{row.episode_id}: frontier Fast schema mismatch")
            else:
                fast_prompt_fingerprint = qwen_prompt_builder.build_prompt(
                    view
                ).fingerprint
                prompt_fingerprints.add(fast_prompt_fingerprint)
                qwen_call_count += 1
            if isinstance(fast_raw, str):
                try:
                    fast_semantic = FastModelOutput.model_validate_json(fast_raw)
                    compile_fast_output(view, fast_semantic)
                except Exception as error:
                    if row.schema_valid:
                        errors.append(
                            f"{row.episode_id}: recorded Fast output does not "
                            "recompile: "
                            f"{type(error).__name__}"
                        )
            expected_input = _fingerprint(
                {
                    "slow": slow_prompt.prompt_fingerprint,
                    "fast": fast_prompt_fingerprint,
                }
            )
            if row.input_fingerprint != expected_input:
                errors.append(f"{row.episode_id}: combined prompt fingerprint mismatch")

        if condition.model_call_count != hosted_call_count + qwen_call_count:
            errors.append(f"{condition.condition}: model-call evidence count mismatch")
        if condition.run_status is RunStatus.FAILED:
            if unknown_cost_failure_count != 1:
                errors.append(
                    f"{condition.condition}: failed condition requires exactly one "
                    "unknown-cost attempt failure"
                )
            if condition.cost_accounting_complete:
                errors.append(
                    f"{condition.condition}: failed provider cost cannot be complete"
                )
        elif unknown_cost_failure_count:
            errors.append(
                f"{condition.condition}: successful condition contains provider failure"
            )
        recorded_prompts = {
            item.prompt_fingerprint for item in condition.prompt_provenance
        }
        if recorded_prompts != prompt_fingerprints:
            errors.append(f"{condition.condition}: prompt provenance replay mismatch")
    return errors


__all__ = ["replay_report"]
