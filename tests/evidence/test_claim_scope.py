"""S1-SYS-14: a claim is scoped to its Fast model (``evidence.reality``).

A Qwen claim needs Qwen@vllm with P3 = pass; a hosted Fast (Luna) passes
``--claim`` only as hosted-Fast evidence under its own ``ModelRef``; a C1
(trained ``-pl-`` slot) bundle needs its adapter shards recorded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.contract.samples import QWEN, SONNET
from tests.support.recorded import write_fast_bundle

from proxyloop import cli
from proxyloop.contract.bundle import EVENTS, MANIFEST, Manifest
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.llm import AdapterKind, ModelRef
from proxyloop.evidence.check import check_path
from proxyloop.evidence.reality import QWEN_PREFIX, TRAINED_MARK
from proxyloop.kernel.session import RunResult
from proxyloop.models import registry
from serving import config

RESPONSE = "Thanks, that helps. Could you read the full offer back to me?\n@hold offer"
LUNA = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="openrouter",
    model_id="openai/gpt-6-luna",
    reasoning_effort="none",
)
LUNA_ID = "openrouter:openai/gpt-6-luna"
C1 = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id="Qwen3.5-9B-pl-x1")
SHARD = "adapters/Qwen3.5-9B-pl-x1/adapter_model.safetensors"


def _edit(run: Path, **update: object) -> None:
    body = json.loads((run / MANIFEST).read_text("utf-8")) | update
    (run / MANIFEST).write_text(
        Manifest.model_validate(body).model_dump_json(), "utf-8"
    )


def _recfg(run: Path, **update: object) -> None:
    """A new cfg, with its hash in the manifest and in session.started."""
    cfg = json.loads((run / MANIFEST).read_text("utf-8"))["cfg"] | update
    cfg_hash = config_hash(SessionConfig.model_validate(cfg))
    _edit(run, cfg=cfg, cfg_hash=cfg_hash)
    first, *rest = (run / EVENTS).read_text("utf-8").splitlines()
    started = json.loads(first)
    started["payload"]["cfg_hash"] = cfg_hash
    lines = [json.dumps(started), *rest]
    (run / EVENTS).write_text("".join(f"{line}\n" for line in lines), "utf-8")


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
    want = f"a Qwen claim needs Qwen@vllm: fast_cp ran hosted {LUNA_ID}"
    assert want in report.failures


def test_a_qwen_claim_rejects_another_model_on_vllm(tmp_path: Path) -> None:
    llama = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id="Llama-4-8B")
    report = check_path(_bundle(tmp_path, llama, p3="pass"), "claim", about="qwen")
    want = "a Qwen claim needs Qwen@vllm: fast_cp ran vllm vllm:Llama-4-8B"
    assert want in report.failures
    assert report.scope == "vllm, not a Qwen claim: fast_cp=vllm:Llama-4-8B; P3 pass"


def test_a_qwen_claim_scopes_a_mixed_lane_bundle_to_its_claimed_lanes(
    tmp_path: Path,
) -> None:  # EVAL A3: a hosted fast_user, a vLLM fast_cp
    run = _bundle(tmp_path, QWEN, p3="pass")
    _recfg(run, fast_user=LUNA.model_dump())
    body = json.loads((run / MANIFEST).read_text("utf-8"))
    models = body["models"] | {"fast_user": {"ref": LUNA.model_dump()}}
    _edit(run, models=models, reality=body["reality"] | {"fast_user": "real_http"})
    both = check_path(run, "claim", about="qwen")
    want = f"a Qwen claim needs Qwen@vllm: fast_user ran hosted {LUNA_ID}"
    assert want in both.failures
    cp = check_path(run, "claim", roles={"fast_cp"}, about="qwen")
    assert cp.ok, cp.failures
    assert cp.scope == "Qwen@vllm: fast_cp=vllm:Qwen3.5-9B; P3 pass"


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


def test_a_trained_slot_is_found_by_its_served_name_too(tmp_path: Path) -> None:
    models = {"fast_cp": {"ref": QWEN.model_dump(), "served_model": C1.model_id}}
    run = _bundle(tmp_path, QWEN, p3="pass", models=models)
    want = "fast_cp runs the trained slot Qwen3.5-9B-pl-x1 with no adapter_shards"
    assert any(f.startswith(want) for f in check_path(run, "claim").failures)


def test_the_marks_are_servings_names() -> None:
    assert config.TRAINED_PREFIX.endswith(TRAINED_MARK)
    assert TRAINED_MARK not in QWEN.model_id
    served = [name for _, _, name in config.MODELS.values()]
    assert all(n.startswith(QWEN_PREFIX) for n in [*served, config.TRAINED_PREFIX])
    names = [n for n in registry.models() if n != registry.TRAINED]
    vllm = [r for r in map(registry.resolve, names) if r.endpoint == "vllm"]
    assert vllm and all(r.model_id.startswith(QWEN_PREFIX) for r in vllm)


def test_a_qwen_claim_rejects_a_teacher_repaired_bundle(tmp_path: Path) -> None:
    run = _bundle(tmp_path, QWEN, p3="pass")
    _recfg(run, teacher=SONNET.model_dump(), ablations=["teacher_repair_cp"])
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


def test_a_live_bundle_cannot_contain_baseline(tmp_path: Path) -> None:
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm-v1")
    run = write_fast_bundle(tmp_path / "f", RESPONSE, ref=fsm, live=True)
    assert "a live bundle contains baseline" in check_path(run).failures


def test_session_claim_prints_the_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _bundle(tmp_path, LUNA)

    async def ran(*_: object, **__: object) -> RunResult:
        return RunResult("run-test", run, "info_only")

    monkeypatch.setattr(cli, "run_session", ran)
    argv = ["session", "--family", "cp-direct-discount", "--condition", "C5"]
    cli.main([*argv, "--claim"])
    out = capsys.readouterr().out
    assert "claim check: ok" in out
    want = "claim scope: hosted-Fast evidence, not a Qwen claim: fast_cp=openrouter:"
    assert want in out
