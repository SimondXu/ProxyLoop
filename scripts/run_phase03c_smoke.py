"""Run one bounded Phase 03C untuned Fast arm with the v3 or v4 prompt.

Stage 0 only re-baselines untuned checkpoints (``--arm a``); tuned arms are a
later stage.  ``--model 8b`` is the re-baseline, ``--model 4b`` the one-time
reference row on the historical 4-bit base.  ``--prompt-version`` defaults to
the Stage 0 v3 prompt; v4 adds the Stage 1b decision-convention block.
Results are descriptive six-episode smokes and never a Go/No-Go on their own.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from statistics import median
from types import ModuleType
from typing import Literal, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxyloop_contracts import canonical_fingerprint  # noqa: E402
from proxyloop_evaluation import fast_parse, qwen_spec  # noqa: E402
from proxyloop_evaluation.phase03b_experiment import (  # noqa: E402
    PHASE03B_SCHEMA_VERSION,
    Phase03BControls,
    Phase03BExample,
    build_phase03b_examples,
    build_phase03b_manifest,
)
from proxyloop_evaluation.phase03c_experiment import (  # noqa: E402
    PHASE03C_EVALUATOR_SOURCE_FINGERPRINT,
    PROMPT_TOKEN_LIMIT,
    Phase03CExecutedRow,
    Phase03CQwenAdapter,
    PromptVersion,
    freeze_phase03c_controls,
    run_phase03c_arm,
)
from proxyloop_evaluation.qwen_mlx import MAX_RAW_OUTPUT_CHARS  # noqa: E402
from proxyloop_evaluation.qwen_spec import (  # noqa: E402
    QWEN3_4B_4BIT_SPEC,
    QWEN3_8B_BF16_SPEC,
    QwenModelSpec,
)

RESULT_SCHEMA_VERSION = "phase-03c-qwen-smoke-result-v1"
RESULT_ROLE = "canonical"
DIAGNOSTIC_ROLE = "diagnostic"
PHASE03C_RUNNER_SOURCE_FINGERPRINT = hashlib.sha256(
    Path(__file__).read_bytes()
).hexdigest()
MODEL_SPECS: dict[str, QwenModelSpec] = {
    "8b": QWEN3_8B_BF16_SPEC,
    "4b": QWEN3_4B_4BIT_SPEC,
}
_METRIC_FIELDS = (
    "json_valid_strict",
    "json_valid_tolerant",
    "duplicate_key",
    "thinking_leak",
    "schema_valid",
    "canonical_valid",
    "end_to_end_valid",
    "dialogue_act_accuracy",
    "reasoner_request_quality",
    "action_candidate_quality",
    "completion_candidate_quality",
    "response_grounded",
    "false_completion",
    "oracle_act_mismatch",
    "policy_violation",
    "pii_violation",
    "disclosure_violation",
    "stale_pin_violation",
    "authority_violation",
    "unsupported_response_violation",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("a",), required=True)
    parser.add_argument("--model", choices=tuple(MODEL_SPECS), required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-version", choices=("v3", "v4"), default="v3")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--verify-token-fit",
        action="store_true",
        help="count templated prompt tokens for all 26 train/dev rows",
    )
    return parser.parse_args(argv)


def _source_fingerprint(module: ModuleType) -> str:
    return hashlib.sha256(Path(str(module.__file__)).read_bytes()).hexdigest()


def _evaluation_pipeline_fingerprint() -> str:
    return canonical_fingerprint(
        {
            "phase03c_experiment": PHASE03C_EVALUATOR_SOURCE_FINGERPRINT,
            "run_phase03c_smoke": PHASE03C_RUNNER_SOURCE_FINGERPRINT,
            "qwen_spec": _source_fingerprint(qwen_spec),
            "fast_parse": _source_fingerprint(fast_parse),
        }
    )


def _manifest_controls(
    adapter: Phase03CQwenAdapter,
) -> tuple[tuple[Phase03BExample, ...], tuple[Phase03BExample, ...], Phase03BControls]:
    examples = build_phase03b_examples()
    development = tuple(item for item in examples if item.split == "development")
    manifest_fingerprint = canonical_fingerprint(build_phase03b_manifest(examples))
    controls = freeze_phase03c_controls(
        development,
        manifest_fingerprint=manifest_fingerprint,
        base_attestation=adapter.checkpoint_attestation,
        prompt_version=adapter.prompt_version,
    )
    return examples, development, controls


def _controls_payload(
    adapter: Phase03CQwenAdapter, controls: Phase03BControls
) -> dict[str, object]:
    if adapter.checkpoint_attestation != controls.base_attestation:
        raise ValueError("adapter base checkpoint attestation differs from controls")
    if adapter.decoding_profile != controls.decoding_profile:
        raise ValueError("adapter decoding profile differs from controls")
    if adapter.adapter_path is not None:
        raise ValueError("Stage 0 Arm A must be untuned")
    spec = adapter.model_spec
    return {
        "base_checkpoint": {
            "model": spec.model,
            "source_lineage": spec.source_lineage,
            "quantization": spec.quantization,
            "run_label": spec.run_label,
            "license": spec.license,
            "enable_thinking": spec.enable_thinking,
            **asdict(adapter.checkpoint_attestation),
        },
        "adapter": {
            "version": adapter.adapter_version,
            "fingerprint": adapter.adapter_fingerprint,
            "path_state": "none",
            "tuning": "untuned",
        },
        "decoding": {
            "profile": asdict(adapter.decoding_profile),
            "fingerprint": adapter.decoding_profile.fingerprint,
        },
        "manifest_fingerprint": controls.manifest_fingerprint,
        "prompt_fingerprints": list(controls.prompt_fingerprints),
        "input_fingerprints": list(controls.input_fingerprints),
        "schema_fingerprint": controls.schema_fingerprint,
        "compiler_version": controls.compiler_version,
        "policy_version": controls.policy_version,
    }


def _raw_hash(raw_output: str | None) -> str | None:
    if raw_output is None:
        return None
    return hashlib.sha256(raw_output.encode("utf-8")).hexdigest()


def _row_payload(
    example: Phase03BExample, executed: Phase03CExecutedRow, prompt_fingerprint: str
) -> dict[str, object]:
    raw_output = executed.raw_output
    if raw_output is not None:
        raw_output = raw_output[:MAX_RAW_OUTPUT_CHARS]
    return {
        "scenario_id": example.scenario_id,
        "family_id": example.family_id,
        "input_fingerprint": example.input_fingerprint,
        "prompt_fingerprint": prompt_fingerprint,
        "raw_output": raw_output,
        "raw_output_sha256": _raw_hash(raw_output),
        "metrics": asdict(executed.metrics),
    }


def _aggregate(rows: Sequence[Phase03CExecutedRow]) -> dict[str, object]:
    denominator = len(rows)
    metrics: dict[str, dict[str, float | int]] = {}
    for field in _METRIC_FIELDS:
        count = sum(bool(getattr(row.metrics, field)) for row in rows)
        metrics[field] = {"count": count, "rate": count / denominator}
    latencies = [
        row.metrics.latency_ms for row in rows if row.metrics.latency_ms is not None
    ]
    input_tokens = [
        row.metrics.input_tokens for row in rows if row.metrics.input_tokens is not None
    ]
    output_tokens = [
        row.metrics.output_tokens
        for row in rows
        if row.metrics.output_tokens is not None
    ]
    statuses: dict[str, int] = {}
    failures: dict[str, int] = {}
    parse_modes: dict[str, int] = {}
    for row in rows:
        statuses[row.metrics.status] = statuses.get(row.metrics.status, 0) + 1
        if row.metrics.failure_category is not None:
            category = row.metrics.failure_category
            failures[category] = failures.get(category, 0) + 1
        mode = str(row.metrics.json_parse_mode)
        parse_modes[mode] = parse_modes.get(mode, 0) + 1
    return {
        "episodes": denominator,
        "metrics": metrics,
        "latency_ms": {
            "observed_count": len(latencies),
            "total": sum(latencies),
            "median": median(latencies) if latencies else None,
        },
        "tokens": {
            "input_observed_count": len(input_tokens),
            "input_total": sum(input_tokens),
            "output_observed_count": len(output_tokens),
            "output_total": sum(output_tokens),
        },
        "status_counts": statuses,
        "failure_category_counts": failures,
        "parse_mode_counts": parse_modes,
    }


def _stage0_pass_bar(aggregate: dict[str, object], *, model: str) -> dict[str, object]:
    """The contract's Stage 0 acceptance line, evaluated but never enforced here."""

    counts = cast(dict[str, dict[str, int]], aggregate["metrics"])
    strict = counts["json_valid_strict"]["count"]
    schema = counts["schema_valid"]["count"]
    leak = counts["thinking_leak"]["count"]
    gates = {
        "strict_json_at_least_5_of_6": strict >= 5,
        "schema_valid_at_least_5_of_6": schema >= 5,
        "thinking_leak_zero": leak == 0,
    }
    return {
        "applies_to": "8b re-baseline" if model == "8b" else "reference row only",
        "gates": gates,
        "all_pass": all(gates.values()),
        "descriptive_only": True,
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _runtime_identity() -> dict[str, object]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {
            name: _package_version(name)
            for name in ("mlx", "mlx-lm", "transformers", "pydantic")
        },
    }


def _peak_rss_bytes() -> int:
    observed = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return observed if sys.platform == "darwin" else observed * 1024


def _mlx_peak_memory_bytes() -> int | None:
    try:
        import mlx.core as mx  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return None
    for name in ("get_peak_memory", "get_active_memory"):
        getter = getattr(mx, name, None)
        if callable(getter):
            try:
                return int(getter())
            except (TypeError, ValueError):
                return None
    return None


def _token_fit(
    adapter: Phase03CQwenAdapter, examples: Sequence[Phase03BExample]
) -> dict[str, object]:
    rows = []
    for example in examples:
        count = adapter.prompt_token_count(example.view)
        rows.append(
            {
                "scenario_id": example.scenario_id,
                "split": example.split,
                "prompt_tokens": count,
                "fits": count is not None and count <= PROMPT_TOKEN_LIMIT,
            }
        )
    counts = [cast(int, row["prompt_tokens"]) for row in rows if row["prompt_tokens"]]
    return {
        "limit": PROMPT_TOKEN_LIMIT,
        "rows": rows,
        "row_count": len(rows),
        "max_prompt_tokens": max(counts) if counts else None,
        "all_fit": len(counts) == len(rows) and all(row["fits"] for row in rows),
    }


def run_smoke(
    *,
    model: str,
    model_path: Path,
    output_path: Path,
    prompt_version: PromptVersion = "v3",
    overwrite: bool = False,
    verify_token_fit: bool = False,
    adapter: Phase03CQwenAdapter | None = None,
) -> dict[str, object]:
    """Run Arm A once; ``adapter`` is an offline-test injection seam."""

    if output_path.exists() and not overwrite:
        raise FileExistsError("output exists; pass --overwrite to replace it")
    spec = MODEL_SPECS[model]
    started = time.perf_counter()
    production_local = adapter is None
    selected_adapter = (
        Phase03CQwenAdapter(
            model_path=str(model_path), model_spec=spec, prompt_version=prompt_version
        )
        if adapter is None
        else adapter
    )
    if selected_adapter.model_spec != spec:
        raise ValueError("adapter model spec differs from --model")
    if selected_adapter.prompt_version != prompt_version:
        raise ValueError("adapter prompt version differs from --prompt-version")
    examples, development, controls = _manifest_controls(selected_adapter)
    controls_payload = _controls_payload(selected_adapter, controls)
    token_fit = _token_fit(selected_adapter, examples) if verify_token_fit else None
    executed = run_phase03c_arm(development, selected_adapter)
    aggregate = _aggregate(executed)
    episode_payloads = [
        _row_payload(example, row, prompt)
        for example, row, prompt in zip(
            development, executed, controls.prompt_fingerprints, strict=True
        )
    ]
    payload: dict[str, object] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "experiment_schema_version": PHASE03B_SCHEMA_VERSION,
        "result_role": RESULT_ROLE if production_local else DIAGNOSTIC_ROLE,
        "execution": {
            "mode": "local_mlx" if production_local else "injected_test",
            "checkpoint_attestation": (
                "observed_local_files" if production_local else "injected_test"
            ),
        },
        "evaluation_pipeline_fingerprint": _evaluation_pipeline_fingerprint(),
        "description": (
            f"descriptive six-episode untuned smoke with the {prompt_version} "
            "prompt; no statistical significance"
        ),
        "arm": "A",
        "model": model,
        "prompt_version": prompt_version,
        "controls": controls_payload,
        "token_fit": token_fit,
        "episodes": episode_payloads,
        "aggregate": aggregate,
        "stage0_pass_bar": _stage0_pass_bar(aggregate, model=model),
        "slow_call_count": 0,
        "hosted_call_count": 0,
        "runtime": _runtime_identity(),
        "resource": {
            "wall_time_ms": round((time.perf_counter() - started) * 1000, 3),
            "process_peak_rss_bytes": _peak_rss_bytes(),
            "mlx_peak_memory_bytes": _mlx_peak_memory_bytes(),
        },
    }
    payload["result_content_fingerprint"] = canonical_fingerprint(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = run_smoke(
            model=cast(Literal["8b", "4b"], args.model),
            model_path=args.model_path,
            output_path=args.output,
            prompt_version=cast(PromptVersion, args.prompt_version),
            overwrite=args.overwrite,
            verify_token_fit=args.verify_token_fit,
        )
    except (FileExistsError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    aggregate = cast(dict[str, object], payload["aggregate"])
    counts = cast(dict[str, dict[str, int]], aggregate["metrics"])
    print(
        "phase03c smoke result: written "
        f"(strict_json={counts['json_valid_strict']['count']}/6 "
        f"schema_valid={counts['schema_valid']['count']}/6 "
        f"thinking_leak={counts['thinking_leak']['count']}/6)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
