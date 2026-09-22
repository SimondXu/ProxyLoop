#!/usr/bin/env python
"""Phase 03C Stage 2: LoRA SFT of Qwen/Qwen3-8B with TRL + PEFT on one GPU.

Reads only the cloud bundle (``bundle-manifest.json``, ``train.jsonl``,
``valid.jsonl``, ``dev-eval.jsonl``, ``schema.json``) and
``configs/lora-8b.json``.  Every eval step generates greedily over a
stratified development subset, scores it with ``scoring.py``, appends to
``dev-evals.jsonl``, and the run ends with ``run-manifest.json``, the
selected adapter under ``adapter/`` and, with ``--merge``, merged bf16
weights under ``merged/``.  Checkpoints are selected by the contract rule,
never by loss.
"""

import argparse
import hashlib
import json
import platform
import shutil
import sys
import time
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring  # noqa: E402

RUN_MANIFEST_SCHEMA_VERSION = "phase-03c-cloud-run-v1"
DEV_EVALS_FILENAME = "dev-evals.jsonl"
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
PACKAGES = (
    "torch",
    "transformers",
    "trl",
    "peft",
    "accelerate",
    "datasets",
    "pydantic",
    "vllm",
)


def log(message: str) -> None:
    print(f"[train] {time.strftime('%H:%M:%S')} {message}", flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def package_versions() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    versions["python"] = platform.python_version()
    return versions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=HERE / "configs/lora-8b.json")
    parser.add_argument(
        "--full-dev",
        action="store_true",
        help="generate over all dev-eval rows at every eval step (slow)",
    )
    parser.add_argument("--merge", action="store_true", help="also export merged bf16")
    parser.add_argument(
        "--per-device-train-batch-size", type=int, default=None, help="config override"
    )
    parser.add_argument(
        "--gradient-accumulation-steps", type=int, default=None, help="config override"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="32 train rows, 4 optimizer steps, eval every 2, 1 dev row per family",
    )
    return parser.parse_args()


# --- data -------------------------------------------------------------------


def render_prompt(tokenizer, messages: list[dict]) -> str:
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )


def template_exposes_generation_mask(tokenizer, messages: list[dict]) -> bool:
    """True when ``{% generation %}`` markers give a non-empty assistant mask."""

    template = tokenizer.chat_template or ""
    if "{% generation %}" not in template and "{%- generation %}" not in template:
        return False
    try:
        rendered = tokenizer.apply_chat_template(
            messages,
            return_assistant_tokens_mask=True,
            return_dict=True,
            enable_thinking=False,
        )
    except Exception:
        return False
    mask = rendered.get("assistant_masks") if hasattr(rendered, "get") else None
    return bool(mask) and any(mask)


def render_rows(tokenizer, rows: list[dict], masking: str) -> list[dict]:
    """Rows in the shape TRL consumes for the detected masking mode.

    ``prompt_completion``: text pre-rendered with ``enable_thinking=False`` so
    the trained span starts right after the empty ``<think></think>`` block
    the evaluator's generation prompt also supplies; the completion ends with
    the tokenizer's EOS (``<|im_end|>``) so TRL appends nothing.
    """

    output = []
    for row in rows:
        messages = row["messages"]
        if masking == "assistant_only_loss":
            output.append({"messages": messages})
            continue
        prompt = render_prompt(tokenizer, messages[:2])
        completion = messages[2]["content"] + tokenizer.eos_token
        output.append({"prompt": prompt, "completion": completion})
    return output


def token_lengths(tokenizer, rows: list[dict]) -> list[int]:
    lengths = []
    for row in rows:
        text = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, enable_thinking=False
        )
        lengths.append(len(tokenizer(text, add_special_tokens=False)["input_ids"]))
    return lengths


def apply_overflow_policy(
    rows: list[dict], lengths: list[int], max_length: int, policy: str
) -> tuple[list[dict], dict]:
    over = [index for index, length in enumerate(lengths) if length > max_length]
    stats = {
        "rows": len(rows),
        "max": max(lengths) if lengths else None,
        "p95": scoring.percentile(lengths, 0.95),
        "total": sum(lengths),
        "max_length": max_length,
        "over_max_length": len(over),
        "over_max_length_prompt_ids": [
            rows[index].get("prompt_id") for index in over[:20]
        ],
        "policy": policy,
    }
    if not over:
        return rows, stats
    if policy == "fail":
        raise SystemExit(
            f"{len(over)} rows exceed max_length={max_length}; raise max_length "
            "in the config or set overflow_policy to drop/truncate"
        )
    if policy == "drop":
        keep = set(range(len(rows))) - set(over)
        return [rows[index] for index in sorted(keep)], stats
    if policy == "truncate":
        # TRL right-truncates to max_length, cutting the assistant target;
        # recorded as a deliberate choice, never the default.
        return rows, stats
    raise SystemExit(f"unknown overflow_policy: {policy}")


def stratified_subset(rows: list[dict], per_family: int) -> list[dict]:
    """First ``per_family`` rows per family in (family, seed, config, position)
    order, the same subset ``phase03c_training.dev_eval.select_rows`` takes."""

    ordered = sorted(
        rows,
        key=lambda row: (
            row["family_id"],
            row["seed"],
            row["configuration_id"],
            row["position_index"],
        ),
    )
    taken: dict[str, int] = {}
    subset = []
    for row in ordered:
        if taken.get(row["family_id"], 0) < per_family:
            taken[row["family_id"]] = taken.get(row["family_id"], 0) + 1
            subset.append(row)
    return subset


# --- generation and scoring --------------------------------------------------


def generate_greedy(
    model, tokenizer, prompts: list[str], max_new_tokens: int, batch_size: int
):
    import torch
    from transformers import GenerationConfig

    stop_ids = sorted(
        {
            tokenizer.eos_token_id,
            *(
                [tokenizer.convert_tokens_to_ids("<|endoftext|>")]
                if "<|endoftext|>" in tokenizer.get_vocab()
                else []
            ),
        }
    )
    generation = GenerationConfig(
        do_sample=False,
        max_new_tokens=max_new_tokens,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=stop_ids,
        temperature=None,
        top_p=None,
        top_k=None,
    )
    outputs: list[dict] = []
    was_training = model.training
    model.eval()
    device = next(model.parameters()).device
    try:
        for start in range(0, len(prompts), batch_size):
            batch = prompts[start : start + batch_size]
            encoded = tokenizer(
                batch, return_tensors="pt", padding=True, add_special_tokens=False
            ).to(device)
            started = time.perf_counter()
            with torch.no_grad():
                generated = model.generate(
                    **encoded, generation_config=generation, use_cache=True
                )
            elapsed_ms = (time.perf_counter() - started) * 1000 / len(batch)
            prompt_length = encoded["input_ids"].shape[1]
            for sequence in generated:
                new_tokens = sequence[prompt_length:]
                text = tokenizer.decode(new_tokens, skip_special_tokens=True)
                emitted = int((new_tokens != tokenizer.pad_token_id).sum().item())
                outputs.append(
                    {
                        "raw_output": text,
                        "output_tokens": emitted,
                        "input_tokens": int(prompt_length),
                        "latency_ms_batch_amortised": round(elapsed_ms, 1),
                    }
                )
    finally:
        if was_training:
            model.train()
    return outputs


def score_rows(rows: list[dict], generated: list[dict]) -> tuple[list[dict], dict]:
    scored = [
        scoring.score_row(row, item["raw_output"])
        for row, item in zip(rows, generated, strict=True)
    ]
    aggregate = scoring.aggregate(scored)
    aggregate["per_family"] = scoring.per_family(
        scored, [row["family_id"] for row in rows]
    )
    return scored, aggregate


class DevEvalCallback:
    """Greedy dev generation + scoring at every Trainer eval step."""

    def __init__(
        self, *, tokenizer_for_generation, dev_rows, dev_eval_cfg, out_dir, full
    ):
        from transformers import TrainerCallback

        class _Callback(TrainerCallback):
            def on_evaluate(inner, args, state, control, **kwargs):
                model = kwargs.get("model")
                if model is not None and state.global_step not in self.evaluated:
                    self.evaluate(model, step=state.global_step, tag="lora")

        self.callback = _Callback()
        self.tokenizer = tokenizer_for_generation
        self.rows = dev_rows
        self.cfg = dev_eval_cfg
        self.selection = "full400" if full else "subset"
        self.prompts = [
            render_prompt(tokenizer_for_generation, r["messages"]) for r in dev_rows
        ]
        self.path = out_dir / DEV_EVALS_FILENAME
        self.evals: list[dict] = []
        self.evaluated: set[int] = set()

    def evaluate(self, model, *, step: int, tag: str) -> dict:
        log(f"dev eval at step {step} ({tag}, {len(self.rows)} rows)")
        started = time.perf_counter()
        generated = generate_greedy(
            model,
            self.tokenizer,
            self.prompts,
            self.cfg["max_new_tokens"],
            self.cfg["batch_size"],
        )
        scored, aggregate = score_rows(self.rows, generated)
        wall = time.perf_counter() - started
        summary = scoring.selection_summary(aggregate, step=step)
        record = {
            "step": step,
            "tag": tag,
            "selection": self.selection,
            "rows": len(self.rows),
            "wall_time_s": round(wall, 1),
            "summary": summary,
            "aggregate": aggregate,
            "outputs": [
                {
                    "prompt_id": row["prompt_id"],
                    "family_id": row["family_id"],
                    **item,
                    "metrics": metrics,
                }
                for row, item, metrics in zip(self.rows, generated, scored, strict=True)
            ],
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.evals.append(record)
        self.evaluated.add(step)
        log(
            f"step {step}: act_agreement={summary['oracle_act_agreement']:.3f} "
            f"policy_violation={summary['policy_violation']} "
            f"unsupported={summary['unsupported_response_violation']} "
            f"schema_valid={summary['schema_valid']:.3f} ({wall:.0f}s)"
        )
        return record


# --- masking self-check -------------------------------------------------------


def verify_trained_span(trainer, tokenizer, expected_completion: str) -> dict:
    """Decode the tokens the collator will train on and compare to the target.

    This is the guard against TRL version drift: whatever the dataset
    pipeline produced, the labels that reach the loss must be exactly the
    assistant JSON plus EOS, and the masked prefix must end with the empty
    thinking block.
    """

    example = trainer.train_dataset[0]
    batch = trainer.data_collator([example])
    labels = batch["labels"][0].tolist()
    input_ids = batch["input_ids"][0].tolist()
    trained = [
        token for token, label in zip(input_ids, labels, strict=True) if label != -100
    ]
    masked = [
        token for token, label in zip(input_ids, labels, strict=True) if label == -100
    ]
    trained_text = tokenizer.decode(trained, skip_special_tokens=False)
    masked_text = tokenizer.decode(masked, skip_special_tokens=False)
    result = {
        "trained_tokens": len(trained),
        "masked_tokens": len(masked),
        "trained_text_equals_target": trained_text == expected_completion,
        "trained_text_equals_target_stripped": (
            trained_text.strip() == expected_completion.strip()
        ),
        "masked_prefix_ends_with_empty_think": masked_text.endswith(
            "<think>\n\n</think>\n\n"
        ),
        "trained_text_head": trained_text[:80],
        "trained_text_tail": trained_text[-40:],
    }
    return result


# --- main ---------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.per_device_train_batch_size is not None:
        config["per_device_train_batch_size"] = args.per_device_train_batch_size
    if args.gradient_accumulation_steps is not None:
        config["gradient_accumulation_steps"] = args.gradient_accumulation_steps
    if args.smoke:
        config.update({"eval_steps": 2, "save_steps": 2, "logging_steps": 1})
        config["dev_eval"]["rows_per_family"] = 1
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    bundle = args.bundle_dir
    manifest = json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((bundle / "schema.json").read_text(encoding="utf-8"))
    schema_ok = scoring.schema_matches(schema)
    log(f"bundle {manifest['dataset_fingerprint'][:12]} schema_matches={schema_ok}")
    if not schema_ok:
        log(
            "WARNING: scoring.py schema differs from bundle schema.json; "
            "scores are still recorded but must be re-scored locally"
        )
    base = manifest["base_model"]["model"]
    revision = manifest["base_model"]["revision"]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    log(f"gpu={gpu} versions={package_versions()}")
    if gpu is None:
        raise SystemExit("CUDA GPU required")

    tokenizer = AutoTokenizer.from_pretrained(base, revision=revision)
    gen_tokenizer = AutoTokenizer.from_pretrained(
        base, revision=revision, padding_side="left"
    )
    for tok in (tokenizer, gen_tokenizer):
        if tok.pad_token_id is None:
            tok.pad_token = "<|endoftext|>"

    train_rows = read_jsonl(bundle / "train.jsonl")
    valid_rows = read_jsonl(bundle / "valid.jsonl")
    dev_rows = read_jsonl(bundle / "dev-eval.jsonl")
    if args.smoke:
        train_rows = train_rows[:32]
        valid_rows = valid_rows[:16]
    for name, rows in (("train", train_rows), ("valid", valid_rows)):
        assert all(
            [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
            for row in rows
        ), f"{name}.jsonl rows must be system/user/assistant"
    masking = (
        "assistant_only_loss"
        if template_exposes_generation_mask(tokenizer, train_rows[0]["messages"])
        else "prompt_completion"
    )
    log(f"loss masking: {masking}")

    train_lengths = token_lengths(tokenizer, train_rows)
    train_rows, train_stats = apply_overflow_policy(
        train_rows, train_lengths, config["max_length"], config["overflow_policy"]
    )
    valid_lengths = token_lengths(tokenizer, valid_rows)
    valid_rows, valid_stats = apply_overflow_policy(
        valid_rows, valid_lengths, config["max_length"], config["overflow_policy"]
    )
    log(
        f"train rows={train_stats['rows']} max_tokens={train_stats['max']} "
        f"over_{config['max_length']}={train_stats['over_max_length']} "
        f"policy={config['overflow_policy']} -> {len(train_rows)} rows"
    )
    train_ds = Dataset.from_list(render_rows(tokenizer, train_rows, masking))
    valid_ds = Dataset.from_list(render_rows(tokenizer, valid_rows, masking))

    dev_subset = (
        dev_rows
        if args.full_dev
        else stratified_subset(dev_rows, config["dev_eval"]["rows_per_family"])
    )
    dev_eval = DevEvalCallback(
        tokenizer_for_generation=gen_tokenizer,
        dev_rows=dev_subset,
        dev_eval_cfg=config["dev_eval"],
        out_dir=args.out_dir,
        full=args.full_dev,
    )
    if dev_eval.path.exists():
        dev_eval.path.unlink()

    model = AutoModelForCausalLM.from_pretrained(
        base, revision=revision, torch_dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    model.config.use_cache = False
    lora = config["lora"]
    peft_config = LoraConfig(
        r=lora["r"],
        lora_alpha=lora["alpha"],
        lora_dropout=lora["dropout"],
        target_modules=list(lora["target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    checkpoints_dir = args.out_dir / "checkpoints"
    sft_kwargs = dict(
        output_dir=str(checkpoints_dir),
        num_train_epochs=config["num_train_epochs"],
        per_device_train_batch_size=config["per_device_train_batch_size"],
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        per_device_eval_batch_size=config["per_device_eval_batch_size"],
        learning_rate=config["learning_rate"],
        lr_scheduler_type=config["lr_scheduler_type"],
        warmup_ratio=config["warmup_ratio"],
        bf16=config["bf16"],
        gradient_checkpointing=config["gradient_checkpointing"],
        gradient_checkpointing_kwargs={"use_reentrant": False},
        seed=config["seed"],
        data_seed=config["seed"],
        eval_strategy="steps",
        eval_steps=config["eval_steps"],
        save_strategy="steps",
        save_steps=config["save_steps"],
        save_only_model=True,
        logging_steps=config["logging_steps"],
        max_length=config["max_length"],
        packing=False,
        report_to="none",
        remove_unused_columns=True,
        dataloader_pin_memory=True,
    )
    if masking == "assistant_only_loss":
        sft_kwargs["assistant_only_loss"] = True
    else:
        sft_kwargs["completion_only_loss"] = True
    if args.smoke:
        sft_kwargs["max_steps"] = 4
    sft_config = SFTConfig(**sft_kwargs)
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        processing_class=tokenizer,
        peft_config=peft_config,
        callbacks=[dev_eval.callback],
    )
    first_target = train_rows[0]["messages"][2]["content"] + tokenizer.eos_token
    span_check = verify_trained_span(trainer, tokenizer, first_target)
    log(f"trained-span self-check: {span_check}")
    if not (
        span_check["trained_text_equals_target_stripped"]
        and span_check["masked_prefix_ends_with_empty_think"]
    ):
        raise SystemExit(
            "the labels reaching the loss are not the assistant JSON after the "
            "empty thinking block; refusing to train (TRL/template drift)"
        )
    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in trainer.model.parameters())
    log(f"trainable parameters: {trainable} / {total} ({100 * trainable / total:.3f}%)")

    # Step 0 = the untuned base measured in the same loop (LoRA B is zero).
    dev_eval.evaluate(trainer.model, step=0, tag="untuned")

    train_started = time.perf_counter()
    train_result = trainer.train()
    train_wall = time.perf_counter() - train_started
    train_metrics = dict(train_result.metrics)
    log_history = [
        {
            key: value
            for key, value in entry.items()
            if key
            in {"step", "epoch", "loss", "eval_loss", "learning_rate", "grad_norm"}
        }
        for entry in trainer.state.log_history
    ]
    final_step = int(trainer.state.global_step)
    final_dir = checkpoints_dir / f"checkpoint-{final_step}"
    if not final_dir.exists():
        trainer.save_model(str(final_dir))
    if final_step not in dev_eval.evaluated:
        dev_eval.evaluate(trainer.model, step=final_step, tag="lora")

    candidates = [
        record["summary"]
        for record in dev_eval.evals
        if record["step"] > 0
        and (checkpoints_dir / f"checkpoint-{record['step']}").exists()
    ]
    selected = scoring.select_checkpoint(candidates)
    untuned = next(r["summary"] for r in dev_eval.evals if r["step"] == 0)
    adapter_dir = args.out_dir / "adapter"
    adapter_hashes: dict[str, str] = {}
    if selected is not None:
        source = checkpoints_dir / f"checkpoint-{selected['step']}"
        if adapter_dir.exists():
            shutil.rmtree(adapter_dir)
        adapter_dir.mkdir(parents=True)
        for name in ADAPTER_FILES:
            shutil.copy2(source / name, adapter_dir / name)
        adapter_hashes = {
            name: sha256_file(adapter_dir / name) for name in ADAPTER_FILES
        }
        log(f"selected step {selected['step']} -> {adapter_dir}")
    else:
        log("no checkpoint has policy_violation == 0; nothing selected")

    merged_hashes: dict[str, str] = {}
    if args.merge and selected is not None:
        log("merging selected adapter into bf16 weights")
        del trainer
        del model
        torch.cuda.empty_cache()
        base_model = AutoModelForCausalLM.from_pretrained(
            base, revision=revision, torch_dtype=torch.bfloat16
        )
        merged = PeftModel.from_pretrained(
            base_model, str(adapter_dir)
        ).merge_and_unload()
        merged_dir = args.out_dir / "merged"
        merged.save_pretrained(str(merged_dir), safe_serialization=True)
        tokenizer.save_pretrained(str(merged_dir))
        merged_hashes = {
            path.name: sha256_file(path)
            for path in sorted(merged_dir.iterdir())
            if path.is_file() and path.suffix in {".safetensors", ".json"}
        }

    run_manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "bundle": {
            "dataset_fingerprint": manifest["dataset_fingerprint"],
            "prompt_version": manifest["prompt_version"],
            "compiler_version": manifest["compiler_version"],
            "train_sha256": manifest["files"]["train.jsonl"]["sha256"],
            "accepted_source": manifest["accepted_source"],
            "git": manifest.get("git"),
        },
        "base_model": manifest["base_model"],
        "config": config,
        "config_hash": config_hash,
        "config_path": args.config.name,
        "loss_masking": masking,
        "trained_span_check": span_check,
        "token_stats": {"train": train_stats, "valid": valid_stats},
        "rows_used": {"train": len(train_rows), "valid": len(valid_rows)},
        "dev_eval": {
            "selection": dev_eval.selection,
            "rows": len(dev_subset),
            "schema_matches_bundle": schema_ok,
            "fields_not_computed_on_cloud": [
                "stale_pin_violation (always False in the adapter path)",
                "verifier end-to-end replay",
            ],
        },
        "trainable_parameters": trainable,
        "total_parameters": total,
        "train_metrics": train_metrics,
        "log_history": log_history,
        "evals": [record["summary"] for record in dev_eval.evals],
        "untuned_baseline": untuned,
        "selected": selected,
        "selected_minus_untuned_act_agreement": (
            selected["oracle_act_agreement"] - untuned["oracle_act_agreement"]
            if selected is not None
            else None
        ),
        "adapter_sha256": adapter_hashes,
        "merged_sha256": merged_hashes,
        "packages": package_versions(),
        "gpu": gpu,
        "wall_time_s": {
            "train": round(train_wall, 1),
            "total": round(time.perf_counter() - started, 1),
        },
        "smoke": args.smoke,
    }
    (args.out_dir / "run-manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    log(f"wrote {args.out_dir / 'run-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
