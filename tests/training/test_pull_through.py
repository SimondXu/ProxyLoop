"""Pull-through without keys or GPU (TRAINING §9): label selection from bundles built by
the real kernel over the vLLM transport double, rows and P5 under the pinned tokenizer,
the trained serving slot, the pull-through recipe, and the result checks. The Modal,
vLLM and live-session steps are root-run (make pull-through)."""

from __future__ import annotations

import json
import shutil
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest
from tests.contract.samples import QWEN
from tests.golden.tokenizer import load_tokenizer
from tests.kernel.test_p3 import vllm
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.llm.wire import set_env
from tests.support.sessions import fake_config, run

from proxyloop.contract.bundle import MANIFEST, Bundle, read_bundle
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.protocol import fingerprint
from proxyloop.training import pull_through as pt
from serving import config
from training_jobs import sft

FPS = pt.current_fingerprints()


@cache
def tok() -> Any:
    return cast(Any, load_tokenizer())


def on_vllm(*roles: str) -> SessionConfig:
    return SessionConfig.model_validate(
        fake_config().model_dump() | dict.fromkeys(roles, QWEN)
    )


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two bundles: FastC on the base model over the vLLM double, and both lanes."""
    root = tmp_path_factory.mktemp("evidence")
    mp = pytest.MonkeyPatch()
    set_env(mp, "vllm")
    for name, roles in (("cp", ("fast_cp",)), ("both", ("fast_user", "fast_cp"))):
        run(root / name, SCRIPTS, cfg=on_vllm(*roles), until=UNTIL, vllm=vllm())
    mp.undo()
    return root


def bundle(evidence: Path, name: str) -> Bundle:
    (run_dir,) = (evidence / name).iterdir()
    return read_bundle(run_dir)


def test_selection_takes_only_base_turns_served_over_real_http(evidence: Path):
    turns, funnel = pt.select(pt.load_bundles(evidence), FPS)
    cp_only = bundle(evidence, "cp")
    assert funnel["bundles"] == 2 and funnel["turns"] == len(turns) > 0
    assert funnel["not_base_real_http"] >= 1  # cp's FastU is a test_fake
    fake_turns = {
        e.event_id
        for e in cp_only.events
        if e.type == "fast.turn" and e.payload["lane"] == "user"
    }
    assert fake_turns and not fake_turns & {t.event_id for t in turns}
    for t in turns:
        assert t.raw.startswith("Could you lower the price?")
        assert t.profile in FPS and json.loads(t.view)["lane"] in ("user", "cp")


def test_rows_render_through_the_contract_and_pass_p5(evidence: Path):
    turns, funnel = pt.select(pt.load_bundles(evidence), FPS)
    doc = pt.rows_doc(turns, funnel, FPS, tok())
    assert doc["p5"] == {"ok": True, "rows": len(turns), "failed": []}
    assert doc["fingerprint"] == {p: fingerprint(p) for p in ("pl_cp_v1", "pl_user_v1")}
    assert (
        doc["adapter_name"] == f"Qwen3.5-9B-pl-pt-{doc['fp8']}" and len(doc["fp8"]) == 8
    )
    assert doc["rows"] == [[t.profile, t.view, t.raw] for t in turns]
    again = pt.rows_doc(turns, funnel, FPS, tok())
    assert again["dataset_hash"] == doc["dataset_hash"]
    fewer = pt.rows_doc(turns[1:], funnel, FPS, tok())
    assert fewer["dataset_hash"] != doc["dataset_hash"]


def test_p5_fails_loudly_on_nothing_to_train():
    assert pt.p5_rows([], tok())["ok"] is False


def test_at_most_60_turns_newest_bundle_first(evidence: Path):
    one = bundle(evidence, "both")
    turns, funnel = pt.select([one] * 61, FPS)
    assert len(turns) == pt.MAX_TURNS == 60 and funnel["turns"] > 60


def test_stale_fingerprint_non_train_and_test_paths_are_never_labels(
    evidence: Path, tmp_path: Path
):
    (src,) = (evidence / "cp").iterdir()
    stale = tmp_path / "s0" / "stale"
    shutil.copytree(src, stale)
    manifest = json.loads((stale / MANIFEST).read_text("utf-8"))
    manifest["fingerprints"]["pl_cp_v1"] = "0" * 64
    (stale / MANIFEST).write_text(json.dumps(manifest), "utf-8")
    sealed = tmp_path / "s4" / "test" / "run"
    sealed.mkdir(parents=True)
    (sealed / MANIFEST).write_text("sealed: never parsed", "utf-8")
    bundles = pt.load_bundles(tmp_path)  # would raise if it opened the sealed one
    assert len(bundles) == 1
    turns, funnel = pt.select(bundles, FPS)
    assert not turns and funnel["bundle_not_train_or_stale_fingerprint"] == 1


def with_calls(b: Bundle, **update: object) -> Bundle:
    """``b`` with every Fast llm.call payload updated (a copy, never written)."""
    events = tuple(
        e.model_copy(update={"payload": e.payload | update})
        if e.type == "llm.call" and e.payload["role"] in pt.FAST_ROLES
        else e
        for e in b.events
    )
    return Bundle(b.manifest, events, b.prompts)


def test_adapter_truncated_and_unparseable_turns_are_never_labels(evidence: Path):
    b = bundle(evidence, "both")
    assert pt.base_turns(b)[0]
    adapter = with_calls(b, served_model_echo="Qwen3.5-9B-pl-pt-00000000")
    turns, skipped = pt.base_turns(adapter)  # an earlier pull-through's own turns
    assert not turns and skipped["not_base_real_http"] > 0
    turns, skipped = pt.base_turns(with_calls(b, finish_reason="length"))
    assert not turns and skipped["finish_length"] > 0
    ref = QWEN.model_dump(mode="json") | {"kind": "recorded_replay"}
    replay = with_calls(b, adapter_kind="recorded_replay", model_ref=ref)
    assert not pt.base_turns(replay)[0]
    bad = dict(b.prompts)
    for e in b.events:
        if e.type == "llm.call" and e.payload["response_sha"]:
            sha = str(e.payload["response_sha"])
            bad[sha] = bad[sha].model_copy(update={"content": "@dance"})
    turns, skipped = pt.base_turns(Bundle(b.manifest, b.events, bad))
    assert not turns and skipped["empty_or_parse_issue"] > 0


def test_echo_check_needs_both_lanes_on_the_adapter(evidence: Path):
    both, cp_only = bundle(evidence, "both"), bundle(evidence, "cp")
    assert pt.echo_failures(both, config.SERVED_NAME) == []
    assert any("fast_user ran" in f for f in pt.echo_failures(cp_only, "Qwen3.5-9B"))
    other = pt.echo_failures(both, "Qwen3.5-9B-pl-pt-00000000")
    assert any("echoed 'Qwen3.5-9B'" in f for f in other)
    assert any(f.startswith("fast_cp ran") for f in other)


def test_adapter_shas_compare_file_for_file(evidence: Path):
    b = bundle(evidence, "both")
    kept = pt.bundle_shards(b, "Qwen3.5-9B-zero")
    assert kept == {"adapter_model.safetensors": "c" * 64}
    assert pt.shard_failures(kept, kept, "bundle") == []
    assert pt.shard_failures({"adapter_model.safetensors": "d" * 64}, kept, "bundle")
    assert pt.shard_failures(kept, None, "/pl/attest")
    assert pt.bundle_shards(b, "Qwen3.5-9B-pl-pt-00000000") == {}


def write_run(run_dir: Path, fps: dict[str, str]) -> None:
    rows = {"fingerprint": fps, "dataset_hash": "h", "p5": {"ok": True, "rows": 3}}
    rows["adapter_name"] = pt.adapter_name(fps)
    train = {"run_id": "pt-x", "adapter_sha256": {"adapter_config.json": "a" * 64}}
    train |= {"p5": {"ok": True}, "recipe": {}, "lora": {}, "batch_note": "n"}
    pt.write(run_dir / "rows.json", rows)
    pt.write(run_dir / "train.json", train)


def test_slot_serves_the_adapter_just_trained_or_the_last_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write_run(tmp_path, FPS)
    assert pt.main(["slot", "--mode", "full", "--dir", str(tmp_path)]) == 0
    spec = capsys.readouterr().out.strip()
    assert spec == f"{pt.adapter_name(FPS)}=train/pt-x/adapter"
    assert config.trained_slot(spec, "/adapters") == {
        pt.adapter_name(FPS): "/adapters/train/pt-x/adapter"
    }
    card = pt.adapter_card("full", tmp_path)
    monkeypatch.setattr(pt, "RESULT", tmp_path / "result.json")
    pt.write(pt.RESULT, card | {"claim": "none"})
    assert pt.adapter_card("verify", tmp_path)["adapter"] == card["adapter"]
    pt.write(pt.RESULT, card | {"fingerprint": {"pl_cp_v1": "old"}})
    with pytest.raises(SystemExit, match="MODE=full"):
        pt.adapter_card("verify", tmp_path)


def test_select_command_writes_the_rows_the_training_entrypoint_reads(
    evidence: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(pt, "load_tokenizer", tok)
    args = ["select", "--dir", str(tmp_path), "--evidence", str(evidence)]
    assert pt.main(args) == 0
    doc = json.loads((tmp_path / "rows.json").read_text("utf-8"))
    keys = ("source", "dataset_hash", "fingerprint", "adapter_name", "fp8", "rows")
    assert all(k in doc for k in keys) and doc["p5"]["ok"]
    assert all(len(r) == 3 for r in doc["rows"])  # (profile, view, turn): sft.train
    assert pt.main([*args[:2], str(tmp_path / "none"), *args[3:4], "/nonexistent"]) == 1


# --- serving: the trained-adapter slot (ADR-0002) -----------------------------------


def test_trained_slot_is_a_third_named_slot_under_the_adapter_volume():
    spec = "Qwen3.5-9B-pl-pt-1a2b3c4d=train/pt-1/adapter"
    slots = config.lora_slots("all", "/adapters", spec)
    assert len(slots) == 3 <= config.MAX_LORAS
    assert slots["Qwen3.5-9B-pl-pt-1a2b3c4d"] == "/adapters/train/pt-1/adapter"
    assert config.lora_slots("all", "/adapters") == config.lora_slots(
        "all", "/adapters", ""
    )
    args = config.serve_args("/m", "pinned", slots)
    assert "Qwen3.5-9B-pl-pt-1a2b3c4d=/adapters/train/pt-1/adapter" in args
    for bad in (
        "Qwen3.5-9B-live=train/x",  # not a trained name
        "Qwen3.5-9B-pl-=train/x",
        "Qwen3.5-9B-pl-pt-1=",
        "Qwen3.5-9B-pl-pt-1=/abs/path",
        "Qwen3.5-9B-pl-pt-1=train/../../hf",
    ):
        with pytest.raises(ValueError):
            config.lora_slots("all", "/adapters", bad)


def test_only_adapters_vllm_can_load_are_served():
    trained = {"r": sft.LORA_PT["r"], "target_modules": sft.TARGET_REGEX}
    config.check_trained(trained, "all")  # pull-through
    config.check_trained(trained | {"r": sft.LORA["r"]}, "all")  # the smoke adapter
    assert config.adapter_targets(trained) == config.RUNGS["all"]
    z_only = {"r": 8, "target_modules": ["q_proj", "in_proj_z"]}
    with pytest.raises(ValueError, match="in_proj_qkv"):  # kills the engine
        config.check_trained(z_only, "all")
    config.check_trained(
        z_only | {"target_modules": ["in_proj_qkv", "in_proj_z"]}, "all"
    )
    with pytest.raises(ValueError, match="r=64"):
        config.check_trained(trained | {"r": 64}, "all")
    with pytest.raises(ValueError, match="outside the rung"):
        config.check_trained(trained, "attn-mlp")
    with pytest.raises(ValueError):
        config.check_trained({"r": 8, "target_modules": ["visual.qkv"]}, "all")


# --- training_jobs: the pull-through recipe ------------------------------------------


def test_pull_through_recipe_is_training_8_with_a_plumbing_batch():
    assert (sft.LORA_PT["r"], sft.LORA_PT["lora_alpha"]) == (8, 16)
    assert sft.LORA_PT["lora_dropout"] == sft.LORA["lora_dropout"]
    for n, batch in ((1, 1), (5, 5), (6, 6), (7, 7), (8, 8), (60, 8)):
        recipe = sft.pull_through_recipe(n)
        micro = recipe["per_device_train_batch_size"]
        assert micro * recipe["gradient_accumulation_steps"] == batch and micro <= 4
        assert recipe["learning_rate"] == 2e-4 and recipe["max_steps"] == 40
        assert recipe["max_length"] is None and not recipe.get("packing")
    assert "64" in sft.PT_BATCH_NOTE and "curve" in sft.PT_BATCH_NOTE


def test_a_run_dir_is_bound_to_its_recipe_and_lora(tmp_path: Path):
    rows = [["pl_cp_v1", '{"lane": "cp"}', "Hello."]]
    first = sft.claim_run_dir(tmp_path, rows, "a" * 40, sft.PULL_THROUGH, sft.LORA_PT)
    stored = json.loads((tmp_path / "config.json").read_text("utf-8"))
    assert stored["recipe"] == sft.PULL_THROUGH and stored["lora"] == sft.LORA_PT
    assert sft.claim_run_dir(tmp_path, rows, "a" * 40, sft.PULL_THROUGH, sft.LORA_PT)
    for recipe, lora in ((sft.SMOKE, sft.LORA_PT), (sft.PULL_THROUGH, sft.LORA)):
        with pytest.raises(RuntimeError, match=first):
            sft.claim_run_dir(tmp_path, rows, "a" * 40, recipe, lora)


def test_a_dead_adapter_never_reaches_the_session_or_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_run(tmp_path, FPS)
    monkeypatch.setattr(pt, "RESULT", tmp_path / "result.json")
    dead = {"ok": False, "complete": True, "mean_abs_diff": 0.0}
    card = {"adapter_config.json": "a" * 64}

    def probe(name: str) -> dict[str, Any]:
        return {"attested": card, "liveness": dead}

    monkeypatch.setattr(pt, "probe_slot", probe)

    def no_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("the product session ran on a dead adapter")

    monkeypatch.setattr(pt.subprocess, "run", no_session)
    assert pt.check("full", tmp_path, "cp-direct-discount") == 1
    doc = json.loads((tmp_path / "pull-through.json").read_text("utf-8"))
    assert (
        doc["claim"] == "none" and not doc["passed"] and not doc["checks"]["liveness"]
    )
    assert not pt.RESULT.exists()
