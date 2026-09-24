"""The runtime HTTP Fast adapter against the in-test fake gateway (PR-9a).

Every case drives the real ``LocalFastHttpAdapter`` through ``ThinAgentRuntime``
and the direct API, then checks the delivered line, the Fast trace, and that
the command applied (AC1, AC2, A1-A14). CI never runs a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from local_fast_fake_gateway import (
    GATE_PASSING_TEXT,
    FakeGateway,
    fixture_bytes,
    model_output,
)
from proxyloop_agent_core import (
    FAST_ADAPTER_FAILURE_CODES,
    FAST_ADAPTER_FAILURE_DETAIL_CODES,
    CaseCoordinator,
    FastAdapterFailure,
    FastAdapterResult,
    IdentifiedAdapter,
    LabelledFastBackend,
    ObservingFastAdapter,
    SafeObservation,
    ScriptedDialogueFastAdapter,
    fast_public_observation,
)
from proxyloop_agent_core.local_fast_wire import (
    DecideResponse,
    WireError,
    canonical_sha256,
    decode_decide_request,
    decode_decide_response,
    decode_identity,
    encode_decide_request,
    encode_decide_response,
    encode_json,
)
from proxyloop_api import create_app
from proxyloop_case_runtime import (
    FAST_FALLBACK_TEXT,
    SCRIPTED_CASE_ID,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime.turn_split import fast_slow_split
from proxyloop_contracts import FastModelView, ModelResult, ModelTrace
from proxyloop_local_fast import LocalFastHttpAdapter, LocalFastStartupError
from proxyloop_openai_adapter import FastModelOutput
from test_fast_dialogue_delivery import CREATE_CASE_REQUEST, SteppingClock

LEAKY_TEXT = "I accept the deal at $61.00 for you."


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    with FakeGateway(backend="distilled") as running:
        yield running


def _adapter(gateway: FakeGateway, timeout_s: float = 5.0) -> LocalFastHttpAdapter:
    return LocalFastHttpAdapter.connect(
        base_url=gateway.url, backend="distilled", timeout_s=timeout_s
    )


def _turn(
    runtime: ThinAgentRuntime, *, stop: FakeGateway | None = None
) -> tuple[int, dict[str, Any], dict[str, Any], str]:
    """Create the Case, post one Consumer message, read the Case back."""

    async def scenario() -> tuple[int, dict[str, Any], dict[str, Any], str]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://testserver",
        ) as client:
            created = await client.post("/cases", json=CREATE_CASE_REQUEST)
            assert created.status_code == 201
            if stop is not None:
                stop.__exit__(None, None, None)
            turn = await client.post(
                f"/cases/{SCRIPTED_CASE_ID}/events",
                json={
                    "content": "Please review the current offer.",
                    "expected_revision": created.json()["revision"],
                },
            )
            live = await client.get("/health/live")
            return turn.status_code, turn.json(), live.json(), turn.text

    return asyncio.run(scenario())


def _fast_trace(repository: InMemoryCaseRepository) -> ModelTrace:
    (trace,) = [
        item
        for item in repository.list_model_traces(SCRIPTED_CASE_ID)
        if item.role == "fast"
    ]
    return trace


def test_the_adapter_implements_the_optional_protocols(gateway: FakeGateway) -> None:
    adapter = _adapter(gateway)
    assert isinstance(adapter, ObservingFastAdapter)
    assert isinstance(adapter, IdentifiedAdapter)
    assert isinstance(adapter, LabelledFastBackend)
    assert adapter.fast_backend_label == "local_distilled_candidate"


def test_a_gate_passing_model_line_is_delivered(gateway: FakeGateway) -> None:
    # AC1, A1: the local identity is on the trace; adapter_mode is the label.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_adapter(gateway)
    )

    status, body, live, _ = _turn(runtime)

    assert status == 200
    line = body["snapshot"]["visible_events"][-1]
    assert (line["actor"], line["event_type"], line["content"]) == (
        "system",
        "assistant_message",
        GATE_PASSING_TEXT,
    )
    assert body["fast"]["response_text"] == GATE_PASSING_TEXT
    assert body["approval"]["decision"] == "pending"
    assert live["adapter_mode"] == "local_distilled_candidate"
    trace = _fast_trace(repository)
    assert trace.result is ModelResult.SUCCEEDED
    assert (
        trace.provider,
        trace.model,
        trace.model_version,
        trace.adapter_version,
        trace.prompt_version,
    ) == (
        "local_mlx_gateway",
        "Qwen/Qwen3-8B-MLX-bf16",
        f"distilled:{gateway.fingerprint[:16]}",
        "local-fast-http-v1",
        "phase-03c-v6+fast-observation-v1",
    )
    assert (trace.input_tokens, trace.output_tokens) == (1_830, 41)
    # A16 end to end: the gateway got the observation of the traced snapshot.
    ((view, observation),) = gateway.requests
    assert trace.input_pins == view.pins
    assert observation.case_id == str(view.case_id)
    assert observation.case_revision == view.pins.case_revision
    assert gateway.raw_requests == [encode_decide_request(view, observation)]


def test_gate_violating_model_text_is_withheld(
    gateway: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    # A1 with the PR-8 gate: a REJECTED trace, not FAILED; no text anywhere.
    caplog.set_level(logging.DEBUG)
    gateway.output = model_output(response_text=LEAKY_TEXT)
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_adapter(gateway)
    )

    status, body, _, raw = _turn(runtime)

    assert status == 200
    assert "fast" not in body
    assert body["snapshot"]["visible_events"][-1]["content"] == FAST_FALLBACK_TEXT
    trace = _fast_trace(repository)
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes is not None
    assert all(code.startswith("fast_gate_") for code in trace.reason_codes)
    for surface in (raw, repr(repository.get(SCRIPTED_CASE_ID)), caplog.text):
        assert "$61" not in surface
        assert "accept the deal" not in surface


@pytest.mark.parametrize(
    ("behaviour", "output", "codes"),
    [
        ("slow", None, ("fast_adapter_timeout",)),
        ("drop", None, ("fast_adapter_unavailable",)),
        ("busy", None, ("fast_adapter_busy",)),
        (
            "server_error",
            None,
            ("fast_adapter_protocol_error", "http_status_unexpected"),
        ),
        ("malformed", None, ("fast_adapter_protocol_error", "body_not_json")),
        ("oversize", None, ("fast_adapter_protocol_error", "response_too_large")),
        (
            "wrong_wire_version",
            None,
            ("fast_adapter_protocol_error", "wire_version_mismatch"),
        ),
        ("invalid_output", None, ("fast_adapter_invalid_output", "invalid_json")),
        ("unrenderable", None, ("fast_input_unrenderable", "prompt_render_refused")),
        ("identity_flip", None, ("fast_adapter_identity_mismatch",)),
        # Review I1: this escaped as a 500 with no Fast trace.
        (
            "detail_not_text",
            None,
            ("fast_adapter_protocol_error", "body_shape_invalid"),
        ),
        # Review M1: a trickle is bounded by the whole-call deadline.
        ("trickle_head", None, ("fast_adapter_timeout",)),
        ("trickle_body", None, ("fast_adapter_timeout",)),
        (
            "success",
            model_output(
                fact_updates=[
                    {
                        "key": "monthly_total",
                        "value": "61",
                        "source_message_id": "not-a-visible-message",
                        "confidence": 0.5,
                        "status": "candidate",
                    }
                ]
            ),
            ("fast_adapter_invalid_output", "fact_updates_not_empty"),
        ),
        (
            "success",
            model_output(dialogue_act="haggle"),
            ("fast_adapter_invalid_output", "output_schema_invalid"),
        ),
    ],
)
def test_each_gateway_failure_delivers_the_fallback_and_applies(
    gateway: FakeGateway,
    behaviour: str,
    output: dict[str, Any] | None,
    codes: tuple[str, ...],
) -> None:
    # AC2, A2-A11: 200, fallback, command applied, FAILED trace, no echo.
    gateway.behaviour = behaviour
    gateway.delay_s = 1.0
    if output is not None:
        gateway.output = output
    repository = InMemoryCaseRepository()
    timed = behaviour == "slow" or behaviour.startswith("trickle")
    timeout_s = 0.3 if timed else 5.0
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_adapter(gateway, timeout_s)
    )

    status, body, _, _ = _turn(runtime)

    if timed:
        # The whole call, not each read, is bounded (the trickle takes 4 s).
        assert _fast_trace(repository).latency_ms < 1_500
    assert status == 200
    assert "fast" not in body
    assert body["route"] == "wait_for_approval"
    assert body["approval"]["decision"] == "pending"
    line = body["snapshot"]["visible_events"][-1]
    assert (line["actor"], line["content"]) == ("system", FAST_FALLBACK_TEXT)
    trace = _fast_trace(repository)
    assert trace.result is ModelResult.FAILED
    assert trace.reason_codes == codes
    assert trace.output_ref is None
    assert trace.provider == "local_mlx_gateway"
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    assert state.last_fast_decision is None
    # PR-8a's split record names the failure (spec §5.2 amendment).
    split = fast_slow_split(repository.list_model_traces(SCRIPTED_CASE_ID), state)
    dialogue = [turn for turn in split["turns"] if turn["fast_calls"]]  # type: ignore[index]
    assert [
        (turn["fast_result"], turn["fallback_cause"], turn["delivered"])
        for turn in dialogue
    ] == [("failed", "failure", "fallback")]


def test_a_gateway_that_went_away_is_unavailable(gateway: FakeGateway) -> None:
    # A3: refused connection after a successful start.
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(
        repository, clock=SteppingClock(), fast=_adapter(gateway)
    )
    status, body, _, _ = _turn(runtime, stop=gateway)

    assert status == 200
    assert body["snapshot"]["visible_events"][-1]["content"] == FAST_FALLBACK_TEXT
    trace = _fast_trace(repository)
    assert (trace.result, trace.reason_codes) == (
        ModelResult.FAILED,
        ("fast_adapter_unavailable",),
    )


def test_plain_decide_is_refused_without_an_observation(gateway: FakeGateway) -> None:
    adapter = _adapter(gateway)
    repository = InMemoryCaseRepository()
    ThinAgentRuntime(repository).create_case()
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    with pytest.raises(FastAdapterFailure) as raised:
        adapter.decide(CaseCoordinator.project_fast_view(state.snapshot))
    assert raised.value.reason_codes == (
        "fast_input_unrenderable",
        "observation_required",
    )
    assert gateway.requests == []


def test_the_scripted_readiness_payload_keys_are_unchanged(
    gateway: FakeGateway,
) -> None:
    # A14: only the value of ``adapter_mode`` differs on an opt-in run.
    _, _, local, _ = _turn(
        ThinAgentRuntime(clock=SteppingClock(), fast=_adapter(gateway))
    )
    _, _, scripted, _ = _turn(ThinAgentRuntime(clock=SteppingClock()))
    assert set(local) == set(scripted)
    assert scripted["adapter_mode"] == "scripted"
    assert {key: value for key, value in local.items() if key != "adapter_mode"} == {
        key: value for key, value in scripted.items() if key != "adapter_mode"
    }


def test_every_code_the_client_can_raise_is_allow_listed() -> None:
    # The FAILED trace can only carry allow-listed, content-free codes.
    assert "fast_adapter_timeout" in FAST_ADAPTER_FAILURE_CODES
    assert len(FAST_ADAPTER_FAILURE_CODES) == 7
    assert not FAST_ADAPTER_FAILURE_CODES & FAST_ADAPTER_FAILURE_DETAIL_CODES


# ---------------------------------------------------------------------------
# A19, A20: the golden wire fixtures decode on the runtime side.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_the_identity_goldens_decode(backend: str) -> None:
    body = fixture_bytes(f"identity-{backend}.json")
    identity = decode_identity(body)
    assert identity.backend == backend
    assert encode_json(json.loads(body)) == body
    assert (identity.adapter_fingerprint is None) == (backend == "untuned")


@pytest.mark.parametrize(
    ("name", "status", "output", "detail"),
    [
        ("succeeded", "succeeded", model_output(), None),
        ("invalid-output", "invalid_output", None, "invalid_json"),
        ("unrenderable", "unrenderable", None, "prompt_render_refused"),
    ],
)
def test_the_decide_response_goldens_decode(
    name: str, status: Any, output: dict[str, Any] | None, detail: str | None
) -> None:
    body = fixture_bytes(f"decide-response-{name}.json")
    expected = DecideResponse(
        identity_fingerprint=decode_identity(
            fixture_bytes("identity-distilled.json")
        ).identity_fingerprint,
        status=status,
        output=output,
        detail_code=detail,
        input_tokens=1_830,
        output_tokens=41,
        generation_ms=2_345,
    )
    assert decode_decide_response(body) == expected
    assert encode_decide_response(expected) == body


def test_the_decide_request_golden_round_trips() -> None:
    body = fixture_bytes("decide-request.json")
    view, observation = decode_decide_request(body)
    assert encode_decide_request(view, observation) == body
    assert observation.case_id == str(view.case_id)


def test_the_runtime_request_is_the_golden_shape() -> None:
    # The product path builds a request the gateway side decodes.
    repository = InMemoryCaseRepository()
    ThinAgentRuntime(repository).create_case()
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    view = CaseCoordinator.project_fast_view(state.snapshot)
    observation = fast_public_observation(state.snapshot)
    assert isinstance(observation, SafeObservation)
    body = encode_decide_request(view, observation)
    assert set(json.loads(body)) == set(
        json.loads(fixture_bytes("decide-request.json"))
    )
    assert decode_decide_request(body) == (view, observation)


def test_the_fast_output_schema_matches_the_golden() -> None:
    # A20: the ml side pins its frozen copy against the same file.
    golden = json.loads(fixture_bytes("fast-model-output.schema.json"))
    assert FastModelOutput.model_json_schema() == golden


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"\xff", "body_not_json"),
        (b'{"a": NaN}', "body_not_json"),
        (b'{"a": 1, "a": 2}', "body_duplicate_key"),
        (b"[]", "body_shape_invalid"),
        (b"[" * 100_000, "body_not_json"),
        # Review I1: past the 4300-digit int conversion limit.
        (
            fixture_bytes("decide-response-invalid-output.json").replace(
                b'"input_tokens":1830', b'"input_tokens":' + b"9" * 5_000
            ),
            "body_not_json",
        ),
        (
            fixture_bytes("decide-response-succeeded.json").replace(
                b'"response_text":"', b'"response_text":' + b"1" * 5_000 + b',"x":"'
            ),
            "body_not_json",
        ),
    ],
    ids=[
        "not-utf8",
        "nan",
        "duplicate-key",
        "array",
        "deep-nesting",
        "huge-int-usage",
        "huge-int-output",
    ],
)
def test_malformed_bodies_are_wire_errors(body: bytes, code: str) -> None:
    with pytest.raises(WireError) as raised:
        decode_decide_response(body)
    assert raised.value.code == code


@pytest.mark.parametrize(
    ("golden", "change", "code"),
    [
        ("succeeded", {"extra": 1}, "body_shape_invalid"),
        ("succeeded", {"detail_code": "free text"}, "body_shape_invalid"),
        ("succeeded", {"status": "maybe"}, "body_shape_invalid"),
        (
            "succeeded",
            {"usage": {"input_tokens": True, "output_tokens": 0, "generation_ms": 0}},
            "body_shape_invalid",
        ),
        ("succeeded", {"identity_fingerprint": "abc"}, "body_shape_invalid"),
        # Review I1: unhashable values where an allow-listed code belongs.
        ("succeeded", {"status": []}, "body_shape_invalid"),
        ("succeeded", {"status": {}}, "body_shape_invalid"),
        ("invalid-output", {"status": []}, "body_shape_invalid"),
        ("invalid-output", {"detail_code": ["x"]}, "body_shape_invalid"),
        ("unrenderable", {"detail_code": {}}, "body_shape_invalid"),
    ],
)
def test_a_decide_response_is_strict(
    golden: str, change: dict[str, Any], code: str
) -> None:
    document = json.loads(fixture_bytes(f"decide-response-{golden}.json"))
    document.update(change)
    with pytest.raises(WireError) as raised:
        decode_decide_response(encode_json(document))
    assert raised.value.code == code


def test_an_unknown_failure_detail_is_refused() -> None:
    document = json.loads(fixture_bytes("decide-response-invalid-output.json"))
    document["detail_code"] = "the model said something private"
    with pytest.raises(WireError) as raised:
        decode_decide_response(encode_json(document))
    assert raised.value.code == "detail_code_unknown"


@pytest.mark.parametrize(
    "change",
    [
        {"label": "production"},
        {"backend": "promoted"},
        {"adapter_fingerprint": None},
        {"base_model": "another/model"},
    ],
)
def test_an_identity_is_bound_by_its_fingerprint(change: dict[str, Any]) -> None:
    # L3, L10: any change to a served field breaks the recomputed fingerprint
    # or the label/backend rules.
    document = json.loads(fixture_bytes("identity-distilled.json"))
    document.update(change)
    with pytest.raises(WireError):
        decode_identity(encode_json(document))


def _identity_body(**change: Any) -> bytes:
    """The distilled golden identity with ``change`` and a matching fingerprint."""

    document = json.loads(fixture_bytes("identity-distilled.json"))
    document.update(change)
    document.pop("identity_fingerprint")
    fingerprint = canonical_sha256(document)
    return encode_json({**document, "identity_fingerprint": fingerprint})


@pytest.mark.parametrize(
    "change",
    [
        {"backend": []},
        {"label": {}},
        {"base_model": "Qwen/Qwen3\n8B"},
        {"prompt_version": "v6\u0000"},
        {"compiler_version": "x" * 200},
        {"adapter_fingerprint": "fake generator"},
        {"mlx_versions": {"mlx": "0.29 beta"}},
    ],
)
def test_identity_fields_are_tokens(change: dict[str, Any]) -> None:
    # Review I1 (unhashable backend) and M2 (tokens: no control characters or
    # spaces, at most 128 characters), with a correctly recomputed fingerprint.
    with pytest.raises(WireError) as raised:
        decode_identity(_identity_body(**change))
    assert raised.value.code == "body_shape_invalid"


@pytest.mark.parametrize(
    "change",
    [{"prompt_version": "v7"}, {"base_model": "Qwen/Qwen3-4B-Instruct-2507"}],
)
def test_connect_pins_the_served_prompt_and_base_model(
    gateway: FakeGateway, change: dict[str, Any]
) -> None:
    # Review M2: a well-formed identity for another prompt or model is refused.
    gateway.identity_body = _identity_body(**change)
    with pytest.raises(LocalFastStartupError, match="serves"):
        _adapter(gateway)


class _Mislabelled:
    fast_backend_label = "local_promoted_production"

    def decide(self, view: FastModelView) -> FastAdapterResult:
        return ScriptedDialogueFastAdapter().decide(view)


def test_an_unknown_backend_label_is_refused() -> None:
    # Review M3: no silent fallback to ``model``.
    with pytest.raises(ValueError, match="Fast backend label"):
        ThinAgentRuntime(fast=_Mislabelled())
