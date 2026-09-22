"""Run one Phase 03C Stage 2 LoRA training run locally with ``mlx_lm lora``.

Local variant of the contract's cloud recipe (no GPU credential exists):
the config from ``phase03c_training.config`` is written as YAML, the base
checkpoint is attested against its frozen spec, ``python -m mlx_lm lora
--config <yaml> --train`` runs as a subprocess with its output streamed to
``train.log``, and ``run-manifest.json`` records the dataset fingerprint,
base attestation, config hash, package versions, machine, wall time, loss
table, and adapter file hashes.  ``--smoke`` trains rank 8 for four
iterations on eight rows against the historical 4B 4-bit base to validate
the pipeline; adapters are never committed.  ``--check`` validates every
committed ``run-manifest.json`` under the training directory.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxyloop_evaluation.phase03c_training.config import (  # noqa: E402
    ADAPTERS_DIRNAME,
    RECIPE,
    SMOKE_ITERS,
    SMOKE_RECIPE,
    SMOKE_TRAIN_ROWS,
    TRAINING_CONFIG_FILENAME,
    TrainingRecipe,
    mlx_lora_config,
    render_yaml,
    training_plan,
)
from proxyloop_evaluation.phase03c_training.dataset import (  # noqa: E402
    TRAIN_FILENAME,
    VALID_FILENAME,
    check_dataset_files,
    load_dataset_manifest,
)
from proxyloop_evaluation.phase03c_training.manifest import (  # noqa: E402
    RUN_MANIFEST_FILENAME,
    TRAIN_LOG_FILENAME,
    adapter_file_hashes,
    build_run_manifest,
    check_run_manifest,
    write_run_manifest,
)
from proxyloop_evaluation.qwen_spec import (  # noqa: E402
    QWEN3_4B_4BIT_SPEC,
    QWEN3_8B_BF16_SPEC,
    attest_qwen_spec,
)

TRAINING_DIR = PROJECT_ROOT / "data/experiments/phase-03c/training"
_PACKAGES = ("mlx", "mlx-lm", "transformers", "pydantic", "numpy")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--train", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=None,
        help="override the recipe's 2048 when the dataset's measured max exceeds it",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cpu_brand() -> str:
    try:
        completed = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return platform.processor() or platform.machine()
    return completed.stdout.strip() or platform.machine()


def _gpu_label(brand: str) -> str:
    """``Apple M4 Pro`` -> ``apple-m4-pro-unified``; unified memory, no dGPU."""

    slug = "-".join(brand.lower().split())
    return f"{slug}-unified" if slug.startswith("apple") else slug


def _machine_identity() -> tuple[dict[str, object], str]:
    brand = _cpu_brand()
    return (
        {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_brand": brand,
        },
        _gpu_label(brand),
    )


def _smoke_data_dir(source_dir: Path, out_dir: Path) -> Path:
    """The first rows of each split, so the smoke sees the same file shapes."""

    target = out_dir / "data"
    target.mkdir(parents=True, exist_ok=True)
    for name in (TRAIN_FILENAME, VALID_FILENAME):
        lines = (source_dir / name).read_text(encoding="utf-8").splitlines()
        (target / name).write_text(
            "\n".join(lines[:SMOKE_TRAIN_ROWS]) + "\n", encoding="utf-8"
        )
    return target


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _require_token_fit(
    dataset_manifest: dict[str, object], recipe: TrainingRecipe
) -> None:
    stats = dataset_manifest.get("token_stats")
    if not isinstance(stats, dict):
        raise ValueError(
            "dataset manifest has no token_stats; rerun "
            "prepare_phase03c_training_data.py with --tokenizer-path"
        )
    if int(stats["max"]) > recipe.max_seq_length:
        raise ValueError(
            f"dataset max templated length {stats['max']} exceeds max_seq_length "
            f"{recipe.max_seq_length}; mlx_lm would truncate the assistant target "
            "(pass --max-seq-length to raise it)"
        )


def train(args: argparse.Namespace) -> int:
    if args.data_dir is None or args.model_path is None or args.out_dir is None:
        raise SystemExit("--train requires --data-dir, --model-path, and --out-dir")
    out_dir = cast(Path, args.out_dir)
    manifest_path = out_dir / RUN_MANIFEST_FILENAME
    if manifest_path.exists() and not args.overwrite:
        raise SystemExit(f"{manifest_path} exists; pass --overwrite to replace it")
    source_dir = cast(Path, args.data_dir)
    dataset_manifest = load_dataset_manifest(source_dir)
    check_dataset_files(source_dir, dataset_manifest)
    recipe = SMOKE_RECIPE if args.smoke else RECIPE
    if args.max_seq_length is not None:
        recipe = replace(recipe, max_seq_length=int(args.max_seq_length))
    spec = QWEN3_4B_4BIT_SPEC if args.smoke else QWEN3_8B_BF16_SPEC
    if args.smoke:
        data_dir = _smoke_data_dir(source_dir, out_dir)
        plan = training_plan(recipe, SMOKE_TRAIN_ROWS, iters=SMOKE_ITERS)
    else:
        _require_token_fit(dataset_manifest, recipe)
        data_dir = source_dir
        plan = training_plan(recipe, _count_lines(source_dir / TRAIN_FILENAME))
    base_attestation = attest_qwen_spec(str(args.model_path), spec)
    adapters_dir = out_dir / ADAPTERS_DIRNAME
    config = mlx_lora_config(
        recipe,
        plan,
        model_path=cast(Path, args.model_path),
        data_dir=data_dir,
        adapter_path=adapters_dir,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / TRAINING_CONFIG_FILENAME
    config_path.write_text(render_yaml(config), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "mlx_lm",
        "lora",
        "--config",
        config_path.as_posix(),
        "--train",
    ]
    log_path = out_dir / TRAIN_LOG_FILENAME
    print(f"phase03c training: {' '.join(command)}")
    print(
        f"plan: rows={plan.train_rows} iters={plan.iters} "
        f"optimizer_steps={plan.optimizer_steps} eval_every={plan.steps_per_eval}"
    )
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        exit_code = process.wait()
    wall_time_s = time.perf_counter() - started
    machine, gpu = _machine_identity()
    document = build_run_manifest(
        run_id=out_dir.name,
        smoke=bool(args.smoke),
        dataset_manifest=dataset_manifest,
        data_dir=source_dir,
        base_spec=spec,
        base_attestation=base_attestation,
        recipe=recipe,
        plan=plan,
        config_document=config,
        command=command,
        exit_code=exit_code,
        wall_time_s=wall_time_s,
        packages={name: _package_version(name) for name in _PACKAGES},
        machine=machine,
        gpu=gpu,
        train_log=log_path.read_text(encoding="utf-8"),
        adapter_hashes=adapter_file_hashes(adapters_dir),
    )
    write_run_manifest(manifest_path, document)
    losses = cast(dict[str, object], document["losses"])
    print(
        f"phase03c training run {out_dir.name}: exit={exit_code} "
        f"wall={wall_time_s:.1f}s final_train_loss={losses['final_train_loss']} "
        f"final_val_loss={losses['final_val_loss']} manifest={manifest_path}"
    )
    return exit_code


def check() -> int:
    manifests = sorted(TRAINING_DIR.glob(f"*/{RUN_MANIFEST_FILENAME}"))
    if not manifests:
        print(f"no run manifest under {TRAINING_DIR}; nothing to check")
        return 0
    problems: list[str] = []
    for path in manifests:
        problems.extend(
            f"{path.parent.name}:{problem}" for problem in check_run_manifest(path)
        )
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"phase03c training manifests are consistent ({len(manifests)} checked)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        return check()
    try:
        return train(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())
