"""LoRA ladder (ADR-0002): which ARCHITECTURE §13 targets does the pinned vLLM load and apply?
Root-run, its own Modal app: `make -f mk/mod.mk serve-lora-ladder`.

Builds PEFT adapters on a meta-device model (only LoRA tensors are materialised) into the adapters
volume, then compares prompt_logprobs against base in one offline vLLM engine with the served
engine arguments. Per rung R (all | attn-mlp):
  zero-R: lora_B = 0 over R's targets; must equal base within ZERO_MAX_DIFF;
  live-R: lora_B != 0 over R's targets; mean |Δ| must exceed LIVE_MIN_MEAN_DIFF.
Per target, probe-<parent>.<proj> (non-zero on that target only) must also exceed LIVE_MIN_MEAN_DIFF:
that separates an applied module from one vLLM loads but silently ignores. An adapter that holds a
trailing packed member without its leader (config.PACKS_NEEDING_LEADER: in_proj_z without in_proj_qkv)
kills the vLLM 0.29.0 engine, so that leader is added with lora_B = 0. zero-R and live-R are the two
served slots. Each finished record is printed as one JSON line. Any engine exception stops the run: the
result keeps the records so far with aborted_at and the error, and its summary is a failure. Once the
remote function has computed the result it saves it on the adapters volume
(results/lora-ladder-<UTC time>.json) before returning it; if the local process disconnects mid-run the
app stops, and only the JSON lines already streamed survive.
"""

import json
import math
import time
from importlib import metadata
from pathlib import Path

import modal

from serving import config, modal_vllm

app = modal.App("proxyloop-lora-ladder")
image = modal_vllm.base_image.uv_pip_install(
    f"peft=={config.PEFT_VERSION}", f"accelerate=={config.ACCELERATE_VERSION}"
).add_local_python_source("serving")


def build_adapter(model_dir: Path, out_dir: Path, targets, *, zero: bool, zero_targets=frozenset(),
                  seed: int = 20260926) -> None:
    """lora_B = 0 on every target when `zero`, else only on `zero_targets`; lora_A initialised as usual."""
    if not set(zero_targets) <= set(targets):
        raise ValueError(f"zero_targets {sorted(zero_targets)} not in targets {targets}")
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
    layers = [(name, m) for name, m in peft_model.named_modules() if isinstance(m, LoraLayer)]
    counts = zero_layer_counts([name for name, _ in layers], zero_targets)
    if unmatched := sorted(t for t, n in counts.items() if n == 0):
        raise ValueError(f"zero_targets matched no LoRA layer: {unmatched}")
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for name, layer in layers:
            for a, b in zip(layer.lora_A.values(), layer.lora_B.values(), strict=True):
                a.to_empty(device="cpu")
                b.to_empty(device="cpu")
                torch.nn.init.kaiming_uniform_(a.weight, a=math.sqrt(5), generator=generator)
                if zero or layer_target(name) in zero_targets:
                    b.weight.zero_()
                else:
                    b.weight.normal_(std=1e-2, generator=generator)
    peft_model.peft_config["default"].base_model_name_or_path = config.MODEL_ID
    peft_model.peft_config["default"].revision = config.MODEL_REVISION
    peft_model.save_pretrained(out_dir)


def layer_target(module_name: str) -> tuple[str, str]:
    """(parent, proj) of a PEFT module name ending in <parent>.<proj>."""
    parent, proj = module_name.split(".")[-2:]
    return parent, proj


def zero_layer_counts(layer_names: list[str], zero_targets) -> dict[tuple[str, str], int]:
    """How many LoRA layers each zero target matches."""
    counts = dict.fromkeys(zero_targets, 0)
    for name in layer_names:
        if (target := layer_target(name)) in counts:
            counts[target] += 1
    return counts


def adapter_plan() -> dict[str, tuple[tuple, bool, frozenset]]:
    """name -> (targets, zero, zero_targets); missing packed leaders are added with lora_B = 0."""
    def spec(targets: tuple, zero: bool) -> tuple[tuple, bool, frozenset]:
        leaders = config.missing_pack_leaders(targets)
        return (*targets, *leaders), zero, frozenset(leaders)

    plan = {}
    for rung, targets in config.RUNGS.items():
        plan[f"zero-{rung}"], plan[f"live-{rung}"] = spec(targets, True), spec(targets, False)
    plan.update({f"probe-{p}.{m}": spec(((p, m),), False) for p, m in config.RUNGS["all"]})
    return plan


def diff_stats(base: list[list[float]], other: list[list[float]]) -> dict:
    diffs = [abs(x - y) for rb, ro in zip(base, other, strict=True) for x, y in zip(rb, ro, strict=True)]
    return {"max_abs_diff": max(diffs), "mean_abs_diff": sum(diffs) / len(diffs)}


def summarise(results: dict, aborted_at: str | None = None) -> dict:
    """An aborted or incomplete run fails every rung, whatever its finished records say."""
    def live(name: str) -> bool:
        r = results.get(name, {})
        return r.get("loaded", False) and r["mean_abs_diff"] > config.LIVE_MIN_MEAN_DIFF

    def rung_ok(rung: str) -> bool:
        zero = results.get(f"zero-{rung}", {})
        return (zero.get("loaded", False) and zero["max_abs_diff"] <= config.ZERO_MAX_DIFF
                and live(f"live-{rung}") and all(live(f"probe-{p}.{m}") for p, m in config.RUNGS[rung]))

    missing = [name for name in adapter_plan() if name not in results]
    complete = aborted_at is None and not missing
    return {"complete": complete, "aborted_at": aborted_at, "missing_adapters": missing,
            "applied_targets": [f"{p}.{m}" for p, m in config.RUNGS["all"] if live(f"probe-{p}.{m}")],
            **{f"rung_ok:{rung}": complete and rung_ok(rung) for rung in config.RUNGS}}


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def run(model_dir: Path, adapter_root: Path) -> dict:
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    plan = adapter_plan()
    for name, (targets, zero, zero_targets) in plan.items():
        build_adapter(model_dir, adapter_root / name, targets, zero=zero, zero_targets=zero_targets)
    modal_vllm.adapter_volume.commit()
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    pairs = [config.pair_ids(tokenizer, pair) for pair in config.PAIRS]
    llm = LLM(model=str(model_dir), **config.ENGINE_KWARGS)
    params = SamplingParams(max_tokens=1, temperature=0.0, prompt_logprobs=0)

    def logprobs(lora=None) -> list[list[float]]:
        outs = llm.generate([{"prompt_token_ids": ids} for ids, _ in pairs], params,
                            lora_request=lora, use_tqdm=False)
        return [[out.prompt_logprobs[i][ids[i]].logprob for i in range(start, len(ids))]
                for out, (ids, start) in zip(outs, pairs, strict=True)]

    base, results, abort = logprobs(), {}, {}
    for lora_id, (name, (targets, zero, zero_targets)) in enumerate(plan.items(), start=1):
        try:
            adapted = logprobs(LoRARequest(name, lora_id, str(adapter_root / name)))
        except Exception as exc:  # noqa: BLE001 -- not swallowed: stops the run, recorded, summary fails
            # A worker-side LoRA failure kills the V1 engine: no later adapter can be measured.
            abort = {"aborted_at": name, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(abort), flush=True)
            break
        results[name] = {"targets": [f"{p}.{m}" for p, m in targets], "zero_init": zero,
                         "zero_targets": sorted(f"{p}.{m}" for p, m in zero_targets),
                         "loaded": True, **diff_stats(base, adapted)}
        print(json.dumps({name: results[name]}), flush=True)
    return {"model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
            "engine_kwargs": config.ENGINE_KWARGS, "lora_rank": config.LORA_RANK,
            "adapters": results, **abort, "summary": summarise(results, abort.get("aborted_at"))}


@app.function(image=image, gpu=config.GPU, volumes=modal_vllm.VOLUMES, timeout=60 * 60)
def lora_ladder() -> dict:
    runtime = {**modal_vllm.runtime(), "peft_version": metadata.version("peft")}
    result = run(modal_vllm.download_model(), Path(modal_vllm.ADAPTER_DIR))
    # Once computed, the result is on the volume even if returning it to the caller fails. A local
    # disconnect during run() stops the app: then only the JSON lines already streamed survive.
    copy = f"results/lora-ladder-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    result = {**result, "runtime": runtime, "volume_copy": copy}
    write_json(Path(modal_vllm.ADAPTER_DIR) / copy, result)
    modal_vllm.adapter_volume.commit()
    return result


@app.local_entrypoint()
def main(out: str = "docs/decisions/data/vllm-lora-ladder.json") -> None:
    result = lora_ladder.remote()
    print(json.dumps(result["summary"], indent=2))
    if not result["summary"]["aborted_at"]:
        write_json(Path(out), result)
        return
    # An aborted run must not satisfy the serve-up order guard (file exists): never write --out, and
    # move a stale --out from an earlier run aside (that one file only; it is paid data, never deleted).
    stale = Path(out)
    if stale.exists():
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        stale.rename(stale.with_name(f"{stale.stem}.superseded-{stamp}.json"))
    partial = stale.with_suffix(".aborted.json")
    write_json(partial, result)
    raise SystemExit(f"ladder aborted at {result['summary']['aborted_at']}: {result.get('error')}; "
                     f"partial result in {partial}")
