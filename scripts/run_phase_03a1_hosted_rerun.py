#!/usr/bin/env python3
"""Run or verify the source-bound Phase 03A1-R hosted reliability rerun."""

from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path

from proxyloop_evaluation.artifacts_v2 import (
    R2_FAST_SLOW_CALL_CAP,
    R2_FAST_SLOW_MAX_MICROUSD,
    R2_FRONTIER_INPUT_TOKEN_CAP,
    R2_FRONTIER_OUTPUT_TOKEN_CAP,
    R2_QWEN_OUTPUT_TOKEN_CAP,
    R2_REFERENCE_CALL_CAP,
    R2_REFERENCE_MAX_MICROUSD,
)
from proxyloop_evaluation.fresh_fixtures import build_fresh_phase03a1_bundle
from proxyloop_evaluation.hosted_rerun import (
    R4_PROBE_BUDGET_CEILING_MICROUSD,
    R4_PROBE_INPUT_TOKEN_CAP,
    R4_PROBE_OUTPUT_TOKEN_CAP,
    R4_REPORT_PATH,
    R4_TOTAL_BUDGET_CEILING_MICROUSD,
    check_hosted_rerun_artifacts,
    check_hosted_rerun_sources,
    compose_r4_report,
    initial_matrix_from_source,
    load_report_r4,
    load_source_reports,
    provider_errors_from_adapters,
    run_hosted_matrix,
    run_provider_probes,
    write_report_r4,
)
from proxyloop_evaluation.models import EvaluationConditionV2
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    OpenAIFrontierAdapter,
)
from proxyloop_evaluation.qwen_mlx import QwenMLXAdapter

ROOT = Path(__file__).resolve().parents[1]


def _host_class() -> str:
    return (
        f"{platform.system().lower()}-{platform.machine().lower()}-local-mlx"
        "+29qg-hosted-r4"
    )


def _frontier(
    *, reasoning_effort: str, call_cap: int, maximum_cost_microusd: int
) -> OpenAIFrontierAdapter:
    return OpenAIFrontierAdapter(
        reasoning_effort=reasoning_effort,
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=call_cap,
        usd_ceiling=maximum_cost_microusd / 1_000_000,
    )


def _probe(reasoning_effort: str) -> OpenAIFrontierAdapter:
    return OpenAIFrontierAdapter(
        reasoning_effort=reasoning_effort,
        input_token_cap=R4_PROBE_INPUT_TOKEN_CAP,
        max_output_tokens=R4_PROBE_OUTPUT_TOKEN_CAP,
        call_cap=1,
        usd_ceiling=(R4_PROBE_BUDGET_CEILING_MICROUSD / 2) / 1_000_000,
    )


def _require_credential(parser: argparse.ArgumentParser) -> None:
    if not os.environ.get(FRONTIER_API_KEY_ENV):
        parser.error(f"Provider execution requires {FRONTIER_API_KEY_ENV}")


def _require_approved_cost(
    parser: argparse.ArgumentParser,
    approved: float | None,
    required_microusd: int,
) -> None:
    required = required_microusd / 1_000_000
    if approved is None or approved + 1e-12 < required:
        parser.error(f"execution requires --approve-max-cost-usd >= {required:.6f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run-probe", action="store_true")
    action.add_argument("--run-hosted", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--check-sources", action="store_true")
    parser.add_argument("--model-path")
    parser.add_argument("--approve-max-cost-usd", type=float)
    args = parser.parse_args()

    if args.check_sources:
        passed, failures = check_hosted_rerun_sources(ROOT)
        if not passed:
            print("Phase 03A1-R source check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 03A1-R deterministic pre-dispatch sources are valid.")
        return 0

    if args.check:
        passed, failures = check_hosted_rerun_artifacts(ROOT)
        if not passed:
            print("Phase 03A1-R artifact check failed:", *failures, sep="\n- ")
            return 1
        report = load_report_r4(ROOT)
        state = "ready" if report.phase_completion_ready else "blocked"
        print(f"Phase 03A1-R r4 artifacts valid ({state}).")
        return 0

    passed, failures = check_hosted_rerun_sources(ROOT)
    if not passed:
        parser.error("immutable r2/r3 source gate failed: " + "; ".join(failures))
    if (ROOT / R4_REPORT_PATH).exists():
        existing = load_report_r4(ROOT)
        if args.run_probe or existing.matrix_external_dispatch_count:
            parser.error("r4 already contains dispatched evidence; use a new version")
    _require_credential(parser)
    source_r2, source_r3 = load_source_reports(ROOT)

    if args.run_probe:
        _require_approved_cost(
            parser,
            args.approve_max_cost_usd,
            R4_PROBE_BUDGET_CEILING_MICROUSD,
        )
        probe_adapters = (_probe("medium"), _probe("high"))
        probes = run_provider_probes(probe_adapters)
        matrix = initial_matrix_from_source(source_r3, host_class=_host_class())
        errors = provider_errors_from_adapters(
            ("provider_probe_medium", "provider_probe_high"), probe_adapters
        )
        report = write_report_r4(
            ROOT,
            compose_r4_report(
                source_r2=source_r2,
                source_r3=source_r3,
                probes=probes,
                matrix_result=matrix,
                provider_errors=errors,
            ),
        )
        if not report.probe_ready:
            print("Phase 03A1-R Provider probe blocked the hosted matrix.")
            return 2
        print("Phase 03A1-R medium/high Provider probe passed with auditable usage.")
        return 0

    if not args.model_path:
        parser.error("--run-hosted requires --model-path")
    if not (ROOT / R4_REPORT_PATH).is_file():
        parser.error("--run-hosted requires a completed r4 Provider probe artifact")
    _require_approved_cost(
        parser,
        args.approve_max_cost_usd,
        R4_TOTAL_BUDGET_CEILING_MICROUSD,
    )
    existing = load_report_r4(ROOT)
    if not existing.probe_ready:
        parser.error("--run-hosted requires a successful frozen r4 Provider probe")
    passed, failures = check_hosted_rerun_artifacts(ROOT)
    if not passed:
        parser.error("pre-matrix r4 drift gate failed: " + "; ".join(failures))
    qwen = QwenMLXAdapter(
        model_path=args.model_path,
        max_tokens=R2_QWEN_OUTPUT_TOKEN_CAP,
    )
    matrix_adapters = (
        _frontier(
            reasoning_effort="medium",
            call_cap=R2_FAST_SLOW_CALL_CAP,
            maximum_cost_microusd=R2_FAST_SLOW_MAX_MICROUSD,
        ),
        _frontier(
            reasoning_effort="high",
            call_cap=R2_FAST_SLOW_CALL_CAP,
            maximum_cost_microusd=R2_FAST_SLOW_MAX_MICROUSD,
        ),
        _frontier(
            reasoning_effort="medium",
            call_cap=R2_REFERENCE_CALL_CAP,
            maximum_cost_microusd=R2_REFERENCE_MAX_MICROUSD,
        ),
        _frontier(
            reasoning_effort="high",
            call_cap=R2_REFERENCE_CALL_CAP,
            maximum_cost_microusd=R2_REFERENCE_MAX_MICROUSD,
        ),
    )
    matrix = run_hosted_matrix(
        source_r3,
        frontier_adapters=matrix_adapters,
        qwen=qwen,
        fixtures=build_fresh_phase03a1_bundle().fixtures,
        host_class=_host_class(),
    )
    scopes = tuple(condition.value for condition in tuple(EvaluationConditionV2)[3:])
    errors = provider_errors_from_adapters(scopes, matrix_adapters)
    write_report_r4(
        ROOT,
        compose_r4_report(
            source_r2=source_r2,
            source_r3=source_r3,
            probes=existing.probe_evidence,
            matrix_result=matrix,
            provider_errors=errors,
        ),
    )
    passed, failures = check_hosted_rerun_artifacts(ROOT)
    if not passed:
        parser.error("completed r4 report failed replay: " + "; ".join(failures))
    final = load_report_r4(ROOT)
    if final.phase_completion_ready:
        print("Recorded the complete Phase 03A1-R medium/high hosted matrix.")
    else:
        print("Recorded an honest terminal Phase 03A1-R Provider blocker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
