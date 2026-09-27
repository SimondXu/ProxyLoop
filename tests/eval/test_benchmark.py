"""The Fast benchmark (S1-MOD-04): the spec refuses held-out families, every
condition runs the same cells, and the report pairs before it compares, labels
latency by endpoint (never a cross-endpoint delta), keeps C1 empty without an
attested adapter and gives every not-computable column its reason."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import QWEN, session_config
from tests.eval.streams import Stream, speech
from tests.eval.test_kernel_bundle import FINISH, SCRIPTS
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import clients, fake, fake_config, patient_task

from proxyloop.contract.bundle import MANIFEST, Manifest, RoleModel
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.benchmark import (
    NO_SHARDS,
    Benchmark,
    build,
    cells,
    live_configs,
    load_spec,
    main,
    run,
)
from proxyloop.eval.matrix import Cell, cell_dir, read_cell_dir
from proxyloop.eval.metrics import HeldOutRefused

INSTANCE = "cp-direct-discount-s0"
LUNA = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="teamrouter",
    model_id="gpt-6-luna",
    reasoning_effort="low",
)
QWEN_LORA = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id="pl-sft")
REFS = {"C5": LUNA, "C2": QWEN, "C1": QWEN_LORA}
SHARD = "adapters/pl-sft/adapter_model.safetensors"
LUNA_RUN = Path(__file__).resolve().parents[2] / "evidence/s0/20260927T011606Z-30d027"


def _spec(tmp_path: Path, split: str = "train", **extra: Any) -> Path:
    body = {
        "id": "b",
        "conditions": [{"name": "A"}, {"name": "B"}],
        "families": [
            {
                "family": "cp-direct-discount",
                "split": split,
                "instances": [INSTANCE],
                "seeds": [1, 2],
            }
        ],
        "salt": 3,
        "comparisons": [["A", "B"]],
    } | extra
    path = tmp_path / "spec.yaml"
    path.write_text(json.dumps(body), "utf-8")  # JSON is YAML
    return path


def test_the_spec_names_c5_c2_c1_on_piloted_families_only() -> None:
    bench = load_spec()
    assert [c.name for c in bench.spec.conditions] == ["C5", "C2", "C1"]
    assert [c.attested_adapter for c in bench.spec.conditions] == [False, False, True]
    assert {f.split for f in bench.spec.families} <= {"train", "dev"}
    assert bench.tasks[INSTANCE].family == "cp-direct-discount"
    assert ("C2", "C5") in bench.spec.comparisons


def test_a_test_family_is_refused_before_its_task_is_read(tmp_path: Path) -> None:
    def never(family: str) -> Task:
        raise AssertionError(f"{family} was read")

    with pytest.raises(HeldOutRefused):
        load_spec(_spec(tmp_path, split="test"), never)


def test_an_instance_the_family_does_not_have_is_refused(tmp_path: Path) -> None:
    fams = [
        {"family": "cp-direct-discount", "split": "dev", "instances": ["x"]}
        | {"seeds": [1]}
    ]
    with pytest.raises(ValueError, match="no instance"):
        load_spec(_spec(tmp_path, families=fams))


def test_every_condition_runs_the_same_cells_in_blocks() -> None:
    spec = load_spec().spec
    todo = cells(spec, ["C5", "C2", "C1"])
    per = {
        c: {(x.instance, x.seed) for x in todo if x.condition == c}
        for c in ("C5", "C2", "C1")
    }
    assert per["C5"] == per["C2"] == per["C1"] and len(per["C2"]) == 5
    for k in range(0, len(todo), 3):  # each block: one (instance, seed), all three
        block = todo[k : k + 3]
        assert len({(c.instance, c.seed) for c in block}) == 1
        assert sorted(c.condition for c in block) == ["C1", "C2", "C5"]
    assert todo == cells(spec, ["C5", "C2", "C1"])  # the salt fixes the order
    with pytest.raises(ValueError, match="not in the spec"):
        cells(spec, ["C4"])


def test_a_cell_folder_names_its_cell(tmp_path: Path) -> None:
    cell = Cell("C5", INSTANCE, 12)
    assert read_cell_dir(cell_dir(tmp_path, 3, cell)) == cell
    assert read_cell_dir(tmp_path / "notes") is None


def test_live_configs_apply_a_registry_condition_to_the_cli_config() -> None:
    bench = load_spec()
    (cfg,) = live_configs(bench, ["C2"], ["--slow-model", "slow-x"]).values()
    assert cfg.live and cfg.fast_cp.model_id == cfg.fast_user.model_id == "Qwen3.5-9B"
    assert cfg.slow.model_id == "slow-x"  # the CLI's options, not a copy of them
    with pytest.raises(KeyError, match="unknown condition"):
        live_configs(bench, ["C0"], [])  # e.g. C5/C1 before the registry has them


# --- the report on synthetic bundles ------------------------------------------
def _bundle(runs: Path, k: int, cell: Cell, reason: str = "info_only") -> Path:
    s = Stream(session_config(seed=cell.seed))
    msg = s.user_says("Hi.")
    s.fast("user", msg, [speech("Hello.")], ref=REFS[cell.condition])
    return s.write(cell_dir(runs, k, cell) / "run-s", reason)


def _attest(run_dir: Path, shards: dict[str, str], attestation: dict[str, str]) -> None:
    m = Manifest.model_validate_json((run_dir / MANIFEST).read_text("utf-8"))
    models = dict(m.models) | {
        "fast_cp": RoleModel(ref=QWEN_LORA, adapter_shards=shards)
    }
    data = m.model_dump(by_alias=True) | {"models": models, "attestation": attestation}
    (run_dir / MANIFEST).write_text(
        Manifest.model_validate(data).model_dump_json(by_alias=True), "utf-8"
    )


def _runs(tmp_path: Path, c1: dict[str, str] | None = None) -> Path:
    """C2 on seeds 1-5, C5 on 1-4 (s5 never ran), C1 on 1-2 (shards: ``c1``)."""
    runs, k = tmp_path / "runs", 0
    for seed in range(1, 6):
        for cond in ("C5", "C2", "C1"):
            if (cond == "C5" and seed == 5) or (cond == "C1" and seed > 2):
                continue
            path = _bundle(runs, k, Cell(cond, INSTANCE, seed))
            if cond == "C1" and c1 is not None:
                _attest(path, c1, {SHARD: "ab", "shards/m.safetensors": "cd"})
            k += 1
    return runs


def _build(tmp_path: Path, c1: dict[str, str] | None = None) -> dict[str, Any]:
    runs = _runs(tmp_path, c1)
    return build(load_spec(), runs, git_sha="g", resamples=100)


def test_the_report_has_the_pl_report_1_shape(tmp_path: Path) -> None:
    report = _build(tmp_path)
    assert {"report_id", "spec_hash", "bundles", "tables"} <= set(report)
    assert report["report_id"] == "fast-benchmark"
    assert report["spec_hash"] == load_spec().spec_hash
    for table in report["tables"].values():
        assert set(table) == {"columns", "rows", "n", "ci"}
    json.dumps(report)


def test_latency_is_one_table_per_endpoint_and_never_compared(
    tmp_path: Path,
) -> None:
    tables = _build(tmp_path)["tables"]
    assert "latency" not in tables
    relay = tables["latency: relay-measured (teamrouter)"]
    hosted = tables["latency: self-hosted (vllm)"]
    assert list(relay["rows"]) == ["C5|user"]  # C5 alone: its own columns
    assert list(hosted["rows"]) == ["C2|user"]  # C1 is excluded (no shards)
    assert relay["rows"]["C5|user"]["ttft_p50"] == 60
    for name, table in tables.items():  # no cross-endpoint latency delta
        latency = [c for c in table["columns"] if "tt" in c or "heard" in c]
        assert not latency or name.startswith("latency: ")
    assert tables["comparison"]["columns"] == [
        "success_delta",
        "safe_success_delta",
        "model_failure_delta",
    ]


def test_missing_and_unpaired_cells_are_listed_and_comparisons_pair(
    tmp_path: Path,
) -> None:
    tables = _build(tmp_path)["tables"]
    rows = tables["conditions"]["rows"]
    assert rows["C5"]["missing"] == ["cp-direct-discount/cp-direct-discount-s0/s5"]
    assert rows["C2"]["unpaired"] == ["cp-direct-discount/cp-direct-discount-s0/s5"]
    assert rows["C5"]["unpaired"] == [] and rows["C2"]["missing"] == []
    assert rows["C1"]["present"] == 0 and len(rows["C1"]["missing"]) == 5
    comparison = tables["comparison"]
    assert comparison["n"]["C2-C5"] == 4  # paired cells only, not C2's 5
    assert comparison["rows"]["C2-C5"]["model_failure_delta"] == 0.0
    assert tables["outcome"]["n"] == {"C5": 4, "C2": 5, "C1": 0}  # all bundles


def test_c1_stays_empty_without_attested_shards(tmp_path: Path) -> None:
    tables = _build(tmp_path)["tables"]
    assert set(tables["outcome"]["rows"]["C1"].values()) == {None}
    reason = tables["not_computable"]["rows"]["condition.C1"]["reason"]
    assert reason == f"no attested adapter: {NO_SHARDS}"
    excluded = [r for r in tables["evidence"]["rows"].values() if r["excluded"]]
    assert len(excluded) == 2 and all(r["condition"] == "C1" for r in excluded)
    assert tables["conditions"]["rows"]["C1"]["excluded"] == 2
    none = tables["not_computable"]["rows"]["comparison.C1-C2"]["reason"]
    assert "share no cell" in none
    assert tables["comparison"]["n"]["C1-C2"] == 0


def test_c1_counts_only_with_shards_matching_the_attestation(tmp_path: Path) -> None:
    good = _build(tmp_path / "good", c1={SHARD: "ab"})["tables"]
    assert good["outcome"]["n"]["C1"] == 2 and good["comparison"]["n"]["C1-C2"] == 2
    assert good["conditions"]["rows"]["C1"]["fast_models"] == ["vllm:pl-sft"]
    bad = _build(tmp_path / "bad", c1={SHARD: "ff"})["tables"]
    assert bad["outcome"]["n"]["C1"] == 0
    reasons = {r["excluded"] for r in bad["evidence"]["rows"].values()}
    assert any(r and "do not match" in r for r in reasons)
    why = bad["not_computable"]["rows"]["condition.C1"]["reason"]
    assert why.startswith("no attested adapter: adapter shards [")


def test_not_computable_columns_carry_reasons(tmp_path: Path) -> None:
    tables = _build(tmp_path)["tables"]
    row = tables["comparison"]["rows"]["C2-C5"]
    assert row["success_delta"] is None and row["safe_success_delta"] is None
    why = tables["not_computable"]["rows"]
    assert "not computable" in why["comparison.C2-C5.success"]["reason"]
    assert "S2" in why["blocked_harm"]["reason"]  # never 0
    assert "acceptable_outcomes" in why["success"]["reason"]
    assert "one instance" in why["comparison.C2-C5.ci"]["reason"]


def test_every_bundle_carries_its_evidence_label(tmp_path: Path) -> None:
    tables = _build(tmp_path)["tables"]
    rows = tables["evidence"]["rows"]
    assert len(rows) == 11  # C5 4, C2 5, C1 2: none dropped
    assert {r["evidence"] for r in rows.values()} == {"failed"}  # synthetic
    assert all(r["failures"] for r in rows.values())
    cond = tables["conditions"]["rows"]["C5"]
    assert cond["claimable"] == 0 and cond["evidence"] == "descriptive (4 unclaimable)"


def test_a_real_luna_bundle_is_kept_as_descriptive(tmp_path: Path) -> None:
    """The committed S0 Luna bundle passes offline but not --claim (its echo
    is the dated id): it stays in the rows, labelled, never dropped."""
    fams = [
        {"family": "cp-direct-discount", "split": "train", "instances": [INSTANCE]}
        | {"seeds": [0]}
    ]
    bench = load_spec(_spec(tmp_path, families=fams))
    runs = tmp_path / "runs"
    shutil.copytree(LUNA_RUN, cell_dir(runs, 0, Cell("A", INSTANCE, 0)) / LUNA_RUN.name)
    tables = build(bench, runs, git_sha="g", resamples=50)["tables"]
    (row,) = tables["evidence"]["rows"].values()
    assert row["evidence"] == "offline"
    assert any("gpt-6-luna-2026-09-22" in f for f in row["failures"])
    cond = tables["conditions"]["rows"]["A"]
    assert cond["evidence"] == "descriptive (1 unclaimable)"
    assert cond["fast_models"] == ["teamrouter:gpt-6-luna"]
    assert tables["outcome"]["n"]["A"] == 1
    relay = tables["latency: relay-measured (teamrouter)"]
    assert set(relay["rows"]) == {"A|user", "A|cp"}
    assert not any(k.startswith("latency: self-hosted") for k in tables)


def test_a_test_split_bundle_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    s = Stream(session_config(seed=1), split="test")
    s.write(cell_dir(runs, 0, Cell("C2", INSTANCE, 1)) / "run-s")
    with pytest.raises(HeldOutRefused):
        build(load_spec(), runs, git_sha="g")


def test_a_bundle_of_another_cell_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    s = Stream(session_config(seed=9))
    s.write(cell_dir(runs, 0, Cell("C2", INSTANCE, 1)) / "run-s")
    with pytest.raises(ValueError, match="not its cell"):
        build(load_spec(), runs, git_sha="g")


def test_the_report_command_writes_the_json(tmp_path: Path) -> None:
    runs, out = _runs(tmp_path), tmp_path / "fast-benchmark.json"
    args = ["report", "--runs", str(runs), "--out", str(out), "--git-sha", "g"]
    assert main(args) == 0
    assert json.loads(out.read_text("utf-8"))["git_sha"] == "g"


# --- one end-to-end matrix on fakes -------------------------------------------
def _seams(cell: Cell) -> dict[str, Any]:
    clock = ScaledClock(100)
    until = {"slow": ("] cp_update", FINISH)}
    fakes = clients(SCRIPTS, clock, [], until)
    return {"clock": clock, "sleep": clock.sleep, "clients": fakes}


def _config(model: str) -> SessionConfig:
    ref = fake("fast_cp").model_copy(update={"model_id": model})
    return SessionConfig.model_validate(fake_config().model_dump() | {"fast_cp": ref})


def test_run_then_report_end_to_end_on_two_fake_conditions(tmp_path: Path) -> None:
    bench: Benchmark = load_spec(_spec(tmp_path), lambda family: patient_task())
    configs = {"A": _config("a-fake"), "B": _config("b-fake")}
    coro = run(bench, configs, tmp_path / "runs", seams=_seams)
    runs = asyncio.run(asyncio.wait_for(coro, timeout=60))
    assert Counter(r.cell.condition for r in runs) == {"A": 2, "B": 2}
    assert all(r.reason == "info_only" for r in runs)
    tables = build(bench, tmp_path / "runs", git_sha="g", resamples=50)["tables"]
    rows = tables["conditions"]["rows"]
    assert rows["A"]["fast_models"] == ["test_fake:a-fake", "test_fake:fast_user-fake"]
    labels = {r["evidence"] for r in tables["evidence"]["rows"].values()}
    assert labels == {"offline"}  # kernel bundles on fakes: never claimable
    assert rows["A"]["evidence"] == "descriptive (2 unclaimable)"
    assert rows["A"]["missing"] == rows["B"]["unpaired"] == []
    assert tables["comparison"]["n"]["A-B"] == 2
    assert tables["outcome"]["rows"]["A"]["infra_errors"] == 0  # the patient task
    assert "latency: in-process (test_fake)" in tables
