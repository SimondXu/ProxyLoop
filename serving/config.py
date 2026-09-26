"""The one pinned serving configuration for Qwen3.5-9B on vLLM (ADR-0002,
ARCHITECTURE §13).

Pure data and helpers, imported on the Mac and in the Modal containers.
"""

from typing import Any

MODEL_ID = "Qwen/Qwen3.5-9B"
# HF API "sha", 2026-09-26; not gated.
MODEL_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
SERVED_NAME = "Qwen3.5-9B"
VLLM_VERSION = "0.29.0"
# Docker Hub tag v0.29.0-x86_64 (linux/amd64), pinned by digest.
VLLM_IMAGE = (
    "vllm/vllm-openai"
    "@sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b"
)
PEFT_VERSION, ACCELERATE_VERSION = "0.21.0", "1.15.0"  # LoRA-ladder image only
GPU, PORT = "H100", 8000
# The secret provides VLLM_API_KEY in the container.
APP_NAME = SECRET_NAME = "proxyloop-vllm"
TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "chat_template.jinja",
)
# What enable_thinking=False appends after the assistant tag.
EMPTY_THINK = "<think>\n\n</think>\n\n"
LORA_RANK, LORA_ALPHA, MAX_LORAS, MAX_MODEL_LEN = 32, 64, 4, 16384
# Zero-initialised adapter: prompt_logprobs equal to base within this.
ZERO_MAX_DIFF = 1e-4
LIVE_MIN_MEAN_DIFF = 1e-3  # non-zero adapter: mean |difference| above this (nats)
# Two served LoRA slots, both built for the chosen ladder rung: lora_B = 0, and
# lora_B != 0.
ZERO_LORA_NAME, LIVE_LORA_NAME = "Qwen3.5-9B-zero", "Qwen3.5-9B-live"

# Prefix caching is OFF in the pinned configuration; the other variant is measure-only.
VARIANTS = {
    "pinned": ("--no-enable-prefix-caching",),
    "prefix-align": ("--enable-prefix-caching", "--mamba-cache-mode", "align"),
}
# The offline-engine form of serve_args(), used by the LoRA ladder.
ENGINE_KWARGS = {
    "served_model_name": SERVED_NAME,
    "dtype": "bfloat16",
    "language_model_only": True,
    "enable_lora": True,
    "max_lora_rank": LORA_RANK,
    "max_loras": MAX_LORAS,
    "max_model_len": MAX_MODEL_LEN,
    "enable_prefix_caching": False,
}

# ARCHITECTURE §13 LoRA targets as (parent, projection); never visual.* or mtp.*.
ATTN = tuple(("self_attn", p) for p in ("q_proj", "k_proj", "v_proj", "o_proj"))
GDN = tuple(
    ("linear_attn", p)
    for p in ("in_proj_qkv", "in_proj_z", "in_proj_b", "in_proj_a", "out_proj")
)
MLP = tuple(("mlp", p) for p in ("gate_proj", "up_proj", "down_proj"))
RUNGS = {"all": ATTN + GDN + MLP, "attn-mlp": ATTN + MLP}  # ladder rungs 1 and 2

# vLLM 0.29.0 model_executor/models/qwen3_5.py packed_modules_mapping fuses §13 targets
# for LoRA: qkv_proj = [q, k, v], gate_up_proj = [gate, up], in_proj_ba = [in_proj_b,
# in_proj_a] and in_proj_qkvz = [in_proj_qkv, in_proj_z]. Only in_proj_qkvz has fewer
# members (2) than output slices (4: q, k, v, z), so only it goes through
# lora/layers/column_parallel_linear.py expand_packed_lora, which gives a missing member
# all remaining slices: an adapter with in_proj_z but no in_proj_qkv raises in the
# worker and kills the engine (ladder run, 2026-09-26). The other packs have one member
# per slice and tolerate a missing member. Listed here: packs whose leading member must
# be present, as (leading member, trailing members).
PACKS_NEEDING_LEADER = {
    "in_proj_qkvz": (("linear_attn", "in_proj_qkv"), (("linear_attn", "in_proj_z"),)),
}


def app_name(variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; known: {sorted(VARIANTS)}")
    return APP_NAME if variant == "pinned" else f"{APP_NAME}-{variant}"


def lora_slots(rung: str, adapter_root: str) -> dict[str, str]:
    if rung not in RUNGS:
        raise ValueError(f"unknown rung {rung!r}; known: {sorted(RUNGS)}")
    return {
        ZERO_LORA_NAME: f"{adapter_root}/zero-{rung}",
        LIVE_LORA_NAME: f"{adapter_root}/live-{rung}",
    }


def serve_args(model_path: str, variant: str, slots: dict[str, str]) -> list[str]:
    """argv for `vllm serve`. No API key in argv: vLLM reads VLLM_API_KEY from the
    environment."""
    app_name(variant)
    return [
        "vllm",
        "serve",
        model_path,
        "--served-model-name",
        SERVED_NAME,
        "--dtype",
        "bfloat16",
        "--language-model-only",
        "--enable-lora",
        "--max-lora-rank",
        str(LORA_RANK),
        "--max-loras",
        str(MAX_LORAS),
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--port",
        str(PORT),
        *VARIANTS[variant],
        "--middleware",
        "serving.attest.AttestMiddleware",
        "--lora-modules",
        *(f"{name}={path}" for name, path in slots.items()),
    ]


def target_regex(targets: tuple[tuple[str, str], ...]) -> str:
    """PEFT full-match regex restricted to the language model's decoder layers."""
    parents: dict[str, list[str]] = {}
    for parent, proj in targets:
        parents.setdefault(parent, []).append(proj)
    alts = "|".join(
        f"{parent}\\.(?:{'|'.join(projs)})" for parent, projs in parents.items()
    )
    return f"model\\.language_model\\.layers\\.\\d+\\.(?:{alts})"


def missing_pack_leaders(
    targets: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Leading packed members an adapter over `targets` must add (with lora_B = 0) to
    load in vLLM."""
    return tuple(
        leader
        for leader, trailing in PACKS_NEEDING_LEADER.values()
        if leader not in targets and any(t in targets for t in trailing)
    )


def chat_ids(tokenizer: Any, messages: list[dict[str, str]]) -> list[int]:
    """HF ids as P3 defines them; raises unless they end with the empty-think
    generation prompt."""
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    ids: list[int] = tokenizer.encode(text, add_special_tokens=False)
    tail: list[int] = tokenizer.encode(EMPTY_THINK, add_special_tokens=False)
    if ids[-len(tail) :] != tail:
        raise ValueError(
            f"rendered prompt does not end with the {EMPTY_THINK!r} ids {tail}"
        )
    return ids


def pair_ids(
    tokenizer: Any, pair: tuple[list[dict[str, str]], str]
) -> tuple[list[int], int]:
    """(prompt + completion + <|im_end|> ids, index of the first completion token)."""
    prompt = chat_ids(tokenizer, pair[0])
    completion: list[int] = tokenizer.encode(
        pair[1] + "<|im_end|>", add_special_tokens=False
    )
    return prompt + completion, len(prompt)


# Five fixed synthetic pairs: their messages are the /tokenize parity prompts, and the
# pairs are the adapter-liveness set. They cover a system turn, multi-turn history,
# non-ASCII text (\u00d7 is the multiplication sign) and an assistant turn whose <think>
# block the template strips.
PAIRS = (
    (
        [{"role": "user", "content": "Say hello to the caller."}],
        "Hello, thanks for calling. How can I help today?",
    ),
    (
        [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 17 \u00d7 23?"},
        ],
        "17 \u00d7 23 is 391.",
    ),
    (
        [
            {"role": "system", "content": "You help with a billing question."},
            {"role": "user", "content": "Hi, I have a question about my bill."},
            {"role": "assistant", "content": "Sure — I can help with that."},
            {"role": "user", "content": "Reference 5501-2234: what is due on the 3rd?"},
        ],
        "Let me check what is due on the 3rd for that reference.",
    ),
    (
        [
            {
                "role": "user",
                "content": "Café ☕ 你好 — please confirm the 3:45 pm slot.",
            }
        ],
        "Confirmed: the 3:45 pm slot is yours.",
    ),
    (
        [
            {"role": "user", "content": "Plan a short reply."},
            {"role": "assistant", "content": "<think>\nconsidering\n</think>\n\nOkay."},
            {"role": "user", "content": "Now ask the agent to hold."},
        ],
        "Could you please hold for a moment while I check?",
    ),
)
