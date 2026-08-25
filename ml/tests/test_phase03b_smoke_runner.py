from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from proxyloop_contracts import canonical_fingerprint
from proxyloop_evaluation.phase03b_experiment import (
    PHASE03B_EVALUATOR_SOURCE_FINGERPRINT,
    Phase03BQwenAdapter,
    build_phase03b_examples,
)
from proxyloop_evaluation.qwen_mlx import MAX_RAW_OUTPUT_CHARS, QwenGenerationText

from scripts.run_phase03b_smoke import (
    PHASE03B_RUNNER_SOURCE_FINGERPRINT,
    _evaluation_pipeline_fingerprint,
    _result_content_fingerprint,
    parse_args,
    run_smoke,
    validate_args,
)


def _args(
    tmp_path: Path,
    arm: str,
    *,
    adapter: Path | None = None,
    baseline: Path | None = None,
):
    values = [
        "--arm",
        arm,
        "--model-path",
        str(tmp_path / "local-model"),
        "--output",
        str(tmp_path / f"{arm}.json"),
    ]
    if adapter is not None:
        values.extend(("--adapter-path", str(adapter)))
    if baseline is not None:
        values.extend(("--baseline-result", str(baseline)))
    return parse_args(values)


def _adapter(
    raw: str,
    *,
    adapter_path: Path | None = None,
) -> Phase03BQwenAdapter:
    return Phase03BQwenAdapter(
        generator=lambda _: QwenGenerationText(
            text=raw,
            input_tokens=3,
            output_tokens=2,
        ),
        adapter_path=str(adapter_path) if adapter_path is not None else None,
    )


def _sequence_adapter(
    raw_outputs: list[str],
    *,
    adapter_path: Path | None = None,
) -> Phase03BQwenAdapter:
    outputs = iter(raw_outputs)
    return Phase03BQwenAdapter(
        generator=lambda _: QwenGenerationText(
            text=next(outputs),
            input_tokens=3,
            output_tokens=2,
        ),
        adapter_path=str(adapter_path) if adapter_path is not None else None,
    )


def _adapter_artifact(tmp_path: Path) -> Path:
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    (adapter_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_path / "adapters.safetensors").write_bytes(b"synthetic")
    return adapter_path


def _write_canonical_baseline(
    path: Path, payload: dict[str, object]
) -> dict[str, object]:
    fixture = dict(payload)
    fixture["result_role"] = "canonical"
    fixture["execution"] = {
        "mode": "local_mlx",
        "checkpoint_attestation": "observed_local_files",
    }
    fixture["result_content_fingerprint"] = _result_content_fingerprint(fixture)
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return fixture


def test_cli_requires_the_correct_adapter_argument_for_each_arm(
    tmp_path: Path,
) -> None:
    validate_args(_args(tmp_path, "A"))
    with pytest.raises(ValueError, match="forbids"):
        validate_args(_args(tmp_path, "A", adapter=tmp_path / "adapter"))
    with pytest.raises(ValueError, match="requires"):
        validate_args(_args(tmp_path, "B"))
    with pytest.raises(ValueError, match="baseline"):
        validate_args(_args(tmp_path, "B", adapter=tmp_path / "adapter"))


def test_runner_keeps_invalid_rows_and_writes_bounded_descriptive_metrics(
    tmp_path: Path,
) -> None:
    raw = (
        '{"completion_claim":{"status":"candidate"},'
        '"response_text":"Contact test@example.com; I completed the request."}'
    )
    output = tmp_path / "nested" / "arm-a.json"
    payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=output,
        adapter=_adapter(raw),
    )

    assert output.exists()
    assert payload["schema_version"] == "phase-03b-qwen-smoke-result-v2"
    assert payload["result_role"] == "diagnostic"
    assert payload["execution"] == {
        "mode": "injected_test",
        "checkpoint_attestation": "injected_test",
    }
    assert len(payload["evaluation_pipeline_fingerprint"]) == 64
    assert "evaluator_source_fingerprint" not in payload
    assert len(payload["result_content_fingerprint"]) == 64
    assert _result_content_fingerprint(payload) == payload["result_content_fingerprint"]
    assert payload["arm"] == "A"
    assert payload["slow_call_count"] == 0
    episodes = payload["episodes"]
    assert isinstance(episodes, list)
    assert len(episodes) == 6
    assert all(item["raw_output"] == raw for item in episodes)
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert all(item["raw_output_sha256"] == expected_hash for item in episodes)
    assert all(len(item["scenario_id"]) > 0 for item in episodes)
    assert all(len(item["family_id"]) > 0 for item in episodes)
    assert all(len(item["input_fingerprint"]) == 64 for item in episodes)
    assert all(len(item["prompt_fingerprint"]) == 64 for item in episodes)

    aggregate = payload["aggregate"]
    assert aggregate["episodes"] == 6
    for field in (
        "schema_valid",
        "canonical_valid",
        "end_to_end_valid",
        "dialogue_act_accuracy",
        "action_candidate_quality",
        "completion_candidate_quality",
        "response_grounded",
    ):
        assert set(aggregate["metrics"][field]) == {"count", "rate"}
        assert aggregate["metrics"][field]["count"] == 0
        assert aggregate["metrics"][field]["rate"] == 0
    assert aggregate["metrics"]["false_completion"]["count"] == 6
    assert aggregate["metrics"]["pii_violation"]["count"] == 6
    assert aggregate["metrics"]["unsupported_response_violation"]["count"] == 6
    assert aggregate["latency_ms"]["observed_count"] == 6
    assert aggregate["tokens"] == {
        "input_observed_count": 6,
        "input_total": 18,
        "output_observed_count": 6,
        "output_total": 12,
    }
    assert payload["hard_gates"]["false_completion_zero_descriptive"] is False
    assert payload["hard_gates"]["all_reported_safety_zero_descriptive"] is False
    assert payload["hard_gates"]["slow_call_count_zero"] is True
    assert payload["hard_gates"]["descriptive_only"] is True
    assert payload["controls"]["adapter"]["path_state"] == "none"
    assert payload["controls"]["adapter"]["tuning"] == "untuned"

    serialized = json.dumps(payload, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "model_path" not in serialized
    assert "adapter_path" not in serialized


def test_runner_rejects_duplicate_json_keys_as_unsupported(tmp_path: Path) -> None:
    raw = (
        '{"completion_claim":{"status":"candidate",'
        '"evidence_message_ids":[]},'
        '"completion_claim":{"status":"not_done",'
        '"evidence_message_ids":[]}}'
    )
    payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=tmp_path / "arm-a.json",
        adapter=_adapter(raw),
    )
    episodes = payload["episodes"]
    assert all(item["metrics"]["status"] == "invalid_output" for item in episodes)
    assert all(
        item["metrics"]["failure_category"] == "duplicate_json_key" for item in episodes
    )
    assert all(
        item["metrics"]["unsupported_response_violation"] is True for item in episodes
    )
    assert payload["hard_gates"]["unsupported_response_violation_zero"] is False


def test_runner_captures_b_adapter_identity_and_refuses_silent_overwrite(
    tmp_path: Path,
) -> None:
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    (adapter_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_path / "adapters.safetensors").write_bytes(b"synthetic")
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("not-json"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    output = tmp_path / "arm-b.json"
    adapter = _adapter("not-json", adapter_path=adapter_path)

    payload = run_smoke(
        arm="B",
        model_path=tmp_path / "local-model",
        output_path=output,
        adapter_path=adapter_path,
        baseline_result_path=baseline,
        adapter=adapter,
    )
    assert payload["controls"]["adapter"]["path_state"] == "local_adapter"
    assert payload["result_role"] == "diagnostic"
    assert payload["execution"] == {
        "mode": "injected_test",
        "checkpoint_attestation": "injected_test",
    }
    assert payload["controls"]["adapter"]["tuning"] == "qlora"
    assert len(payload["controls"]["adapter"]["fingerprint"]) == 64
    with pytest.raises(FileExistsError, match="overwrite"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=output,
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=adapter,
        )
    run_smoke(
        arm="B",
        model_path=tmp_path / "local-model",
        output_path=output,
        adapter_path=adapter_path,
        baseline_result_path=baseline,
        overwrite=True,
        adapter=adapter,
    )


@pytest.mark.parametrize(
    ("arm_b_false_completion_count", "expected_relative_gate"),
    ((1, True), (2, False)),
)
def test_b_records_false_completion_comparison_and_hard_gate(
    tmp_path: Path,
    arm_b_false_completion_count: int,
    expected_relative_gate: bool,
) -> None:
    examples = [
        example
        for example in build_phase03b_examples()
        if example.split == "development"
    ]
    false_raw = (
        '{"completion_claim":{"status":"candidate"},"response_text":"Offer completed."}'
    )
    target_outputs = [example.target.model_dump_json() for example in examples]
    arm_a_outputs = [false_raw, *target_outputs[1:]]
    arm_b_outputs = [
        false_raw if index < arm_b_false_completion_count else target_outputs[index]
        for index in range(len(target_outputs))
    ]
    baseline = tmp_path / "arm-a.json"
    arm_a = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_sequence_adapter(arm_a_outputs),
    )
    canonical_arm_a = _write_canonical_baseline(baseline, arm_a)
    assert arm_a["aggregate"]["metrics"]["false_completion"]["count"] == 1
    assert "comparison" not in arm_a

    adapter_path = _adapter_artifact(tmp_path)
    arm_b = run_smoke(
        arm="B",
        model_path=tmp_path / "local-model",
        output_path=tmp_path / "arm-b.json",
        adapter_path=adapter_path,
        baseline_result_path=baseline,
        adapter=_sequence_adapter(arm_b_outputs, adapter_path=adapter_path),
    )
    assert arm_b["result_role"] == "diagnostic"
    assert arm_b["execution"] == {
        "mode": "injected_test",
        "checkpoint_attestation": "injected_test",
    }
    comparison = arm_b["comparison"]
    assert comparison["arm_a_false_completion_count"] == 1
    assert comparison["arm_b_false_completion_count"] == arm_b_false_completion_count
    assert comparison["false_completion_not_above_arm_a"] is expected_relative_gate
    assert arm_b["hard_gates"]["false_completion_not_above_arm_a"] is (
        expected_relative_gate
    )
    absolute_safety_fields = (
        "policy_violation",
        "pii_violation",
        "disclosure_violation",
        "stale_pin_violation",
        "authority_violation",
        "unsupported_response_violation",
    )
    expected_hard_gate = expected_relative_gate and all(
        arm_b["hard_gates"][f"{field}_zero"] for field in absolute_safety_fields
    )
    assert arm_b["hard_gates"]["arm_b_hard_gates_pass"] is expected_hard_gate
    assert (
        comparison["canonical_arm_a_result_content_fingerprint"]
        == canonical_arm_a["result_content_fingerprint"]
    )
    assert _result_content_fingerprint(arm_b) == arm_b["result_content_fingerprint"]


def test_b_rejects_tampered_arm_a_before_generation(tmp_path: Path) -> None:
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    tampered["result_role"] = "diagnostic"
    baseline.write_text(json.dumps(tampered), encoding="utf-8")

    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    (adapter_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_path / "adapters.safetensors").write_bytes(b"synthetic")

    def forbidden(_: str) -> QwenGenerationText:
        raise AssertionError("generation must not run")

    output = tmp_path / "arm-b.json"
    adapter = Phase03BQwenAdapter(
        generator=forbidden,
        adapter_path=str(adapter_path),
    )
    with pytest.raises(ValueError, match="canonical Arm A baseline"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=output,
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=adapter,
        )
    assert not output.exists()


def test_injected_arm_a_is_diagnostic_and_cannot_be_b_baseline(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "arm-a.json"
    injected_a = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    assert injected_a["result_role"] == "diagnostic"
    assert injected_a["execution"] == {
        "mode": "injected_test",
        "checkpoint_attestation": "injected_test",
    }

    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="canonical Arm A baseline"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=tmp_path / "arm-b.json",
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0
    assert not (tmp_path / "arm-b.json").exists()


def test_b_rejects_baseline_output_path_alias_before_generation(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "arm-a.json"
    run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    before = baseline.read_bytes()
    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="must differ"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=baseline,
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            overwrite=True,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0
    assert baseline.read_bytes() == before


def test_b_rejects_hardlink_baseline_output_alias_before_generation(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "arm-a.json"
    run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    before = baseline.read_bytes()
    hardlink = tmp_path / "arm-b-hardlink.json"
    os.link(baseline, hardlink)
    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="must differ"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=hardlink,
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            overwrite=True,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0
    assert baseline.read_bytes() == before
    assert hardlink.read_bytes() == before


@pytest.mark.parametrize(
    "tamper",
    ("pipeline", "content", "runtime", "shared_control", "scenario_order"),
)
def test_b_rejects_each_baseline_provenance_tamper_before_generation(
    tmp_path: Path,
    tamper: str,
) -> None:
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    if tamper == "pipeline":
        tampered["evaluation_pipeline_fingerprint"] = "0" * 64
    elif tamper == "content":
        tampered["result_content_fingerprint"] = "0" * 64
    elif tamper == "runtime":
        tampered["runtime"]["python"] = "tampered"
    elif tamper == "shared_control":
        tampered["controls"]["manifest_fingerprint"] = "0" * 64
    elif tamper == "scenario_order":
        tampered["episodes"][0]["scenario_id"] = "tampered"
    if tamper != "content":
        tampered["result_content_fingerprint"] = _result_content_fingerprint(tampered)
    baseline.write_text(json.dumps(tampered), encoding="utf-8")

    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="canonical Arm A baseline"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=tmp_path / "arm-b.json",
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0


def test_b_rejects_nonzero_slow_call_count_before_generation(tmp_path: Path) -> None:
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    tampered["slow_call_count"] = 1
    tampered["result_content_fingerprint"] = _result_content_fingerprint(tampered)
    baseline.write_text(json.dumps(tampered), encoding="utf-8")

    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    (adapter_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_path / "adapters.safetensors").write_bytes(b"synthetic")

    def forbidden(_: str) -> QwenGenerationText:
        raise AssertionError("generation must not run")

    output = tmp_path / "arm-b.json"
    adapter = Phase03BQwenAdapter(
        generator=forbidden,
        adapter_path=str(adapter_path),
    )
    with pytest.raises(ValueError, match="slow_call_count"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=output,
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=adapter,
        )
    assert not output.exists()


@pytest.mark.parametrize("bad_count", (True, -1, 7, "1"))
def test_b_rejects_malformed_arm_a_false_completion_count_before_generation(
    tmp_path: Path,
    bad_count: object,
) -> None:
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    tampered["aggregate"]["metrics"]["false_completion"]["count"] = bad_count
    tampered["result_content_fingerprint"] = _result_content_fingerprint(tampered)
    baseline.write_text(json.dumps(tampered), encoding="utf-8")
    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="false_completion count"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=tmp_path / "arm-b.json",
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0


def test_b_rejects_valid_but_stale_arm_a_false_completion_count(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "arm-a.json"
    false_raw = '{"completion_claim":{"status":"candidate"}}'
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter(false_raw),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    assert tampered["aggregate"]["metrics"]["false_completion"]["count"] == 6
    tampered["aggregate"]["metrics"]["false_completion"]["count"] = 5
    tampered["result_content_fingerprint"] = _result_content_fingerprint(tampered)
    baseline.write_text(json.dumps(tampered), encoding="utf-8")
    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="does not match episode metrics"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=tmp_path / "arm-b.json",
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0


def test_b_rejects_non_boolean_episode_false_completion(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "arm-a.json"
    baseline_payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=baseline,
        adapter=_adapter("{}"),
    )
    _write_canonical_baseline(baseline, baseline_payload)
    tampered = json.loads(baseline.read_text(encoding="utf-8"))
    tampered["episodes"][0]["metrics"]["false_completion"] = 0
    tampered["result_content_fingerprint"] = _result_content_fingerprint(tampered)
    baseline.write_text(json.dumps(tampered), encoding="utf-8")
    adapter_path = _adapter_artifact(tmp_path)
    calls = 0

    def forbidden(_: str) -> QwenGenerationText:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not run")

    with pytest.raises(ValueError, match="must be boolean"):
        run_smoke(
            arm="B",
            model_path=tmp_path / "local-model",
            output_path=tmp_path / "arm-b.json",
            adapter_path=adapter_path,
            baseline_result_path=baseline,
            adapter=Phase03BQwenAdapter(
                generator=forbidden,
                adapter_path=str(adapter_path),
            ),
        )
    assert calls == 0


def test_evaluation_pipeline_fingerprint_binds_runner_source() -> None:
    expected = canonical_fingerprint(
        {
            "phase03b_experiment": PHASE03B_EVALUATOR_SOURCE_FINGERPRINT,
            "run_phase03b_smoke": PHASE03B_RUNNER_SOURCE_FINGERPRINT,
        }
    )
    assert _evaluation_pipeline_fingerprint() == expected
    assert _evaluation_pipeline_fingerprint() != canonical_fingerprint(
        {
            "phase03b_experiment": PHASE03B_EVALUATOR_SOURCE_FINGERPRINT,
            "run_phase03b_smoke": "0" * 64,
        }
    )


def test_raw_capture_is_capped_by_historical_limit(tmp_path: Path) -> None:
    raw = "x" * (MAX_RAW_OUTPUT_CHARS + 100)
    payload = run_smoke(
        arm="A",
        model_path=tmp_path / "local-model",
        output_path=tmp_path / "arm-a.json",
        adapter=_adapter(raw),
    )
    episodes = payload["episodes"]
    assert all(len(item["raw_output"]) <= MAX_RAW_OUTPUT_CHARS for item in episodes)


def test_runner_rejects_mismatched_adapter_before_generation(tmp_path: Path) -> None:
    base = _adapter("{}")

    class MismatchedAdapter:
        checkpoint_attestation = replace(
            base.checkpoint_attestation,
            checkpoint_fingerprint="f" * 64,
        )
        decoding_profile = base.decoding_profile
        adapter_version = base.adapter_version
        adapter_fingerprint = base.adapter_fingerprint
        adapter_path = None

        def generate(self, _view):
            raise AssertionError("generation must not run")

        def decide(self, _view):
            raise AssertionError("decide must not run")

    output = tmp_path / "mismatched.json"
    with pytest.raises(ValueError, match="base checkpoint attestation"):
        run_smoke(
            arm="A",
            model_path=tmp_path / "local-model",
            output_path=output,
            adapter=MismatchedAdapter(),
        )
    assert not output.exists()
