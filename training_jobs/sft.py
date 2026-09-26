"""BF16 LoRA SFT on Qwen3.5-9B (ADR-0003, TRAINING §8), run by modal_train.py; run as
a script, the CPU named_modules() dump. Torch, peft, trl and proxyloop load lazily."""

# pyright: basic, reportMissingImports=false

import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

from serving import config

# torch 2.13 brings triton 3.7.1 (fla #640); causal-conv1d is built from source.
BASE_IMAGE = "nvidia/cuda:12.9.1-devel-ubuntu24.04"
TORCH, TORCH_INDEX = "torch==2.13.0", "https://download.pytorch.org/whl/cu129"
REST = ("transformers==5.17.0", "trl==1.14.0", "datasets==5.0.1", "pydantic==2.13.5")
REST += ("huggingface_hub==1.33.0", "flash-linear-attention==0.5.2", "fla-core==0.5.2")
REST += (f"peft=={config.PEFT_VERSION}", f"accelerate=={config.ACCELERATE_VERSION}")
REST += ("setuptools==84.0.0", "wheel==0.48.0", "ninja==1.13.2", "packaging==26.3")
CONV1D = "causal-conv1d==1.7.0"
PINS = (TORCH, *REST, CONV1D)
DISTS = (*(p.split("==")[0] for p in PINS), "triton")
TARGETS = config.RUNGS["all"]  # the served rung (ADR-0002): train = serve
TARGET_REGEX = config.target_regex(TARGETS)
LORA: dict[str, Any] = {"r": config.LORA_RANK, "lora_alpha": config.LORA_ALPHA}
LORA["lora_dropout"] = 0.05  # TRAINING §8
LORA_PARAM = re.compile(rf"base_model\.model\.({TARGET_REGEX})\.lora_[AB]\.\w+\.weight")
# Wrappers in transformers 5.17.0 modeling_qwen3_5 -> the package of the fused kernel.
FUSED = {"causal_conv1d_fn": "causal_conv1d", "causal_conv1d_update": "causal_conv1d"}
FUSED |= {
    "torch_chunk_gated_delta_rule": "fla",
    "torch_recurrent_gated_delta_rule": "fla",
}
# SFTConfig kwargs over the defaults (TRAINING §8, ADR-0003): no packing, no truncation.
RECIPE: dict[str, Any] = {"learning_rate": 1e-4, "lr_scheduler_type": "cosine"}
RECIPE |= {"warmup_steps": 0.03, "bf16": True, "num_train_epochs": 2, "seed": 20260926}
RECIPE |= {"per_device_train_batch_size": 8, "gradient_accumulation_steps": 8}
RECIPE |= {"train_sampling_strategy": "batch_rebalance", "gradient_checkpointing": True}
RECIPE |= {
    "max_length": None,
    "save_steps": 100,
    "save_total_limit": 2,
    "logging_steps": 1,
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
    rows = [(*views[i % len(views)], i // len(views)) for i in range(n)]
    return [(p, v, SMOKE_TURNS[json.loads(v)["lane"]][k % 3]) for p, v, k in rows]


def fused_kernels(impl: Mapping[str, str] | None = None) -> dict[str, str]:
    """{wrapper: its import-time `implementation` module}; raises unless all fused."""
    if impl is None:
        from transformers.models.qwen3_5 import modeling_qwen3_5 as qwen

        cells = {n: inspect.getclosurevars(getattr(qwen, n)).nonlocals for n in FUSED}
        impl = {n: c["implementation"].__module__ for n, c in cells.items()}
    bad = {n: m for n, m in impl.items() if m.split(".")[0] != FUSED.get(n)}
    if bad or set(impl) != set(FUSED):
        raise RuntimeError(f"GDN/conv on the torch fallback, not fused kernels: {bad}")
    return dict(impl)


def gdn_bwd_rule(hopper: bool, t340: bool, t371: bool, tilelang: bool) -> None:
    """fla 0.5.2 chunk_bwd_dqkwg's own refusal (#640), checked before any model load."""
    if hopper and t340 and not t371 and not tilelang:
        raise RuntimeError("fla #640: Hopper, triton in [3.4.0, 3.7.1), no tilelang")


def preflight() -> tuple[dict[str, str], dict[str, Any]]:
    """(fused kernels, runtime) after fla's rule and a tiny GDN + conv fwd/bwd."""
    import torch
    from fla import utils
    from fla.ops.common.backends.tilelang import TileLangBackend
    from transformers.models.qwen3_5 import modeling_qwen3_5 as qwen

    kernels, cuda = fused_kernels(), {"device": "cuda", "dtype": torch.bfloat16}
    flags = (utils.IS_NVIDIA_HOPPER, utils.TRITON_ABOVE_3_4_0, utils.TRITON_ABOVE_3_7_1)
    gdn_bwd_rule(*flags, TileLangBackend.can_use())
    q, k, v = (torch.randn(1, 64, 2, 128, **cuda, requires_grad=True) for _ in "qkv")
    x = torch.randn(1, 128, 64, **cuda, requires_grad=True)  # [batch, dim, time]
    g, beta = -torch.rand(1, 64, 2, device="cuda"), torch.rand(1, 64, 2, **cuda)
    gdn, conv = qwen.torch_chunk_gated_delta_rule, qwen.causal_conv1d_fn
    o = gdn(q, k, v, g=g, beta=beta, use_qk_l2norm_in_kernel=True)[0]
    y = conv(x, torch.randn(128, 4, **cuda), None, activation="silu")
    (o.float().sum() + y.float().sum()).backward()
    if not all(t.grad is not None and t.grad.isfinite().all() for t in (q, k, v, x)):
        raise RuntimeError("preflight backward: missing or non-finite gradients")
    smi = ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]
    gpu, driver = subprocess.check_output(smi, text=True).strip().split(", ")
    rt = {"provider": "modal", "gpu_name": gpu, "driver_version": driver}
    img = os.environ.get("MODAL_IMAGE_ID")
    rt |= {"torch_cuda": torch.version.cuda, "modal_image_id": img}
    rt |= {"image_spec": {"base": BASE_IMAGE, "torch_index": TORCH_INDEX, "pins": PINS}}
    return kernels, rt | {"versions": {d: metadata.version(d) for d in DISTS}}


def target_report(names: list[str]) -> dict[str, Any]:
    """LoRA modules per target; raises unless exactly the served targets train."""
    modules = sorted({m[1] for n in names if (m := LORA_PARAM.fullmatch(n))})
    per = {t: sum(m.endswith("." + t) for m in modules) for t in map(".".join, TARGETS)}
    bad = [n for n in names if not LORA_PARAM.fullmatch(n)]
    if bad or 0 in per.values():
        raise RuntimeError(f"not exactly the served targets: {per}, untargeted {bad}")
    return {"lora_modules": len(modules), "per_target": per}


def latest_checkpoint(ckpt_dir: Path) -> Path | None:
    """Highest-step complete checkpoint; Trainer writes trainer_state.json last."""
    states = ckpt_dir.glob("checkpoint-*/trainer_state.json")
    done = {int(s.parent.name[11:]): s.parent for s in states}
    return done[max(done)] if done else None


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n")  # never lose a run


def claim_run_dir(run_dir: Path, views: list[tuple[str, str]], git_sha: str) -> str:
    """One config per run dir: never resume or return a result under another."""
    body = {"pins": PINS, "target_regex": TARGET_REGEX, "lora": LORA, "smoke": SMOKE}
    body |= {"views": views, "git_sha": git_sha}
    new = hashlib.sha256(json.dumps(body).encode()).hexdigest()
    if not (path := run_dir / "config.json").is_file():
        write_json(path, {"hash": new, **body})
    elif (old := json.loads(path.read_text())["hash"]) != new:
        raise RuntimeError(f"{run_dir} belongs to config {old}, not {new}")
    return new


def perf_record(
    metrics: dict[str, Any], tokens: int, commit_s: float, peak: float, resumed: Any
) -> dict[str, Any]:
    """Whole-run performance; nulls with a reason when only a resumed segment ran."""
    keys = ("train", "tokens", "tokens_per_s", "peak_mem_gib")
    if resumed:
        why = f"resumed from {resumed}: only a segment was measured"
        return {**dict.fromkeys(keys), "null_reason": why, "segment": metrics}
    rate = tokens / (metrics["train_runtime"] - commit_s)  # volume commits excluded
    return dict(zip(keys, (metrics, tokens, rate, peak), strict=True))


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
    report = target_report(names) | {"trainable_params": trainable, "all_params": total}
    return model, report | ({"named_modules": modules} if meta else {})


def train(
    download: Callable, run_dir: Path, views: list, git_sha: str, commit: Callable
) -> dict[str, Any]:
    """The S0 smoke: resumable, P5 on the real batch, adapter + merged BF16 copy."""
    config_hash = claim_run_dir(run_dir, views, git_sha)
    if (done := run_dir / "result.json").is_file():
        return json.loads(done.read_text())
    import torch
    from datasets import Dataset
    from transformers import AutoTokenizer, TrainerCallback
    from trl import SFTConfig, SFTTrainer

    from proxyloop.contract.views import FastView
    from proxyloop.training import dataset, masking

    kernels, rt = preflight()  # before any model download or load
    tok = AutoTokenizer.from_pretrained(model_dir := download())
    parsed = [(p, FastView.model_validate_json(v), t) for p, v, t in smoke_rows(views)]
    rows = [dataset.build_row(v, p, t, tok) for p, v, t in parsed]
    pairs = [(r, dataset.tokenize_row(r, tok)) for r in rows]
    data = [d for _, d in pairs]
    targets = {tuple(d["input_ids"]): r.completion for r, d in pairs}
    model, lora = peft_model(str(model_dir), meta=False)

    class Stream(TrainerCallback):
        commit_s = 0.0

        def on_log(self, args, state, control, logs=None, **kwargs):
            line = json.dumps({"step": state.global_step, **(logs or {})})
            print(line, flush=True)
            with (run_dir / "metrics.jsonl").open("a") as f:
                f.write(line + "\n")

        def on_save(self, args, state, control, **kwargs):
            start = time.monotonic()
            commit()  # a preempted restart resumes from here
            self.commit_s += time.monotonic() - start

    args = SFTConfig(output_dir=str(run_dir / "checkpoints"), **SMOKE)
    train_set = Dataset.from_list(data)
    trainer = SFTTrainer(model, args, train_dataset=train_set, processing_class=tok)
    trainer.add_callback(stream := Stream())
    batch = next(iter(trainer.get_train_dataloader()))
    p5 = masking.verify_batch({k: v.tolist() for k, v in batch.items()}, tok, targets)
    if not all(r["ok"] for r in p5):
        raise RuntimeError(f"P5 failed on the first batch: {p5}")
    sampler, plan = trainer._get_train_sampler(), []
    epochs = args.max_steps * args.gradient_accumulation_steps // len(sampler) + 1
    for epoch in range(epochs):
        sampler.set_epoch(epoch)
        plan += list(sampler)
    worst = dataset.max_padded_tokens(plan, [len(d["input_ids"]) for d in data])
    resume = latest_checkpoint(run_dir / "checkpoints")
    torch.cuda.reset_peak_memory_stats()
    out = trainer.train(resume_from_checkpoint=str(resume) if resume else None).metrics
    if not (perf_file := run_dir / "perf.json").is_file():  # else a finished run's
        peak = torch.cuda.max_memory_allocated() / 2**30  # before the merge
        tokens, resumed = trainer._total_train_tokens, resume and resume.name
        write_json(perf_file, perf_record(out, tokens, stream.commit_s, peak, resumed))
        commit()
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
    result = {"run_id": run_dir.name, "config_hash": config_hash, "git_sha": git_sha}
    result |= {"rows": "synthetic-smoke", "claim": False, "runtime": rt}
    result |= {"model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION}}
    result |= {"lora": {**LORA, **lora, "target_regex": TARGET_REGEX}}
    result |= {"sft_config": args.to_dict(), "fused_kernels": kernels}
    result |= {"p5": {"ok": True, "rows": p5}, "resumed_from": resume and resume.name}
    result |= {"fingerprints": sorted({r.fingerprint for r in rows})}
    result |= {"max_microbatch_padded_tokens": worst, "adapter_sha256": shas}
    result |= json.loads(perf_file.read_text())
    write_json(done, result)
    commit()
    return result


if __name__ == "__main__":
    doc = {"model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION}}
    versions = {d: metadata.version(d) for d in ("torch", "transformers", "peft")}
    doc |= {"versions": versions, "target_regex": TARGET_REGEX}
    write_json(Path(sys.argv[1]), doc | peft_model(config.MODEL_ID, meta=True)[1])
