"""Development-row evaluation of a base or LoRA-adapted checkpoint.

Every development row of the prompt set is rebuilt as a ``Phase03BExample``
whose target is the oracle target, then scored by ``run_phase03c_row`` (the
real Stage 0 evaluator, unchanged).  ``select_checkpoint`` is the contract's
rule: max dev ``oracle_act_agreement`` with ``policy_violation == 0``, ties by
lower ``unsupported_response_violation``, then the earlier step; never loss.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Final, Literal, cast

from proxyloop_contracts import FastModelView
from proxyloop_data_pipeline import NormalizedTrajectory

from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.phase03b_experiment import Phase03BExample
from proxyloop_evaluation.phase03c_experiment import (
    Phase03CExecutedRow,
    Phase03CQwenAdapter,
    analyze_raw_output,
    run_phase03c_row,
)
from proxyloop_evaluation.phase03c_prompt_set import (
    PromptSetRow,
    render_prompt_view,
    resolve_row,
)

from .dataset import canonical_dev_target, sha256_text

DEV_EVAL_SCHEMA_VERSION: Final = "phase-03c-dev-eval-v1"
RowSelection = Literal["subset60", "full400"]
SUBSET_PER_FAMILY: Final = 6
STEP_ADAPTER_DIRNAME: Final = "steps"
# Rates reported per run and per family; each is a Phase03CRowMetrics field
# except ``needed_agreement`` (derived below) and ``oracle_act_agreement``,
# which is ``dialogue_act_accuracy`` because a development row's target is
# the oracle target (an unparseable output counts as disagreement).
RATE_FIELDS: Final = (
    "oracle_act_agreement",
    "needed_agreement",
    "reasoner_request_agreement",
    "strict_json",
    "schema_valid",
    "policy_violation",
    "unsupported_response_violation",
    "end_to_end_valid",
    "thinking_leak",
)
_METRIC_SOURCE: Final = {
    "oracle_act_agreement": "dialogue_act_accuracy",
    "reasoner_request_agreement": "reasoner_request_quality",
    "strict_json": "json_valid_strict",
    "schema_valid": "schema_valid",
    "policy_violation": "policy_violation",
    "unsupported_response_violation": "unsupported_response_violation",
    "end_to_end_valid": "end_to_end_valid",
    "thinking_leak": "thinking_leak",
}


def development_rows(rows: Iterable[PromptSetRow]) -> tuple[PromptSetRow, ...]:
    return tuple(
        sorted(
            (row for row in rows if row.split == "development"),
            key=lambda row: (
                row.family_id,
                row.seed,
                row.configuration_id,
                row.position_index,
            ),
        )
    )


def select_rows(
    rows: Iterable[PromptSetRow], selection: RowSelection
) -> tuple[PromptSetRow, ...]:
    """``subset60``: the first six rows per family in (seed, config, position)."""

    dev = development_rows(rows)
    if selection == "full400":
        return dev
    per_family: dict[str, list[PromptSetRow]] = defaultdict(list)
    for row in dev:
        if len(per_family[row.family_id]) < SUBSET_PER_FAMILY:
            per_family[row.family_id].append(row)
    return tuple(row for family in sorted(per_family) for row in per_family[family])


def build_dev_example(row: PromptSetRow) -> tuple[Phase03BExample, FastModelView]:
    """A ``Phase03BExample`` for the evaluator; no source trajectory exists.

    The evaluator reads ``view``, ``target``, and ``public_observation`` only;
    ``source_record`` is a Phase 03B lineage field the prompt set has no
    equivalent for, so it is left unset behind a cast.
    """

    scenario, position = resolve_row(row)
    view = render_prompt_view(scenario, position)
    target = FastModelOutput.model_validate_json(
        canonical_dev_target(row.oracle_action)
    )
    example = Phase03BExample(
        split="development",
        scenario_id=row.scenario_id,
        family_id=row.family_id,
        source_record=cast(NormalizedTrajectory, None),
        public_observation=position.observation,
        view=view,
        target=target,
    )
    return example, view


@dataclass(frozen=True, slots=True)
class DevRowResult:
    prompt_id: str
    family_id: str
    prompt_fingerprint: str
    executed: Phase03CExecutedRow
    needed_agreement: bool

    def to_dict(self) -> dict[str, object]:
        raw = self.executed.raw_output
        return {
            "prompt_id": self.prompt_id,
            "family_id": self.family_id,
            "prompt_fingerprint": self.prompt_fingerprint,
            "raw_output": raw,
            "raw_output_sha256": sha256_text(raw) if raw is not None else None,
            "needed_agreement": self.needed_agreement,
            "metrics": asdict(self.executed.metrics),
        }


def _needed_agreement(raw_output: str | None, example: Phase03BExample) -> bool:
    parsed = analyze_raw_output(raw_output).parsed
    if parsed is None:
        return False
    reasoner = parsed.get("reasoner_request")
    if not isinstance(reasoner, dict):
        return False
    return reasoner.get("needed") == example.target.reasoner_request.needed


def evaluate_dev_rows(
    rows: Sequence[PromptSetRow], adapter: Phase03CQwenAdapter
) -> tuple[DevRowResult, ...]:
    results: list[DevRowResult] = []
    for row in rows:
        example, view = build_dev_example(row)
        prompt = adapter.build_prompt(view)
        if prompt.fingerprint != row.prompt_fingerprint:
            raise ValueError(f"prompt_fingerprint_drift:{row.prompt_id}")
        executed = run_phase03c_row(example, adapter)
        results.append(
            DevRowResult(
                prompt_id=row.prompt_id,
                family_id=row.family_id,
                prompt_fingerprint=prompt.fingerprint,
                executed=executed,
                needed_agreement=_needed_agreement(executed.raw_output, example),
            )
        )
    return tuple(results)


def _rate_value(result: DevRowResult, field: str) -> bool:
    if field == "needed_agreement":
        return result.needed_agreement
    return bool(getattr(result.executed.metrics, _METRIC_SOURCE[field]))


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def aggregate_results(results: Sequence[DevRowResult]) -> dict[str, object]:
    if not results:
        raise ValueError("no development rows evaluated")
    rates = {
        field: {
            "count": sum(_rate_value(item, field) for item in results),
            "rate": sum(_rate_value(item, field) for item in results) / len(results),
        }
        for field in RATE_FIELDS
    }
    latencies = [
        item.executed.metrics.latency_ms
        for item in results
        if item.executed.metrics.latency_ms is not None
    ]
    statuses: dict[str, int] = defaultdict(int)
    failures: dict[str, int] = defaultdict(int)
    for item in results:
        statuses[item.executed.metrics.status] += 1
        if item.executed.metrics.failure_category is not None:
            failures[item.executed.metrics.failure_category] += 1
    return {
        "rows": len(results),
        "metrics": rates,
        "latency_ms": {
            "observed_count": len(latencies),
            "median": median(latencies) if latencies else None,
            "p95": _percentile(latencies, 0.95) if latencies else None,
            "total": sum(latencies),
        },
        "status_counts": dict(sorted(statuses.items())),
        "failure_category_counts": dict(sorted(failures.items())),
    }


def aggregate_per_family(results: Sequence[DevRowResult]) -> dict[str, object]:
    by_family: dict[str, list[DevRowResult]] = defaultdict(list)
    for item in results:
        by_family[item.family_id].append(item)
    return {
        family: {
            "rows": len(items),
            **{
                field: sum(_rate_value(item, field) for item in items)
                for field in RATE_FIELDS
            },
        }
        for family, items in sorted(by_family.items())
    }


def selection_summary(
    aggregate: Mapping[str, object], *, step: int | None
) -> dict[str, object]:
    """The per-eval row ``select_checkpoint`` consumes (counts, not rates)."""

    metrics = cast(Mapping[str, Mapping[str, float | int]], aggregate["metrics"])
    return {
        "step": step,
        "rows": aggregate["rows"],
        "oracle_act_agreement": metrics["oracle_act_agreement"]["rate"],
        "policy_violation": metrics["policy_violation"]["count"],
        "unsupported_response_violation": metrics["unsupported_response_violation"][
            "count"
        ],
        "schema_valid": metrics["schema_valid"]["rate"],
    }


def select_checkpoint(
    evals: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    """Contract rule; ``None`` when every candidate has a policy violation."""

    candidates = [item for item in evals if item["policy_violation"] == 0]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            -float(cast(float, item["oracle_act_agreement"])),
            int(cast(int, item["unsupported_response_violation"])),
            int(cast(int, item["step"])) if item.get("step") is not None else -1,
        ),
    )


def step_adapter_dir(adapters_dir: Path, step: int) -> Path:
    """Materialise ``<adapters>/steps/step-<n>/`` from a saved step checkpoint.

    ``mlx_lm.load(adapter_path=...)`` and the Phase 03B adapter attestation
    both expect ``adapter_config.json`` plus ``adapters.safetensors`` in one
    directory, while the trainer writes ``<iter>_adapters.safetensors``
    siblings; the step file is hard-linked (copied on failure).
    """

    source = adapters_dir / f"{step:07d}_adapters.safetensors"
    config = adapters_dir / "adapter_config.json"
    if not source.is_file() or not config.is_file():
        raise FileNotFoundError(
            f"no saved checkpoint for step {step} in {adapters_dir}"
        )
    target_dir = adapters_dir / STEP_ADAPTER_DIRNAME / f"step-{step:07d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config, target_dir / "adapter_config.json")
    weights = target_dir / "adapters.safetensors"
    if not weights.exists():
        try:
            os.link(source, weights)
        except OSError:
            shutil.copy2(source, weights)
    return target_dir


def dev_eval_document(
    *,
    model: str,
    prompt_version: str,
    selection: RowSelection,
    adapter: Phase03CQwenAdapter,
    step: int | None,
    results: Sequence[DevRowResult],
    runtime: Mapping[str, object],
    wall_time_ms: float,
    injected: bool,
) -> dict[str, object]:
    aggregate = aggregate_results(results)
    spec = adapter.model_spec
    document: dict[str, object] = {
        "schema_version": DEV_EVAL_SCHEMA_VERSION,
        "result_role": "diagnostic" if injected else "canonical",
        "execution": {"mode": "injected_test" if injected else "local_mlx"},
        "model": model,
        "prompt_version": prompt_version,
        "compiler_version": adapter.compiler_version,
        "rows": selection,
        "base_checkpoint": {
            "model": spec.model,
            "quantization": spec.quantization,
            "enable_thinking": spec.enable_thinking,
            **asdict(adapter.checkpoint_attestation),
        },
        "adapter": {
            "path": adapter.adapter_path,
            "path_state": "none" if adapter.adapter_path is None else "local_dir",
            "version": adapter.adapter_version,
            "fingerprint": adapter.adapter_fingerprint,
            "step": step,
            "tuning": "untuned" if adapter.adapter_path is None else "lora",
        },
        "decoding": asdict(adapter.decoding_profile),
        "aggregate": aggregate,
        "per_family": aggregate_per_family(results),
        "selection_summary": selection_summary(aggregate, step=step),
        "episodes": [item.to_dict() for item in results],
        "runtime": dict(runtime),
        "wall_time_ms": round(wall_time_ms, 3),
    }
    document["result_content_fingerprint"] = sha256_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return document


__all__ = [
    "DEV_EVAL_SCHEMA_VERSION",
    "RATE_FIELDS",
    "SUBSET_PER_FAMILY",
    "DevRowResult",
    "RowSelection",
    "aggregate_per_family",
    "aggregate_results",
    "build_dev_example",
    "dev_eval_document",
    "development_rows",
    "evaluate_dev_rows",
    "select_checkpoint",
    "select_rows",
    "selection_summary",
    "step_adapter_dir",
]
