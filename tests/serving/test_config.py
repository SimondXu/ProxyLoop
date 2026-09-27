import os
import re
import subprocess
from pathlib import Path

import pytest

from serving import config

ROOT = Path(__file__).resolve().parents[2]
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


def test_the_4b_runs_the_9b_engine_flags_without_lora_slots():
    """C3: base Qwen3.5-4B on the same app definition; only the model changes."""
    assert config.lora_slots("all", "/adapters", model="4b") == {}
    args = config.serve_args("/hf/4b", "pinned", {}, "4b")
    nine = config.serve_args(MODEL, "pinned", SLOTS)
    assert flag_value(args, "--served-model-name") == "Qwen3.5-4B"
    assert {"--language-model-only", "--enable-lora"} <= set(args)
    same = nine[3 : nine.index("--lora-modules")]  # everything but the slots
    assert args == ["vllm", "serve", "/hf/4b"] + [
        "Qwen3.5-4B" if a == "Qwen3.5-9B" else a for a in same
    ]


def test_a_trained_slot_is_never_served_on_the_4b():
    with pytest.raises(ValueError, match="9B adapter"):
        config.lora_slots("all", "/adapters", "Qwen3.5-9B-pl-x=a/b", "4b")


def test_app_names_by_model_and_variant(monkeypatch: pytest.MonkeyPatch):
    assert config.app_name("pinned", "4b") == "proxyloop-vllm-4b"
    assert config.app_name("prefix-align", "4b") == "proxyloop-vllm-4b-prefix-align"
    monkeypatch.setenv(config.MODEL_ENV, "4b")  # a stray shell never redirects the 9B
    assert config.app_name("pinned") == config.app_name("pinned", "9b")
    assert config.app_name("pinned") == "proxyloop-vllm"
    with pytest.raises(ValueError, match="unknown model"):
        config.app_name("pinned", "8b")


def make(*argv: str, env: dict[str, str], mk: str = "mk/mod.mk") -> str:
    """``make -n`` unless argv says otherwise: it only prints, never reaches Modal.

    The child ignores an outer make's flags (CI's ``make check`` passes ``w``), so
    no "Entering directory" line wraps the recipe.
    """
    outer = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}
    base = {k: v for k, v in os.environ.items() if k not in outer}
    run = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-f",
            mk,
            *(argv if "-s" in argv else ("-n", *argv)),
        ],
        cwd=ROOT,
        env=base | env,
        capture_output=True,
        text=True,
        check=True,
    )
    return run.stdout


STRAY = {"PL_SERVE_MODEL": "4b", "SERVE_MODEL": "4b", "MODEL": "4b"}


def test_the_outer_makes_print_directory_flag_never_reaches_the_child(
    monkeypatch: pytest.MonkeyPatch,
):
    # CI runs these tests under `make check`, whose MAKEFLAGS carries `w`.
    monkeypatch.setenv("MAKEFLAGS", "w")
    monkeypatch.setenv("MAKELEVEL", "1")
    assert "directory" not in make("serve-down", env={})


def test_a_stray_shell_never_redirects_the_9b_targets(tmp_path: Path):
    probe = make("serve-probe", env=STRAY)
    assert set(re.findall(r"proxyloop-vllm[\w-]*", probe)) == {"proxyloop-vllm"}
    assert "--model 9b" in probe and "4b" not in probe
    down = make("serve-down", env={"MODEL": "4b", "PL_SERVE_MODEL": "4b"})
    assert down.split()[-1] == "proxyloop-vllm"
    # What a deploy sees: every recipe but serve-up/serve-down exports the 9B (the
    # pull-through and liveness deploys included).
    show = tmp_path / "show.mk"
    show.write_text(f"include {ROOT}/mk/mod.mk\nshow:\n\t@echo $$PL_SERVE_MODEL\n")
    assert make("-s", "show", env=STRAY, mk=str(show)).strip() == "9b"


def test_serve_model_4b_selects_the_4b_app_for_serve_up_and_down_only():
    up = make("serve-up", "SERVE_MODEL=4b", env={})
    assert "--model 4b" in up and "vllm-coldstart-4b.json" in up
    assert up.rstrip().endswith("proxyloop-vllm-4b; exit 1; }")
    down = make("serve-down", "SERVE_MODEL=4b", env={})
    assert down.split()[-1] == "proxyloop-vllm-4b"


def test_model_pins():
    assert config.MODELS["9b"] == (
        config.MODEL_ID,
        config.MODEL_REVISION,
        config.SERVED_NAME,
    )
    hf_id, revision, served = config.MODELS["4b"]
    assert (hf_id, served) == ("Qwen/Qwen3.5-4B", "Qwen3.5-4B")
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
