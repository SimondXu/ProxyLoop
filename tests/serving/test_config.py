import re

import pytest

from serving import config

MODEL = "/hf/hub/models--Qwen--Qwen3.5-9B/snapshots/rev"
SLOTS = config.lora_slots("all", "/adapters")


def flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_pinned_args_are_architecture_13_with_prefix_caching_off():
    args = config.serve_args(MODEL, "pinned", SLOTS)
    assert args[:3] == ["vllm", "serve", MODEL]
    assert flag_value(args, "--served-model-name") == "Qwen3.5-9B"
    assert flag_value(args, "--dtype") == "bfloat16"
    assert flag_value(args, "--max-lora-rank") == "32"
    assert flag_value(args, "--max-loras") == "4"
    assert flag_value(args, "--max-model-len") == "16384"
    assert flag_value(args, "--port") == "8000"
    assert {
        "--language-model-only",
        "--enable-lora",
        "--no-enable-prefix-caching",
    } <= set(args)
    assert "--enable-prefix-caching" not in args and "--mamba-cache-mode" not in args
    assert flag_value(args, "--middleware") == "serving.attest.AttestMiddleware"
    assert args[-3:] == [
        "--lora-modules",
        "Qwen3.5-9B-zero=/adapters/zero-all",
        "Qwen3.5-9B-live=/adapters/live-all",
    ]


def test_lora_slots_serve_the_zero_and_live_adapter_of_one_rung():
    assert config.lora_slots("attn-mlp", "/a") == {
        "Qwen3.5-9B-zero": "/a/zero-attn-mlp",
        "Qwen3.5-9B-live": "/a/live-attn-mlp",
    }
    with pytest.raises(ValueError):
        config.lora_slots("zero-all", "/a")


def test_api_key_never_in_argv():
    for variant in config.VARIANTS:
        assert not any(
            "api-key" in a or "KEY" in a
            for a in config.serve_args(MODEL, variant, SLOTS)
        )


def test_prefix_align_variant_is_separate_and_measure_only():
    args = config.serve_args(MODEL, "prefix-align", SLOTS)
    assert (
        "--enable-prefix-caching" in args and "--no-enable-prefix-caching" not in args
    )
    assert flag_value(args, "--mamba-cache-mode") == "align"
    assert (
        config.app_name("prefix-align") != config.app_name("pinned") == "proxyloop-vllm"
    )
    with pytest.raises(ValueError):
        config.serve_args(MODEL, "prefix", SLOTS)


def test_engine_kwargs_mirror_the_served_flags():
    args = config.serve_args(MODEL, "pinned", SLOTS)
    kw = config.ENGINE_KWARGS
    assert kw["served_model_name"] == flag_value(args, "--served-model-name")
    assert kw["dtype"] == flag_value(args, "--dtype")
    assert str(kw["max_lora_rank"]) == flag_value(args, "--max-lora-rank")
    assert str(kw["max_loras"]) == flag_value(args, "--max-loras")
    assert str(kw["max_model_len"]) == flag_value(args, "--max-model-len")
    assert (
        kw["language_model_only"]
        and kw["enable_lora"]
        and kw["enable_prefix_caching"] is False
    )


def test_pins_are_exact():
    assert re.fullmatch(r"[0-9a-f]{40}", config.MODEL_REVISION)
    assert re.fullmatch(r"vllm/vllm-openai@sha256:[0-9a-f]{64}", config.VLLM_IMAGE)
    for version in (
        config.VLLM_VERSION,
        config.PEFT_VERSION,
        config.ACCELERATE_VERSION,
    ):
        assert re.fullmatch(r"\d+\.\d+\.\d+", version)


# Module names as they appear in the pinned checkpoint's weight index (minus ".weight").
LANG = "model.language_model.layers.{}."
ALL_TARGETS = [
    *(
        LANG.format(3) + f"self_attn.{p}"
        for p in ("q_proj", "k_proj", "v_proj", "o_proj")
    ),
    *(
        LANG.format(0) + f"linear_attn.{p}"
        for p in ("in_proj_qkv", "in_proj_z", "in_proj_b", "in_proj_a", "out_proj")
    ),
    *(LANG.format(31) + f"mlp.{p}" for p in ("gate_proj", "up_proj", "down_proj")),
]
NEVER = [
    "model.visual.blocks.0.attn.qkv",
    "model.visual.blocks.0.mlp.linear_fc1",
    "model.visual.merger.linear_fc1",
    "mtp.layers.0.self_attn.q_proj",
    "mtp.layers.0.mlp.up_proj",
    "mtp.fc",
    "lm_head",
    "model.language_model.embed_tokens",
    LANG.format(3) + "self_attn.q_norm",
    LANG.format(0) + "linear_attn.conv1d",
    LANG.format(0) + "linear_attn.norm",
]


def test_rung_1_regex_matches_every_target_and_nothing_else():
    regex = re.compile(config.target_regex(config.RUNGS["all"]))
    assert all(regex.fullmatch(name) for name in ALL_TARGETS)
    assert not any(regex.fullmatch(name) for name in NEVER)


def test_rung_2_regex_drops_the_gdn_projections():
    regex = re.compile(config.target_regex(config.RUNGS["attn-mlp"]))
    matched = {name for name in ALL_TARGETS if regex.fullmatch(name)}
    assert matched == {n for n in ALL_TARGETS if "linear_attn" not in n}
    assert len(matched) == 7


def test_five_fixed_pairs():
    assert len(config.PAIRS) == 5
    assert all(
        msgs[-1]["role"] == "user" and completion for msgs, completion in config.PAIRS
    )
