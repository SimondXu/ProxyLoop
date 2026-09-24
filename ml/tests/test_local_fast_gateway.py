"""Local Fast gateway: the silent-load guard (G3), the trained view and core
(G1), and the HTTP layer (G4).  No MLX is imported; the model is a fake."""

from __future__ import annotations

import http.client
import json
import logging
import socket
import struct
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from proxyloop_agent_core import CaseCoordinator
from proxyloop_contracts import CaseContextSnapshot, FastModelView
from proxyloop_evaluation.local_fast import gateway_core
from proxyloop_evaluation.local_fast.gateway_core import (
    INVALID_OUTPUT_DETAIL_CODES,
    GatewayModelError,
    LocalFastGatewayCore,
    LoraLoadError,
    check_loaded_lora_weights,
    check_lora_layers,
    collect_lora_layers,
)
from proxyloop_evaluation.local_fast.http_server import make_server
from proxyloop_evaluation.local_fast.identity import MAX_TOKENS
from proxyloop_evaluation.local_fast.mlx_adapter_conversion import (
    ConversionAttestation,
    convert_peft_lora_to_mlx,
    read_safetensors_header,
    verify_mlx_adapter,
)
from proxyloop_evaluation.local_fast.trained_view import (
    ObservationMismatchError,
    trained_view,
)
from proxyloop_evaluation.phase03c_experiment import Phase03CQwenAdapter
from proxyloop_evaluation.phase03c_prompt_set import (
    build_parameterised_snapshot,
    render_prompt,
    render_prompt_view,
)
from proxyloop_evaluation.phase03c_scenarios import FastPosition, harvest_positions
from proxyloop_evaluation.qwen_spec import QWEN3_8B_BF16_SPEC
from proxyloop_provider_simulator.scenarios import (
    SCENARIO_FAMILIES,
    BenchmarkScenario,
    build_parameterised_scenarios,
)
from test_mlx_adapter_conversion import _peft_dir

from scripts.build_phase03c_cloud_bundle import heldout_families, render_eval_row

Tensor = tuple[tuple[int, ...], bytes]


class _FakeLoRA:
    """``mlx_lm``'s LoRALinear as the guard sees it: ``lora_a`` starts random
    (non-zero), ``lora_b`` at zero.  Values are ``(shape, F32 bytes)``."""

    def __init__(self) -> None:
        self.lora_a: Tensor = ((1,), struct.pack("<f", 0.5))
        self.lora_b: Tensor = ((1,), struct.pack("<f", 0.0))


class _FakeModel:
    def __init__(self, modules: dict[str, object]) -> None:
        self._modules = modules

    def named_modules(self) -> list[tuple[str, object]]:
        return [("", self), *self._modules.items()]


def _fake_mlx_load(adapter_dir: Path, attestation: ConversionAttestation) -> _FakeModel:
    """``linear_to_lora_layers`` + ``load_weights(strict=False)``, faked.

    LoRA modules are created from the config; a weight whose name matches no
    module is silently ignored, exactly the hazard the guard exists for.
    """

    modules: dict[str, object] = {
        name: _FakeLoRA() for name in attestation.expected_lora_modules()
    }
    modules["model.embed_tokens"] = object()
    weights = adapter_dir / "adapters.safetensors"
    table, data_start = read_safetensors_header(weights)
    raw = weights.read_bytes()
    for key, entry in table.items():
        owner, _, param = key.rpartition(".")
        module = modules.get(owner)
        if isinstance(module, _FakeLoRA) and param in ("lora_a", "lora_b"):
            data = raw[data_start + entry.start : data_start + entry.end]
            setattr(module, param, (entry.shape, data))
    return _FakeModel(modules)


def _nonzero(value: object) -> bool:
    assert isinstance(value, tuple)
    return any(value[1])


def _tensor_bytes(value: object) -> tuple[str, tuple[int, ...], bytes]:
    assert isinstance(value, tuple)
    return "F32", value[0], value[1]


def _converted(tmp_path: Path) -> tuple[Path, ConversionAttestation]:
    source, sha = _peft_dir(tmp_path)
    out = tmp_path / "mlx"
    return out, convert_peft_lora_to_mlx(source, out, expected_source_sha256=sha)


def _rename_tensors(path: Path, old: str, new: str) -> None:
    raw = path.read_bytes()
    (size,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + size])
    renamed = {key.replace(old, new): value for key, value in header.items()}
    encoded = json.dumps(renamed).encode()
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + raw[8 + size :])


def test_guard_accepts_a_fully_loaded_adapter(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    layers = collect_lora_layers(_fake_mlx_load(out, attestation), nonzero=_nonzero)
    assert len(layers) == attestation.lora_layers == 14
    check_lora_layers(layers, expected=attestation.expected_lora_modules())


def test_guard_refuses_an_adapter_with_renamed_layers(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    _rename_tensors(out / "adapters.safetensors", "model.layers.", "model.layer.")
    layers = collect_lora_layers(_fake_mlx_load(out, attestation), nonzero=_nonzero)
    with pytest.raises(LoraLoadError, match="all-zero lora_b"):
        check_lora_layers(layers, expected=attestation.expected_lora_modules())


def test_guard_refuses_one_unloaded_layer(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    _rename_tensors(
        out / "adapters.safetensors",
        "model.layers.1.mlp.up_proj.lora_b",
        "model.layers.1.mlp.up_proj.lora_B",
    )
    layers = collect_lora_layers(_fake_mlx_load(out, attestation), nonzero=_nonzero)
    with pytest.raises(LoraLoadError, match="1 of 14"):
        check_lora_layers(layers, expected=attestation.expected_lora_modules())


def test_guard_refuses_a_wrong_layer_count(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    model = _fake_mlx_load(out, attestation)
    layers = collect_lora_layers(model, nonzero=_nonzero)
    layers.pop(sorted(layers)[0])
    with pytest.raises(LoraLoadError, match="expected 14 LoRA layers, found 13"):
        check_lora_layers(layers, expected=attestation.expected_lora_modules())


def test_guard_refuses_lora_layers_on_the_untuned_backend(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    layers = collect_lora_layers(_fake_mlx_load(out, attestation), nonzero=_nonzero)
    with pytest.raises(LoraLoadError, match="expected 0 LoRA layers"):
        check_lora_layers(layers, expected=frozenset())
    check_lora_layers({}, expected=frozenset())


def test_weight_check_accepts_the_attested_tensors(tmp_path: Path) -> None:
    out, attestation = _converted(tmp_path)
    model = _fake_mlx_load(out, attestation)
    check_loaded_lora_weights(model, attestation, tensor_bytes=_tensor_bytes)


def test_weight_check_refuses_a_partial_load_the_layer_guard_misses(
    tmp_path: Path,
) -> None:
    """Only one ``lora_a`` misses its module: ``lora_b`` loaded, so every layer
    is non-zero and the layer guard passes, but the weights are not the
    attested ones (that ``lora_a`` kept its random init)."""

    out, attestation = _converted(tmp_path)
    _rename_tensors(
        out / "adapters.safetensors",
        "model.layers.1.mlp.up_proj.lora_a",
        "model.layers.1.mlp.up_proj.lora_A",
    )
    model = _fake_mlx_load(out, attestation)
    check_lora_layers(
        collect_lora_layers(model, nonzero=_nonzero),
        expected=attestation.expected_lora_modules(),
    )
    with pytest.raises(LoraLoadError, match="differ from the attested"):
        check_loaded_lora_weights(model, attestation, tensor_bytes=_tensor_bytes)


def test_weight_check_refuses_a_file_changed_after_verification(
    tmp_path: Path,
) -> None:
    """TOCTOU: the file passed ``verify_mlx_adapter``, then changed before the
    model read it; the committed hash is checked against memory, not the file."""

    out, attestation = _converted(tmp_path)
    verify_mlx_adapter(out, attestation)
    weights = out / "adapters.safetensors"
    data = bytearray(weights.read_bytes())
    data[-1] ^= 0x01
    weights.write_bytes(bytes(data))
    model = _fake_mlx_load(out, attestation)
    with pytest.raises(LoraLoadError, match="differ from the attested"):
        check_loaded_lora_weights(model, attestation, tensor_bytes=_tensor_bytes)


# --- G1: trained view and core ------------------------------------------------


def _heldout_positions() -> list[tuple[BenchmarkScenario, FastPosition]]:
    split_by_family = dict(heldout_families())
    families = tuple(f for f in SCENARIO_FAMILIES if f.family_id in split_by_family)
    scenario = build_parameterised_scenarios(seeds=(950,), families=families[:1])[0]
    return [(scenario, position) for position in harvest_positions(scenario)]


def _product_view(scenario: BenchmarkScenario, position: FastPosition) -> FastModelView:
    """The product shape: the latest Provider event is prose, not the marker."""

    snapshot = build_parameterised_snapshot(scenario, position)
    events = list(snapshot.visible_events)
    events[-1] = events[-1].model_copy(
        update={"content": position.provider_turn.message}
    )
    data = snapshot.model_dump(mode="python")
    data["visible_events"] = tuple(event.model_dump(mode="python") for event in events)
    return CaseCoordinator.project_fast_view(CaseContextSnapshot.model_validate(data))


def _oracle_json(scenario: BenchmarkScenario, position: FastPosition) -> str:
    row = render_eval_row(scenario, position, split="development", prompt_version="v6")
    return json.dumps(row["oracle_target"])


@pytest.mark.parametrize("index", [0, 1])
def test_product_path_prompt_is_byte_equal_to_the_trained_prompt(index: int) -> None:
    scenario, position = _heldout_positions()[index]
    product = _product_view(scenario, position)
    with pytest.raises(ValueError, match="public observation marker"):
        render_prompt(product)

    served = render_prompt(trained_view(product, position.observation))
    trained = render_prompt(render_prompt_view(scenario, position))
    assert (served.system, served.user) == (trained.system, trained.user)
    assert served.fingerprint == trained.fingerprint


def test_core_returns_the_semantic_fields_for_a_valid_output() -> None:
    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    prompts: list[str] = []

    def generator(prompt: str) -> str:
        prompts.append(prompt)
        return oracle

    core = LocalFastGatewayCore.with_generator(generator)
    result = core.decide(_product_view(scenario, position), position.observation)

    assert result.status == "succeeded" and result.detail_code is None
    assert result.output == json.loads(oracle)
    trained = render_prompt(render_prompt_view(scenario, position))
    assert result.prompt_fingerprint == trained.fingerprint
    assert prompts == [trained.rendered]


@pytest.mark.parametrize(
    ("raw", "detail"),
    [
        ("not json", "invalid_json"),
        ("<think>hm</think>{}", "thinking_leak"),
        ('{"dialogue_act": "counter"}', "fast_action_intent_forbidden"),
    ],
)
def test_core_reports_invalid_output_with_an_allow_listed_code(
    raw: str, detail: str
) -> None:
    scenario, position = _heldout_positions()[0]
    core = LocalFastGatewayCore.with_generator(lambda _: raw)
    result = core.decide(_product_view(scenario, position), position.observation)
    assert (result.status, result.detail_code, result.output) == (
        "invalid_output",
        detail,
        None,
    )
    assert detail in INVALID_OUTPUT_DETAIL_CODES


def test_core_refuses_a_mismatched_observation_and_a_missing_event() -> None:
    scenario, position = _heldout_positions()[0]
    view = _product_view(scenario, position)
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    stale = replace(position.observation, case_revision=view.pins.case_revision + 1)
    with pytest.raises(ObservationMismatchError):
        core.decide(view, stale)

    no_event = view.model_copy(update={"latest_provider_event": None})
    result = core.decide(no_event, position.observation)
    assert (result.status, result.detail_code) == ("unrenderable", "no_provider_event")


def test_core_raises_on_a_model_runtime_failure() -> None:
    scenario, position = _heldout_positions()[0]

    def broken(_: str) -> str:
        raise RuntimeError("metal went away")

    core = LocalFastGatewayCore.with_generator(broken)
    with pytest.raises(GatewayModelError, match="generation_error"):
        core.decide(_product_view(scenario, position), position.observation)


def test_identity_binds_backend_label_and_decoding() -> None:
    distilled = LocalFastGatewayCore.with_generator(lambda _: "{}").identity
    untuned = LocalFastGatewayCore.with_generator(
        lambda _: "{}", backend="untuned"
    ).identity
    assert distilled.to_dict()["label"] == "local opt-in candidate"
    assert untuned.to_dict()["label"] == "untuned local baseline"
    assert untuned.adapter_fingerprint is None
    assert distilled.identity_fingerprint != untuned.identity_fingerprint
    payload = distilled.to_dict()
    assert payload["prompt_version"] == "v6"
    assert payload["base_revision"] == "6766fd4b8101fa4201cc55c5a2e464f3d301f792"
    assert payload["wire_version"] == "local-fast-wire-v1"


# --- G4: HTTP layer -----------------------------------------------------------


@contextmanager
def _running(core: LocalFastGatewayCore) -> Iterator[int]:
    server = make_server(core, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _call(
    port: int, method: str, path: str, body: bytes | None = None
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _request_body(
    view: FastModelView, observation: object, **overrides: object
) -> bytes:
    assert hasattr(observation, "to_dict")
    document = {
        "wire_version": "local-fast-wire-v1",
        "view": view.model_dump(mode="json"),
        "observation": observation.to_dict(),
        **overrides,
    }
    return json.dumps(document).encode()


def test_http_decide_round_trip_and_identity() -> None:
    scenario, position = _heldout_positions()[1]
    oracle = _oracle_json(scenario, position)
    prompts: list[str] = []

    def generator(prompt: str) -> str:
        prompts.append(prompt)
        return oracle

    core = LocalFastGatewayCore.with_generator(generator)
    body = _request_body(_product_view(scenario, position), position.observation)
    with _running(core) as port:
        status, identity = _call(port, "GET", "/v1/identity")
        assert status == 200 and identity == core.identity.to_dict()
        status, response = _call(port, "POST", "/v1/fast/decide", body)

    assert status == 200
    assert response == {
        "wire_version": "local-fast-wire-v1",
        "identity_fingerprint": core.identity.identity_fingerprint,
        "status": "succeeded",
        "output": json.loads(oracle),
        "detail_code": None,
        "usage": {"input_tokens": 0, "output_tokens": 0, "generation_ms": 0},
    }
    # the JSON wire is lossless for the prompt: byte-identical to the trained one
    assert prompts == [render_prompt(render_prompt_view(scenario, position)).rendered]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda body: b"not json", 400),
        (lambda body: body.replace(b"local-fast-wire-v1", b"local-fast-wire-v0"), 400),
        (lambda body: body[:-1] + b',"extra":1}', 400),
        (lambda body: body[:-1] + b',"view":{}}', 400),
        (lambda body: b"[" * 100_000 + b"]" * 100_000, 400),
    ],
)
def test_http_refuses_invalid_requests(
    mutate: Callable[[bytes], bytes], expected: int
) -> None:
    scenario, position = _heldout_positions()[0]
    calls: list[str] = []

    def generator(prompt: str) -> str:
        calls.append(prompt)
        return "{}"

    core = LocalFastGatewayCore.with_generator(generator)
    body = mutate(
        _request_body(_product_view(scenario, position), position.observation)
    )
    with _running(core) as port:
        status, response = _call(port, "POST", "/v1/fast/decide", body)
    assert status == expected
    assert set(response) == {"wire_version", "error"}
    assert calls == []


def _raw(port: int, head: str, body: bytes = b"") -> bytes:
    with socket.create_connection(("127.0.0.1", port)) as sock:
        sock.sendall(head.format(port=port).encode() + b"\r\n\r\n" + body)
        return sock.makefile("rb").read()


def _error_body(code: str) -> bytes:
    return f'{{"error":"{code}","wire_version":"local-fast-wire-v1"}}'.encode()


def test_http_refuses_an_oversized_body_without_reading_it() -> None:
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    with _running(core) as port:
        reply = _raw(
            port,
            "POST /v1/fast/decide HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\nContent-Length: 262145",
        )
    assert reply.startswith(b"HTTP/1.0 413 ")
    assert reply.endswith(_error_body("request_too_large"))


@pytest.mark.parametrize(
    "host",
    [None, "127.0.0.1", "localhost:{port}", "attacker.example:{port}", "127.0.0.1:1"],
)
def test_http_refuses_a_host_other_than_the_bound_loopback(host: str | None) -> None:
    """DNS rebinding: a browser page on another name reaches 127.0.0.1 with
    its own Host header; only the exact bound host:port is served."""

    scenario, position = _heldout_positions()[0]
    calls: list[str] = []

    def generator(prompt: str) -> str:
        calls.append(prompt)
        return "{}"

    core = LocalFastGatewayCore.with_generator(generator)
    body = _request_body(_product_view(scenario, position), position.observation)
    host_line = "" if host is None else f"\r\nHost: {host}"
    with _running(core) as port:
        post = _raw(
            port,
            f"POST /v1/fast/decide HTTP/1.1{host_line}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}",
            body,
        )
        get = _raw(port, f"GET /v1/identity HTTP/1.1{host_line}")
    for reply in (post, get):
        assert reply.startswith(b"HTTP/1.0 400 ")
        assert reply.endswith(_error_body("host_not_allowed"))
    assert calls == []


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/x-www-form-urlencoded"]
)
def test_http_refuses_a_simple_cross_origin_post(content_type: str | None) -> None:
    scenario, position = _heldout_positions()[0]
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    body = _request_body(_product_view(scenario, position), position.observation)
    type_line = "" if content_type is None else f"\r\nContent-Type: {content_type}"
    with _running(core) as port:
        reply = _raw(
            port,
            "POST /v1/fast/decide HTTP/1.1\r\nHost: 127.0.0.1:{port}"
            f"{type_line}\r\nContent-Length: {len(body)}",
            body,
        )
    assert reply.startswith(b"HTTP/1.0 415 ")
    assert reply.endswith(_error_body("unsupported_media_type"))


def test_http_accepts_a_json_content_type_with_parameters() -> None:
    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    core = LocalFastGatewayCore.with_generator(lambda _: oracle)
    body = _request_body(_product_view(scenario, position), position.observation)
    with _running(core) as port:
        reply = _raw(
            port,
            "POST /v1/fast/decide HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}",
            body,
        )
    assert reply.startswith(b"HTTP/1.0 200 ")


def test_http_times_out_a_body_that_never_arrives() -> None:
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    server = make_server(core, host="127.0.0.1", port=0, socket_timeout=0.5)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with socket.create_connection(("127.0.0.1", port)) as sock:
            sock.settimeout(10)
            sock.sendall(
                f"POST /v1/fast/decide HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
                "{".encode()
            )
            reply = sock.makefile("rb").read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert reply.startswith(b"HTTP/1.0 408 ")
    assert reply.endswith(_error_body("request_timeout"))


def test_http_refuses_an_observation_for_another_revision() -> None:
    scenario, position = _heldout_positions()[0]
    view = _product_view(scenario, position)
    stale = replace(position.observation, case_revision=view.pins.case_revision + 1)
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    with _running(core) as port:
        status, response = _call(
            port, "POST", "/v1/fast/decide", _request_body(view, stale)
        )
    assert (status, response["error"]) == (400, "request_invalid")


def test_http_is_single_flight_and_identity_answers_while_busy() -> None:
    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    entered, release = threading.Event(), threading.Event()

    def slow(_: str) -> str:
        entered.set()
        assert release.wait(timeout=10)
        return oracle

    core = LocalFastGatewayCore.with_generator(slow)
    body = _request_body(_product_view(scenario, position), position.observation)
    with _running(core) as port:
        first: list[tuple[int, dict[str, object]]] = []
        worker = threading.Thread(
            target=lambda: first.append(_call(port, "POST", "/v1/fast/decide", body))
        )
        worker.start()
        assert entered.wait(timeout=10)
        assert _call(port, "GET", "/v1/identity")[0] == 200
        assert _call(port, "POST", "/v1/fast/decide", body) == (
            503,
            {"wire_version": "local-fast-wire-v1", "error": "busy"},
        )
        release.set()
        worker.join(timeout=10)
    assert first[0][0] == 200


def test_generation_runs_on_one_model_thread_whatever_thread_calls() -> None:
    """MLX streams are thread-local: a model loaded on one thread fails with
    "There is no Stream(cpu, 0) in current thread" when a fresh HTTP handler
    thread generates (observed on the live gateway).  Load and every generate
    must share one thread."""

    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    threads: list[str] = []

    def generator(_: str) -> str:
        threads.append(threading.current_thread().name)
        return oracle

    core = LocalFastGatewayCore.with_generator(generator)
    body = _request_body(_product_view(scenario, position), position.observation)
    with _running(core) as port:
        for _ in range(3):
            assert _call(port, "POST", "/v1/fast/decide", body)[0] == 200
    core.decide(_product_view(scenario, position), position.observation)
    assert len(threads) == 4
    assert len(set(threads)) == 1
    assert threads[0].startswith("local-fast-model")


def test_load_and_decide_run_on_the_same_model_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real ``load`` path (untuned: no adapter) with the MLX calls replaced
    by recorders: construction, ``_load_mlx`` and every generation share one
    thread, whichever thread calls ``load`` and ``decide``."""

    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    events: list[tuple[str, str]] = []

    def record(step: str) -> None:
        events.append((step, threading.current_thread().name))

    class _Recording(Phase03CQwenAdapter):
        def __init__(self, **kwargs: object) -> None:
            record("construct")
            super().__init__(
                generator=self._generate,
                max_tokens=MAX_TOKENS,
                model_spec=QWEN3_8B_BF16_SPEC,
                prompt_version="v6",
            )

        def _generate(self, _: str) -> str:
            record("generate")
            return oracle

        def _load_mlx(self) -> tuple[object, object, Callable[..., object]]:
            record("load")
            return _FakeModel({}), object(), lambda *_, **__: ""

    monkeypatch.setattr(gateway_core, "Phase03CQwenAdapter", _Recording)
    core = LocalFastGatewayCore.load(backend="untuned", model_path=tmp_path)
    view = _product_view(scenario, position)
    assert core.decide(view, position.observation).status == "succeeded"
    body = _request_body(view, position.observation)
    with _running(core) as port:
        assert _call(port, "POST", "/v1/fast/decide", body)[0] == 200

    assert [step for step, _ in events] == [
        "construct",
        "load",
        "generate",
        "generate",
    ]
    threads = {name for _, name in events}
    assert len(threads) == 1
    assert next(iter(threads)).startswith("local-fast-model")
    assert threading.current_thread().name not in threads


def test_http_model_failure_is_a_content_free_500() -> None:
    scenario, position = _heldout_positions()[0]

    def broken(_: str) -> str:
        raise RuntimeError("secret model text")

    core = LocalFastGatewayCore.with_generator(broken)
    body = _request_body(_product_view(scenario, position), position.observation)
    with _running(core) as port:
        status, response = _call(port, "POST", "/v1/fast/decide", body)
    assert (status, response) == (
        500,
        {"wire_version": "local-fast-wire-v1", "error": "gateway_error"},
    )


def test_http_binds_loopback_only() -> None:
    core = LocalFastGatewayCore.with_generator(lambda _: "{}")
    for host in ("0.0.0.0", "localhost", "::"):
        with pytest.raises(ValueError, match=r"127\.0\.0\.1 only"):
            make_server(core, host=host, port=0)


def test_http_logs_carry_no_content(caplog: pytest.LogCaptureFixture) -> None:
    scenario, position = _heldout_positions()[0]
    oracle = _oracle_json(scenario, position)
    view = _product_view(scenario, position)
    core = LocalFastGatewayCore.with_generator(lambda _: oracle)
    caplog.set_level(logging.DEBUG, logger="proxyloop.local_fast.gateway")
    with _running(core) as port:
        _call(
            port, "POST", "/v1/fast/decide", _request_body(view, position.observation)
        )
        _call(port, "POST", "/v1/fast/decide", b"not json")
    text = caplog.text
    assert "status=succeeded" in text and "http=400" in text
    response_text = str(json.loads(oracle)["response_text"])
    for secret in (
        response_text,
        position.observation.provider_message,
        str(view.case_id),
        view.goal.desired_outcome,
        "COMPACT_FAST_VIEW",
    ):
        assert secret not in text
