import pytest

from scripts.mod import lora_ladder
from serving import config


def test_plan_has_zero_and_live_per_rung_and_one_nonzero_probe_per_target():
    plan = lora_ladder.adapter_plan()
    for rung, targets in config.RUNGS.items():
        assert plan[f"zero-{rung}"] == (targets, True)
        assert plan[f"live-{rung}"] == (targets, False)
    probes = {name: spec for name, spec in plan.items() if name.startswith("probe-")}
    assert len(probes) == 12 and len(plan) == 16
    assert all(len(targets) == 1 and zero is False for targets, zero in probes.values())
    assert "probe-linear_attn.in_proj_qkv" in probes and "probe-self_attn.o_proj" in probes


def test_diff_stats():
    stats = lora_ladder.diff_stats([[-1.0, -2.0], [-3.0]], [[-1.0, -2.5], [-2.0]])
    assert stats == {"max_abs_diff": 1.0, "mean_abs_diff": pytest.approx(0.5)}


def results(**overrides) -> dict:
    out = {}
    for rung in config.RUNGS:
        out[f"zero-{rung}"] = {"loaded": True, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
        out[f"live-{rung}"] = {"loaded": True, "max_abs_diff": 0.3, "mean_abs_diff": 0.05}
    for parent, proj in config.RUNGS["all"]:
        out[f"probe-{parent}.{proj}"] = {"loaded": True, "mean_abs_diff": 0.02}
    out.update(overrides)
    return out


def test_everything_applied_passes_both_rungs():
    summary = lora_ladder.summarise(results())
    assert summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]
    assert len(summary["applied_targets"]) == 12


def test_a_silently_ignored_gdn_target_fails_rung_1_only():
    summary = lora_ladder.summarise(results(**{
        "probe-linear_attn.in_proj_b": {"loaded": True, "mean_abs_diff": 0.0}}))
    assert not summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]
    assert "linear_attn.in_proj_b" not in summary["applied_targets"]


@pytest.mark.parametrize("name, record", [
    ("zero-all", {"loaded": False, "error": "ValueError: expected target modules in [...]"}),
    ("zero-all", {"loaded": True, "max_abs_diff": 2e-4, "mean_abs_diff": 1e-5}),
    ("live-all", {"loaded": True, "max_abs_diff": 1e-4, "mean_abs_diff": 1e-4}),
    ("live-all", {"loaded": False, "error": "x"}),
])
def test_zero_or_live_adapter_failures_fail_their_rung(name, record):
    summary = lora_ladder.summarise(results(**{name: record}))
    assert not summary["rung_ok:all"] and summary["rung_ok:attn-mlp"]


def test_a_rejected_probe_is_not_applied():
    summary = lora_ladder.summarise(results(**{"probe-mlp.down_proj": {"loaded": False, "error": "x"}}))
    assert not summary["rung_ok:all"] and not summary["rung_ok:attn-mlp"]
