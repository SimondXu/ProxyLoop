import json
import re
from pathlib import Path
from typing import Any

import pytest
from scripts.mod import lora_ladder

from serving import config

QKV, Z = ("linear_attn", "in_proj_qkv"), ("linear_attn", "in_proj_z")
Records = dict[str, dict[str, Any]]


def test_plan_has_zero_and_live_per_rung_and_one_nonzero_probe_per_target():
    plan = lora_ladder.adapter_plan()
    for rung, targets in config.RUNGS.items():
        assert plan[f"zero-{rung}"] == (targets, True, frozenset())
        assert plan[f"live-{rung}"] == (targets, False, frozenset())
    probes = {name: spec for name, spec in plan.items() if name.startswith("probe-")}
    assert len(probes) == 12 and len(plan) == 16
    for name, (targets, zero, zero_targets) in probes.items():
        assert zero is False and name == f"probe-{'.'.join(targets[0])}"
        # Exactly one non-zero target: the probed one.
        assert set(targets) - zero_targets == {targets[0]}
    assert (
        "probe-linear_attn.in_proj_qkv" in probes and "probe-self_attn.o_proj" in probes
    )


def test_every_adapter_with_in_proj_z_also_carries_in_proj_qkv():
    # vLLM 0.29.0 expand_packed_lora kills the engine on in_proj_qkvz packed as
    # [None, b_z].
    plan = lora_ladder.adapter_plan()
    for name, (targets, _, _) in plan.items():
        assert Z not in targets or QKV in targets, name
    targets, zero, zero_targets = plan["probe-linear_attn.in_proj_z"]
    assert targets == (Z, QKV) and zero is False
    assert QKV in zero_targets and Z not in zero_targets
    assert plan["probe-linear_attn.in_proj_qkv"] == ((QKV,), False, frozenset())


def test_missing_pack_leaders_adds_only_the_leading_member():
    assert config.missing_pack_leaders((Z,)) == (QKV,)
    assert config.missing_pack_leaders((QKV, Z)) == ()
    assert config.missing_pack_leaders((QKV,)) == ()
    assert (
        config.missing_pack_leaders(
            (("linear_attn", "in_proj_a"), ("self_attn", "k_proj"))
        )
        == ()
    )


def test_diff_stats():
    stats = lora_ladder.diff_stats([[-1.0, -2.0], [-3.0]], [[-1.0, -2.5], [-2.0]])
    assert stats == {"max_abs_diff": 1.0, "mean_abs_diff": pytest.approx(0.5)}


def results(**overrides: dict[str, Any]) -> Records:
    out: Records = {}
    for rung in config.RUNGS:
        out[f"zero-{rung}"] = {
            "loaded": True,
            "max_abs_diff": 0.0,
            "mean_abs_diff": 0.0,
        }
        out[f"live-{rung}"] = {
            "loaded": True,
            "max_abs_diff": 0.3,
            "mean_abs_diff": 0.05,
        }
    for parent, proj in config.RUNGS["all"]:
        out[f"probe-{parent}.{proj}"] = {"loaded": True, "mean_abs_diff": 0.02}
    out.update(overrides)
    return out


def test_everything_applied_passes_both_rungs():
    summary = lora_ladder.summarise(results())
    assert summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]
    assert len(summary["applied_targets"]) == 12


def test_a_silently_ignored_gdn_target_fails_rung_1_only():
    summary = lora_ladder.summarise(
        results(
            **{"probe-linear_attn.in_proj_b": {"loaded": True, "mean_abs_diff": 0.0}}
        )
    )
    assert not summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]
    assert "linear_attn.in_proj_b" not in summary["applied_targets"]


@pytest.mark.parametrize(
    "name, record",
    [
        (
            "zero-all",
            {"loaded": False, "error": "ValueError: expected target modules in [...]"},
        ),
        ("zero-all", {"loaded": True, "max_abs_diff": 2e-4, "mean_abs_diff": 1e-5}),
        ("live-all", {"loaded": True, "max_abs_diff": 1e-4, "mean_abs_diff": 1e-4}),
        ("live-all", {"loaded": False, "error": "x"}),
    ],
)
def test_zero_or_live_adapter_failures_fail_their_rung(
    name: str, record: dict[str, Any]
) -> None:
    summary = lora_ladder.summarise(results(**{name: record}))
    assert not summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]


def test_a_rejected_probe_is_not_applied():
    summary = lora_ladder.summarise(
        results(**{"probe-mlp.down_proj": {"loaded": False, "error": "x"}})
    )
    assert not summary["rung_ok:all"] and not summary["rung_ok:attn-mlp"]


def test_an_aborted_run_is_a_failure_and_lists_the_missing_adapters():
    done = {
        name: r
        for name, r in results().items()
        if not name.startswith(
            (
                "probe-linear_attn.in_proj_z",
                "probe-linear_attn.in_proj_b",
                "probe-linear_attn.in_proj_a",
                "probe-linear_attn.out_proj",
                "probe-mlp",
            )
        )
    }
    summary = lora_ladder.summarise(done, aborted_at="probe-linear_attn.in_proj_z")
    assert (
        summary["complete"] is False
        and summary["aborted_at"] == "probe-linear_attn.in_proj_z"
    )
    assert summary["missing_adapters"] == [
        "probe-linear_attn.in_proj_z",
        "probe-linear_attn.in_proj_b",
        "probe-linear_attn.in_proj_a",
        "probe-linear_attn.out_proj",
        "probe-mlp.gate_proj",
        "probe-mlp.up_proj",
        "probe-mlp.down_proj",
    ]
    assert not summary["rung_ok:all"] and not summary["rung_ok:attn-mlp"]


def test_an_abort_fails_every_rung_even_with_all_records_present():
    summary = lora_ladder.summarise(results(), aborted_at="probe-mlp.down_proj")
    assert summary["complete"] is False and summary["missing_adapters"] == []
    assert not summary["rung_ok:all"] and not summary["rung_ok:attn-mlp"]


def test_a_complete_run_reports_complete():
    summary = lora_ladder.summarise(results())
    assert (
        summary["complete"] is True
        and summary["aborted_at"] is None
        and summary["missing_adapters"] == []
    )


class Remote:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def remote(self) -> dict[str, Any]:
        return self.result


def run_main(out: Path) -> None:
    """The local entrypoint's undecorated body."""
    raw_f = lora_ladder.main.info.raw_f
    assert raw_f is not None
    raw_f(out=str(out))


def test_a_complete_run_writes_out_into_a_missing_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result: dict[str, Any] = {
        "adapters": results(),
        "summary": lora_ladder.summarise(results()),
    }
    monkeypatch.setattr(lora_ladder, "lora_ladder", Remote(result))
    out = tmp_path / "new" / "dir" / "ladder.json"
    run_main(out)
    assert json.loads(out.read_text()) == result
    assert not out.with_suffix(".aborted.json").exists()


def test_main_keeps_an_aborted_result_beside_out_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = lora_ladder.summarise({}, aborted_at="zero-all")
    result = {
        "adapters": {},
        "aborted_at": "zero-all",
        "error": "EngineDeadError: x",
        "summary": summary,
    }
    monkeypatch.setattr(lora_ladder, "lora_ladder", Remote(result))
    out = tmp_path / "missing" / "ladder.json"
    with pytest.raises(SystemExit, match="aborted at zero-all"):
        run_main(out)
    # The serve-up order guard only checks that --out exists.
    assert not out.exists()
    assert (
        json.loads((tmp_path / "missing" / "ladder.aborted.json").read_text()) == result
    )


def test_an_aborted_run_moves_a_stale_out_aside_and_touches_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = lora_ladder.summarise({}, aborted_at="zero-all")
    result = {
        "adapters": {},
        "aborted_at": "zero-all",
        "error": "EngineDeadError: x",
        "summary": summary,
    }
    out, neighbour = tmp_path / "ladder.json", tmp_path / "vllm-probe.json"
    out.write_text('{"earlier": "paid run"}')
    neighbour.write_text("{}")
    monkeypatch.setattr(lora_ladder, "lora_ladder", Remote(result))
    with pytest.raises(SystemExit):
        run_main(out)
    assert not out.exists() and neighbour.read_text() == "{}"
    superseded = [
        p for p in tmp_path.iterdir() if p.name.startswith("ladder.superseded-")
    ]
    assert len(superseded) == 1 and re.fullmatch(
        r"ladder\.superseded-\d{8}T\d{6}Z\.json", superseded[0].name
    )
    assert superseded[0].read_text() == '{"earlier": "paid run"}'
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["ladder.aborted.json", superseded[0].name, "vllm-probe.json"]
    )


def test_zero_layer_counts_matches_parent_and_projection_exactly():
    names = [
        f"base_model.model.model.language_model.layers.{i}.linear_attn.{proj}"
        for i in (0, 1)
        for proj in ("in_proj_qkv", "in_proj_z")
    ]
    counts = lora_ladder.zero_layer_counts(
        names, frozenset({QKV, ("self_attn", "q_proj")})
    )
    assert counts == {QKV: 2, ("self_attn", "q_proj"): 0}
    assert lora_ladder.zero_layer_counts(names, frozenset()) == {}


class Volume:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


@pytest.mark.filterwarnings("ignore:The lora_ladder function is executing locally")
def test_the_remote_function_saves_its_result_on_the_adapters_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial: dict[str, Any] = {
        "adapters": {},
        "aborted_at": "zero-all",
        "error": "EngineDeadError: x",
        "summary": lora_ladder.summarise({}, aborted_at="zero-all"),
    }
    volume = Volume()

    def download_model() -> Path:
        return tmp_path / "model"

    def runtime() -> dict[str, Any]:
        return {"vllm_version": "0.29.0", "gpu_name": "H100"}

    def version(name: str) -> str:
        return "0.21.0"

    def run(model_dir: Path, adapter_root: Path) -> dict[str, Any]:
        return partial

    monkeypatch.setattr(
        lora_ladder.modal_vllm, "ADAPTER_DIR", str(tmp_path / "adapters")
    )
    monkeypatch.setattr(lora_ladder.modal_vllm, "adapter_volume", volume)
    monkeypatch.setattr(lora_ladder.modal_vllm, "download_model", download_model)
    monkeypatch.setattr(lora_ladder.modal_vllm, "runtime", runtime)
    monkeypatch.setattr(lora_ladder.metadata, "version", version)
    monkeypatch.setattr(lora_ladder, "run", run)
    returned = lora_ladder.lora_ladder.local()
    saved = tmp_path / "adapters" / returned["volume_copy"]
    assert (
        json.loads(saved.read_text()) == returned
        and returned["aborted_at"] == "zero-all"
    )
    assert returned["runtime"]["peft_version"] == "0.21.0" and volume.commits == 1
