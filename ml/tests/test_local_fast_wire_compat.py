"""The gateway against PR-9a's side of ``local-fast-wire-v1``.

Golden fixtures under ``tests/fixtures/local-fast-wire/`` pin the bytes both
sides agree on, and an end-to-end test drives the real PR-9a
``LocalFastHttpAdapter`` (runtime environment, a subprocess: ml never imports
runtime packages that need the runtime lock) against the real gateway HTTP
server with an injected generator, so no model is needed.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from proxyloop_agent_core.local_fast_wire import (
    decode_decide_request,
    decode_decide_response,
    encode_decide_request,
    encode_decide_response,
    encode_json,
)
from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.local_fast.gateway_core import (
    GatewayResult,
    LocalFastGatewayCore,
)
from proxyloop_evaluation.local_fast.http_server import decide_response, make_server
from proxyloop_evaluation.local_fast.identity import Backend
from test_local_fast_gateway import _heldout_positions, _oracle_json, _product_view

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/local-fast-wire"
RUNTIME_PYTHON = ROOT / "runtime/.venv/bin/python"


def _fixture(name: str) -> bytes:
    raw = (FIXTURES / name).read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    return raw[:-1]


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_the_fake_identity_equals_the_golden(backend: Backend) -> None:
    core = LocalFastGatewayCore.with_generator(lambda _: "{}", backend=backend)
    assert encode_json(core.identity.to_dict()) == _fixture(f"identity-{backend}.json")


@pytest.mark.parametrize("name", ["succeeded", "invalid-output", "unrenderable"])
def test_a_core_result_encodes_to_the_response_golden(name: str) -> None:
    golden = _fixture(f"decide-response-{name}.json")
    expected = decode_decide_response(golden)
    result = GatewayResult(
        status=expected.status,
        output=expected.output,
        detail_code=expected.detail_code,
        input_tokens=expected.input_tokens,
        output_tokens=expected.output_tokens,
        generation_ms=expected.generation_ms,
        raw_output="never on the wire",
        prompt_fingerprint="never on the wire",
    )
    encoded = encode_decide_response(
        decide_response(expected.identity_fingerprint, result)
    )
    assert encoded == golden


def test_the_request_golden_is_served() -> None:
    view, observation = decode_decide_request(_fixture("decide-request.json"))
    output = json.loads(_fixture("decide-response-succeeded.json"))["output"]
    core = LocalFastGatewayCore.with_generator(lambda _: json.dumps(output))
    result = core.decide(view, observation)
    assert (result.status, result.output) == ("succeeded", output)


def _without_descriptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_descriptions(item)
            for key, item in value.items()
            if key != "description"
        }
    if isinstance(value, list):
        return [_without_descriptions(item) for item in value]
    return value


def test_the_frozen_output_schema_matches_the_golden_except_descriptions() -> None:
    golden = json.loads(_fixture("fast-model-output.schema.json"))
    assert _without_descriptions(FastModelOutput.model_json_schema()) == (
        _without_descriptions(golden)
    )


# --- end to end: the PR-9a client against this gateway ------------------------

_CLIENT = r"""
import json, sys
from proxyloop_agent_core import FastAdapterFailure
from proxyloop_agent_core.local_fast_wire import decode_decide_request
from proxyloop_local_fast import LocalFastHttpAdapter, LocalFastStartupError

base_url, backend, request_path = sys.argv[1:4]
view, observation = decode_decide_request(open(request_path, "rb").read())
try:
    adapter = LocalFastHttpAdapter.connect(
        base_url=base_url, backend=backend, timeout_s=10
    )
except LocalFastStartupError as error:
    print(json.dumps({"startup_error": str(error)}))
    raise SystemExit(0)
out = {
    "label": adapter.fast_backend_label,
    "identity": adapter.gateway_identity.identity_fingerprint,
}
try:
    result, usage = adapter.decide_observed(view, observation)
    out["dialogue_act"] = str(result.decision.dialogue_act)
    out["response_text"] = result.decision.response_text
except FastAdapterFailure as failure:
    out["failure"] = [failure.reason_code, failure.detail_code]
print(json.dumps(out))
"""


@contextmanager
def _gateway(core: LocalFastGatewayCore) -> Iterator[int]:
    server = make_server(core, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run_client(base_url: str, backend: str, request: Path) -> dict[str, Any]:
    if not RUNTIME_PYTHON.is_file():
        pytest.fail("runtime env missing: uv sync --project runtime --all-packages")
    completed = subprocess.run(
        [str(RUNTIME_PYTHON), "-c", _CLIENT, base_url, backend, str(request)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def _request_file(tmp_path: Path) -> tuple[Path, str]:
    scenario, position = _heldout_positions()[0]
    request = tmp_path / "request.json"
    request.write_bytes(
        encode_decide_request(_product_view(scenario, position), position.observation)
    )
    return request, _oracle_json(scenario, position)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_the_pr9a_client_gets_a_line_from_this_gateway(
    tmp_path: Path, host: str
) -> None:
    request, oracle = _request_file(tmp_path)
    core = LocalFastGatewayCore.with_generator(lambda _: oracle)
    with _gateway(core) as port:
        answer = _run_client(f"http://{host}:{port}", "distilled", request)
    assert answer == {
        "label": "local_distilled_candidate",
        "identity": core.identity.identity_fingerprint,
        "dialogue_act": json.loads(oracle)["dialogue_act"],
        "response_text": json.loads(oracle)["response_text"],
    }


def test_the_pr9a_client_maps_an_invalid_output_to_a_typed_failure(
    tmp_path: Path,
) -> None:
    request, _ = _request_file(tmp_path)
    core = LocalFastGatewayCore.with_generator(lambda _: "not json", backend="untuned")
    with _gateway(core) as port:
        answer = _run_client(f"http://127.0.0.1:{port}", "untuned", request)
    assert answer["label"] == "local_untuned_baseline"
    assert answer["failure"] == ["fast_adapter_invalid_output", "invalid_json"]


def test_the_pr9a_client_refuses_a_gateway_serving_another_backend(
    tmp_path: Path,
) -> None:
    request, _ = _request_file(tmp_path)
    core = LocalFastGatewayCore.with_generator(lambda _: "{}", backend="untuned")
    with _gateway(core) as port:
        answer = _run_client(f"http://127.0.0.1:{port}", "distilled", request)
    assert "serves backend untuned" in answer["startup_error"]
