"""Pull-through without keys or GPU (TRAINING §9): label selection from bundles built by
the real kernel over the vLLM transport double, rows and P5 under the pinned tokenizer,
the trained serving slot, the pull-through recipe, and the result checks. The Modal,
vLLM and live-session steps are root-run (make pull-through)."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
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

from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Bundle,
    PromptRecord,
    read_bundle,
)
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.protocol import PROFILES, fingerprint, render_prompt
from proxyloop.contract.views import FastView
from proxyloop.kernel import lanes
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
        (run_dir,) = (root / name).iterdir()
        served_as_pinned(run_dir)
    mp.undo()
    return root


def served_as_pinned(run_dir: Path) -> None:
    """The kernel under test renders with a fake tokenizer (the P3 double); rewrite
    each Fast prompt as a real vLLM run serves it: the pinned tokenizer's render."""
    b = read_bundle(run_dir)
    prompts, events = dict(b.prompts), list(b.events)
    for i, e in enumerate(events):
        if e.type == "fast.request":
            view = FastView.model_validate_json(
                prompts[str(e.payload["view_sha"])].content
            )
            text = render_prompt(view, str(e.payload["profile"]), tok())
            sha = sha256_text(text)
            prompts[sha] = PromptRecord(sha=sha, kind="prompt", content=text)
            events[i] = e.model_copy(
                update={"payload": e.payload | {"prompt_sha": sha}}
            )
    (run_dir / EVENTS).write_text("".join(e.model_dump_json() + "\n" for e in events))
    lines = (r.model_dump_json() + "\n" for r in prompts.values())
    (run_dir / PROMPTS).write_text("".join(lines))


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
    assert doc["p5"] == {
        "ok": True,
        "rows": len(turns),
        "failed": [],
        "dropped_prompt_mismatch": 0,
    }
    assert doc["fingerprint"] == {p: fingerprint(p) for p in ("pl_cp_v3", "pl_user_v1")}
    assert (
        doc["adapter_name"] == f"Qwen3.5-9B-pl-pt-{doc['fp8']}" and len(doc["fp8"]) == 8
    )
    assert doc["rows"] == [[t.profile, t.view, t.raw] for t in turns]
    again = pt.rows_doc(turns, funnel, FPS, tok())
    assert again["dataset_hash"] == doc["dataset_hash"]
    fewer = pt.rows_doc(turns[1:], funnel, FPS, tok())
    assert fewer["dataset_hash"] != doc["dataset_hash"]


def test_p5_fails_loudly_on_nothing_to_train():
    assert pt.p5_rows([], tok())[1]["ok"] is False


def test_a_label_whose_view_does_not_render_the_served_prompt_is_dropped(
    evidence: Path,
):
    turns, _ = pt.select(pt.load_bundles(evidence), FPS)
    drifted = [dataclasses.replace(turns[0], prompt_sha="0" * 64), *turns[1:]]
    kept, p5 = pt.p5_rows(drifted, tok())
    assert kept == turns[1:] and p5["dropped_prompt_mismatch"] == 1 and p5["ok"]


def test_at_most_60_turns_newest_bundle_first(evidence: Path):
    one = bundle(evidence, "both")
    turns, funnel = pt.select([one] * 61, FPS)
    assert len(turns) == pt.MAX_TURNS == 60 == funnel["selected"]
    assert funnel["dropped_over_cap"] == funnel["turns"] - 60 > 0


def test_stale_fingerprint_non_train_and_test_paths_are_never_labels(
    evidence: Path, tmp_path: Path
):
    (src,) = (evidence / "cp").iterdir()
    stale = tmp_path / "s0" / "stale"
    shutil.copytree(src, stale)
    manifest = json.loads((stale / MANIFEST).read_text("utf-8"))
    manifest["fingerprints"][lanes.PROFILE["cp"]] = "0" * 64  # a recorded profile
    (stale / MANIFEST).write_text(json.dumps(manifest), "utf-8")
    dev = tmp_path / "s0" / "dev"
    shutil.copytree(src, dev)
    manifest = json.loads((dev / MANIFEST).read_text("utf-8"))
    (dev / MANIFEST).write_text(json.dumps(manifest | {"split": "dev"}), "utf-8")
    sealed = tmp_path / "s4" / "test" / "run"
    sealed.mkdir(parents=True)
    (sealed / MANIFEST).write_text("sealed: never parsed", "utf-8")
    bundles = pt.load_bundles(tmp_path)  # would raise if it opened the sealed one
    assert len(bundles) == 2
    turns, funnel = pt.select(bundles, FPS)
    assert not turns and funnel["selected"] == 0
    assert funnel["bundle_stale_fingerprint"] == funnel["bundle_not_train"] == 1


def test_current_means_the_profiles_the_product_path_renders_with(evidence: Path):
    """PROFILES keeps the frozen pl_cp_v1; the kernel renders cp with pl_cp_v3 (I3)."""
    live = {"pl_user_v1", "pl_cp_v3"}
    assert "pl_cp_v1" in PROFILES and set(lanes.PROFILE.values()) == live
    assert pt.current_fingerprints() == {p: fingerprint(p) for p in sorted(live)}
    b = bundle(evidence, "cp")
    assert b.manifest.fingerprints == pt.current_fingerprints()
    turns, funnel = pt.select([b], pt.current_fingerprints())
    assert turns and "bundle_stale_fingerprint" not in funnel


def test_a_bundle_rendered_with_the_frozen_cp_profile_is_stale(
    evidence: Path, tmp_path: Path
):
    """pl_cp_v1's fingerprint is unchanged, but the served adapter never sees its
    prompts: no subset match."""
    (src,) = (evidence / "cp").iterdir()
    old = tmp_path / "old"
    shutil.copytree(src, old)
    manifest = json.loads((old / MANIFEST).read_text("utf-8"))
    manifest["fingerprints"] = {p: fingerprint(p) for p in ("pl_cp_v1", "pl_user_v1")}
    (old / MANIFEST).write_text(json.dumps(manifest), "utf-8")
    turns, funnel = pt.select(pt.load_bundles(tmp_path), pt.current_fingerprints())
    assert not turns and funnel["bundle_stale_fingerprint"] == 1


def test_a_card_on_every_contract_profile_is_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    every = {p: fingerprint(p) for p in sorted(PROFILES)}
    assert every != pt.current_fingerprints()
    write_run(tmp_path, every)
    monkeypatch.setattr(pt, "RESULT", tmp_path / "result.json")
    live = {"ok": True, "complete": True, "mean_abs_diff": 0.5}

    def probe(name: str) -> dict[str, Any]:
        return {"attested": {"adapter_config.json": "a" * 64}, "liveness": live}

    def no_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("the product session ran on a stale card")

    monkeypatch.setattr(pt, "probe_slot", probe)
    monkeypatch.setattr(pt.subprocess, "run", no_session)
    assert pt.check("full", tmp_path, "cp-direct-discount") == 1
    doc = json.loads((tmp_path / "pull-through.json").read_text("utf-8"))
    assert not doc["checks"]["fingerprint_current"] and not pt.RESULT.exists()
    pt.write(pt.RESULT, pt.adapter_card("full", tmp_path) | {"claim": "none"})
    with pytest.raises(SystemExit, match="MODE=full"):
        pt.adapter_card("verify", tmp_path)


def test_an_evidence_root_inside_a_sealed_test_dir_is_refused(
    evidence: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (src,) = (evidence / "cp").iterdir()
    sealed = tmp_path / "evidence" / "s4" / "test"
    shutil.copytree(src, sealed / "families" / "run")  # a real, parseable bundle
    monkeypatch.setattr(pt, "load_tokenizer", tok)
    for root in (sealed, sealed / "families"):  # PT_EVIDENCE=.../test/...
        with pytest.raises(SystemExit, match="sealed test dir"):
            out = ["--dir", str(tmp_path / "out"), "--source", "base_9b"]
            pt.main(["select", *out, "--evidence", str(root)])
    link = tmp_path / "innocent"
    link.symlink_to(sealed / "families")
    with pytest.raises(SystemExit, match="sealed test dir"):
        pt.load_bundles(link)  # resolved, so a symlink does not unseal it
    assert not (tmp_path / "out").exists()


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
    assert pt.label_turns(b)[0]
    adapter = with_calls(b, served_model_echo="Qwen3.5-9B-pl-pt-00000000")
    turns, skipped = pt.label_turns(adapter)  # an earlier pull-through's own turns
    assert not turns and skipped["not_base_real_http"] > 0
    turns, skipped = pt.label_turns(with_calls(b, finish_reason="length"))
    assert not turns and skipped["finish_length"] > 0
    ref = QWEN.model_dump(mode="json") | {"kind": "recorded_replay"}
    replay = with_calls(b, adapter_kind="recorded_replay", model_ref=ref)
    assert not pt.label_turns(replay)[0]
    bad = dict(b.prompts)
    for e in b.events:
        if e.type == "llm.call" and e.payload["response_sha"]:
            sha = str(e.payload["response_sha"])
            bad[sha] = bad[sha].model_copy(update={"content": "@dance"})
    turns, skipped = pt.label_turns(Bundle(b.manifest, b.events, bad))
    assert not turns and skipped["empty_or_parse_issue"] > 0


SPEECH_AFTER_PAUSE = "@hold decision\nSure, one moment."


def cp_saying(b: Bundle, raw: str, profile: str | None = None) -> Bundle:
    """``b`` with every Fast response ``raw`` and, given ``profile``, every cp
    request recorded under it (a copy, never written)."""
    shas = {
        str(e.payload["response_sha"])
        for e in b.events
        if e.type == "llm.call" and e.payload["role"] in pt.FAST_ROLES
    }
    prompts = {
        s: r.model_copy(update={"content": raw}) if s in shas else r
        for s, r in b.prompts.items()
    }
    events = tuple(
        e.model_copy(update={"payload": e.payload | {"profile": profile}})
        if profile and e.type == "fast.request" and e.payload["lane"] == "cp"
        else e
        for e in b.events
    )
    return Bundle(b.manifest, events, prompts)


def test_speech_after_a_pause_is_a_parse_issue_under_the_turn_s_own_profile(
    evidence: Path,
):
    """pl_cp_v3 (ADR-0017): a line after @hold is not clean; under the frozen
    pl_cp_v2 the same turn still is, so the grammar is the request's profile's."""
    b = bundle(evidence, "cp")
    cp = [t for t in pt.label_turns(b)[0] if json.loads(t.view)["lane"] == "cp"]
    assert cp and {t.profile for t in cp} == {lanes.PROFILE["cp"]} == {"pl_cp_v3"}
    turns, skipped = pt.label_turns(cp_saying(b, SPEECH_AFTER_PAUSE))
    assert not turns and skipped["empty_or_parse_issue"] >= len(cp)
    turns, _ = pt.label_turns(cp_saying(b, SPEECH_AFTER_PAUSE, "pl_cp_v2"))
    assert len(turns) == len(cp)
    assert {(t.profile, t.raw) for t in turns} == {("pl_cp_v2", SPEECH_AFTER_PAUSE)}


def test_echo_check_needs_both_lanes_on_the_adapter(evidence: Path):
    both, cp_only = bundle(evidence, "both"), bundle(evidence, "cp")
    assert pt.echo_failures(both, config.SERVED_NAME) == []
    assert any("fast_user ran" in f for f in pt.echo_failures(cp_only, "Qwen3.5-9B"))
    other = pt.echo_failures(both, "Qwen3.5-9B-pl-pt-00000000")
    assert any("echoed 'Qwen3.5-9B'" in f for f in other)
    assert any(f.startswith("fast_cp ran") for f in other)
    failed = with_calls(both, error="cancelled", served_model_echo="Qwen3.5-9B-other")
    out = pt.echo_failures(failed, config.SERVED_NAME)  # errored calls' echoes count
    assert any("echoed 'Qwen3.5-9B-other'" in f for f in out)
    assert {"no served fast_user call", "no served fast_cp call"} <= set(out)


def test_adapter_shas_compare_file_for_file(evidence: Path):
    b = bundle(evidence, "both")
    kept = pt.bundle_shards(b, "Qwen3.5-9B-zero")
    assert kept == {"adapter_model.safetensors": "c" * 64}
    assert pt.shard_failures(kept, kept, "bundle") == []
    assert pt.shard_failures({"adapter_model.safetensors": "d" * 64}, kept, "bundle")
    assert pt.shard_failures(kept, None, "/pl/attest")
    assert pt.bundle_shards(b, "Qwen3.5-9B-pl-pt-00000000") == {}


PROVENANCE = {
    "label_models": [
        {"endpoint": "openrouter", "model_id": "openai/gpt-6-luna"}
        | {"reasoning_effort": "none"}
    ],
    "rows": 3,
    "run_ids": ["r1", "r2"],
}


def write_run(run_dir: Path, fps: dict[str, str]) -> None:
    rows: dict[str, Any] = {"fingerprint": fps, "dataset_hash": "h"}
    rows["p5"] = {"ok": True, "rows": 3}
    rows["adapter_name"] = pt.adapter_name(fps)
    rows["source"] = "hosted openrouter:openai/gpt-6-luna (teacher_exec)"
    ref = {"endpoint": "openrouter", "model_id": "openai/gpt-6-luna"}
    ref["reasoning_effort"] = "none"
    rows["provenance"] = [{"run_id": r, "model_ref": ref} for r in ("r2", "r1", "r2")]
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
    assert card["source"] == "hosted openrouter:openai/gpt-6-luna (teacher_exec)"
    assert card["provenance"] == PROVENANCE
    monkeypatch.setattr(pt, "RESULT", tmp_path / "result.json")
    pt.write(pt.RESULT, card | {"claim": "none"})
    again = pt.adapter_card("verify", tmp_path)
    assert again["adapter"] == card["adapter"]
    assert (again["source"], again["provenance"]) == (card["source"], PROVENANCE)
    pt.write(pt.RESULT, card | {"fingerprint": {"pl_cp_v1": "old"}})
    with pytest.raises(SystemExit, match="MODE=full"):
        pt.adapter_card("verify", tmp_path)


def test_select_command_writes_the_rows_the_training_entrypoint_reads(
    evidence: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(pt, "load_tokenizer", tok)
    base = ["--source", "base_9b"]
    args = ["select", "--dir", str(tmp_path), "--evidence", str(evidence), *base]
    assert pt.main(args) == 0
    doc = json.loads((tmp_path / "rows.json").read_text("utf-8"))
    keys = ("source", "dataset_hash", "fingerprint", "adapter_name", "fp8", "rows")
    assert all(k in doc for k in keys) and doc["p5"]["ok"]
    assert (
        doc["source"] == pt.BASE_9B.label == "base-9B turns (S0 labels, TRAINING §9 E1)"
    )
    assert all(len(r) == 3 for r in doc["rows"])  # (profile, view, turn): sft.train
    assert len(doc["provenance"]) == len(doc["rows"])
    assert {p["model_ref"]["model_id"] for p in doc["provenance"]} == {"Qwen3.5-9B"}
    none = [*args[:2], str(tmp_path / "none"), *args[3:4], "/nonexistent", *base]
    assert pt.main(none) == 1


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


@pytest.mark.parametrize(
    ("exit_code", "name", "card", "failed"),
    [
        (0, "Qwen3.5-9B", {}, None),
        (1, "Qwen3.5-9B", {}, "evidence_check_claim"),
        (0, "Qwen3.5-9B-pl-pt-00000000", {}, "echoes_and_shards"),
        (0, "Qwen3.5-9B", {"adapter_model.safetensors": "d" * 64}, "echoes_and_shards"),
    ],
    ids=["pass", "cli_exit", "echo_mismatch", "shard_mismatch"],
)
def test_check_passes_only_on_a_claimed_bundle_with_the_adapter_echoed_and_attested(
    evidence: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    name: str,
    card: dict[str, str],
    failed: str | None,
):
    """The both-lanes bundle echoes Qwen3.5-9B and attests no Qwen3.5-9B adapter, so a
    card for that name with no files is the passing case."""
    write_run(tmp_path, FPS)
    rows = json.loads((tmp_path / "rows.json").read_text("utf-8"))
    pt.write(tmp_path / "rows.json", rows | {"adapter_name": name})
    train = json.loads((tmp_path / "train.json").read_text("utf-8"))
    pt.write(tmp_path / "train.json", train | {"adapter_sha256": card})
    monkeypatch.setattr(pt, "RESULT", tmp_path / "result.json")
    live = {"ok": True, "complete": True, "mean_abs_diff": 0.5}

    def probe(slot: str) -> dict[str, Any]:
        return {"attested": card, "liveness": live}

    (src,) = (evidence / "both").iterdir()

    def session(
        cli: list[str], check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        assert cli[cli.index("--fast-model") + 1] == name and "--claim" in cli
        runs = Path(cli[cli.index("--runs") + 1])
        shutil.copytree(src, runs / src.name)
        return subprocess.CompletedProcess(cli, exit_code)

    monkeypatch.setattr(pt, "probe_slot", probe)
    monkeypatch.setattr(pt.subprocess, "run", session)
    code = pt.check("full", tmp_path, "cp-direct-discount")
    doc = json.loads((tmp_path / "pull-through.json").read_text("utf-8"))
    assert doc["claim"] == "none" and doc["bundle"].endswith(src.name)
    assert doc["run_id"] == read_bundle(src).manifest.run_id
    if failed is None:
        assert code == 0 and doc["passed"] and not doc["failures"]
        assert doc["source"].startswith("hosted ") and doc["provenance"] == PROVENANCE
        assert json.loads(pt.RESULT.read_text("utf-8")) == doc
    else:
        assert code == 1 and not doc["passed"] and not doc["checks"][failed]
        assert not pt.RESULT.exists()
