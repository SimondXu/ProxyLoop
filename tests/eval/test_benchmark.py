"""The Fast benchmark (S1-MOD-04): the spec refuses held-out families, every
condition runs the same cells, and the report pairs before it compares, labels
latency by endpoint (never a cross-endpoint delta), keeps C1 empty without an
attested adapter and gives every not-computable column its reason. The gate
(integrity, pairing, one shared config) refuses a report unless descriptive."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import QWEN, SONNET, session_config
from tests.eval.streams import Stream, speech
from tests.eval.test_kernel_bundle import FINISH, SCRIPTS
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import clients, fake, fake_config, patient_task

from proxyloop.contract.bundle import MANIFEST, Manifest, RoleModel
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.env.tasks.schema import Task
from proxyloop.eval.benchmark import (
    ADAPTER,
    NO_SHARDS,
    NOT_INTERLEAVED,
    Benchmark,
    ConditionSpec,
    build,
    cells,
    live_configs,
    load_spec,
    main,
    refusals,
    run,
)
from proxyloop.eval.matrix import Cell, cell_dir, read_cell_dir
from proxyloop.eval.metrics import HeldOutRefused
from proxyloop.models import registry
from proxyloop.models.registry import Condition

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
FAKE_USER = fake("fast_user")
FAKE_A, FAKE_B = (
    fake("fast_cp").model_copy(update={"model_id": m}) for m in ("a-fake", "b-fake")
)
_FAST = ("fast_user", "fast_cp")
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
        live_configs(bench, ["C0"], [])  # e.g. C1: the registry does not have it


@pytest.fixture(autouse=True)
def stand_ins(monkeypatch: pytest.MonkeyPatch) -> None:
    """C5 as the S0 TeamRouter Luna ref (the synthetic streams' and the
    committed S0 bundle's; the registry's C5 is OpenRouter since S1-MOD-01) and
    the fake conditions A, B; every other name resolves through the registry."""
    real = registry.condition
    lanes = {"C5": (LUNA, LUNA), "A": (FAKE_USER, FAKE_A), "B": (FAKE_USER, FAKE_B)}

    def condition(name: str) -> Condition:
        if name not in lanes:
            return real(name)
        user, cp = lanes[name]
        return Condition(name=name, fast_user=user, fast_cp=cp)

    monkeypatch.setattr(registry, "condition", condition)


# --- the run -----------------------------------------------------------------
def test_a_runs_dir_of_another_condition_list_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # M1: the folder names carry the schedule index k
    bench, runs = load_spec(), tmp_path / "runs"
    for k, cell in enumerate(cells(bench.spec, ["C5", "C2"])):
        cell_dir(runs, k, cell).mkdir(parents=True)  # a C5,C2 matrix ran here
    calls: list[object] = []

    async def session(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    monkeypatch.setattr("proxyloop.eval.matrix.run_session", session)
    wider = {c: fake_config() for c in ("C5", "C2", "C1")}
    with pytest.raises(ValueError, match="fresh RUNS dir"):
        asyncio.run(run(bench, wider, runs))
    assert calls == []  # refused before any run_session
    asyncio.run(run(bench, {c: fake_config() for c in ("C5", "C2")}, runs))
    assert len(calls) == 10  # the identical list resumes


# --- the report on synthetic bundles ------------------------------------------
def _bundle(
    runs: Path,
    k: int,
    cell: Cell,
    reason: str = "info_only",
    ref: ModelRef | None = None,
    **cfg: Any,
) -> Path:
    ref = ref or REFS[cell.condition]
    s = Stream(session_config(seed=cell.seed, fast_user=ref, fast_cp=ref, **cfg))
    msg = s.user_says("Hi.")
    s.fast("user", msg, [speech("Hello.")], ref=ref)
    return s.write(cell_dir(runs, k, cell) / "run-s", reason)


def _attest(
    run_dir: Path,
    shards: dict[str, str],
    ref: ModelRef = QWEN_LORA,
    roles: tuple[str, ...] = ("fast_cp",),
) -> None:
    """Adapter shards on the Fast roles, with an attestation that matches."""
    m = Manifest.model_validate_json((run_dir / MANIFEST).read_text("utf-8"))
    models = dict(m.models) | {
        r: RoleModel(ref=ref, adapter_shards=shards) for r in roles
    }
    data = m.model_dump(by_alias=True) | {"models": models, "attestation": shards}
    (run_dir / MANIFEST).write_text(
        Manifest.model_validate(data).model_dump_json(by_alias=True), "utf-8"
    )


def _runs(
    tmp_path: Path, c1: dict[str, str] | None = None, reason: str = "info_only"
) -> Path:
    """C2 on seeds 1-5, C5 on 1-4 (s5 never ran), C1 on 1-2 (shards: ``c1``)."""
    runs, k = tmp_path / "runs", 0
    for seed in range(1, 6):
        for cond in ("C5", "C2", "C1"):
            if (cond == "C5" and seed == 5) or (cond == "C1" and seed > 2):
                continue
            path = _bundle(runs, k, Cell(cond, INSTANCE, seed), reason)
            if cond == "C1" and c1 is not None:
                _attest(path, c1)
            k += 1
    return runs


def _paired(runs: Path, *, c2_reason: str = "info_only", **c2_cfg: Any) -> Path:
    """C5 and C2 on seeds 1-2, fully paired; C2's seed 2 ends ``c2_reason``."""
    k = 0
    for seed in (1, 2):
        for cond in ("C5", "C2"):
            last = cond == "C2" and seed == 2
            reason, cfg = (c2_reason, c2_cfg) if last else ("info_only", {})
            _bundle(runs, k, Cell(cond, INSTANCE, seed), reason, **cfg)
            k += 1
    return runs


def _build(tmp_path: Path, c1: dict[str, str] | None = None) -> dict[str, Any]:
    runs = _runs(tmp_path, c1)
    return build(load_spec(), [runs], git_sha="g", resamples=100)


def _two_seeds(tmp_path: Path) -> Benchmark:
    fams = [
        {"family": "cp-direct-discount", "split": "train", "instances": [INSTANCE]}
        | {"seeds": [1, 2]}
    ]
    conds = [{"name": "C5"}, {"name": "C2"}]
    return load_spec(
        _spec(tmp_path, families=fams, conditions=conds, comparisons=[["C2", "C5"]])
    )


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
    assert list(hosted["rows"]) == ["C2|user"]  # C1 is excluded
    assert relay["rows"]["C5|user"]["ttft_p50"] == 60
    for name, table in tables.items():  # no cross-endpoint latency delta
        latency = [c for c in table["columns"] if "tt" in c or "heard" in c]
        assert not latency or name.startswith("latency: ")
    assert tables["comparison"]["columns"] == [
        "success_delta",
        "safe_success_delta",
        "model_failure_delta",
        "interleaving",
    ]


def test_missing_and_unpaired_cells_are_listed_and_comparisons_pair(
    tmp_path: Path,
) -> None:
    report = _build(tmp_path)
    tables = report["tables"]
    rows = tables["conditions"]["rows"]
    assert rows["C5"]["missing"] == ["cp-direct-discount/cp-direct-discount-s0/s5"]
    assert rows["C2"]["unpaired"] == ["cp-direct-discount/cp-direct-discount-s0/s5"]
    assert rows["C5"]["unpaired"] == [] and rows["C2"]["missing"] == []
    assert rows["C1"]["present"] == 0 and len(rows["C1"]["missing"]) == 5
    comparison = tables["comparison"]
    assert comparison["n"]["C2-C5"] == 4  # paired cells only, not C2's 5
    assert comparison["rows"]["C2-C5"]["model_failure_delta"] == 0.0
    assert comparison["rows"]["C2-C5"]["interleaving"] == "interleaved"
    assert tables["outcome"]["n"] == {"C5": 4, "C2": 5, "C1": 0}  # all bundles
    pairing = tables["gate"]["rows"]["pairing"]
    assert not pairing["ok"] and len(pairing["reasons"]) == 2  # C1: no bundles
    assert all(not r.startswith("C1") for r in refusals(report))


def test_c1_stays_empty_without_attested_shards(tmp_path: Path) -> None:
    tables = _build(tmp_path)["tables"]
    assert set(tables["outcome"]["rows"]["C1"].values()) == {None}
    reason = tables["not_computable"]["rows"]["condition.C1"]["reason"]
    assert reason == ADAPTER + NO_SHARDS
    assert "attestation equality alone is insufficient" in reason
    excluded = [r for r in tables["evidence"]["rows"].values() if r["excluded"]]
    assert len(excluded) == 2 and all(r["condition"] == "C1" for r in excluded)
    assert tables["conditions"]["rows"]["C1"]["excluded"] == 2
    none = tables["not_computable"]["rows"]["comparison.C1-C2"]["reason"]
    assert "share no cell" in none
    assert tables["comparison"]["n"]["C1-C2"] == 0


@pytest.mark.parametrize(
    ("shards", "ref", "why"),
    [  # M3: base Qwen requested with a pl-sft slot loaded; shards/ only
        ({SHARD: "ab"}, QWEN, "not under adapters/Qwen3.5-9B/"),
        ({"shards/m.safetensors": "cd"}, QWEN_LORA, "not under adapters/pl-sft/"),
        ({SHARD: "ab"}, QWEN_LORA, "evidence-check --claim fails (failed)"),
    ],
)
def test_c1_needs_its_own_slot_shards_and_a_claim_label(
    tmp_path: Path, shards: dict[str, str], ref: ModelRef, why: str
) -> None:
    runs = _runs(tmp_path)
    for path in runs.glob("*-C1-*/run-s"):
        _attest(path, shards, ref)  # the attestation matches in every case
    tables = build(load_spec(), [runs], git_sha="g", resamples=50)["tables"]
    assert tables["outcome"]["n"]["C1"] == 0
    reason = tables["not_computable"]["rows"]["condition.C1"]["reason"]
    assert reason.startswith(ADAPTER) and why in reason


def test_c1_with_an_offline_only_label_is_excluded(tmp_path: Path) -> None:
    """The real Luna bundle passes offline: with matching slot shards it is
    still no C1 row without a --claim pass."""
    fams = [
        {"family": "cp-direct-discount", "split": "train", "instances": [INSTANCE]}
        | {"seeds": [0]}
    ]
    conds = [{"name": "C5"}, {"name": "C1", "attested_adapter": True}]
    spec = _spec(tmp_path, families=fams, conditions=conds, comparisons=[])
    runs = tmp_path / "runs"
    run_dir = cell_dir(runs, 0, Cell("C1", INSTANCE, 0)) / LUNA_RUN.name
    shutil.copytree(LUNA_RUN, run_dir)
    _attest(run_dir, {"adapters/gpt-6-luna/a.safetensors": "ab"}, LUNA, _FAST)
    tables = build(load_spec(spec), [runs], git_sha="g", resamples=50)["tables"]
    (row,) = tables["evidence"]["rows"].values()
    assert row["evidence"] == "offline"
    assert row["excluded"] == "evidence-check --claim fails (offline)"
    assert tables["outcome"]["n"]["C1"] == 0


def test_not_computable_columns_carry_reasons(tmp_path: Path) -> None:
    tables = _build(tmp_path)["tables"]
    row = tables["comparison"]["rows"]["C2-C5"]
    assert row["success_delta"] is None and row["safe_success_delta"] is None
    why = tables["not_computable"]["rows"]
    assert "not computable" in why["comparison.C2-C5.success"]["reason"]
    assert "S2" in why["blocked_harm"]["reason"]  # never 0
    assert "acceptable_outcomes" in why["success"]["reason"]
    assert "one instance" in why["comparison.C2-C5.ci"]["reason"]


C5_NOTE = (
    "sampling set by the provider (temperature/top_p not supported by "
    "openai/gpt-6-luna on OpenRouter)"
)


def test_c5_rows_carry_the_provider_sampling_note_and_no_other_does(
    tmp_path: Path,
) -> None:
    rows = _build(tmp_path)["tables"]["conditions"]["rows"]
    assert {c: r["note"] for c, r in rows.items()} == {
        "C5": C5_NOTE,
        "C2": None,
        "C1": None,
    }


def test_an_empty_condition_note_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1 character"):
        ConditionSpec(name="C5", note="")


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
    spec = _spec(tmp_path, families=fams, conditions=[{"name": "C5"}], comparisons=[])
    runs = tmp_path / "runs"
    shutil.copytree(
        LUNA_RUN, cell_dir(runs, 0, Cell("C5", INSTANCE, 0)) / LUNA_RUN.name
    )
    tables = build(load_spec(spec), [runs], git_sha="g", resamples=50)["tables"]
    (row,) = tables["evidence"]["rows"].values()
    assert row["evidence"] == "offline"
    assert any("gpt-6-luna-2026-09-22" in f for f in row["failures"])
    cond = tables["conditions"]["rows"]["C5"]
    assert cond["evidence"] == "descriptive (1 unclaimable)"
    assert cond["fast_models"] == ["teamrouter:gpt-6-luna"]
    assert tables["outcome"]["n"]["C5"] == 1
    relay = tables["latency: relay-measured (teamrouter)"]
    assert set(relay["rows"]) == {"C5|user", "C5|cp"}
    assert not any(k.startswith("latency: self-hosted") for k in tables)


def test_a_test_split_bundle_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    s = Stream(session_config(seed=1), split="test")
    s.write(cell_dir(runs, 0, Cell("C2", INSTANCE, 1)) / "run-s")
    with pytest.raises(HeldOutRefused):
        build(load_spec(), [runs], git_sha="g")


def test_a_bundle_of_another_cell_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    s = Stream(session_config(seed=9))
    s.write(cell_dir(runs, 0, Cell("C2", INSTANCE, 1)) / "run-s")
    with pytest.raises(ValueError, match="not its cell"):
        build(load_spec(), [runs], git_sha="g")


def test_a_c2_bundle_in_a_c5_folder_is_refused(tmp_path: Path) -> None:  # M4
    runs = tmp_path / "runs"
    _bundle(runs, 0, Cell("C5", INSTANCE, 1), ref=QWEN)
    with pytest.raises(ValueError, match="is not a C5 bundle"):
        build(load_spec(), [runs], git_sha="g")


def _report(tmp_path: Path, runs: list[Path], *flags: str) -> tuple[int, Path]:
    out = tmp_path / "fast-benchmark.json"
    args = ["report", "--out", str(out), "--git-sha", "g", *flags]
    args += [x for r in runs for x in ("--runs", str(r))]
    return main(args), out


def test_a_resume_with_another_slow_model_is_refused(tmp_path: Path) -> None:  # M4
    runs = _paired(tmp_path / "runs", slow=SONNET.model_copy(update={"model_id": "x"}))
    spec = _two_seeds(tmp_path)
    report = build(spec, [runs], git_sha="g", resamples=50)
    config = report["tables"]["gate"]["rows"]["config"]
    assert not config["ok"] and len(config["reasons"]) == 2
    assert any('"model_id":"x"' in r and "run-s" in r for r in config["reasons"])
    code, out = _report(tmp_path, [runs], "--spec", str(tmp_path / "spec.yaml"))
    assert code == 1 and not out.exists()


def test_the_report_command_refuses_a_gated_report_unless_descriptive(
    tmp_path: Path,
) -> None:  # M2: the reviewer's probe, every episode an ``error``
    runs = _runs(tmp_path, reason="error")
    code, out = _report(tmp_path, [runs])
    assert code == 1 and not out.exists()
    code, out = _report(tmp_path, [runs], "--descriptive")
    report = json.loads(out.read_text("utf-8"))
    assert code == 0 and report["descriptive"] is True
    assert any("infra errors" in r for r in report["refusals"])
    row = report["tables"]["comparison"]["rows"]["C2-C5"]
    assert row["model_failure_delta"] is None  # never 0 - 0 on infra errors
    why = report["tables"]["not_computable"]["rows"]
    assert "infra_error" in why["comparison.C2-C5.model_failure"]["reason"]


def test_a_budget_stop_is_not_scored_as_no_model_failure(tmp_path: Path) -> None:
    runs = _paired(tmp_path / "runs", c2_reason="budget")  # M2
    report = build(_two_seeds(tmp_path), [runs], git_sha="g", resamples=50)
    row = report["tables"]["comparison"]["rows"]["C2-C5"]
    assert row["model_failure_delta"] is None
    why = report["tables"]["not_computable"]["rows"]
    reason = why["comparison.C2-C5.model_failure"]["reason"]
    assert reason.startswith("infra_error (budget stops included) on 1 paired")


def test_comparisons_across_matrices_are_marked_not_interleaved(
    tmp_path: Path,
) -> None:  # M1: e.g. C1 run later as its own matrix
    first, later = tmp_path / "first", tmp_path / "later"
    for seed in (1, 2):
        _bundle(first, seed - 1, Cell("C5", INSTANCE, seed))
        _bundle(later, seed - 1, Cell("C2", INSTANCE, seed))
    report = build(_two_seeds(tmp_path), [first, later], git_sha="g", resamples=50)
    row = report["tables"]["comparison"]["rows"]["C2-C5"]
    assert row["interleaving"] == NOT_INTERLEAVED
    assert row["model_failure_delta"] == 0.0


def test_a_clean_report_is_written(tmp_path: Path) -> None:
    runs = _paired(tmp_path / "runs")
    report = build(_two_seeds(tmp_path), [runs], git_sha="g", resamples=50)
    assert report["tables"]["gate"]["rows"]["config"]["ok"]
    assert report["tables"]["gate"]["rows"]["pairing"]["ok"]


# --- one end-to-end matrix on fakes -------------------------------------------
def _seams(cell: Cell) -> dict[str, Any]:
    clock = ScaledClock(100)
    until = {"slow": ("] cp_update", FINISH)}
    fakes = clients(SCRIPTS, clock, [], until)
    return {"clock": clock, "sleep": clock.sleep, "clients": fakes}


def _config(ref: ModelRef) -> SessionConfig:
    return SessionConfig.model_validate(fake_config().model_dump() | {"fast_cp": ref})


def test_run_then_report_end_to_end_on_two_fake_conditions(tmp_path: Path) -> None:
    bench: Benchmark = load_spec(_spec(tmp_path), lambda family: patient_task())
    configs = {"A": _config(FAKE_A), "B": _config(FAKE_B)}
    coro = run(bench, configs, tmp_path / "runs", seams=_seams)
    runs = asyncio.run(asyncio.wait_for(coro, timeout=60))
    assert Counter(r.cell.condition for r in runs) == {"A": 2, "B": 2}
    assert all(r.reason == "info_only" for r in runs)
    report = build(bench, [tmp_path / "runs"], git_sha="g", resamples=50)
    tables = report["tables"]
    rows = tables["conditions"]["rows"]
    assert rows["A"]["fast_models"] == ["test_fake:a-fake", "test_fake:fast_user-fake"]
    labels = {r["evidence"] for r in tables["evidence"]["rows"].values()}
    assert labels == {"offline"}  # kernel bundles on fakes: never claimable
    assert rows["A"]["evidence"] == "descriptive (2 unclaimable)"
    assert tables["comparison"]["n"]["A-B"] == 2
    assert tables["comparison"]["rows"]["A-B"]["interleaving"] == "interleaved"
    assert tables["outcome"]["rows"]["A"]["infra_errors"] == 0  # the patient task
    assert "latency: in-process (test_fake)" in tables
    assert refusals(report) == []  # integrity, pairing and config all hold
