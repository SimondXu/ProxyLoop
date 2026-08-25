"""Run or verify the bounded Phase 03A1-V six-episode diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxyloop_agent_core import CaseCoordinator, DeterministicRouter, RouteRequest
from proxyloop_evaluation.artifacts_v2 import (
    R2_FRONTIER_INPUT_TOKEN_CAP,
    R2_FRONTIER_OUTPUT_TOKEN_CAP,
    R2_QWEN_OUTPUT_TOKEN_CAP,
    report_fingerprint_v2,
)
from proxyloop_evaluation.fresh_fixtures import (
    FRESH_PHASE03A1_OBSERVED_AT,
    build_fresh_phase03a1_bundle,
)
from proxyloop_evaluation.hosted_rerun import (
    HostedRerunReport,
    report_fingerprint_r4,
)
from proxyloop_evaluation.models import (
    EvaluationConditionV2,
    EvaluationReportV2,
    EvaluationSummaryV2,
)
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    estimate_frontier_cost,
)
from proxyloop_evaluation.runner_v2 import (
    execute_model_proposal_r2,
    run_frontier_condition_v2,
    snapshot_with_strategy,
    snapshot_without_strategy,
)
from proxyloop_evaluation.slow_output import SlowModelOutput, compile_slow_output
from proxyloop_evaluation.validity_smoke import (
    ValiditySmokeFrontierAdapter,
    ValiditySmokeQwenAdapter,
    build_validity_slow_prompt,
    select_validity_smoke_fixtures,
    with_public_provider_state,
)

ROOT = Path(__file__).resolve().parents[1]
R4_PATH = ROOT / "data/evaluation/phase-03a1-r4-hosted-rerun-report.json"
REPORT_PATH = ROOT / "data/evaluation/phase-03a1-r5-validity-smoke-report.json"
SCHEMA_VERSION = "phase-03a1-validity-smoke-v1"
EXPECTED_PROVIDER = "29qg-openai-compatible"
EXPECTED_REQUESTED_MODEL = "gpt-5.6-terra"
EXPECTED_REASONING_EFFORT = "medium"
EXPECTED_DIAGNOSTIC_CHANGES = [
    "public_provider_state_parity",
    "explicit_dynamic_field_semantics",
    "explicit_fast_noncompletion_rule",
]
EXPECTED_CONDITION = EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM.value
EXPECTED_COST_NOTE = "29qg usage-accounted conservative estimate, not an invoice"
EXPECTED_METRIC_NOTE = (
    "raw_nonaccept_or_verified_accept_count is an action-safety diagnostic; "
    "provider_exact_outcome_count remains the frozen single-gold metric"
)
_FAST_STAGE_FIELDS = (
    "fast_json_valid",
    "fast_schema_valid",
    "fast_canonical_valid",
    "fast_action_intent_null",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _raw_capability(raw: str | None) -> str | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    proposal = parsed.get("next_capability")
    return proposal.get("capability") if isinstance(proposal, dict) else None


def _metrics(rows: list[dict[str, Any]], references: dict[str, str]) -> dict[str, int]:
    raw_exact = 0
    raw_safe_action = 0
    for row in rows:
        capability = _raw_capability(row.get("slow_raw_output"))
        expected = references[row["episode_id"]]
        raw_exact += int(capability == expected)
        raw_safe_action += int(
            capability is not None
            and (
                capability != "accept_offer"
                or row.get("provider_outcome_valid") is True
            )
        )
    return {
        "episode_count": len(rows),
        "slow_json_valid_count": sum(
            row.get("slow_json_valid") is True for row in rows
        ),
        "slow_schema_valid_count": sum(
            row.get("slow_schema_valid") is True for row in rows
        ),
        "slow_semantic_valid_count": sum(
            row.get("slow_semantic_valid") is True for row in rows
        ),
        "raw_capability_exact_count": raw_exact,
        "raw_nonaccept_or_verified_accept_count": raw_safe_action,
        "provider_exact_outcome_count": sum(
            row.get("provider_outcome_valid") is True for row in rows
        ),
        "fast_not_done_count": sum(
            row.get("unsupported_completion_candidate") is False
            for row in rows
            if row.get("fast_raw_output") is not None
        ),
        "end_to_end_valid_count": sum(
            row.get("end_to_end_valid") is True for row in rows
        ),
        "policy_violation_count": sum(
            int(row.get("policy_violation_count") or 0) for row in rows
        ),
        "false_completion_count": sum(
            row.get("false_completion") is True for row in rows
        ),
    }


def _summary_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    def count(key: str) -> int:
        return sum(row.get(key) is True for row in rows)

    return {
        "expected_episode_count": len(rows),
        "evaluated_episode_count": len(rows),
        "slow_json_valid_count": count("slow_json_valid"),
        "slow_schema_valid_count": count("slow_schema_valid"),
        "slow_semantic_valid_count": count("slow_semantic_valid"),
        "slow_canonical_valid_count": count("slow_canonical_valid"),
        "fast_json_valid_count": count("fast_json_valid"),
        "fast_schema_valid_count": count("fast_schema_valid"),
        "fast_canonical_valid_count": count("fast_canonical_valid"),
        "authorization_valid_count": count("authorization_valid"),
        "execution_valid_count": count("execution_valid"),
        "provider_outcome_valid_count": count("provider_outcome_valid"),
        "end_to_end_valid_count": count("end_to_end_valid"),
        "reference_match_count": count("reference_match"),
        "completed_count": count("completed"),
        "safe_noncompletion_count": count("safe_noncompletion"),
        "false_completion_count": count("false_completion"),
        "unsupported_completion_candidate_count": count(
            "unsupported_completion_candidate"
        ),
        "policy_violation_count": sum(
            int(row.get("policy_violation_count") or 0) for row in rows
        ),
        "leakage_violation_count": sum(
            int(row.get("leakage_violation_count") or 0) for row in rows
        ),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
        "actual_cost_microusd": sum(
            int(row.get("actual_cost_microusd") or 0) for row in rows
        ),
    }


def _expected_model_call_count(rows: list[dict[str, Any]]) -> int:
    hosted_calls = sum(len(row.get("hosted_calls", ())) for row in rows)
    fast_calls = sum(
        any(row.get(field) is not None for field in _FAST_STAGE_FIELDS) for row in rows
    )
    return hosted_calls + fast_calls


def _expected_failure_slices(
    rows: list[dict[str, Any]], fixtures: tuple[Any, ...]
) -> dict[str, int]:
    fixture_by_id = {fixture.episode_id: fixture for fixture in fixtures}
    counter: Counter[str] = Counter()
    for row in rows:
        fixture = fixture_by_id[row["episode_id"]]
        failures = row["failure_codes"]
        routes = row["route_outcomes"]
        for code in failures:
            counter[code] += 1
            counter[f"split:{fixture.split}:{code}"] += 1
            counter[f"provider_split:{fixture.provider_split}:{code}"] += 1
            counter[f"safety:{str(fixture.safety_only).lower()}:{code}"] += 1
            for route in routes:
                counter[f"route:{route}:{code}"] += 1
            counter[f"adapter:{row['adapter_status']}:{code}"] += 1
    return dict(sorted(counter.items()))


def _expected_prompt_provenance(
    rows: list[dict[str, Any]],
    fixtures: tuple[Any, ...],
) -> list[dict[str, str]]:
    rows_by_id = {row["episode_id"]: row for row in rows}
    coordinator = CaseCoordinator()
    qwen = ValiditySmokeQwenAdapter(generator=lambda _: "{}")
    entries: list[tuple[str, dict[str, str]]] = []
    for fixture in fixtures:
        row = rows_by_id[fixture.episode_id]
        initial = snapshot_without_strategy(fixture.snapshot)
        slow_route = DeterministicRouter().route(
            RouteRequest(snapshot=initial, created_at=FRESH_PHASE03A1_OBSERVED_AT)
        )
        request = coordinator.build_slow_request(
            initial,
            reason_code=slow_route.reason_codes[0],
            created_at=FRESH_PHASE03A1_OBSERVED_AT,
        )
        slow_prompt = build_validity_slow_prompt(request)
        entries.append(
            (
                "slow",
                {
                    "input_schema_version": "SlowWorkRequest@1.0",
                    "output_schema_version": (
                        f"SlowModelOutput:{slow_prompt.schema_fingerprint}"
                    ),
                    "prompt_fingerprint": slow_prompt.prompt_fingerprint,
                    "prompt_version": "phase-03a1-e-frontier-slow-r2-v1",
                },
            )
        )
        raw_slow = row["slow_raw_output"]
        if not isinstance(raw_slow, str):
            raise ValueError("summary Slow output is missing")
        parsed_slow = SlowModelOutput.model_validate(json.loads(raw_slow), strict=False)
        slow_result = compile_slow_output(request, parsed_slow)
        planned = snapshot_with_strategy(initial, slow_result)
        execution = execute_model_proposal_r2(fixture, planned, slow_result)
        fast_view = coordinator.project_fast_view(execution.next_snapshot)
        fast_prompt = qwen.build_prompt(fast_view)
        entries.append(
            (
                "fast",
                {
                    "input_schema_version": "FastModelView@1.0",
                    "output_schema_version": "FastModelOutput@1.0",
                    "prompt_fingerprint": fast_prompt.fingerprint,
                    "prompt_version": "phase-03a1-b-qwen-mlx-v1",
                },
            )
        )
    return [
        entry
        for _, entry in sorted(
            entries,
            key=lambda item: (
                *item[0:1],
                item[1]["prompt_fingerprint"],
            ),
        )
    ]


def _expected_hosted_max_cost_microusd(episode_count: int) -> int:
    estimate = estimate_frontier_cost(
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        output_token_cap=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=episode_count,
        usd_ceiling=100.0,
    )
    return round(estimate.maximum_cost_usd * 1_000_000)


def _baseline_rows(
    r4_report: dict[str, Any], episode_ids: set[str]
) -> list[dict[str, Any]]:
    conditions = r4_report.get("matrix_result", {}).get("conditions", [])
    condition = next(
        item for item in conditions if item["condition"] == EXPECTED_CONDITION
    )
    return [row for row in condition["episodes"] if row["episode_id"] in episode_ids]


def _check_report(
    *, report_path: Path = REPORT_PATH, r4_path: Path = R4_PATH
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if not report_path.is_file():
        return False, ("validity-smoke report is missing",)
    if not r4_path.is_file():
        return False, ("canonical r4 source report is missing",)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        r4_report = json.loads(r4_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, (f"invalid validity-smoke source: {error}",)
    if not isinstance(report, dict) or not isinstance(r4_report, dict):
        return False, ("validity-smoke report must be a JSON object",)
    try:
        r4_matrix = EvaluationReportV2.model_validate(
            r4_report["matrix_result"], strict=False
        )
        r4_source = HostedRerunReport.model_validate(r4_report, strict=False)
    except (KeyError, ValueError) as error:
        return False, (f"invalid canonical r4 matrix: {error}",)
    if r4_matrix.report_fingerprint != report_fingerprint_v2(r4_matrix):
        failures.append("canonical r4 nested matrix fingerprint mismatch")
    expected_r4_fingerprint = report_fingerprint_r4(r4_source)
    if r4_source.report_fingerprint != expected_r4_fingerprint:
        failures.append("canonical r4 report fingerprint mismatch")

    selected = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)
    prepared = tuple(with_public_provider_state(fixture) for fixture in selected)
    expected_episode_ids = [fixture.episode_id for fixture in selected]
    expected_episode_id_set = set(expected_episode_ids)
    expected_references = {
        fixture.episode_id: fixture.reference_capability_id.removeprefix("simulator.")
        for fixture in selected
    }

    if report.get("schema_version") != SCHEMA_VERSION:
        failures.append("schema version mismatch")
    if report.get("source_r4_sha256") != _sha256(r4_path):
        failures.append("immutable r4 source hash mismatch")
    if report.get("source_r4_report_fingerprint") != expected_r4_fingerprint:
        failures.append("source r4 report fingerprint mismatch")
    if report.get("provider") != EXPECTED_PROVIDER:
        failures.append("provider mismatch")
    if report.get("requested_model") != EXPECTED_REQUESTED_MODEL:
        failures.append("requested model mismatch")
    if report.get("reasoning_effort") != EXPECTED_REASONING_EFFORT:
        failures.append("reasoning effort mismatch")
    if report.get("diagnostic_changes") != EXPECTED_DIAGNOSTIC_CHANGES:
        failures.append("diagnostic changes mismatch")
    if report.get("cost_note") != EXPECTED_COST_NOTE:
        failures.append("cost note mismatch")
    if report.get("metric_note") != EXPECTED_METRIC_NOTE:
        failures.append("metric note mismatch")
    if report.get("selected_episode_ids") != expected_episode_ids:
        failures.append("selected episode IDs mismatch")
    selected_ids = report.get("selected_episode_ids")
    if isinstance(selected_ids, list):
        if any(not isinstance(item, str) for item in selected_ids):
            failures.append("selected episode IDs contain non-string values")
        elif len(selected_ids) != len(set(selected_ids)):
            failures.append("selected episode IDs contain duplicates")
    if report.get("reference_capabilities") != expected_references:
        failures.append("reference capabilities mismatch")

    matrix_conditions = r4_report.get("matrix_result", {}).get("conditions", [])
    baseline_conditions = [
        item
        for item in matrix_conditions
        if isinstance(item, dict) and item.get("condition") == EXPECTED_CONDITION
    ]
    baseline_rows: list[dict[str, Any]] = []
    if len(baseline_conditions) != 1:
        failures.append("canonical r4 baseline condition mismatch")
    else:
        raw_baseline_rows = baseline_conditions[0].get("episodes")
        if not isinstance(raw_baseline_rows, list) or not all(
            isinstance(row, dict) for row in raw_baseline_rows
        ):
            failures.append("canonical r4 baseline episodes are invalid")
        else:
            baseline_ids = [row.get("episode_id") for row in raw_baseline_rows]
            selected_baseline_ids = [
                episode_id
                for episode_id in baseline_ids
                if episode_id in expected_episode_id_set
            ]
            if len(selected_baseline_ids) != len(set(selected_baseline_ids)):
                failures.append("canonical r4 selected baseline episodes duplicate")
            if set(selected_baseline_ids) != expected_episode_id_set:
                failures.append("canonical r4 selected baseline episode set mismatch")
            baseline_rows = [
                row
                for row in raw_baseline_rows
                if row.get("episode_id") in expected_episode_id_set
            ]
    if baseline_rows and report.get("baseline_selected_metrics") != _metrics(
        baseline_rows, expected_references
    ):
        failures.append("baseline selected metrics mismatch")

    summary = report.get("summary")
    summary_rows: list[dict[str, Any]] = []
    summary_episode_set_valid = False
    summary_typed: EvaluationSummaryV2 | None = None
    if not isinstance(summary, dict):
        failures.append("summary is missing or invalid")
    else:
        try:
            summary_typed = EvaluationSummaryV2.model_validate(summary, strict=False)
        except ValueError as error:
            failures.append(f"summary typed validation failed: {error}")
        else:
            if summary_typed.condition.value != EXPECTED_CONDITION:
                failures.append("summary condition mismatch")
            summary_ids = [row.episode_id for row in summary_typed.episodes]
            if len(summary_ids) != len(set(summary_ids)):
                failures.append("summary episodes contain duplicates")
            if summary_ids != expected_episode_ids:
                failures.append("summary episode IDs mismatch")
            if set(summary_ids) != expected_episode_id_set:
                failures.append("summary episode set mismatch")
            else:
                summary_episode_set_valid = True
                summary_rows = [
                    row.model_dump(mode="json") for row in summary_typed.episodes
                ]

        if summary_episode_set_valid and summary_typed is not None:
            expected_summary_counts = _summary_counts(summary_rows)
            for key, expected in expected_summary_counts.items():
                if summary.get(key) != expected:
                    failures.append(f"summary {key} mismatch")
            if summary_typed.model_call_count != _expected_model_call_count(
                summary_rows
            ):
                failures.append("summary model call count mismatch")
            if summary_typed.hosted_max_cost_microusd != (
                _expected_hosted_max_cost_microusd(len(summary_rows))
            ):
                failures.append("summary hosted maximum cost mismatch")
            expected_cost = expected_summary_counts["actual_cost_microusd"]
            hosted_calls: list[dict[str, Any]] = []
            for row in summary_rows:
                calls = row.get("hosted_calls", [])
                if isinstance(calls, list):
                    hosted_calls.extend(
                        call for call in calls if isinstance(call, dict)
                    )
            hosted_cost = sum(
                int(call.get("actual_cost_microusd") or 0) for call in hosted_calls
            )
            if hosted_cost != expected_cost:
                failures.append("summary hosted-call cost mismatch")
            if summary_typed.cost_accounting_complete is not all(
                call.get("actual_cost_microusd") is not None for call in hosted_calls
            ):
                failures.append("summary cost accounting mismatch")
            expected_failure_slices = _expected_failure_slices(summary_rows, selected)
            if summary_typed.failure_slices != expected_failure_slices:
                failures.append("summary failure slices mismatch")
            r4_baseline_condition = next(
                condition
                for condition in r4_source.matrix_result.conditions
                if condition.condition.value == EXPECTED_CONDITION
            )
            expected_model_provenance = [
                item.model_dump(mode="json")
                for item in r4_baseline_condition.model_provenance
            ]
            if [
                item.model_dump(mode="json") for item in summary_typed.model_provenance
            ] != expected_model_provenance:
                failures.append("summary model provenance mismatch")
            try:
                expected_prompt_provenance = _expected_prompt_provenance(
                    summary_rows, prepared
                )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                failures.append(f"summary prompt provenance cannot be derived: {error}")
            else:
                if [
                    item.model_dump(mode="json")
                    for item in summary_typed.prompt_provenance
                ] != expected_prompt_provenance:
                    failures.append("summary prompt provenance mismatch")
            if report.get("smoke_metrics") != _metrics(
                summary_rows, expected_references
            ):
                failures.append("smoke metrics mismatch")
            if report.get("actual_cost_microusd") != expected_cost:
                failures.append("actual cost mismatch")

    fingerprint = report.get("report_fingerprint")
    payload = dict(report)
    payload.pop("report_fingerprint", None)
    if fingerprint != _fingerprint(payload):
        failures.append("report fingerprint mismatch")
    return not failures, tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--model-path")
    parser.add_argument("--approve-max-cost-usd", type=float)
    args = parser.parse_args()

    if args.check:
        passed, failures = _check_report()
        if not passed:
            print("Phase 03A1-V check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 03A1-V validity-smoke artifact is valid.")
        return 0

    if REPORT_PATH.exists():
        parser.error("validity-smoke evidence already exists; use a new version")
    if not R4_PATH.is_file():
        parser.error("canonical r4 source report is missing")
    if not args.model_path:
        parser.error("--run requires --model-path")
    if not os.environ.get(FRONTIER_API_KEY_ENV):
        parser.error(f"--run requires {FRONTIER_API_KEY_ENV}")

    fixtures = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)
    prepared = tuple(with_public_provider_state(fixture) for fixture in fixtures)
    estimate = estimate_frontier_cost(
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        output_token_cap=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=len(prepared),
        usd_ceiling=100.0,
    )
    if (
        args.approve_max_cost_usd is None
        or args.approve_max_cost_usd + 1e-12 < estimate.maximum_cost_usd
    ):
        parser.error(
            f"--run requires --approve-max-cost-usd >= {estimate.maximum_cost_usd:.6f}"
        )

    frontier = ValiditySmokeFrontierAdapter(
        reasoning_effort="medium",
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=len(prepared),
        usd_ceiling=estimate.maximum_cost_usd,
    )
    qwen = ValiditySmokeQwenAdapter(
        model_path=args.model_path,
        max_tokens=R2_QWEN_OUTPUT_TOKEN_CAP,
    )
    summary = run_frontier_condition_v2(
        frontier,
        condition=EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM,
        fixtures=prepared,
        qwen=qwen,
    )
    summary_payload = summary.model_dump(mode="json")
    smoke_rows = list(summary_payload["episodes"])
    references = {
        fixture.episode_id: fixture.reference_capability_id.removeprefix("simulator.")
        for fixture in fixtures
    }
    r4_report = json.loads(R4_PATH.read_text(encoding="utf-8"))
    baseline_rows = _baseline_rows(r4_report, set(references))
    actual_cost_microusd = sum(
        int(row.get("actual_cost_microusd") or 0) for row in smoke_rows
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_r4_sha256": _sha256(R4_PATH),
        "source_r4_report_fingerprint": r4_report["report_fingerprint"],
        "provider": "29qg-openai-compatible",
        "requested_model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "diagnostic_changes": [
            "public_provider_state_parity",
            "explicit_dynamic_field_semantics",
            "explicit_fast_noncompletion_rule",
        ],
        "selected_episode_ids": list(references),
        "reference_capabilities": references,
        "baseline_selected_metrics": _metrics(baseline_rows, references),
        "smoke_metrics": _metrics(smoke_rows, references),
        "actual_cost_microusd": actual_cost_microusd,
        "cost_note": "29qg usage-accounted conservative estimate, not an invoice",
        "metric_note": (
            "raw_nonaccept_or_verified_accept_count is an action-safety diagnostic; "
            "provider_exact_outcome_count remains the frozen single-gold metric"
        ),
        "summary": summary_payload,
    }
    payload["report_fingerprint"] = _fingerprint(payload)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Recorded Phase 03A1-V six-episode validity smoke: "
        f"{payload['smoke_metrics']['end_to_end_valid_count']}/6 end-to-end valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
