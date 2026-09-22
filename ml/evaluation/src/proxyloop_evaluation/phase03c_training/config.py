"""The contract's Stage 2 recipe mapped onto ``mlx_lm.lora`` (0.31.3).

Two ``mlx_lm`` semantics differ from the TRL/PEFT wording of the contract and
are mapped here explicitly rather than copied by name:

* ``iters`` counts micro-batches of ``batch_size`` rows; the optimizer
  updates once every ``grad_accumulation_steps`` iterations and the learning
  rate schedule advances per optimizer update.  Three epochs at batch 1 with
  accumulation 16 are therefore ``iters = 3 * rows`` (rounded up to a whole
  accumulation window), ``steps_per_eval``/``save_every`` are
  ``100 * 16`` iterations for "every 100 optimizer steps", and the cosine
  schedule is sized in optimizer steps.
* ``lora_parameters.scale`` multiplies the low-rank update directly
  (``y + scale * x @ A @ B``), unlike PEFT's ``lora_alpha`` which is divided
  by the rank.  The contract's ``r 32, alpha 64`` is ``scale = 64 / 32``.

``mask_prompt`` makes the loss assistant-only.  The mlx_lm ``ChatDataset``
renders the full conversation through the checkpoint's chat template; for the
Qwen3 hybrid template the last assistant turn is rendered as
``<think>\\n\\n</think>\\n\\n{content}`` and the masked prefix ends at
``<|im_start|>assistant\\n``, so the trained span starts with the same empty
thinking block the evaluator's ``enable_thinking=False`` prefix supplies.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final

TRAINING_CONFIG_FILENAME: Final = "config.yaml"
ADAPTERS_DIRNAME: Final = "adapters"


@dataclass(frozen=True, slots=True)
class TrainingRecipe:
    """Hyper-parameters in the contract's vocabulary."""

    lora_rank: int = 32
    lora_alpha: int = 64
    lora_dropout: float = 0.05
    num_layers: int = -1  # every transformer block
    epochs: int = 3
    learning_rate: float = 1.5e-4
    warmup_fraction: float = 0.03
    seed: int = 0
    max_seq_length: int = 2048
    batch_size: int = 1
    grad_accumulation_steps: int = 16
    eval_every_optimizer_steps: int = 100
    val_batches: int = 50
    grad_checkpoint: bool = True

    @property
    def lora_scale(self) -> float:
        return self.lora_alpha / self.lora_rank


RECIPE: Final = TrainingRecipe()
# Pipeline smoke on the historical 4B 4-bit base: rank 8, two optimizer
# steps of two micro-batches each, eval/save every optimizer step.
SMOKE_RECIPE: Final = replace(
    RECIPE,
    lora_rank=8,
    grad_accumulation_steps=2,
    eval_every_optimizer_steps=1,
    val_batches=4,
)
SMOKE_TRAIN_ROWS: Final = 8
SMOKE_ITERS: Final = 4


@dataclass(frozen=True, slots=True)
class TrainingPlan:
    """The iteration arithmetic derived from a recipe and a row count."""

    train_rows: int
    iters: int
    optimizer_steps: int
    warmup_steps: int
    decay_steps: int
    steps_per_eval: int

    @property
    def effective_batch_size(self) -> int:
        return self.iters // self.optimizer_steps


def training_plan(
    recipe: TrainingRecipe, train_rows: int, *, iters: int | None = None
) -> TrainingPlan:
    """``iters`` overrides the epoch count (pipeline smoke only)."""

    if train_rows < 1:
        raise ValueError("train_rows must be positive")
    window = recipe.batch_size * recipe.grad_accumulation_steps
    if iters is None:
        optimizer_steps = math.ceil(recipe.epochs * train_rows / window)
    else:
        if iters < 1 or iters % recipe.grad_accumulation_steps:
            raise ValueError("iters must be a positive multiple of the accumulation")
        optimizer_steps = iters // recipe.grad_accumulation_steps
    total_iters = optimizer_steps * recipe.grad_accumulation_steps
    warmup_steps = max(1, math.ceil(recipe.warmup_fraction * optimizer_steps))
    decay_steps = max(1, optimizer_steps - warmup_steps)
    return TrainingPlan(
        train_rows=train_rows,
        iters=total_iters,
        optimizer_steps=optimizer_steps,
        warmup_steps=warmup_steps,
        decay_steps=decay_steps,
        steps_per_eval=recipe.eval_every_optimizer_steps
        * recipe.grad_accumulation_steps,
    )


def mlx_lora_config(
    recipe: TrainingRecipe,
    plan: TrainingPlan,
    *,
    model_path: Path,
    data_dir: Path,
    adapter_path: Path,
) -> dict[str, object]:
    """The YAML document ``mlx_lm lora --config`` consumes; keys are its own."""

    return {
        "model": model_path.as_posix(),
        "data": data_dir.as_posix(),
        "adapter_path": adapter_path.as_posix(),
        "train": True,
        "fine_tune_type": "lora",
        "optimizer": "adamw",
        "num_layers": recipe.num_layers,
        "lora_parameters": {
            "rank": recipe.lora_rank,
            "scale": recipe.lora_scale,
            "dropout": recipe.lora_dropout,
        },
        "mask_prompt": True,
        "batch_size": recipe.batch_size,
        "grad_accumulation_steps": recipe.grad_accumulation_steps,
        "iters": plan.iters,
        "learning_rate": recipe.learning_rate,
        "lr_schedule": {
            "name": "cosine_decay",
            "warmup": plan.warmup_steps,
            "warmup_init": 0.0,
            "arguments": [recipe.learning_rate, plan.decay_steps, 0.0],
        },
        "steps_per_report": recipe.grad_accumulation_steps,
        "steps_per_eval": plan.steps_per_eval,
        "save_every": plan.steps_per_eval,
        "val_batches": recipe.val_batches,
        "max_seq_length": recipe.max_seq_length,
        "grad_checkpoint": recipe.grad_checkpoint,
        "seed": recipe.seed,
        "test": False,
    }


def render_yaml(document: dict[str, object]) -> str:
    """A minimal YAML writer for the flat/one-level document above.

    Keys are sorted so the text is a pure function of the document (the run
    manifest check re-renders it); strings are always quoted (JSON quoting
    is valid YAML), so paths and scientific-notation floats survive
    ``yaml.SafeLoader`` unchanged.
    """

    def scalar(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, list):
            return "[" + ", ".join(scalar(item) for item in value) + "]"
        raise TypeError(f"unsupported YAML scalar: {type(value).__name__}")

    lines: list[str] = []
    for key, value in sorted(document.items()):
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines.extend(
                f"  {inner}: {scalar(item)}" for inner, item in sorted(value.items())
            )
        else:
            lines.append(f"{key}: {scalar(value)}")
    return "\n".join(lines) + "\n"


def config_hash(document: dict[str, object]) -> str:
    serialized = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def recipe_dict(recipe: TrainingRecipe) -> dict[str, object]:
    return {**asdict(recipe), "lora_scale": recipe.lora_scale}


__all__ = [
    "ADAPTERS_DIRNAME",
    "RECIPE",
    "SMOKE_ITERS",
    "SMOKE_RECIPE",
    "SMOKE_TRAIN_ROWS",
    "TRAINING_CONFIG_FILENAME",
    "TrainingPlan",
    "TrainingRecipe",
    "config_hash",
    "mlx_lora_config",
    "recipe_dict",
    "render_yaml",
    "training_plan",
]
