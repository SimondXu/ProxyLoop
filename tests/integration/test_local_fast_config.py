"""``PROXYLOOP_FAST_BACKEND`` selection refuses every unsafe start (PR-9a AC3)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from local_fast_fake_gateway import FakeGateway, fixture_bytes
from proxyloop_agent_core.local_fast_wire import encode_json
from proxyloop_api.config import runtime_from_environment, services_from_environment
from proxyloop_local_fast import (
    DEFAULT_TIMEOUT_S,
    MAX_TIMEOUT_S,
    LocalFastHttpAdapter,
    LocalFastStartupError,
    fast_adapter_from_environment,
)
from proxyloop_local_fast.adapter import _CallFailed, _exchange

MODEL_KEYS = {
    "PROXYLOOP_MODEL_API_KEY": "test-key-not-real",
    "PROXYLOOP_MODEL_BASE_URL": "http://127.0.0.1:9",
    "PROXYLOOP_MODEL_NAME": "test-model",
}


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    with FakeGateway(backend="distilled") as running:
        yield running


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"PROXYLOOP_FAST_BACKEND": "bogus"}, "PROXYLOOP_FAST_BACKEND must be"),
        (
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": "http://10.0.0.5:8765",
            },
            "loopback",
        ),
        (
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": "https://127.0.0.1:8765",
            },
            "http://",
        ),
        (
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": "http://user:secret@127.0.0.1:8765",
            },
            "credential",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "0"},
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "25.5"},
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "nan"},
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        # Re-review N1: below the 0.1 s floor.
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "1e-300"},
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "untuned", "PROXYLOOP_FAST_TIMEOUT_S": "0.09"},
            "PROXYLOOP_FAST_TIMEOUT_S",
        ),
        (
            {"PROXYLOOP_FAST_BACKEND": "distilled", "PROXYLOOP_RUNTIME_MODE": "model"}
            | MODEL_KEYS,
            "requires PROXYLOOP_RUNTIME_MODE=scripted",
        ),
    ],
)
def test_local_fast_backend_requires_scripted_runtime_and_direct_mode(
    environ: dict[str, str], message: str
) -> None:
    # F3 / AC3: on main every one of these started a Runtime.
    with pytest.raises(ValueError, match=message):
        runtime_from_environment(environ=environ)


def test_temporal_refuses_a_local_fast_backend() -> None:
    # F3 / AC3, L11: until PR-11 the Temporal path is scripted only.
    environ = {
        "PROXYLOOP_ORCHESTRATION_MODE": "temporal",
        "PROXYLOOP_STORAGE_MODE": "postgres",
        "PROXYLOOP_DATABASE_URL": "postgresql://unused.invalid/none",
        "PROXYLOOP_FAST_BACKEND": "distilled",
    }
    with pytest.raises(ValueError, match="Temporal orchestration requires"):
        asyncio.run(services_from_environment(environ=environ))


def test_a_missing_gateway_refuses_to_start() -> None:
    # AC3: nothing listens on the port.
    with FakeGateway(backend="distilled") as stopped:
        url = stopped.url
    with pytest.raises(LocalFastStartupError, match="unavailable"):
        runtime_from_environment(
            environ={
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": url,
            }
        )


def test_a_backend_mismatch_refuses_to_start(gateway: FakeGateway) -> None:
    # AC3, L5
    with pytest.raises(LocalFastStartupError, match="backend"):
        runtime_from_environment(
            environ={
                "PROXYLOOP_FAST_BACKEND": "untuned",
                "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
            }
        )


def _identity_with(field: str, value: bytes) -> bytes:
    document = json.loads(fixture_bytes("identity-distilled.json"))
    document[field] = "__raw__"
    return encode_json(document).replace(b'"__raw__"', value)


@pytest.mark.parametrize(
    "body",
    [
        b'{"wire_version": "local-fast-wire-v1"}',
        # Review I1: these escaped as TypeError / ValueError, not a refusal.
        _identity_with("backend", b"[]"),
        _identity_with("label", b"{}"),
        _identity_with("prompt_version", b"9" * 5_000),
        b"[" * 100_000,
    ],
    ids=["missing-keys", "backend-list", "label-dict", "huge-int", "deep-nesting"],
)
def test_a_bad_identity_body_refuses_to_start(
    gateway: FakeGateway, body: bytes
) -> None:
    gateway.identity_body = body
    with pytest.raises(LocalFastStartupError, match="identity"):
        fast_adapter_from_environment(
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
            }
        )


def test_the_default_timeout_is_the_25_second_cap(gateway: FakeGateway) -> None:
    # Root amendment 2026-09-24 (measured distilled p50 21.3 s, max 26.9 s).
    assert (DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S) == (25.0, 25.0)
    adapter = fast_adapter_from_environment(
        {
            "PROXYLOOP_FAST_BACKEND": "distilled",
            "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
        }
    )
    assert adapter is not None
    assert adapter._timeout_s == 25.0


@pytest.mark.parametrize("timeout_s", [0.0, 1e-300, 0.099])
def test_connect_refuses_a_timeout_below_the_floor(timeout_s: float) -> None:
    # Re-review N1 (a): a near-zero budget is a configuration error.
    with pytest.raises(ValueError, match="timeout"):
        LocalFastHttpAdapter.connect(
            base_url="http://127.0.0.1:8765", backend="distilled", timeout_s=timeout_s
        )


def test_an_expired_deadline_is_a_typed_timeout(gateway: FakeGateway) -> None:
    # Re-review N1 (b): expiry while the connection is built maps to the
    # allow-listed timeout, never an untyped TimeoutError.
    host, port = gateway.url.removeprefix("http://").split(":")
    with pytest.raises(_CallFailed) as raised:
        _exchange(host, int(port), 1e-300, "GET", "/v1/identity", None)
    assert raised.value.code == "fast_adapter_timeout"


def test_scripted_is_the_default_and_starts_no_client() -> None:
    assert fast_adapter_from_environment({}) is None
    assert fast_adapter_from_environment({"PROXYLOOP_FAST_BACKEND": "scripted"}) is None
    assert runtime_from_environment(environ={}).adapter_mode == "scripted"


@pytest.mark.parametrize("backend", ["distilled", "untuned"])
def test_a_matching_gateway_selects_the_labelled_backend(backend: str) -> None:
    # A14, L10
    with FakeGateway(backend=backend) as running:
        runtime = runtime_from_environment(
            environ={
                "PROXYLOOP_FAST_BACKEND": backend,
                "PROXYLOOP_FAST_GATEWAY_URL": running.url,
                "PROXYLOOP_FAST_TIMEOUT_S": "25",
            }
        )
    assert (
        runtime.adapter_mode
        == {
            "distilled": "local_distilled_candidate",
            "untuned": "local_untuned_baseline",
        }[backend]
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.2:8765",
        "http://example.test:8765",
        "http://[::2]:8765",
        "http://127.0.0.1:8765/prefix",
        "http://127.0.0.1:8765?x=1",
        "file:///tmp/socket",
    ],
)
def test_connect_refuses_anything_but_a_loopback_origin(url: str) -> None:
    # A13, L1
    with pytest.raises(ValueError):
        LocalFastHttpAdapter.connect(base_url=url, backend="distilled")
