"""BF16 LoRA SFT on Qwen3.5-9B (ADR-0003, TRAINING §8), run by modal_train.py.
`python -m training_jobs.sft <out.json>` is the CPU named_modules() dump (meta device).
Module level is stdlib + serving.config: torch, peft, trl and proxyloop load lazily.
"""

# pyright: basic, reportMissingImports=false

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

from serving import config

PINS = (
    "torch==2.10.0",
    "transformers==5.17.0",
    f"peft=={config.PEFT_VERSION}",
    f"accelerate=={config.ACCELERATE_VERSION}",
    "trl==1.14.0",
    "datasets==5.0.1",
    "huggingface_hub==1.33.0",
    "flash-linear-attention==0.5.2",
    "fla-core==0.5.2",
    "pydantic==2.13.5",
    # Prebuilt for torch 2.10 / CUDA 12 / cp312, so the image needs no nvcc.
    "causal-conv1d @ https://github.com/Dao-AILab/causal-conv1d/releases/download/"
    "v1.7.0/causal_conv1d-1.7.0+cu12torch2.10cxx11abiTRUE-cp312-cp312-linux_x86_64.whl",
)
DISTS = (*(re.split(r"==| @ ", p)[0] for p in PINS), "triton")
TARGETS = config.RUNGS["all"]  # the served rung (ADR-0002): train = serve
TARGET_REGEX = config.target_regex(TARGETS)
LORA: dict[str, Any] = {"r": config.LORA_RANK, "lora_alpha": config.LORA_ALPHA}
LORA["lora_dropout"] = 0.05  # TRAINING §8
LORA_PARAM = re.compile(
    rf"base_model\.model\.({TARGET_REGEX})\.lora_[AB]\.default\.weight"
)
# transformers 5.17.0 modeling_qwen3_5 wraps these at import; each wrapper keeps the
# implementation it resolved from the package, or silently the torch reference.
FUSED = {
    "causal_conv1d_fn": "causal_conv1d",
    "causal_conv1d_update": "causal_conv1d",
    "torch_chunk_gated_delta_rule": "fla",
    "torch_recurrent_gated_delta_rule": "fla",
}
RECIPE: dict[str, Any] = {  # SFTConfig kwargs over the defaults (TRAINING §8)
    "learning_rate": 1e-4,
    "lr_scheduler_type": "cosine",
    "warmup_steps": 0.03,
    "bf16": True,
    "num_train_epochs": 2,
    # 64 rows a step in 8 micro-batches of balanced padded cost (length-sorted: long
    # rows go in smaller micro-batches). No packing (ADR-0003).
    "per_device_train_batch_size": 8,
    "gradient_accumulation_steps": 8,
    "train_sampling_strategy": "batch_rebalance",
    "gradient_checkpointing": True,
    "max_length": None,  # never truncate: tokenize_row raises instead
    "save_steps": 100,
    "save_total_limit": 2,
    "logging_steps": 1,
    "seed": 20260926,
}
SMOKE: dict[str, Any] = {**RECIPE, "max_steps": 50, "save_steps": 10}
SMOKE.update(per_device_train_batch_size=4, gradient_accumulation_steps=2)
SMOKE_TURNS = {  # synthetic plumbing targets, canonicalised like teacher turns
    "user": (
        "I'm on it. I'll tell you as soon as the rep answers.",
        "Would $65.00 a month for 12 months work?\n@slow: Dana is waiting on us.",
        "Got it, no contract extension.\n@slow: correction user.plan=no_extension",
    ),
    "cp": (
        "Could you read me back every charge, including any one-time fees?",
        "Thanks, Jordan. Can you do better?\n@slow: fact rep.name=Jordan",
        "Let me check that with the account holder.\n@hold offer",
    ),
}


def smoke_rows(views: list[tuple[str, str]], n: int = 64) -> list[tuple[str, ...]]:
    """(profile, FastView JSON, teacher turn), cycling views and lane turns."""
    rows = [(*views[i % len(views)], i // len(views)) for i in range(n)]
    return [(p, v, SMOKE_TURNS[json.loads(v)["lane"]][k % 3]) for p, v, k in rows]


def fused_kernels() -> dict[str, str]:
    import inspect

    from transformers.models.qwen3_5 import modeling_qwen3_5 as qwen

    impl = {n: inspect.getclosurevars(getattr(qwen, n)).nonlocals for n in FUSED}
    return kernel_verdict({n: c["implementation"].__module__ for n, c in impl.items()})


def kernel_verdict(impl_modules: Mapping[str, str]) -> dict[str, str]:
    """{wrapper: implementation module}; raises unless all are the fused kernels."""
    bad = {n: m for n, m in impl_modules.items() if m.split(".")[0] != FUSED.get(n)}
    if bad or set(impl_modules) != set(FUSED):
        raise RuntimeError(f"GDN/conv on the torch fallback, not fused kernels: {bad}")
    return dict(impl_modules)


def target_report(trainable: Iterable[str]) -> dict[str, Any]:
    """LoRA modules per target in trainable parameter names; raises unless the set is
    exactly the served targets on every layer that has them."""
    names = list(trainable)
    modules = sorted({m[1] for n in names if (m := LORA_PARAM.fullmatch(n))})
    per = {
        f"{p}.{q}": sum(m.endswith(f".{p}.{q}") for m in modules) for p, q in TARGETS
    }
    bad = [n for n in names if not LORA_PARAM.fullmatch(n)]
    if bad or 0 in per.values():
        raise RuntimeError(f"not exactly the served targets: {per}, untargeted {bad}")
    return {"lora_modules": len(modules), "per_target": per}


def latest_checkpoint(ckpt_dir: Path) -> Path | None:
    """Highest-step complete checkpoint; Trainer writes trainer_state.json last."""
    done = [
        (int(m[1]), p)
        for p in ckpt_dir.glob("checkpoint-*")
        if (m := re.fullmatch(r"checkpoint-(\d+)", p.name))
        and (p / "trainer_state.json").is_file()
    ]
    return max(done)[1] if done else None


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n")  # never lose a run


def peft_model(path: str, *, meta: bool) -> tuple[Any, dict[str, Any]]:
    """(PEFT model over TARGET_REGEX, report with the base named_modules())."""
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoConfig
    from transformers import AutoModelForImageTextToText as Auto

    if meta:
        cfg = AutoConfig.from_pretrained(path, revision=config.MODEL_REVISION)
        with torch.device("meta"):
            model = Auto.from_config(cfg, dtype=torch.bfloat16)
    else:
        model = Auto.from_pretrained(path, dtype=torch.bfloat16, device_map="cuda")
    modules = [[n, type(m).__name__] for n, m in model.named_modules()]
    model = get_peft_model(model, LoraConfig(**LORA, target_modules=TARGET_REGEX))
    trainable, total = model.get_nb_trainable_parameters()
    names = [n for n, p in model.named_parameters() if p.requires_grad]
    report = {**target_report(names), "trainable_params": trainable}
    return model, {**report, "all_params": total, "named_modules": modules}


def runtime() -> dict[str, Any]:
    import torch

    smi = ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]
    gpu, driver = subprocess.check_output(smi, text=True).strip().split(", ")
    return {
        "provider": "modal",
        "gpu_name": gpu,
        "driver_version": driver,
        "torch_cuda": torch.version.cuda,
        "modal_image_id": os.environ.get("MODAL_IMAGE_ID"),
        "image_spec": {"base": "debian_slim python 3.12", "pins": PINS},
        "versions": {d: metadata.version(d) for d in DISTS},
    }


def train(
    model_dir: Path, run_dir: Path, views: list[tuple[str, str]], commit: Callable
) -> dict[str, Any]:
    """The S0 smoke: resumable, P5 on the real batch, adapter + merged BF16 copy."""
    if (done := run_dir / "result.json").is_file():
        return json.loads(done.read_text())
    import torch
    from datasets import Dataset
    from transformers import AutoTokenizer, TrainerCallback
    from trl import SFTConfig, SFTTrainer

    from proxyloop.contract.views import FastView
    from proxyloop.training import dataset, masking

    kernels = fused_kernels()  # before the model loads: a fallback aborts the run
    tok = AutoTokenizer.from_pretrained(model_dir)
    parsed = [(p, FastView.model_validate_json(v), t) for p, v, t in smoke_rows(views)]
    rows = [dataset.build_row(v, p, t, tok) for p, v, t in parsed]
    data = [dataset.tokenize_row(r, tok) for r in rows]
    targets = {
        tuple(d["input_ids"]): r.completion for d, r in zip(data, rows, strict=True)
    }
    model, lora = peft_model(str(model_dir), meta=False)
    del lora["named_modules"]

    class Stream(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            line = json.dumps({"step": state.global_step, **(logs or {})})
            print(line, flush=True)
            with (run_dir / "metrics.jsonl").open("a") as f:
                f.write(line + "\n")

        def on_save(self, args, state, control, **kwargs):
            commit()  # a preempted restart resumes from here

    run_dir.mkdir(parents=True, exist_ok=True)
    args = SFTConfig(output_dir=str(run_dir / "checkpoints"), **SMOKE)
    train_set = Dataset.from_list(data)
    trainer = SFTTrainer(model, args, train_dataset=train_set, processing_class=tok)
    trainer.add_callback(Stream())
    batch = next(iter(trainer.get_train_dataloader()))
    p5 = masking.verify_batch({k: v.tolist() for k, v in batch.items()}, tok, targets)
    if not all(r["ok"] for r in p5):
        raise RuntimeError(f"P5 failed on the first batch: {p5}")
    sampler, plan = trainer._get_train_sampler(), []
    epochs = math.ceil(args.max_steps * args.gradient_accumulation_steps / len(sampler))
    for epoch in range(epochs):
        sampler.set_epoch(epoch)
        plan += list(sampler)
    worst = dataset.max_padded_tokens(plan, [len(d["input_ids"]) for d in data])
    resume = latest_checkpoint(run_dir / "checkpoints")
    torch.cuda.reset_peak_memory_stats()
    out = trainer.train(resume_from_checkpoint=str(resume) if resume else None).metrics
    peak_gib = torch.cuda.max_memory_allocated() / 2**30  # before the merge
    if any(not p.abs().max() > 0 for n, p in model.named_parameters() if "lora_B" in n):
        raise RuntimeError("a lora_B tensor is still zero after training")
    model.peft_config["default"].base_model_name_or_path = config.MODEL_ID
    model.peft_config["default"].revision = config.MODEL_REVISION
    model.save_pretrained(run_dir / "adapter")
    commit()
    model.merge_and_unload().save_pretrained(run_dir / "merged")
    tok.save_pretrained(run_dir / "merged")
    files = sorted(f for f in (run_dir / "adapter").iterdir() if f.is_file())
    shas = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    result = {
        "run_id": run_dir.name,
        "model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
        "target_regex": TARGET_REGEX,
        "lora": {**LORA, **lora},
        "sft_config": args.to_dict(),
        "fused_kernels": kernels,
        "p5": {"ok": True, "rows": p5},
        "fingerprints": sorted({r.fingerprint for r in rows}),
        "resumed_from": resume and resume.name,
        "max_microbatch_padded_tokens": worst,
        "train": out,
        "tokens": trainer._total_train_tokens,  # non-pad tokens, this segment
        "tokens_per_s": trainer._total_train_tokens / out["train_runtime"],
        "peak_mem_gib": peak_gib,
        "adapter_sha256": shas,
        "runtime": runtime(),
    }
    write_json(done, result)
    commit()
    return result


if __name__ == "__main__":
    import peft
    import torch
    import transformers

    doc = {
        "model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
        "device": "meta",
        "versions": {m.__name__: m.__version__ for m in (torch, transformers, peft)},
        "target_regex": TARGET_REGEX,
        **peft_model(config.MODEL_ID, meta=True)[1],
    }
    write_json(Path(sys.argv[1]), doc)
