"""Run the frozen Phase 03A1-E local and hosted r2 model matrix."""

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
    R2_HOSTED_BUDGET_CEILING_MICROUSD,
    R2_QWEN_OUTPUT_TOKEN_CAP,
    R2_REFERENCE_CALL_CAP,
    R2_REFERENCE_MAX_MICROUSD,
    check_r2_artifacts,
    check_r2_fixture_artifacts,
    write_report_v2,
)
from proxyloop_evaluation.fresh_fixtures import build_fresh_phase03a1_bundle
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    OpenAIFrontierAdapter,
)
from proxyloop_evaluation.qwen_mlx import QwenMLXAdapter
from proxyloop_evaluation.runner_v2 import (
    hosted_report_v2,
    initial_report_v2,
    load_report_v2,
    local_report_v2,
)

ROOT = Path(__file__).resolve().parents[1]


def _host_class() -> str:
    return (
        f"{platform.system().lower()}-{platform.machine().lower()}-local-mlx"
        "+29qg-hosted"
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


def _require_fixture_gate(
    parser: argparse.ArgumentParser, *, include_report: bool
) -> None:
    checker = check_r2_artifacts if include_report else check_r2_fixture_artifacts
    passed, failures = checker(ROOT)
    if not passed:
        parser.error("deterministic r2 fixture gate failed: " + "; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write-initial-report", action="store_true")
    action.add_argument("--run-local", action="store_true")
    action.add_argument("--run-hosted", action="store_true")
    parser.add_argument("--model-path")
    parser.add_argument("--approve-max-cost-usd", type=float)
    args = parser.parse_args()
    _require_fixture_gate(parser, include_report=not args.write_initial_report)
    fixtures = build_fresh_phase03a1_bundle().fixtures

    if args.write_initial_report:
        write_report_v2(
            ROOT,
            initial_report_v2(fixtures, host_class=_host_class()),
        )
        print("Recorded the frozen pre-model Phase 03A1-E report.")
        return 0

    if not args.model_path:
        parser.error("model execution requires --model-path")
    qwen = QwenMLXAdapter(
        model_path=args.model_path,
        max_tokens=R2_QWEN_OUTPUT_TOKEN_CAP,
    )
    if args.run_local:
        write_report_v2(
            ROOT,
            local_report_v2(qwen, fixtures, host_class=_host_class()),
        )
        print("Recorded local untuned Qwen r2 evidence.")
        return 0

    if not os.environ.get(FRONTIER_API_KEY_ENV):
        parser.error(
            f"--run-hosted requires {FRONTIER_API_KEY_ENV} in the process environment"
        )
    approved = args.approve_max_cost_usd
    frozen_ceiling = R2_HOSTED_BUDGET_CEILING_MICROUSD / 1_000_000
    if approved is None or approved + 1e-12 < frozen_ceiling:
        parser.error(
            f"--run-hosted requires --approve-max-cost-usd >= {frozen_ceiling:.6f}"
        )
    existing = load_report_v2(ROOT)
    report = hosted_report_v2(
        existing.conditions[:3],
        frontier_adapters=(
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
        ),
        qwen=qwen,
        fixtures=fixtures,
        host_class=_host_class(),
    )
    write_report_v2(ROOT, report)
    passed, failures = check_r2_artifacts(ROOT)
    if not passed:
        parser.error("completed r2 report failed replay: " + "; ".join(failures))
    print("Recorded the frozen medium/high Terra r2 matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
