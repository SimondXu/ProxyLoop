"""Phase 03C Stage 2 (local MLX LoRA) pipeline: offline, no model load."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from proxyloop_evaluation.phase03b_readiness import proposed_fast_target
from proxyloop_evaluation.phase03c_experiment import Phase03CQwenAdapter
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    PromptSetRow,
    load_prompt_set_manifest,
    render_prompt,
    render_prompt_view,
    resolve_row,
)
from proxyloop_evaluation.phase03c_training.cloud_manifest import (
    check_cloud_run_manifest,
)
from proxyloop_evaluation.phase03c_training.config import (
    RECIPE,
    SMOKE_ITERS,
    SMOKE_RECIPE,
    SMOKE_TRAIN_ROWS,
    TRAINING_CONFIG_FILENAME,
    config_hash,
    mlx_lora_config,
    render_yaml,
    training_plan,
)
from proxyloop_evaluation.phase03c_training.dataset import (
    DATASET_MANIFEST_FILENAME,
    TRAIN_FILENAME,
    VALID_FILENAME,
    AcceptedRecord,
    DatasetRow,
    assert_splits_disjoint,
    build_dev_rows,
    build_train_rows,
    canonical_dev_target,
    check_dataset_files,
    load_dataset_manifest,
    read_accepted_records,
    rows_by_prompt_id,
    sha256_file,
    write_dataset,
)
from proxyloop_evaluation.phase03c_training.dev_eval import (
    RATE_FIELDS,
    SUBSET_PER_FAMILY,
    development_rows,
    evaluate_dev_rows,
    select_checkpoint,
    select_rows,
    step_adapter_dir,
)
from proxyloop_evaluation.phase03c_training.manifest import (
    DEVIATION,
    RUN_MANIFEST_FILENAME,
    build_run_manifest,
    check_run_manifest,
    manifest_fingerprint,
    parse_train_log,
    write_run_manifest,
)
from proxyloop_evaluation.qwen_spec import QWEN3_4B_4BIT_SPEC

import scripts.run_phase03c_training as training_script
from scripts.run_phase03c_dev_eval import run_dev_eval

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TRAIN_IDS = (
    "direct-success@1.0::transparent-public-v1@1.0::p7::pos1",
    "fee-total-cost-trap@1.0::retention-gated-v1@1.0::p41::pos2",
    "disclosure-restriction@1.0::retention-gated-v1@1.0::p3::pos1",
)
_TRAIN_TAIL = (
    "It/sec 0.088, Tokens/sec 13.367, Trained Tokens {tokens}, Peak mem 6.4 GB"
)
SAMPLE_LOG = "\n".join(
    (
        "Loading configuration file x.yaml",
        "Trainable parameters: 0.411% (16.515M/4022.468M)",
        "Starting training..., iters: 4",
        "Iter 1: Val loss 3.556, Val took 11.766s",
        "Iter 2: Val loss 3.591, Val took 11.804s",
        "Iter 2: Train loss 2.393, Learning Rate 0.000e+00, "
        + _TRAIN_TAIL.format(tokens=305),
        "Iter 2: Saved adapter weights to a/adapters.safetensors and "
        "a/0000002_adapters.safetensors.",
        "Iter 4: Val loss 3.583, Val took 12.063s",
        "Iter 4: Train loss 2.186, Learning Rate 1.500e-04, "
        + _TRAIN_TAIL.format(tokens=566),
        "Saved final weights to a/adapters.safetensors.",
        "",
    )
)


@pytest.fixture(scope="module")
def committed_rows() -> tuple[PromptSetRow, ...]:
    return load_prompt_set_manifest(ROOT / PROMPT_SET_MANIFEST_PATH)


def _accepted_record(row: PromptSetRow, assistant: str) -> AcceptedRecord:
    prompt = render_prompt(render_prompt_view(*resolve_row(row)), prompt_version="v6")
    return AcceptedRecord(
        prompt_id=row.prompt_id,
        content_hash="0" * 64,
        messages=(
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
            {"role": "assistant", "content": assistant},
        ),
    )


def _sample_train_rows(rows: tuple[PromptSetRow, ...]) -> tuple[PromptSetRow, ...]:
    by_id = rows_by_prompt_id(rows)
    return tuple(by_id[prompt_id] for prompt_id in SAMPLE_TRAIN_IDS)


# --- dataset ---------------------------------------------------------------


def test_train_rows_are_byte_equal_to_the_prompt_builder(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    sample = _sample_train_rows(committed_rows)
    assert {row.split for row in sample} == {"train"}
    records = tuple(
        _accepted_record(row, canonical_dev_target(row.oracle_action)) for row in sample
    )
    index = rows_by_prompt_id(committed_rows)
    built = build_train_rows(records, index, prompt_version="v6")
    assert [row.prompt_id for row in built] == list(SAMPLE_TRAIN_IDS)
    for record, row in zip(records, built, strict=True):
        assert row.messages == record.messages  # verbatim, never re-rendered
        assert row.split == "train"
    # One byte of drift in the user prompt fails the whole dataset.
    drifted = replace(
        records[0],
        messages=(
            records[0].messages[0],
            {"role": "user", "content": records[0].user + " "},
            records[0].messages[2],
        ),
    )
    with pytest.raises(ValueError, match="user_prompt_mismatch"):
        build_train_rows((drifted,), index, prompt_version="v6")
    with pytest.raises(ValueError, match="system_prompt_mismatch"):
        build_train_rows(
            (
                replace(
                    records[1],
                    messages=(
                        {"role": "system", "content": "x"},
                        *records[1].messages[1:],
                    ),
                ),
            ),
            index,
            prompt_version="v6",
        )
    # A v5 prompt is drift against the v6 manifest, not a silent acceptance.
    with pytest.raises(ValueError, match="prompt_fingerprint_drift"):
        build_train_rows(records[:1], index, prompt_version="v5")


def test_development_prompts_never_enter_train(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    dev_row = development_rows(committed_rows)[0]
    record = _accepted_record(dev_row, canonical_dev_target(dev_row.oracle_action))
    with pytest.raises(ValueError, match="non_train_prompt_in_accepted"):
        build_train_rows(
            (record,), rows_by_prompt_id(committed_rows), prompt_version="v6"
        )
    with pytest.raises(ValueError, match="unknown_prompt_id"):
        build_train_rows(
            (replace(record, prompt_id="missing"),),
            rows_by_prompt_id(committed_rows),
            prompt_version="v6",
        )
    train_row = DatasetRow(
        dev_row.prompt_id, dev_row.family_id, "train", record.messages
    )
    dev = DatasetRow(
        dev_row.prompt_id, dev_row.family_id, "development", record.messages
    )
    with pytest.raises(ValueError, match="development_prompt_in_train"):
        assert_splits_disjoint((train_row,), (dev,))


def test_dev_rows_carry_the_same_prompt_and_the_canonical_oracle_target(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    dev = development_rows(committed_rows)[:4]
    rows = build_dev_rows(dev, prompt_version="v6")
    assert len(rows) == 4
    for source, row in zip(dev, rows, strict=True):
        prompt = render_prompt(
            render_prompt_view(*resolve_row(source)), prompt_version="v6"
        )
        assert row.messages[0] == {"role": "system", "content": prompt.system}
        assert row.messages[1] == {"role": "user", "content": prompt.user}
        assistant = row.messages[2]["content"]
        assert assistant == json.dumps(
            proposed_fast_target(source.oracle_action),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert json.loads(assistant)["action_intent"] is None
        assert json.loads(assistant)["fact_updates"] == []
    with pytest.raises(ValueError, match="no development rows"):
        build_dev_rows(_sample_train_rows(committed_rows), prompt_version="v6")


def test_write_dataset_manifest_hashes_counts_and_token_stats(
    committed_rows: tuple[PromptSetRow, ...], tmp_path: Path
) -> None:
    sample = _sample_train_rows(committed_rows)
    dev = development_rows(committed_rows)[:3]
    accepted = tmp_path / "teacher-accepted.jsonl"
    with accepted.open("w", encoding="utf-8") as handle:
        for row in sample[:2]:
            record = _accepted_record(row, canonical_dev_target(row.oracle_action))
            handle.write(
                json.dumps(
                    {
                        "content_hash": record.content_hash,
                        "generator": {"adapter_id": "fake"},
                        "lexical_fingerprint": "1" * 64,
                        "messages": list(record.messages),
                        "prompt_fingerprint": row.prompt_fingerprint,
                        "schema_fingerprint": "2" * 64,
                        "prompt_id": row.prompt_id,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    assert len(read_accepted_records(accepted)) == 2

    def count_tokens(messages: object) -> int:
        assert isinstance(messages, tuple)
        return sum(len(item["content"]) for item in messages) // 4

    out_dir = tmp_path / "data"
    document = write_dataset(
        accepted_path=accepted,
        out_dir=out_dir,
        prompt_set_rows=(*sample, *dev),
        prompt_set_content_fingerprint="f" * 64,
        prompt_version="v6",
        count_tokens=count_tokens,
        max_seq_length=2048,
    )
    assert document["split_counts"] == {"train": 2, "development": 3}
    assert document["train_prompt_count"] == 2
    assert document["compiler_version"] == "phase-03c-fast-compiler-v6"
    files = document["files"]
    assert isinstance(files, dict)
    assert files[TRAIN_FILENAME]["sha256"] == sha256_file(out_dir / TRAIN_FILENAME)
    assert files[VALID_FILENAME]["sha256"] == sha256_file(out_dir / VALID_FILENAME)
    source = document["accepted_source"]
    assert isinstance(source, dict)
    assert source["sha256"] == sha256_file(accepted)
    assert source["teacher_manifest_sha256"] is None  # no sibling manifest here
    stats = document["token_stats"]
    assert isinstance(stats, dict)
    assert stats["rows"] == 5
    assert stats["max"] >= stats["p95"] >= stats["min"]
    assert stats["over_max_seq_length"] == sum(
        count_tokens(row.messages) > 2048
        for row in (
            *build_train_rows(
                read_accepted_records(accepted),
                rows_by_prompt_id(sample),
                prompt_version="v6",
            ),
            *build_dev_rows(dev, prompt_version="v6"),
        )
    )
    lines = (out_dir / TRAIN_FILENAME).read_text(encoding="utf-8").splitlines()
    assert all(set(json.loads(line)) == {"messages"} for line in lines)
    # The manifest round-trips, its fingerprint is a pure function of its
    # body, and any drift in a JSONL file is refused.
    loaded = load_dataset_manifest(out_dir)
    assert loaded == json.loads(json.dumps(document))
    check_dataset_files(out_dir, loaded)
    again = write_dataset(
        accepted_path=accepted,
        out_dir=tmp_path / "again",
        prompt_set_rows=(*sample, *dev),
        prompt_set_content_fingerprint="f" * 64,
        prompt_version="v6",
        count_tokens=count_tokens,
    )
    assert again["dataset_fingerprint"] == document["dataset_fingerprint"]
    (out_dir / VALID_FILENAME).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"dataset_file_drift:valid\.jsonl"):
        check_dataset_files(out_dir, loaded)
    assert (out_dir / DATASET_MANIFEST_FILENAME).is_file()


# --- config ------------------------------------------------------------------


def test_training_plan_counts_micro_iters_and_optimizer_steps() -> None:
    plan = training_plan(RECIPE, 3000)
    assert plan.optimizer_steps == 563  # ceil(3 * 3000 / 16)
    assert plan.iters == 563 * 16  # mlx_lm iters are micro-batches
    assert plan.effective_batch_size == 16
    assert plan.warmup_steps == 17  # ceil(0.03 * 563)
    assert plan.decay_steps == 563 - 17
    assert plan.steps_per_eval == 1600  # every 100 optimizer steps
    exact = training_plan(RECIPE, 1600)
    assert exact.iters == 4800 and exact.optimizer_steps == 300
    smoke = training_plan(SMOKE_RECIPE, SMOKE_TRAIN_ROWS, iters=SMOKE_ITERS)
    assert (smoke.iters, smoke.optimizer_steps, smoke.steps_per_eval) == (4, 2, 2)
    with pytest.raises(ValueError):
        training_plan(RECIPE, 100, iters=15)
    with pytest.raises(ValueError):
        training_plan(RECIPE, 0)


def test_mlx_config_maps_the_contract_recipe_onto_mlx_lm_keys() -> None:
    plan = training_plan(RECIPE, 3000)
    config = mlx_lora_config(
        RECIPE,
        plan,
        model_path=Path("/models/8b"),
        data_dir=Path("data"),
        adapter_path=Path("run/adapters"),
    )
    assert config["lora_parameters"] == {"rank": 32, "scale": 2.0, "dropout": 0.05}
    assert config["num_layers"] == -1
    assert config["mask_prompt"] is True
    assert config["batch_size"] == 1
    assert config["grad_accumulation_steps"] == 16
    assert config["iters"] == plan.iters
    assert config["steps_per_eval"] == config["save_every"] == 1600
    assert config["lr_schedule"] == {
        "name": "cosine_decay",
        "warmup": 17,
        "warmup_init": 0.0,
        "arguments": [1.5e-4, 546, 0.0],
    }
    assert config["max_seq_length"] == 2048
    assert config["seed"] == 0
    assert config["grad_checkpoint"] is True
    assert SMOKE_RECIPE.lora_rank == 8 and SMOKE_RECIPE.lora_scale == 8.0
    yaml = pytest.importorskip("yaml")
    text = render_yaml(config)
    assert yaml.safe_load(text) == config
    assert text == render_yaml(dict(reversed(list(config.items()))))
    assert config_hash(config) == config_hash(dict(reversed(list(config.items()))))
    assert config_hash(config) != config_hash({**config, "iters": 1})


# --- run manifest -------------------------------------------------------------


def _run_manifest(tmp_path: Path, *, smoke: bool = True) -> dict[str, object]:
    recipe = SMOKE_RECIPE if smoke else RECIPE
    plan = (
        training_plan(recipe, SMOKE_TRAIN_ROWS, iters=SMOKE_ITERS)
        if smoke
        else training_plan(recipe, 3000)
    )
    config = mlx_lora_config(
        recipe,
        plan,
        model_path=Path("/models/4b"),
        data_dir=tmp_path / "data",
        adapter_path=tmp_path / "adapters",
    )
    return build_run_manifest(
        run_id="smoke" if smoke else "run-1",
        smoke=smoke,
        dataset_manifest={
            "dataset_fingerprint": "d" * 64,
            "prompt_version": "v6",
            "compiler_version": "phase-03c-fast-compiler-v6",
            "split_counts": {"train": 214, "development": 400},
            "token_stats": None,
        },
        data_dir=tmp_path / "data",
        base_spec=QWEN3_4B_4BIT_SPEC,
        base_attestation=QWEN3_4B_4BIT_SPEC.attestation,
        recipe=recipe,
        plan=plan,
        config_document=config,
        command=["python", "-m", "mlx_lm", "lora"],
        exit_code=0,
        wall_time_s=81.3,
        packages={"mlx-lm": "0.31.3"},
        machine={"cpu_brand": "Apple M4 Pro"},
        gpu="apple-m4-pro-unified",
        train_log=SAMPLE_LOG,
        adapter_hashes={"adapters.safetensors": {"sha256": "a" * 64, "size": 1}},
    )


def test_parse_train_log_reads_the_loss_table() -> None:
    losses = parse_train_log(SAMPLE_LOG)
    assert losses["final_train_loss"] == 2.186
    assert losses["final_val_loss"] == 3.583
    assert losses["saved_iters"] == [2]
    assert losses["val_loss"] == [
        {"iter": 1, "val_loss": 3.556},
        {"iter": 2, "val_loss": 3.591},
        {"iter": 4, "val_loss": 3.583},
    ]
    train = losses["train_loss"]
    assert isinstance(train, list)
    assert train[1] == {
        "iter": 4,
        "train_loss": 2.186,
        "learning_rate": 1.5e-4,
        "trained_tokens": 566,
    }
    assert parse_train_log("")["final_train_loss"] is None


def test_run_manifest_fingerprint_is_reproducible_and_checked(tmp_path: Path) -> None:
    document = _run_manifest(tmp_path)
    assert document["deviation"] == DEVIATION
    assert document["gpu"] == "apple-m4-pro-unified"
    assert document["fingerprint"] == manifest_fingerprint(document)
    assert _run_manifest(tmp_path)["fingerprint"] == document["fingerprint"]
    config = document["config"]
    assert isinstance(config, dict)
    assert document["config_hash"] == config_hash(config)
    path = tmp_path / RUN_MANIFEST_FILENAME
    write_run_manifest(path, document)
    (tmp_path / TRAINING_CONFIG_FILENAME).write_text(
        render_yaml(config), encoding="utf-8"
    )
    assert check_run_manifest(path) == ()
    assert check_run_manifest(tmp_path / "missing.json") == (
        f"missing_manifest:{tmp_path / 'missing.json'}",
    )
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["wall_time_s"] = 1.0
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert "fingerprint_drift" in check_run_manifest(path)
    tampered = json.loads(json.dumps(document))
    tampered["config"]["iters"] = 2
    tampered["config_hash"] = config_hash(tampered["config"])
    tampered["fingerprint"] = manifest_fingerprint(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")
    problems = check_run_manifest(path)
    assert "config_drift:iters" in problems and "config_yaml_drift" in problems
    # A non-smoke manifest whose iters are not three epochs is refused.
    full = _run_manifest(tmp_path, smoke=False)
    full_path = tmp_path / "run-1" / RUN_MANIFEST_FILENAME
    write_run_manifest(full_path, full)
    assert check_run_manifest(full_path) == ()
    short = json.loads(json.dumps(full))
    short["plan"]["iters"] = 16
    short["plan"]["optimizer_steps"] = 1
    short["plan"]["warmup_steps"] = 1
    short["plan"]["decay_steps"] = 1
    short["config"]["iters"] = 16
    short["config_hash"] = config_hash(short["config"])
    short["fingerprint"] = manifest_fingerprint(short)
    write_run_manifest(full_path, short)
    problems = check_run_manifest(full_path)
    assert "iters_not_three_epochs" in problems
    assert "plan_drift" not in problems


def test_training_check_visits_every_committed_run_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The local smoke manifest sits one level down, the two cloud runs two.
    assert training_script.check() == 0
    out = capsys.readouterr().out
    for relative in (
        "smoke/run-manifest.json",
        "smoke-01/train/run-manifest.json",
        "cloud-run-01/train/run-manifest.json",
    ):
        assert relative in out
    assert "(3 checked" in out


def test_cloud_run_manifest_config_tamper_is_caught(tmp_path: Path) -> None:
    source = ROOT / "data/experiments/phase-03c/training/cloud-run-01/train"
    document = json.loads((source / RUN_MANIFEST_FILENAME).read_text("utf-8"))
    path = tmp_path / RUN_MANIFEST_FILENAME
    path.write_text(json.dumps(document), encoding="utf-8")
    assert check_cloud_run_manifest(path) == ()
    document["config"]["learning_rate"] = document["config"]["learning_rate"] * 2
    path.write_text(json.dumps(document), encoding="utf-8")
    assert check_cloud_run_manifest(path) == ("config_hash_drift",)


def _selected(document: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in document["evals"] if e == document["selected"])


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda d: d.update(selected_minus_untuned_act_agreement=0.4),
            "selected_delta_drift",
        ),
        (
            lambda d: d["selected"].update(oracle_act_agreement=0.1),
            "selected_not_in_evals",
        ),
        (
            lambda d: d["bundle"].update(dataset_fingerprint="0" * 64),
            "bundle_fingerprint_mismatch",
        ),
        (
            lambda d: d["bundle"].update(train_sha256="0" * 64),
            "bundle_train_sha256_mismatch",
        ),
        (lambda d: d.pop("gpu"), "missing_key:gpu"),
        (
            # The evals entry first, while it still equals ``selected``.
            lambda d: (
                _selected(d).update(policy_violation=1),
                d["selected"].update(policy_violation=1),
            ),
            "selected_has_policy_violation",
        ),
    ],
)
def test_cloud_run_manifest_invariants_are_each_checked(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], object], expected: str
) -> None:
    source = ROOT / "data/experiments/phase-03c/training/cloud-run-01/train"
    document = json.loads((source / RUN_MANIFEST_FILENAME).read_text("utf-8"))
    mutate(document)
    path = tmp_path / RUN_MANIFEST_FILENAME
    path.write_text(json.dumps(document), encoding="utf-8")
    assert check_cloud_run_manifest(path) == (expected,)


def _training_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: tuple[str, ...]
) -> Path:
    monkeypatch.setattr(training_script, "TRAINING_DIR", tmp_path)
    monkeypatch.setattr(training_script, "EXPECTED_RUN_MANIFESTS", expected)
    smoke = ROOT / "data/experiments/phase-03c/training/smoke" / RUN_MANIFEST_FILENAME
    target = tmp_path / "smoke" / RUN_MANIFEST_FILENAME
    target.parent.mkdir()
    target.write_bytes(smoke.read_bytes())
    return tmp_path


def test_training_check_refuses_an_unknown_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _training_dir(tmp_path, monkeypatch, ("smoke/run-manifest.json",))
    extra = root / "run-x" / "train" / RUN_MANIFEST_FILENAME
    extra.parent.mkdir(parents=True)
    extra.write_text(json.dumps({"schema_version": "bogus"}), encoding="utf-8")
    assert training_script.check() == 1
    out = capsys.readouterr().out
    assert "run-x/train/run-manifest.json:unknown_schema_version:bogus" in out


def test_training_check_fails_on_a_missing_expected_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = ("gone/train/run-manifest.json", "smoke/run-manifest.json")
    _training_dir(tmp_path, monkeypatch, expected)
    assert training_script.check() == 1
    out = capsys.readouterr().out
    assert "gone/train/run-manifest.json:missing_expected_manifest" in out
    assert "smoke/run-manifest.json: phase-03c-training-run-v1" in out


def test_training_check_reports_a_malformed_manifest_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _training_dir(tmp_path, monkeypatch, ("smoke/run-manifest.json",))
    broken = root / "a-broken" / "train" / RUN_MANIFEST_FILENAME
    broken.parent.mkdir(parents=True)
    broken.write_text("{not json", encoding="utf-8")
    assert training_script.check() == 1
    out = capsys.readouterr().out
    assert "a-broken/train/run-manifest.json:malformed_manifest:JSONDecodeError" in out
    # The next manifest in sorted order is still checked.
    assert "smoke/run-manifest.json: phase-03c-training-run-v1" in out


# --- dev eval -----------------------------------------------------------------


def test_select_checkpoint_prefers_agreement_then_unsupported_then_earlier_step() -> (
    None
):
    evals = [
        {
            "step": 100,
            "oracle_act_agreement": 0.80,
            "policy_violation": 0,
            "unsupported_response_violation": 3,
        },
        {
            "step": 200,
            "oracle_act_agreement": 0.90,
            "policy_violation": 1,
            "unsupported_response_violation": 0,
        },
        {
            "step": 300,
            "oracle_act_agreement": 0.85,
            "policy_violation": 0,
            "unsupported_response_violation": 2,
        },
        {
            "step": 400,
            "oracle_act_agreement": 0.85,
            "policy_violation": 0,
            "unsupported_response_violation": 1,
        },
        {
            "step": 500,
            "oracle_act_agreement": 0.85,
            "policy_violation": 0,
            "unsupported_response_violation": 1,
        },
    ]
    selected = select_checkpoint(evals)
    assert selected is not None and selected["step"] == 400
    assert select_checkpoint(evals[:2]) is evals[0]  # step 200 violates policy
    assert select_checkpoint([evals[1]]) is None
    untuned = {
        "step": None,
        "oracle_act_agreement": 0.95,
        "policy_violation": 0,
        "unsupported_response_violation": 0,
    }
    assert select_checkpoint([*evals, untuned]) is untuned


def test_subset60_is_six_per_family_and_deterministic(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    subset = select_rows(committed_rows, "subset60")
    assert len(subset) == 60
    assert {row.split for row in subset} == {"development"}
    families = [row.family_id for row in subset]
    assert all(families.count(family) == SUBSET_PER_FAMILY for family in set(families))
    assert families == sorted(families)
    assert subset == select_rows(tuple(reversed(committed_rows)), "subset60")
    assert {row.position_index for row in subset} == {1, 2}
    assert len({row.configuration_id for row in subset}) == 2
    assert len(select_rows(committed_rows, "full400")) == 400


def test_dev_eval_aggregates_the_real_evaluator_with_an_injected_generator(
    committed_rows: tuple[PromptSetRow, ...], tmp_path: Path
) -> None:
    rows = select_rows(committed_rows, "subset60")[:12]  # two families
    constant = json.dumps(proposed_fast_target("decline"))  # counter, needed false
    adapter = Phase03CQwenAdapter(
        generator=lambda _: constant,
        model_spec=QWEN3_4B_4BIT_SPEC,
        prompt_version="v6",
    )
    results = evaluate_dev_rows(rows, adapter)
    assert [item.prompt_id for item in results] == [row.prompt_id for row in rows]
    expected_act = sum(
        proposed_fast_target(row.oracle_action)["dialogue_act"] == "counter"
        for row in rows
    )
    expected_needed = sum(
        proposed_fast_target(row.oracle_action)["reasoner_request"]["needed"] is False  # type: ignore[index]
        for row in rows
    )
    assert (
        sum(item.executed.metrics.dialogue_act_accuracy for item in results)
        == expected_act
    )
    assert sum(item.needed_agreement for item in results) == expected_needed
    assert all(item.executed.metrics.schema_valid for item in results)

    output = tmp_path / "dev-eval.json"
    document = run_dev_eval(
        model="4b",
        model_path=Path("/unused"),
        adapter_path=None,
        step=None,
        prompt_version="v6",
        selection="subset60",
        manifest=ROOT / PROMPT_SET_MANIFEST_PATH,
        output=output,
        adapter=adapter,
    )
    assert document["result_role"] == "diagnostic"
    assert document["rows"] == "subset60"
    aggregate = document["aggregate"]
    assert isinstance(aggregate, dict)
    assert aggregate["rows"] == 60
    metrics = aggregate["metrics"]
    assert set(metrics) == set(RATE_FIELDS)
    assert metrics["schema_valid"] == {"count": 60, "rate": 1.0}
    assert metrics["strict_json"]["count"] == 60
    assert metrics["policy_violation"]["count"] == 0
    assert metrics["thinking_leak"]["count"] == 0
    per_family = document["per_family"]
    assert isinstance(per_family, dict) and len(per_family) == 10
    assert (
        sum(item["oracle_act_agreement"] for item in per_family.values())
        == (metrics["oracle_act_agreement"]["count"])
    )
    summary = document["selection_summary"]
    assert isinstance(summary, dict)
    assert summary["step"] is None
    assert summary["policy_violation"] == 0
    assert summary["oracle_act_agreement"] == metrics["oracle_act_agreement"]["rate"]
    adapter_info = document["adapter"]
    assert isinstance(adapter_info, dict)
    assert adapter_info["path_state"] == "none" and adapter_info["tuning"] == "untuned"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert (
        written["result_content_fingerprint"] == document["result_content_fingerprint"]
    )
    assert len(written["episodes"]) == 60
    with pytest.raises(FileExistsError):
        run_dev_eval(
            model="4b",
            model_path=Path("/unused"),
            adapter_path=None,
            step=None,
            prompt_version="v6",
            selection="subset60",
            manifest=ROOT / PROMPT_SET_MANIFEST_PATH,
            output=output,
            adapter=adapter,
        )


def test_step_adapter_dir_materialises_a_loadable_checkpoint(tmp_path: Path) -> None:
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapters / "0000100_adapters.safetensors").write_bytes(b"weights")
    with pytest.raises(FileNotFoundError):
        step_adapter_dir(adapters, 200)
    target = step_adapter_dir(adapters, 100)
    assert target == adapters / "steps" / "step-0000100"
    assert (target / "adapters.safetensors").read_bytes() == b"weights"
    assert (target / "adapter_config.json").read_text(encoding="utf-8") == "{}"
    assert step_adapter_dir(adapters, 100) == target  # idempotent
