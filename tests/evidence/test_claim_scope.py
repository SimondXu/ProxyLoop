"""S1-SYS-14: a claim is scoped to its Fast model (``evidence.reality``).

A Qwen claim needs Qwen@vllm with P3 = pass; a hosted Fast (Luna) passes
``--claim`` only as hosted-Fast evidence under its own ``ModelRef``; a C1
(trained ``-pl-`` slot) bundle needs its adapter shards recorded."""

from __future__ import annotations

import json
from pathlib import Path

from tests.contract.samples import QWEN, SONNET
from tests.support.recorded import write_fast_bundle

from proxyloop.contract.bundle import MANIFEST, Manifest
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.evidence.check import check_path
from proxyloop.evidence.reality import TRAINED_MARK
from serving import config

RESPONSE = "Thanks, that helps. Could you read the full offer back to me?\n@hold offer"
LUNA = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="openrouter",
    model_id="openai/gpt-6-luna",
    reasoning_effort="none",
)
C1 = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id="Qwen3.5-9B-pl-x1")
SHARD = "adapters/Qwen3.5-9B-pl-x1/adapter_model.safetensors"


def _edit(run: Path, **update: object) -> None:
    body = json.loads((run / MANIFEST).read_text("utf-8")) | update
    (run / MANIFEST).write_text(
        Manifest.model_validate(body).model_dump_json(), "utf-8"
    )


def _bundle(tmp_path: Path, ref: ModelRef, **update: object) -> Path:
    run = write_fast_bundle(tmp_path / "run", RESPONSE, ref=ref, live=True)
    _edit(run, **update)
    return run


def test_a_luna_bundle_passes_the_claim_as_hosted_fast_evidence(
    tmp_path: Path,
) -> None:
    report = check_path(_bundle(tmp_path, LUNA), "claim")  # P3 not_applicable
    assert report.ok, report.failures
    assert report.scope is not None
    assert report.scope.startswith("hosted-Fast evidence, not a Qwen claim:")
    assert "fast_cp=openrouter:openai/gpt-6-luna (effort none)" in report.scope
    assert "P3 not_applicable (hosted Fast)" in report.scope


def test_a_qwen_claim_rejects_a_hosted_fast_bundle(tmp_path: Path) -> None:
    report = check_path(_bundle(tmp_path, LUNA), "claim", about="qwen")
    assert "a Qwen claim needs Qwen@vllm: fast_cp ran hosted" in report.failures


def test_a_qwen_bundle_with_p3_pass_supports_a_qwen_claim(tmp_path: Path) -> None:
    report = check_path(_bundle(tmp_path, QWEN, p3="pass"), "claim", about="qwen")
    assert report.ok, report.failures
    assert report.scope == "Qwen@vllm: fast_cp=vllm:Qwen3.5-9B; P3 pass"


def test_a_qwen_claim_needs_p3_pass(tmp_path: Path) -> None:
    for p3 in ("fail", "not_applicable"):
        run = _bundle(tmp_path / p3, QWEN, p3=p3)
        failures = check_path(run, "claim", about="qwen").failures
        assert f"P3 is {p3}" in failures
        assert f"a Qwen claim needs P3 pass, not {p3}" in failures


def test_p3_not_applicable_on_a_vllm_fast_fails_any_claim(tmp_path: Path) -> None:
    run = _bundle(tmp_path, QWEN)  # p3 not_applicable
    assert "P3 is not_applicable" in check_path(run, "claim").failures


def test_a_qwen_claim_needs_a_claimed_fast_role(tmp_path: Path) -> None:
    run = _bundle(tmp_path, QWEN, p3="pass")
    failures = check_path(run, "claim", roles=(), about="qwen").failures
    assert failures == ("a Qwen claim needs a claimed Fast role",)


def test_a_c1_bundle_without_adapter_shards_fails_the_claim(tmp_path: Path) -> None:
    report = check_path(_bundle(tmp_path, C1, p3="pass"), "claim")
    assert (
        "fast_cp runs the trained slot Qwen3.5-9B-pl-x1 with no adapter_shards"
        " (the training-card comparison is deferred)" in report.failures
    )


def test_a_c1_bundle_whose_shards_differ_from_the_attestation_fails(
    tmp_path: Path,
) -> None:
    models = {"fast_cp": {"ref": C1.model_dump(), "adapter_shards": {SHARD: "a" * 64}}}
    run = _bundle(tmp_path, C1, p3="pass", models=models, attestation={SHARD: "b"})
    failures = check_path(run, "claim").failures
    assert "the attestation does not match the adapter card" in failures
    assert not any("no adapter_shards" in f for f in failures)


def test_the_trained_mark_is_servings_slot_prefix() -> None:
    assert config.TRAINED_PREFIX.endswith(TRAINED_MARK)
    assert TRAINED_MARK not in QWEN.model_id


def test_a_qwen_claim_rejects_a_teacher_repaired_bundle(tmp_path: Path) -> None:
    run = _bundle(tmp_path, QWEN, p3="pass")
    cfg = json.loads((run / MANIFEST).read_text("utf-8"))["cfg"]
    cfg |= {"teacher": SONNET.model_dump(), "ablations": ["teacher_repair_cp"]}
    _edit(run, cfg=cfg, cfg_hash=config_hash(SessionConfig.model_validate(cfg)))
    report = check_path(run, "claim", roles={"fast_cp"}, about="qwen")
    assert (
        "a Qwen claim excludes teacher repair (R): the teacher spoke" in report.failures
    )
    assert report.scope is not None
    assert report.scope.startswith("teacher-repaired (R), not a Qwen claim:")


def test_an_f_bundle_fails_the_claim(tmp_path: Path) -> None:
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm-v1")
    run = write_fast_bundle(tmp_path / "f", RESPONSE, ref=fsm)
    report = check_path(run, "claim")
    assert "claimed role fast_cp ran baseline" in report.failures
    assert report.reality == {"fast_cp": "baseline_fsm"}
