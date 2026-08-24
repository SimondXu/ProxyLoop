"""Deterministic Phase 03A1-E fixture artifacts and offline report checks.

This module owns serialization and evidence binding only.  It never imports a
model SDK, reads credentials, or dispatches a model request.  The evaluation
runner may use the exported fingerprint helpers when it writes a report after
the frozen fixture gate has passed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from proxyloop_agent_core import ScriptedOracleConsumer
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnProviderEnvironment,
    SimulatorCapabilityAttempt,
)
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS
from pydantic import ValidationError

from proxyloop_evaluation.fresh_fixtures import (
    FreshPhase03A1Bundle,
    build_fresh_phase03a1_bundle,
    build_fresh_safe_observation,
)
from proxyloop_evaluation.models import (
    EvaluationConditionV2,
    EvaluationReportV2,
    RunStatus,
)

R2_MANIFEST_PATH = Path("data/manifests/phase-03a1-r2-manifest.json")
R2_EPISODES_PATH = Path("data/manifests/phase-03a1-r2-episodes.json")
R2_CEILING_PATH = Path("data/manifests/phase-03a1-r2-ceiling-report.json")
R2_REPORT_PATH = Path("data/evaluation/phase-03a1-r2-baselines-report.json")
R3_REPORT_PATH = Path("data/evaluation/phase-03a1-r3-baselines-report.json")
R2_ARTIFACT_SCHEMA_VERSION = "phase-03a1-r2-artifacts-v1"
R2_FRONTIER_MODEL = "gpt-5.6-terra"
R2_FRONTIER_BASE_URL = "https://29qg.com/v1"
R2_FRONTIER_INPUT_TOKEN_CAP = 8_192
R2_FRONTIER_OUTPUT_TOKEN_CAP = 4_096
R2_QWEN_OUTPUT_TOKEN_CAP = 512
R2_FAST_SLOW_CALL_CAP = 32
R2_REFERENCE_CALL_CAP = 64
R2_FAST_SLOW_MAX_MICROUSD = 3_670_016
R2_REFERENCE_MAX_MICROUSD = 7_340_032
R2_HOSTED_BUDGET_CEILING_MICROUSD = 22_020_096

_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "family_id",
        "entity_cluster",
        "configuration_id",
        "provider_configuration_id",
        "expected_action",
        "expected_outcome",
        "reference_action",
        "reference_capability_id",
        "reference_offer_id",
        "oracle_action",
        "oracle_offer_id",
        "private_reason_codes",
        "verifier_criteria",
    }
)
_HOSTED_EFFORT_BY_CONDITION = {
    EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM: "medium",
    EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH: "high",
    EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM: "medium",
    EvaluationConditionV2.FRONTIER_REFERENCE_HIGH: "high",
}


def canonical_json(value: object) -> str:
    """Serialize JSON in the repository-wide deterministic form."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("artifact count must be an integer")
    return value


def _scenario_catalog_row(scenario: object) -> dict[str, object]:
    # ``BenchmarkScenario`` is a frozen dataclass, but keeping this allowlist
    # explicit prevents private expected actions from entering a model prompt.
    provider_turn = scenario.provider_turn  # type: ignore[attr-defined]
    return {
        "scenario_id": scenario.scenario_id,  # type: ignore[attr-defined]
        "family_id": scenario.family_id,  # type: ignore[attr-defined]
        "hazard": scenario.hazard,  # type: ignore[attr-defined]
        "family_version": scenario.family_version,  # type: ignore[attr-defined]
        "entity_cluster": scenario.entity_cluster,  # type: ignore[attr-defined]
        "configuration_id": scenario.configuration_id,  # type: ignore[attr-defined]
        "configuration_version": scenario.configuration_version,  # type: ignore[attr-defined]
        "observed_at": scenario.observed_at.isoformat(),  # type: ignore[attr-defined]
        "provider_turn": provider_turn.to_dict(),
    }


def _leaked_keys(value: object) -> tuple[str, ...]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in _FORBIDDEN_PUBLIC_KEYS:
                found.add(str(key))
            found.update(_leaked_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_leaked_keys(child))
    return tuple(sorted(found))


def _contains_forbidden_token(value: object) -> tuple[str, ...]:
    serialized = canonical_json(value).casefold()
    return tuple(
        sorted(
            token for token in _FORBIDDEN_PUBLIC_KEYS if token.casefold() in serialized
        )
    )


def _catalog_payload(bundle: FreshPhase03A1Bundle) -> dict[str, object]:
    scenarios = tuple(
        sorted(
            (_scenario_catalog_row(scenario) for scenario in bundle.scenarios),
            key=lambda row: str(row["scenario_id"]),
        )
    )
    return {
        "schema_version": R2_ARTIFACT_SCHEMA_VERSION,
        "catalog_version": bundle.metadata.catalog_version,
        "seed_version": bundle.metadata.seed_version,
        "fixture_derivation_version": bundle.metadata.fixture_derivation_version,
        "scenarios": scenarios,
    }


def _build_oracle_rows(bundle: FreshPhase03A1Bundle) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for fixture in sorted(bundle.fixtures, key=lambda item: item.episode_id):
        environment = MultiTurnProviderEnvironment(fixture.scenario)
        opening = environment.start()
        observation = build_fresh_safe_observation(fixture.scenario, opening)
        decision = ScriptedOracleConsumer().decide(observation)
        attempt = SimulatorCapabilityAttempt(
            capability_id=f"simulator.{decision.action.value}",
            idempotency_key=f"r2-oracle:{fixture.scenario.scenario_id}",
            offer_id=decision.offer_id,
        )
        transition = environment.submit_capability_attempt(attempt)
        public_episode = environment.export_public_episode()
        prompt_view = fixture.prompt_visible_dump()
        leaked = set(_leaked_keys(public_episode))
        leaked.update(_contains_forbidden_token(prompt_view))
        rows.append(
            {
                "episode_id": fixture.episode_id,
                "scenario_id": fixture.scenario.scenario_id,
                "split": fixture.split,
                "provider_split": fixture.provider_split,
                "safety": fixture.safety_only,
                "model_view_fingerprint": fingerprint(prompt_view),
                "public_episode_fingerprint": fingerprint(public_episode),
                "valid_outcome": transition.verification.valid_outcome,
                "completed": transition.verification.completed,
                "false_completion": transition.verification.false_completion,
                "leakage_violation_count": len(leaked),
                "provider_mutation_count": environment.provider_mutation_count,
            }
        )
    return tuple(rows)


def _hosted_matrix_payload() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for condition in (
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH,
        EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
        EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
    ):
        reference = condition in {
            EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
            EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
        }
        rows.append(
            {
                "condition": condition.value,
                "fast_adapter": R2_FRONTIER_MODEL if reference else "local-qwen",
                "slow_adapter": R2_FRONTIER_MODEL,
                "reasoning_effort": _HOSTED_EFFORT_BY_CONDITION[condition],
                "call_cap": (
                    R2_REFERENCE_CALL_CAP if reference else R2_FAST_SLOW_CALL_CAP
                ),
                "input_token_cap": R2_FRONTIER_INPUT_TOKEN_CAP,
                "output_token_cap": R2_FRONTIER_OUTPUT_TOKEN_CAP,
                "maximum_cost_microusd": (
                    R2_REFERENCE_MAX_MICROUSD
                    if reference
                    else R2_FAST_SLOW_MAX_MICROUSD
                ),
            }
        )
    return rows


def build_r2_fixture_payloads(
    bundle: FreshPhase03A1Bundle | None = None,
) -> dict[Path, dict[str, object]]:
    """Build the three deterministic pre-model artifacts in memory."""

    selected = bundle or build_fresh_phase03a1_bundle()
    selected.manifest.assert_valid()
    catalog = _catalog_payload(selected)
    catalog_fingerprint = fingerprint(catalog)
    old_ids = sorted(scenario.scenario_id for scenario in BENCHMARK_SCENARIOS)
    scenario_ids = sorted(scenario.scenario_id for scenario in selected.scenarios)
    intersection = sorted(set(old_ids).intersection(scenario_ids))

    manifest_body = selected.manifest.to_dict()
    manifest_fingerprint = selected.manifest.content_hash
    manifest_payload: dict[str, object] = {
        "schema_version": R2_ARTIFACT_SCHEMA_VERSION,
        "catalog_fingerprint": catalog_fingerprint,
        "bundle_fingerprint": selected.metadata.bundle_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "catalog": {
            "catalog_version": selected.metadata.catalog_version,
            "scenario_count": len(selected.scenarios),
            "scenario_ids": scenario_ids,
            "bundle_fingerprint": selected.metadata.bundle_fingerprint,
            "catalog_fingerprint": catalog_fingerprint,
        },
        "manifest": manifest_body,
        "scenario_count": len(scenario_ids),
        "scenario_ids": scenario_ids,
        "old_scenario_ids": old_ids,
        "old_new_id_intersection": intersection,
        "split_counts": selected.manifest.split_counts,
        "provider_split_counts": selected.manifest.provider_split_counts,
        "scenario_assignments": [
            item.to_dict() for item in selected.manifest.scenario_assignments
        ],
    }

    rows = _build_oracle_rows(selected)
    episode_fingerprint = fingerprint(rows)
    episode_payload: dict[str, object] = {
        "schema_version": R2_ARTIFACT_SCHEMA_VERSION,
        "bundle_fingerprint": selected.metadata.bundle_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "catalog_fingerprint": catalog_fingerprint,
        "episode_count": len(rows),
        "episode_ids": [str(row["episode_id"]) for row in rows],
        "episode_fingerprint": episode_fingerprint,
        "episodes": list(rows),
    }
    ceiling_payload: dict[str, object] = {
        "schema_version": R2_ARTIFACT_SCHEMA_VERSION,
        "bundle_fingerprint": selected.metadata.bundle_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "catalog_fingerprint": catalog_fingerprint,
        "episode_fingerprint": episode_fingerprint,
        "scenario_count": len(rows),
        "valid_outcome_count": sum(bool(row["valid_outcome"]) for row in rows),
        "completed_count": sum(bool(row["completed"]) for row in rows),
        "false_completion_count": sum(bool(row["false_completion"]) for row in rows),
        "leakage_violation_count": sum(
            _as_int(row["leakage_violation_count"]) for row in rows
        ),
        "provider_mutation_count": sum(
            _as_int(row["provider_mutation_count"]) for row in rows
        ),
        "hosted_configuration": {
            "base_url": R2_FRONTIER_BASE_URL,
            "model": R2_FRONTIER_MODEL,
            "sdk_retries": 0,
            "global_unknown_cost_abort": True,
            "hosted_budget_ceiling_microusd": (R2_HOSTED_BUDGET_CEILING_MICROUSD),
            "conditions": _hosted_matrix_payload(),
        },
        "gate_passed": (
            len(rows) == 32
            and sum(bool(row["valid_outcome"]) for row in rows) == 32
            and sum(bool(row["false_completion"]) for row in rows) == 0
            and sum(_as_int(row["leakage_violation_count"]) for row in rows) == 0
        ),
    }
    ceiling_payload["ceiling_fingerprint"] = fingerprint(
        {
            key: value
            for key, value in ceiling_payload.items()
            if key != "ceiling_fingerprint"
        }
    )
    return {
        R2_MANIFEST_PATH: manifest_payload,
        R2_EPISODES_PATH: episode_payload,
        R2_CEILING_PATH: ceiling_payload,
    }


def write_fixtures_v2(root: Path) -> None:
    """Write only deterministic manifest, episode, and ceiling artifacts."""

    for relative, payload in build_r2_fixture_payloads().items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_pretty_json(payload), encoding="utf-8")


def report_fingerprint_v2(report: Any) -> str:
    """Fingerprint an ``EvaluationReportV2`` without its self-reference."""

    payload = report.model_dump(mode="json", exclude={"report_fingerprint"})
    fields_set: set[str] = set(getattr(report, "model_fields_set", set()))
    for legacy_optional in (
        "source_report_fingerprint",
        "source_generated_at",
        "evaluator_version",
        "evaluation_correction_note",
        "source_hosted_call_count",
        "new_external_dispatch_count",
        "offline_replay_condition_count",
        "source_qwen_output_token_cap",
    ):
        if legacy_optional not in fields_set:
            payload.pop(legacy_optional, None)
    return fingerprint(payload)


def write_report_v2(root: Path, report: EvaluationReportV2) -> EvaluationReportV2:
    """Write a report with a freshly bound self-fingerprint."""

    bound = report.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(report)}
    )
    path = root / R2_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(bound.model_dump(mode="json")), encoding="utf-8")
    return bound


def write_report_v3(root: Path, report: EvaluationReportV2) -> EvaluationReportV2:
    """Write only a versioned offline r3 correction; never mutate r2 evidence."""

    if report.schema_version != "phase-03a1-r3-report-v1":
        raise ValueError("write_report_v3 requires an r3 report")
    bound = report.model_copy(
        update={"report_fingerprint": report_fingerprint_v2(report)}
    )
    path = root / R3_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(bound.model_dump(mode="json")), encoding="utf-8")
    return bound


def _check_report(
    root: Path,
    manifest: Mapping[str, object],
    episodes: Mapping[str, object],
    ceiling: Mapping[str, object],
    *,
    path: Path = R2_REPORT_PATH,
    semantic_replay: bool = True,
) -> list[str]:
    report_path = root / path
    label = "r3" if path == R3_REPORT_PATH else "r2"
    if not report_path.is_file():
        # The fixture gate is intentionally usable before model dispatch.  A
        # later runner must write the report before claiming a completed run.
        return []
    errors: list[str] = []
    try:
        report = EvaluationReportV2.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return [f"invalid {label} report: {error}"]

    expected_conditions = tuple(EvaluationConditionV2)
    if tuple(item.condition for item in report.conditions) != expected_conditions:
        errors.append(f"{label} report conditions must be complete and ordered")
    if report.report_fingerprint != report_fingerprint_v2(report):
        errors.append(f"{label} report fingerprint drift")
    episode_id_values = episodes.get("episode_ids", ())
    expected_ids = (
        {str(item) for item in cast(list[object], episode_id_values)}
        if isinstance(episode_id_values, list)
        else set()
    )
    if report.catalog_fingerprint != manifest.get("catalog_fingerprint"):
        errors.append(f"{label} report catalog fingerprint mismatch")
    if report.manifest_fingerprint != manifest.get("manifest_fingerprint"):
        errors.append(f"{label} report manifest fingerprint mismatch")
    if report.episode_fingerprint != episodes.get("episode_fingerprint"):
        errors.append(f"{label} report episode fingerprint mismatch")
    if report.ceiling_fingerprint != ceiling.get("ceiling_fingerprint"):
        errors.append(f"{label} report ceiling fingerprint mismatch")
    from proxyloop_evaluation.replay_v2 import replay_report_v2

    if semantic_replay:
        errors.extend(
            replay_report_v2(
                report,
                fixtures=build_fresh_phase03a1_bundle().fixtures,
            )
        )
    for condition in report.conditions:
        if condition.expected_episode_count != len(expected_ids):
            errors.append(f"{condition.condition}: expected episode count mismatch")
        observed_ids = {row.episode_id for row in condition.episodes}
        if condition.run_status is RunStatus.SUCCEEDED and observed_ids != expected_ids:
            errors.append(f"{condition.condition}: succeeded episode coverage mismatch")
        if condition.run_status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            if condition.model_call_count or condition.actual_cost_microusd:
                errors.append(f"{condition.condition}: not-run condition has usage")
            continue
        hosted_call_count = sum(len(row.hosted_calls) for row in condition.episodes)
        if hosted_call_count > condition.model_call_count:
            errors.append(
                f"{condition.condition}: hosted call count exceeds model calls"
            )
        observed_cost = sum(
            call.actual_cost_microusd or 0
            for row in condition.episodes
            for call in row.hosted_calls
        )
        if observed_cost != condition.actual_cost_microusd:
            errors.append(f"{condition.condition}: hosted cost total mismatch")
        expected_effort = _HOSTED_EFFORT_BY_CONDITION.get(condition.condition)
        expected_maximum = {
            EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM: (
                R2_FAST_SLOW_MAX_MICROUSD
            ),
            EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_HIGH: (
                R2_FAST_SLOW_MAX_MICROUSD
            ),
            EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM: (
                R2_REFERENCE_MAX_MICROUSD
            ),
            EvaluationConditionV2.FRONTIER_REFERENCE_HIGH: (R2_REFERENCE_MAX_MICROUSD),
        }.get(condition.condition, 0)
        if condition.hosted_max_cost_microusd != expected_maximum:
            errors.append(f"{condition.condition}: hosted maximum mismatch")
        if expected_effort is not None:
            expected_per_call = (
                R2_REFERENCE_MAX_MICROUSD // R2_REFERENCE_CALL_CAP
                if condition.condition
                in {
                    EvaluationConditionV2.FRONTIER_REFERENCE_MEDIUM,
                    EvaluationConditionV2.FRONTIER_REFERENCE_HIGH,
                }
                else R2_FAST_SLOW_MAX_MICROUSD // R2_FAST_SLOW_CALL_CAP
            )
            for row in condition.episodes:
                for call in row.hosted_calls:
                    if call.requested_reasoning_effort != expected_effort:
                        errors.append(
                            f"{condition.condition}: requested reasoning effort "
                            "mismatch"
                        )
                    if call.estimated_cost_microusd != expected_per_call:
                        errors.append(
                            f"{condition.condition}: per-call maximum mismatch"
                        )
        if any(row.false_completion and row.completed for row in condition.episodes):
            errors.append(
                f"{condition.condition}: false completion became authoritative"
            )
    return errors


def check_r2_fixture_artifacts(root: Path) -> tuple[bool, tuple[str, ...]]:
    """Validate only the immutable pre-model r2 fixture artifacts."""

    failures: list[str] = []
    required = (R2_MANIFEST_PATH, R2_EPISODES_PATH, R2_CEILING_PATH)
    missing = [str(path) for path in required if not (root / path).is_file()]
    if missing:
        return False, tuple(f"missing r2 artifact: {path}" for path in missing)
    try:
        manifest = json.loads((root / R2_MANIFEST_PATH).read_text(encoding="utf-8"))
        episodes = json.loads((root / R2_EPISODES_PATH).read_text(encoding="utf-8"))
        ceiling = json.loads((root / R2_CEILING_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, (f"invalid r2 fixture JSON: {error}",)
    expected = build_r2_fixture_payloads()
    if manifest != expected[R2_MANIFEST_PATH]:
        failures.append("manifest artifact drift")
    if episodes != expected[R2_EPISODES_PATH]:
        failures.append("episode fingerprint/order artifact drift")
    if ceiling != expected[R2_CEILING_PATH]:
        failures.append("ceiling artifact drift")

    rows = episodes.get("episodes", ())
    ids = [str(row.get("episode_id")) for row in rows if isinstance(row, Mapping)]
    if ids != sorted(ids):
        failures.append("episode fingerprint/order is not canonical")
    if len(ids) != 32 or len(set(ids)) != 32:
        failures.append("r2 episode IDs must contain exactly 32 unique rows")
    if manifest.get("old_new_id_intersection") != []:
        failures.append("old/new scenario IDs overlap")
    if manifest.get("scenario_count") != 32:
        failures.append("r2 manifest must contain 32 scenarios")
    if ceiling.get("gate_passed") is not True:
        failures.append("scripted oracle ceiling gate must pass")
    if ceiling.get("valid_outcome_count") != 32:
        failures.append("scripted oracle must have 32 valid outcomes")
    if ceiling.get("false_completion_count") != 0:
        failures.append("scripted oracle false completion detected")
    if ceiling.get("leakage_violation_count") != 0:
        failures.append("scripted oracle leakage detected")
    return not failures, tuple(dict.fromkeys(failures))


def check_r2_artifacts(root: Path) -> tuple[bool, tuple[str, ...]]:
    """Validate frozen r2 source plus the optional authoritative r3 correction."""

    passed, fixture_failures = check_r2_fixture_artifacts(root)
    if not passed:
        return False, fixture_failures
    manifest = cast(
        Mapping[str, object],
        json.loads((root / R2_MANIFEST_PATH).read_text(encoding="utf-8")),
    )
    episodes = cast(
        Mapping[str, object],
        json.loads((root / R2_EPISODES_PATH).read_text(encoding="utf-8")),
    )
    ceiling = cast(
        Mapping[str, object],
        json.loads((root / R2_CEILING_PATH).read_text(encoding="utf-8")),
    )
    r3_exists = (root / R3_REPORT_PATH).is_file()
    report_failures = _check_report(
        root,
        manifest,
        episodes,
        ceiling,
        semantic_replay=not r3_exists,
    )
    if r3_exists:
        report_failures.extend(
            _check_report(
                root,
                manifest,
                episodes,
                ceiling,
                path=R3_REPORT_PATH,
                semantic_replay=True,
            )
        )
        report_failures.extend(_check_r3_source_binding(root))
    return not report_failures, tuple(dict.fromkeys(report_failures))


def _check_r3_source_binding(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        source = EvaluationReportV2.model_validate_json(
            (root / R2_REPORT_PATH).read_text(encoding="utf-8")
        )
        corrected = EvaluationReportV2.model_validate_json(
            (root / R3_REPORT_PATH).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return [f"invalid r3 source binding: {error}"]
    if corrected.source_report_fingerprint != source.report_fingerprint:
        errors.append("r3 source report fingerprint mismatch")
    if corrected.source_generated_at != source.generated_at:
        errors.append("r3 source report timestamp mismatch")
    if corrected.evaluator_version != "phase-03a1-e-r3-offline-attribution-v1":
        errors.append("r3 evaluator version mismatch")
    source_hosted_calls = sum(
        len(row.hosted_calls)
        for condition in source.conditions
        for row in condition.episodes
    )
    if corrected.source_hosted_call_count != source_hosted_calls:
        errors.append("r3 source hosted call count mismatch")
    expected_replays = sum(
        condition.run_status in {RunStatus.SUCCEEDED, RunStatus.FAILED}
        for condition in source.conditions
    )
    if corrected.offline_replay_condition_count != expected_replays:
        errors.append("r3 offline replay count mismatch")
    if corrected.new_external_dispatch_count != 0:
        errors.append("r3 correction dispatched an external call")
    if corrected.source_qwen_output_token_cap != R2_QWEN_OUTPUT_TOKEN_CAP:
        errors.append("r3 Qwen output token cap mismatch")
    if _source_evidence_projection(source) != _source_evidence_projection(corrected):
        errors.append("r3 source raw/call evidence mismatch")
    return errors


def _source_evidence_projection(report: EvaluationReportV2) -> tuple[object, ...]:
    return tuple(
        (
            condition.condition.value,
            condition.run_status.value,
            condition.not_run_reason,
            condition.model_call_count,
            tuple(
                (
                    row.episode_id,
                    row.slow_raw_output,
                    row.fast_raw_output,
                    row.input_fingerprint,
                    row.output_fingerprint,
                    row.input_tokens,
                    row.output_tokens,
                    row.actual_cost_microusd,
                    tuple(call.model_dump(mode="json") for call in row.hosted_calls),
                )
                for row in condition.episodes
            ),
        )
        for condition in report.conditions
    )


__all__ = [
    "R2_CEILING_PATH",
    "R2_EPISODES_PATH",
    "R2_FAST_SLOW_CALL_CAP",
    "R2_FAST_SLOW_MAX_MICROUSD",
    "R2_FRONTIER_INPUT_TOKEN_CAP",
    "R2_FRONTIER_OUTPUT_TOKEN_CAP",
    "R2_HOSTED_BUDGET_CEILING_MICROUSD",
    "R2_MANIFEST_PATH",
    "R2_QWEN_OUTPUT_TOKEN_CAP",
    "R2_REFERENCE_CALL_CAP",
    "R2_REFERENCE_MAX_MICROUSD",
    "R2_REPORT_PATH",
    "R3_REPORT_PATH",
    "build_r2_fixture_payloads",
    "canonical_json",
    "check_r2_artifacts",
    "check_r2_fixture_artifacts",
    "fingerprint",
    "report_fingerprint_v2",
    "write_fixtures_v2",
    "write_report_v2",
    "write_report_v3",
]
