"""Evaluate a base or LoRA-adapted Qwen checkpoint on the Phase 03C dev rows.

``--adapter-path none`` gives the untuned row; ``--adapter-path <adapters
dir> --step N`` materialises the trainer's ``N_adapters.safetensors`` step
checkpoint as a loadable adapter directory first.  ``subset60`` is a fixed
six-rows-per-family slice for cheap per-checkpoint comparison; ``full400``
is every development row.  Scores come from the unchanged Stage 0 evaluator
(``run_phase03c_row``); the JSON output carries per-row raw outputs, the
aggregate and per-family rates, and the ``selection_summary`` row that
``select_checkpoint`` consumes.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxyloop_evaluation.phase03c_experiment import (  # noqa: E402
    PHASE03C_COMPILER_VERSIONS,
    Phase03CQwenAdapter,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (  # noqa: E402
    PROMPT_SET_MANIFEST_PATH,
    load_prompt_set_manifest,
)
from proxyloop_evaluation.phase03c_training.dev_eval import (  # noqa: E402
    RowSelection,
    dev_eval_document,
    evaluate_dev_rows,
    select_rows,
    step_adapter_dir,
)
from proxyloop_evaluation.qwen_spec import (  # noqa: E402
    QWEN3_4B_4BIT_SPEC,
    QWEN3_8B_BF16_SPEC,
    QwenModelSpec,
)

MODEL_SPECS: dict[str, QwenModelSpec] = {
    "8b": QWEN3_8B_BF16_SPEC,
    "4b": QWEN3_4B_4BIT_SPEC,
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-path", required=True, help="directory or 'none'")
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model", choices=tuple(MODEL_SPECS), required=True)
    parser.add_argument(
        "--prompt-version", choices=tuple(PHASE03C_COMPILER_VERSIONS), default="v6"
    )
    parser.add_argument("--rows", choices=("subset60", "full400"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / PROMPT_SET_MANIFEST_PATH
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


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


def resolve_adapter_path(adapter_path: str, step: int | None) -> str | None:
    if adapter_path == "none":
        if step is not None:
            raise ValueError("--step requires an adapter directory")
        return None
    directory = Path(adapter_path)
    if step is not None:
        directory = step_adapter_dir(directory, step)
    return directory.as_posix()


def run_dev_eval(
    *,
    model: str,
    model_path: Path,
    adapter_path: str | None,
    step: int | None,
    prompt_version: PromptVersion,
    selection: RowSelection,
    manifest: Path,
    output: Path,
    overwrite: bool = False,
    adapter: Phase03CQwenAdapter | None = None,
) -> dict[str, object]:
    """``adapter`` is the offline-test injection seam (fake generator)."""

    if output.exists() and not overwrite:
        raise FileExistsError(f"{output} exists; pass --overwrite to replace it")
    spec = MODEL_SPECS[model]
    injected = adapter is not None
    selected_adapter = (
        Phase03CQwenAdapter(
            model_path=model_path.as_posix(),
            adapter_path=adapter_path,
            model_spec=spec,
            prompt_version=prompt_version,
        )
        if adapter is None
        else adapter
    )
    if selected_adapter.model_spec != spec:
        raise ValueError("adapter model spec differs from --model")
    if selected_adapter.prompt_version != prompt_version:
        raise ValueError("adapter prompt version differs from --prompt-version")
    rows = select_rows(load_prompt_set_manifest(manifest), selection)
    started = time.perf_counter()
    results = evaluate_dev_rows(rows, selected_adapter)
    document = dev_eval_document(
        model=model,
        prompt_version=prompt_version,
        selection=selection,
        adapter=selected_adapter,
        step=step,
        results=results,
        runtime=_runtime_identity(),
        wall_time_ms=(time.perf_counter() - started) * 1000,
        injected=injected,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = run_dev_eval(
            model=args.model,
            model_path=args.model_path,
            adapter_path=resolve_adapter_path(args.adapter_path, args.step),
            step=args.step,
            prompt_version=cast(PromptVersion, args.prompt_version),
            selection=cast(RowSelection, args.rows),
            manifest=args.manifest,
            output=args.output,
            overwrite=args.overwrite,
        )
    except (FileExistsError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    summary = cast(dict[str, object], document["selection_summary"])
    print(
        f"phase03c dev eval written to {args.output}: rows={summary['rows']} "
        f"oracle_act_agreement={summary['oracle_act_agreement']} "
        f"schema_valid={summary['schema_valid']} "
        f"policy_violation={summary['policy_violation']} "
        f"unsupported={summary['unsupported_response_violation']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
