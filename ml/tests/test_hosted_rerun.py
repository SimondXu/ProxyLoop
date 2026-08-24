from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from proxyloop_evaluation.artifacts_v2 import (
    R2_CEILING_PATH,
    R2_EPISODES_PATH,
    R2_MANIFEST_PATH,
    R2_REPORT_PATH,
    R3_REPORT_PATH,
)
from proxyloop_evaluation.hosted_rerun import (
    R4_PROBE_INPUT_TOKEN_CAP,
    R4_PROBE_LABEL_BY_EFFORT,
    R4_PROBE_OUTPUT_TOKEN_CAP,
    R4_REPORT_PATH,
    ProviderErrorEvidence,
    check_hosted_rerun_artifacts,
    check_hosted_rerun_sources,
    compose_r4_report,
    initial_matrix_from_source,
    load_source_reports,
    provider_errors_from_adapters,
    report_fingerprint_r4,
    run_provider_probes,
    write_report_r4,
)
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    FRONTIER_MODEL,
    FrontierResponseValidationError,
    OpenAIFrontierAdapter,
    ProviderProbeOutput,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class _Usage:
    prompt_tokens: int = 10
    completion_tokens: int = 20


@dataclass
class _Message:
    parsed: object


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]
    model: str = f"{FRONTIER_MODEL}-2026-07-09"
    id: str | None = "probe-response"
    usage: _Usage = field(default_factory=_Usage)


@dataclass
class _Completions:
    parsed: object

    def parse(self, **_: object) -> _Response:
        return _Response(choices=[_Choice(_Message(self.parsed))])


@dataclass
class _Client:
    chat: SimpleNamespace


def _adapter(effort: str, parsed: object) -> OpenAIFrontierAdapter:
    client = _Client(SimpleNamespace(completions=_Completions(parsed)))
    return OpenAIFrontierAdapter(
        client=client,
        reasoning_effort=effort,
        input_token_cap=R4_PROBE_INPUT_TOKEN_CAP,
        max_output_tokens=R4_PROBE_OUTPUT_TOKEN_CAP,
        call_cap=1,
        usd_ceiling=0.011264,
    )


def _successful_probe_adapters() -> tuple[OpenAIFrontierAdapter, OpenAIFrontierAdapter]:
    return (
        _adapter(
            "medium",
            ProviderProbeOutput(
                ok=True,
                label=R4_PROBE_LABEL_BY_EFFORT["medium"],
            ),
        ),
        _adapter(
            "high",
            ProviderProbeOutput(
                ok=True,
                label=R4_PROBE_LABEL_BY_EFFORT["high"],
            ),
        ),
    )


def test_provider_probe_requires_two_auditable_ordered_successes() -> None:
    probes = run_provider_probes(_successful_probe_adapters())

    assert tuple(item.reasoning_effort for item in probes) == ("medium", "high")
    assert all(item.output_ok and item.dispatched for item in probes)
    assert all(item.call.response_id == "probe-response" for item in probes)
    assert all(item.call.input_tokens == 10 for item in probes)
    assert all(item.call.output_tokens == 20 for item in probes)
    assert all(item.call.actual_cost_microusd == 440 for item in probes)


def test_provider_probe_records_allowlisted_error_and_blocks_follow_on_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-test-secret-value"
    monkeypatch.setenv(FRONTIER_API_KEY_ENV, secret)

    class FakeProviderError(RuntimeError):
        status_code = 503
        request_id = "req-probe-503"
        body: ClassVar[dict[str, object]] = {
            "error": {
                "code": "upstream_unavailable",
                "type": "provider_error",
                "param": "model",
                "message": (
                    f"request echo Authorization: Bearer {secret}; "
                    'body={"api_key":"another-private-value"}'
                ),
            }
        }

    @dataclass
    class RaisingCompletions:
        calls: int = 0

        def parse(self, **_: object) -> object:
            self.calls += 1
            raise FakeProviderError("raw exception must not be persisted")

    first_calls = RaisingCompletions()
    first = OpenAIFrontierAdapter(
        client=_Client(SimpleNamespace(completions=first_calls)),
        reasoning_effort="medium",
        input_token_cap=R4_PROBE_INPUT_TOKEN_CAP,
        max_output_tokens=R4_PROBE_OUTPUT_TOKEN_CAP,
        call_cap=1,
        usd_ceiling=0.011264,
    )
    second = _successful_probe_adapters()[1]

    probes = run_provider_probes((first, second))

    assert first_calls.calls == 1
    assert second.calls_started == 0
    assert probes[0].error is not None
    assert probes[0].error.status_code == 503
    assert probes[0].error.request_id == "req-probe-503"
    assert probes[0].error.provider_code == "upstream_unavailable"
    serialized = json.dumps(probes[0].model_dump(mode="json"))
    assert secret not in serialized
    assert "another-private-value" not in serialized
    assert "request echo" not in serialized
    assert "provider_message" not in serialized
    assert probes[1].call.status == "not_run_probe_rejected"


def test_provider_probe_missing_response_id_records_terminal_audit_evidence() -> None:
    parsed = ProviderProbeOutput(
        ok=True,
        label=R4_PROBE_LABEL_BY_EFFORT["medium"],
    )

    @dataclass
    class MissingIdCompletions:
        calls: int = 0

        def parse(self, **_: object) -> _Response:
            self.calls += 1
            return _Response(
                choices=[_Choice(_Message(parsed))],
                id=None,
            )

    first_calls = MissingIdCompletions()
    first = OpenAIFrontierAdapter(
        client=_Client(SimpleNamespace(completions=first_calls)),
        reasoning_effort="medium",
        input_token_cap=R4_PROBE_INPUT_TOKEN_CAP,
        max_output_tokens=R4_PROBE_OUTPUT_TOKEN_CAP,
        call_cap=1,
        usd_ceiling=0.011264,
    )
    second = _successful_probe_adapters()[1]

    probes = run_provider_probes((first, second))

    assert first_calls.calls == 1
    assert probes[0].dispatched is True
    assert probes[0].output_ok is False
    assert probes[0].call.status == "failed_invalid_response"
    assert probes[0].call.response_id is None
    assert probes[0].call.actual_cost_microusd == 440
    assert probes[0].error is not None
    assert probes[0].error.error_class == "MissingResponseId"
    assert second.calls_started == 0
    assert probes[1].call.status == "not_run_probe_rejected"


def test_matrix_error_history_survives_a_later_success() -> None:
    label = "matrix-history-regression"
    parsed = ProviderProbeOutput(ok=True, label=label)

    @dataclass
    class RecoveringCompletions:
        calls: int = 0

        def parse(self, **_: object) -> _Response:
            self.calls += 1
            return _Response(
                choices=[_Choice(_Message(parsed))],
                id=None if self.calls == 1 else "recovered-response",
            )

    completions = RecoveringCompletions()
    adapter = OpenAIFrontierAdapter(
        client=_Client(SimpleNamespace(completions=completions)),
        reasoning_effort="medium",
        input_token_cap=R4_PROBE_INPUT_TOKEN_CAP,
        max_output_tokens=R4_PROBE_OUTPUT_TOKEN_CAP,
        call_cap=2,
        usd_ceiling=0.022528,
    )

    with pytest.raises(FrontierResponseValidationError):
        adapter.probe(label=label)
    assert adapter.probe(label=label).ok is True

    errors = provider_errors_from_adapters(
        ("untuned_fast_frontier_slow_medium",),
        (adapter,),
    )
    assert len(errors) == 1
    assert errors[0].call_index == 1
    assert errors[0].error_class == "MissingResponseId"


def _copy_sources(tmp_path: Path) -> None:
    for relative in (
        R2_MANIFEST_PATH,
        R2_EPISODES_PATH,
        R2_CEILING_PATH,
        R2_REPORT_PATH,
        R3_REPORT_PATH,
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def test_source_check_passes_before_separate_r4_artifact_exists(
    tmp_path: Path,
) -> None:
    _copy_sources(tmp_path)

    passed, failures = check_hosted_rerun_sources(tmp_path)

    assert passed, failures
    assert not (tmp_path / R4_REPORT_PATH).exists()


def test_r4_report_binds_sources_reuses_local_conditions_and_replays(
    tmp_path: Path,
) -> None:
    _copy_sources(tmp_path)
    source_r2, source_r3 = load_source_reports(tmp_path)
    probes = run_provider_probes(_successful_probe_adapters())
    matrix = initial_matrix_from_source(source_r3, host_class="test-r4")
    r2_before = (tmp_path / R2_REPORT_PATH).read_bytes()
    r3_before = (tmp_path / R3_REPORT_PATH).read_bytes()

    report = write_report_r4(
        tmp_path,
        compose_r4_report(
            source_r2=source_r2,
            source_r3=source_r3,
            probes=probes,
            matrix_result=matrix,
        ),
    )
    passed, failures = check_hosted_rerun_artifacts(tmp_path)

    assert passed, failures
    assert report.phase_completion_ready is False
    assert report.probe_ready is True
    assert report.new_external_dispatch_count == 2
    assert report.matrix_result.conditions[:3] == source_r3.conditions[:3]
    assert (tmp_path / R2_REPORT_PATH).read_bytes() == r2_before
    assert (tmp_path / R3_REPORT_PATH).read_bytes() == r3_before


def test_r4_checker_rejects_refingerprinted_source_binding_tamper(
    tmp_path: Path,
) -> None:
    _copy_sources(tmp_path)
    source_r2, source_r3 = load_source_reports(tmp_path)
    report = compose_r4_report(
        source_r2=source_r2,
        source_r3=source_r3,
        probes=run_provider_probes(_successful_probe_adapters()),
        matrix_result=initial_matrix_from_source(source_r3, host_class="test-r4"),
    )
    tampered = report.model_copy(update={"source_r3_report_fingerprint": "f" * 64})
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(tampered)}
    )
    write_report_r4(tmp_path, tampered)

    passed, failures = check_hosted_rerun_artifacts(tmp_path)

    assert not passed
    assert "r4 source r3 fingerprint mismatch" in failures


@pytest.mark.parametrize("mutation", ("delete", "index", "duplicate"))
def test_r4_checker_rejects_refingerprinted_provider_error_tamper(
    tmp_path: Path,
    mutation: str,
) -> None:
    _copy_sources(tmp_path)
    source_r2, source_r3 = load_source_reports(tmp_path)
    matrix_scope = source_r3.conditions[3].condition.value
    evidence = ProviderErrorEvidence(
        scope=matrix_scope,
        call_index=1,
        error_class="TimeoutError",
    )
    report = write_report_r4(
        tmp_path,
        compose_r4_report(
            source_r2=source_r2,
            source_r3=source_r3,
            probes=run_provider_probes(_successful_probe_adapters()),
            matrix_result=source_r3,
            provider_errors=(evidence,),
        ),
    )
    passed, failures = check_hosted_rerun_artifacts(tmp_path)
    assert passed, failures

    if mutation == "delete":
        provider_errors: tuple[ProviderErrorEvidence, ...] = ()
    elif mutation == "index":
        provider_errors = (evidence.model_copy(update={"call_index": 2}),)
    else:
        provider_errors = (evidence, evidence)
    tampered = report.model_copy(update={"provider_errors": provider_errors})
    tampered = tampered.model_copy(
        update={"report_fingerprint": report_fingerprint_r4(tampered)}
    )
    write_report_r4(tmp_path, tampered)

    passed, failures = check_hosted_rerun_artifacts(tmp_path)

    assert not passed
    assert any("Provider error evidence" in failure for failure in failures)


def test_r4_checker_requires_the_separate_artifact(tmp_path: Path) -> None:
    _copy_sources(tmp_path)

    passed, failures = check_hosted_rerun_artifacts(tmp_path)

    assert not passed
    assert failures == (f"missing r4 artifact: {R4_REPORT_PATH}",)
