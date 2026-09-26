"""LoRA ladder (ADR-0002): which ARCHITECTURE §13 targets does the pinned vLLM load and apply?

Runs in the Modal ladder image. Builds PEFT adapters on a meta-device model (only LoRA tensors
are materialised), then compares prompt_logprobs against base in one offline vLLM engine:
  zero-all / zero-attn-mlp: lora_B = 0 over rung 1 / rung 2; must equal base within 1e-4;
  probe-<parent>.<proj>: one target with non-zero lora_B; "applied" needs a mean |difference|
  above 1e-3 nats, which tells an applied module from one vLLM loads but silently ignores.
A load failure is recorded with its error; nothing is retried.
"""

import math
from pathlib import Path

from serving import config


def build_adapter(model_dir: Path, out_dir: Path, targets, *, zero: bool, seed: int = 20260926) -> None:
    import torch
    from peft import LoraConfig, get_peft_model
    from peft.tuners.lora import LoraLayer
    from transformers import AutoConfig, AutoModelForImageTextToText

    with torch.device("meta"):
        model = AutoModelForImageTextToText.from_config(AutoConfig.from_pretrained(model_dir),
                                                        dtype=torch.bfloat16)
    peft_model = get_peft_model(model, LoraConfig(
        r=config.LORA_RANK, lora_alpha=config.LORA_ALPHA, lora_dropout=0.0, bias="none",
        target_modules=config.target_regex(targets)))
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for layer in (m for m in peft_model.modules() if isinstance(m, LoraLayer)):
            for a, b in zip(layer.lora_A.values(), layer.lora_B.values(), strict=True):
                a.to_empty(device="cpu")
                b.to_empty(device="cpu")
                torch.nn.init.kaiming_uniform_(a.weight, a=math.sqrt(5), generator=generator)
                if zero:
                    b.weight.zero_()
                else:
                    b.weight.normal_(std=1e-2, generator=generator)
    peft_model.peft_config["default"].base_model_name_or_path = config.MODEL_ID
    peft_model.peft_config["default"].revision = config.MODEL_REVISION
    peft_model.save_pretrained(out_dir)


def adapter_plan() -> dict[str, tuple[tuple, bool]]:
    plan = {name: (targets, True) for name, targets in config.RUNGS.items()}
    plan.update({f"probe-{p}.{m}": (((p, m),), False) for p, m in config.RUNGS["zero-all"]})
    return plan


def diff_stats(base: list[list[float]], other: list[list[float]]) -> dict:
    diffs = [abs(x - y) for rb, ro in zip(base, other, strict=True) for x, y in zip(rb, ro, strict=True)]
    return {"max_abs_diff": max(diffs), "mean_abs_diff": sum(diffs) / len(diffs)}


def summarise(results: dict) -> dict:
    def applied(p: str, m: str) -> bool:
        r = results.get(f"probe-{p}.{m}", {})
        return r.get("loaded", False) and r["mean_abs_diff"] > config.LIVE_MIN_MEAN_DIFF

    def rung_ok(name: str) -> bool:
        r = results.get(name, {})
        return (r.get("loaded", False) and r["max_abs_diff"] <= config.ZERO_MAX_DIFF
                and all(applied(p, m) for p, m in config.RUNGS[name]))

    return {"applied_targets": [f"{p}.{m}" for p, m in config.RUNGS["zero-all"] if applied(p, m)],
            **{f"rung_ok:{name}": rung_ok(name) for name in config.RUNGS}}


def run(model_dir: Path, adapter_root: Path) -> dict:
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    plan = adapter_plan()
    for name, (targets, zero) in plan.items():
        build_adapter(model_dir, adapter_root / name, targets, zero=zero)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    pairs = [config.pair_ids(tokenizer, pair) for pair in config.PAIRS]
    llm = LLM(model=str(model_dir), **config.ENGINE_KWARGS)
    params = SamplingParams(max_tokens=1, temperature=0.0, prompt_logprobs=0)

    def logprobs(lora=None) -> list[list[float]]:
        outs = llm.generate([{"prompt_token_ids": ids} for ids, _ in pairs], params,
                            lora_request=lora, use_tqdm=False)
        return [[out.prompt_logprobs[i][ids[i]].logprob for i in range(start, len(ids))]
                for out, (ids, start) in zip(outs, pairs, strict=True)]

    base, results = logprobs(), {}
    for lora_id, (name, (targets, zero)) in enumerate(plan.items(), start=1):
        record = {"targets": [f"{p}.{m}" for p, m in targets], "zero_init": zero}
        try:
            record.update(loaded=True, **diff_stats(base, logprobs(
                LoRARequest(name, lora_id, str(adapter_root / name)))))
        except Exception as exc:  # noqa: BLE001 -- the load failure is the measurement; recorded
            record.update(loaded=False, error=f"{type(exc).__name__}: {exc}")
        results[name] = record
    return {"model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
            "engine_kwargs": config.ENGINE_KWARGS, "lora_rank": config.LORA_RANK,
            "adapters": results, "summary": summarise(results)}
