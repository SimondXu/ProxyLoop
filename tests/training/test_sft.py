"""The training job's pure parts: targets = served targets, the module dump, the fused
kernel verdict, resume, pins and the recipe (no torch here)."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from serving import config
from training_jobs import sft

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs/decisions/data"


def load(name: str) -> dict[str, Any]:
    return json.loads((DATA / name).read_text("utf-8"))


def test_train_targets_are_the_served_rung_and_the_ladder_applied_set():
    ladder = load("vllm-lora-ladder.json")["summary"]
    assert ladder["complete"] and ladder["rung_ok:all"]
    assert config.RUNGS["all"] == sft.TARGETS
    assert {f"{p}.{q}" for p, q in sft.TARGETS} == set(ladder["applied_targets"])
    assert config.target_regex(config.RUNGS["all"]) == sft.TARGET_REGEX


def test_every_packed_trailer_trains_with_its_leader():
    # vLLM 0.29.0 kills the engine on an adapter with in_proj_z but no in_proj_qkv.
    assert config.missing_pack_leaders(sft.TARGETS) == ()
    for leader, trailing in config.PACKS_NEEDING_LEADER.values():
        if any(t in sft.TARGETS for t in trailing):
            assert leader in sft.TARGETS


def test_module_dump_targets_only_language_model_layers():
    """docs/decisions/data/peft-modules.json: real PEFT on the meta-device model."""
    dump = load("peft-modules.json")
    assert dump["model"] == {"id": config.MODEL_ID, "revision": config.MODEL_REVISION}
    assert dump["target_regex"] == sft.TARGET_REGEX
    names = [name for name, _ in dump["named_modules"]]
    matched = [n for n in names if re.fullmatch(sft.TARGET_REGEX, n)]
    assert len(matched) == dump["lora_modules"] > 0
    assert any(n.startswith("model.visual.") for n in names)  # the tower exists...
    assert all(
        n.startswith("model.language_model.layers.") for n in matched
    )  # ...untargeted
    layers = {
        k: {n.split(".")[3] for n in matched if n.endswith(k)}
        for k in (
            "linear_attn.in_proj_qkv",
            "linear_attn.in_proj_z",
        )
    }
    assert layers["linear_attn.in_proj_z"] == layers["linear_attn.in_proj_qkv"]
    per = dump["per_target"]
    assert set(per) == {f"{p}.{q}" for p, q in sft.TARGETS} and 0 not in per.values()


def test_target_report_rejects_untargeted_or_missing_trainables():
    prefix = "base_model.model.model.language_model.layers.3"
    names = [
        f"{prefix}.{p}.{q}.lora_{ab}.default.weight"
        for p, q in sft.TARGETS
        for ab in "AB"
    ]
    report = sft.target_report(names)
    assert report["lora_modules"] == len(sft.TARGETS)
    with pytest.raises(RuntimeError, match="untargeted"):
        sft.target_report(
            [*names, "base_model.model.model.visual.blocks.0.attn.qkv.weight"]
        )
    with pytest.raises(RuntimeError, match="served targets"):
        sft.target_report([n for n in names if ".mlp.down_proj." not in n])


def test_fused_kernel_check_fails_on_any_torch_fallback():
    fused = {
        "causal_conv1d_fn": "causal_conv1d.causal_conv1d_interface",
        "causal_conv1d_update": "causal_conv1d.causal_conv1d_interface",
        "torch_chunk_gated_delta_rule": "fla.ops.gated_delta_rule.chunk",
        "torch_recurrent_gated_delta_rule": "fla.ops.gated_delta_rule.fused_recurrent",
    }
    assert sft.fused_kernels(fused) == fused
    torch_ref = "transformers.models.qwen3_5.modeling_qwen3_5"
    for name in fused:
        with pytest.raises(RuntimeError, match="torch fallback"):
            sft.fused_kernels({**fused, name: torch_ref})
    with pytest.raises(RuntimeError):
        sft.fused_kernels({k: v for k, v in fused.items() if "update" not in k})


def test_latest_checkpoint_picks_the_highest_complete_step(tmp_path: Path):
    assert sft.latest_checkpoint(tmp_path / "absent") is None
    for step, complete in ((5, True), (20, True), (100, True), (110, False)):
        ckpt = tmp_path / f"checkpoint-{step}"
        ckpt.mkdir()
        (ckpt / "adapter_model.safetensors").write_bytes(b"x")
        if complete:
            (ckpt / "trainer_state.json").write_text("{}")
    (tmp_path / "tmp-checkpoint-120").mkdir()
    (tmp_path / "tmp-checkpoint-120" / "trainer_state.json").write_text("{}")
    assert sft.latest_checkpoint(tmp_path) == tmp_path / "checkpoint-100"  # not 20
    assert sft.latest_checkpoint(tmp_path / "checkpoint-5") is None


def pin(requirements: list[str], name: str) -> str:
    return next(r for r in requirements if r.startswith(f"{name}=="))


def test_image_pins_match_the_repo_pins():
    project = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))
    dev = project["dependency-groups"]["dev"]
    assert pin(dev, "transformers") in sft.PINS
    assert pin(project["project"]["dependencies"], "pydantic") in sft.PINS
    assert f"peft=={config.PEFT_VERSION}" in sft.PINS
    assert f"accelerate=={config.ACCELERATE_VERSION}" in sft.PINS
    assert all("==" in p or " @ https://" in p for p in sft.PINS)
    mk = (REPO / "mk/mod.mk").read_text("utf-8")
    cpu = set(re.findall(r"--with ((?:torch|transformers|peft|accelerate)==\S+)", mk))
    assert len(cpu) == 4 and cpu <= set(sft.PINS)  # train-modules = the image


def test_recipe_is_training_8_without_packing_or_truncation():
    lora, smoke = sft.LORA, sft.SMOKE
    assert (lora["r"], lora["lora_alpha"]) == (config.LORA_RANK, config.LORA_ALPHA)
    assert lora["lora_dropout"] == 0.05
    assert sft.RECIPE["learning_rate"] == 1e-4 and sft.RECIPE["bf16"] is True
    assert sft.RECIPE["lr_scheduler_type"] == "cosine"
    effective = (
        sft.RECIPE["per_device_train_batch_size"]
        * sft.RECIPE["gradient_accumulation_steps"]
    )
    assert effective == 64
    assert sft.RECIPE["train_sampling_strategy"] == "batch_rebalance"
    for recipe in (sft.RECIPE, smoke):
        assert recipe["max_length"] is None and not recipe.get("packing")
    assert smoke["max_steps"] == 50 and smoke["save_steps"] < smoke["max_steps"]


VIEWS = [("pl_cp_v1", '{"lane": "cp"}')]


def test_a_run_dir_never_resumes_or_returns_under_another_config(tmp_path: Path):
    run = tmp_path / "train" / "r1"
    first = sft.claim_run_dir(run, VIEWS, "a" * 40)
    stored = json.loads((run / "config.json").read_text())
    assert stored["hash"] == first and stored["git_sha"] == "a" * 40
    assert stored["pins"] == list(sft.PINS) and stored["views"] == [list(VIEWS[0])]
    assert sft.claim_run_dir(run, VIEWS, "a" * 40) == first  # same config: resume
    (run / "result.json").write_text("{}")  # a finished run under the first config
    for views, sha in ((VIEWS, "b" * 40), ([*VIEWS, VIEWS[0]], "a" * 40)):
        with pytest.raises(RuntimeError, match=first):
            sft.claim_run_dir(run, views, sha)
    assert json.loads((run / "config.json").read_text())["hash"] == first  # untouched


def test_perf_is_whole_run_or_null_never_a_resumed_segment():
    metrics = {"train_runtime": 110.0, "train_loss": 1.5}
    whole = sft.perf_record(metrics, 50_000, 10.0, 40.0, None)
    assert whole["tokens_per_s"] == 500.0  # 110 s minus 10 s of volume commits
    assert whole["peak_mem_gib"] == 40.0 and whole["train"] == metrics
    part = sft.perf_record(metrics, 20_000, 0.0, 30.0, "checkpoint-30")
    for key in ("train", "tokens", "tokens_per_s", "peak_mem_gib"):
        assert part[key] is None
    assert "checkpoint-30" in part["null_reason"] and part["segment"] == metrics
