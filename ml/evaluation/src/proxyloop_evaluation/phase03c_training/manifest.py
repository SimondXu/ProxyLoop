"""The committed run manifest of one local MLX LoRA training run.

Weights never enter Git; the manifest carries the dataset fingerprint, the
attested base checkpoint, the exact ``mlx_lm`` config and its hash, package
versions, machine, wall time, the loss table parsed from ``train.log``, and
the SHA-256 of every adapter file the run wrote.  ``check_run_manifest``
re-derives every derived field so a committed manifest cannot drift from
the config and plan it claims.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Final

from proxyloop_evaluation.qwen_mlx import QwenCheckpointAttestation
from proxyloop_evaluation.qwen_spec import QwenModelSpec

from .config import (
    TRAINING_CONFIG_FILENAME,
    TrainingPlan,
    TrainingRecipe,
    config_hash,
    recipe_dict,
    render_yaml,
    training_plan,
)
from .dataset import sha256_file

RUN_MANIFEST_SCHEMA_VERSION: Final = "phase-03c-training-run-v1"
RUN_MANIFEST_FILENAME: Final = "run-manifest.json"
TRAIN_LOG_FILENAME: Final = "train.log"
DEVIATION: Final = "local-mlx-lora-instead-of-cloud-trl-peft"
_TRAIN_LINE: Final = re.compile(
    r"^Iter (?P<iter>\d+): Train loss (?P<loss>[0-9.]+), "
    r"Learning Rate (?P<lr>[0-9.eE+-]+), .*Trained Tokens (?P<tokens>\d+)"
)
_VAL_LINE: Final = re.compile(r"^Iter (?P<iter>\d+): Val loss (?P<loss>[0-9.]+)")
_SAVE_LINE: Final = re.compile(r"^Iter (?P<iter>\d+): Saved adapter weights")


def parse_train_log(text: str) -> dict[str, object]:
    """The loss table and save points ``mlx_lm.tuner.trainer`` printed."""

    train: list[dict[str, float | int]] = []
    val: list[dict[str, float | int]] = []
    saved: list[int] = []
    for line in text.splitlines():
        if match := _TRAIN_LINE.match(line):
            train.append(
                {
                    "iter": int(match["iter"]),
                    "train_loss": float(match["loss"]),
                    "learning_rate": float(match["lr"]),
                    "trained_tokens": int(match["tokens"]),
                }
            )
        elif match := _VAL_LINE.match(line):
            val.append({"iter": int(match["iter"]), "val_loss": float(match["loss"])})
        elif match := _SAVE_LINE.match(line):
            saved.append(int(match["iter"]))
    return {
        "train_loss": train,
        "val_loss": val,
        "saved_iters": saved,
        "final_train_loss": train[-1]["train_loss"] if train else None,
        "final_val_loss": val[-1]["val_loss"] if val else None,
    }


def adapter_file_hashes(adapters_dir: Path) -> dict[str, dict[str, object]]:
    """SHA-256 and size of every file the trainer wrote under ``adapters/``."""

    rows: dict[str, dict[str, object]] = {}
    if not adapters_dir.is_dir():
        return rows
    for path in sorted(adapters_dir.rglob("*"), key=lambda item: str(item)):
        if path.is_file() and not path.name.startswith("."):
            rows[path.relative_to(adapters_dir).as_posix()] = {
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
    return rows


def manifest_fingerprint(document: Mapping[str, object]) -> str:
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    serialized = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_run_manifest(
    *,
    run_id: str,
    smoke: bool,
    dataset_manifest: Mapping[str, object],
    data_dir: Path,
    base_spec: QwenModelSpec,
    base_attestation: QwenCheckpointAttestation,
    recipe: TrainingRecipe,
    plan: TrainingPlan,
    config_document: Mapping[str, object],
    command: list[str],
    exit_code: int,
    wall_time_s: float,
    packages: Mapping[str, str | None],
    machine: Mapping[str, object],
    gpu: str,
    train_log: str,
    adapter_hashes: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    config = dict(config_document)
    document: dict[str, object] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "smoke": smoke,
        "deviation": DEVIATION,
        "gpu": gpu,
        "dataset": {
            "dir": data_dir.as_posix(),
            "fingerprint": dataset_manifest["dataset_fingerprint"],
            "prompt_version": dataset_manifest["prompt_version"],
            "compiler_version": dataset_manifest["compiler_version"],
            "split_counts": dataset_manifest["split_counts"],
            "token_stats": dataset_manifest.get("token_stats"),
        },
        "base_checkpoint": {
            "model": base_spec.model,
            "source_lineage": base_spec.source_lineage,
            "quantization": base_spec.quantization,
            "enable_thinking": base_spec.enable_thinking,
            **asdict(base_attestation),
        },
        "recipe": recipe_dict(recipe),
        "plan": asdict(plan),
        "config": config,
        "config_hash": config_hash(config),
        "command": list(command),
        "exit_code": exit_code,
        "wall_time_s": round(wall_time_s, 3),
        "packages": dict(packages),
        "machine": dict(machine),
        "losses": parse_train_log(train_log),
        "adapter_files": {key: dict(value) for key, value in adapter_hashes.items()},
        "selection": {
            "rule": (
                "max dev oracle_act_agreement with policy_violation == 0, ties by "
                "lower unsupported_response_violation, then earlier step; never "
                "by loss"
            ),
            "dev_evals": [],
            "selected_step": None,
        },
    }
    document["fingerprint"] = manifest_fingerprint(document)
    return document


def write_run_manifest(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def check_run_manifest(path: Path) -> tuple[str, ...]:
    """Every derived field of a committed manifest must re-derive from its inputs."""

    if not path.is_file():
        return (f"missing_manifest:{path}",)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return (f"malformed_manifest:{path}",)
    problems: list[str] = []
    if document.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        problems.append("schema_version_mismatch")
    if document.get("deviation") != DEVIATION:
        problems.append("deviation_missing")
    if not isinstance(document.get("gpu"), str):
        problems.append("gpu_missing")
    if document.get("fingerprint") != manifest_fingerprint(document):
        problems.append("fingerprint_drift")
    config = document.get("config")
    recipe_fields = document.get("recipe")
    plan_fields = document.get("plan")
    if not isinstance(config, dict) or not isinstance(recipe_fields, dict):
        return tuple([*problems, "config_or_recipe_missing"])
    if document.get("config_hash") != config_hash(config):
        problems.append("config_hash_drift")
    if not isinstance(plan_fields, dict):
        return tuple([*problems, "plan_missing"])
    known = {name for name in TrainingRecipe.__dataclass_fields__}
    recipe = TrainingRecipe(
        **{key: value for key, value in recipe_fields.items() if key in known}
    )
    if recipe_fields.get("lora_scale") != recipe.lora_scale:
        problems.append("lora_scale_not_alpha_over_rank")
    expected_plan = training_plan(
        recipe, int(plan_fields["train_rows"]), iters=int(plan_fields["iters"])
    )
    if asdict(expected_plan) != plan_fields:
        problems.append("plan_drift")
    if not document.get("smoke") and expected_plan != training_plan(
        recipe, int(plan_fields["train_rows"])
    ):
        problems.append("iters_not_three_epochs")
    for key, expected in (
        ("iters", expected_plan.iters),
        ("steps_per_eval", expected_plan.steps_per_eval),
        ("save_every", expected_plan.steps_per_eval),
        ("mask_prompt", True),
        ("max_seq_length", recipe.max_seq_length),
        ("seed", recipe.seed),
    ):
        if config.get(key) != expected:
            problems.append(f"config_drift:{key}")
    lora = config.get("lora_parameters")
    if not isinstance(lora, dict) or lora != {
        "rank": recipe.lora_rank,
        "scale": recipe.lora_scale,
        "dropout": recipe.lora_dropout,
    }:
        problems.append("config_drift:lora_parameters")
    yaml_path = path.with_name(TRAINING_CONFIG_FILENAME)
    if yaml_path.is_file() and yaml_path.read_text(encoding="utf-8") != render_yaml(
        config
    ):
        problems.append("config_yaml_drift")
    if document.get("exit_code") != 0:
        problems.append("exit_code_nonzero")
    losses = document.get("losses")
    if not isinstance(losses, dict) or losses.get("final_train_loss") is None:
        problems.append("losses_missing")
    return tuple(problems)


__all__ = [
    "DEVIATION",
    "RUN_MANIFEST_FILENAME",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "TRAIN_LOG_FILENAME",
    "adapter_file_hashes",
    "build_run_manifest",
    "check_run_manifest",
    "manifest_fingerprint",
    "parse_train_log",
    "write_run_manifest",
]
