import pytest

from serving import config, zero_lora


def test_plan_has_both_zero_rungs_and_one_nonzero_probe_per_target():
    plan = zero_lora.adapter_plan()
    assert plan["zero-all"] == (config.RUNGS["zero-all"], True)
    assert plan["zero-attn-mlp"] == (config.RUNGS["zero-attn-mlp"], True)
    probes = {name: spec for name, spec in plan.items() if name.startswith("probe-")}
    assert len(probes) == 12
    assert all(len(targets) == 1 and zero is False for targets, zero in probes.values())
    assert "probe-linear_attn.in_proj_qkv" in probes and "probe-self_attn.o_proj" in probes


def test_diff_stats():
    stats = zero_lora.diff_stats([[-1.0, -2.0], [-3.0]], [[-1.0, -2.5], [-2.0]])
    assert stats == {"max_abs_diff": 1.0, "mean_abs_diff": pytest.approx(0.5)}


def results(**overrides) -> dict:
    out = {"zero-all": {"loaded": True, "max_abs_diff": 0.0},
           "zero-attn-mlp": {"loaded": True, "max_abs_diff": 0.0}}
    for parent, proj in config.RUNGS["zero-all"]:
        out[f"probe-{parent}.{proj}"] = {"loaded": True, "mean_abs_diff": 0.02}
    out.update(overrides)
    return out


def test_everything_applied_passes_both_rungs():
    summary = zero_lora.summarise(results())
    assert summary["rung_ok:zero-all"] and summary["rung_ok:zero-attn-mlp"]
    assert len(summary["applied_targets"]) == 12


def test_a_silently_ignored_gdn_target_fails_rung_1_only():
    summary = zero_lora.summarise(results(**{
        "probe-linear_attn.in_proj_b": {"loaded": True, "mean_abs_diff": 0.0}}))
    assert not summary["rung_ok:zero-all"] and summary["rung_ok:zero-attn-mlp"]
    assert "linear_attn.in_proj_b" not in summary["applied_targets"]


def test_a_rejected_zero_adapter_or_a_nonzero_zero_adapter_fails_its_rung():
    rejected = {"loaded": False, "error": "ValueError: expected target modules in [...]"}
    assert not zero_lora.summarise(results(**{"zero-all": rejected}))["rung_ok:zero-all"]
    drifted = {"loaded": True, "max_abs_diff": 2e-4}
    assert not zero_lora.summarise(results(**{"zero-attn-mlp": drifted}))["rung_ok:zero-attn-mlp"]


def test_a_rejected_probe_is_not_applied():
    summary = zero_lora.summarise(results(**{"probe-mlp.down_proj": {"loaded": False, "error": "x"}}))
    assert not summary["rung_ok:zero-all"] and not summary["rung_ok:zero-attn-mlp"]
