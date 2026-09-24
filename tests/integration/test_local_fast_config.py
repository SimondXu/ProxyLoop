"""``PROXYLOOP_FAST_BACKEND`` selection refuses every unsafe start (PR-9a AC3)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from local_fast_fake_gateway import FakeGateway
from proxyloop_api.config import runtime_from_environment, services_from_environment
from proxyloop_local_fast import (
    LocalFastHttpAdapter,
    LocalFastStartupError,
    fast_adapter_from_environment,
)

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


def test_a_bad_identity_body_refuses_to_start(gateway: FakeGateway) -> None:
    gateway.identity_body = b'{"wire_version": "local-fast-wire-v1"}'
    with pytest.raises(LocalFastStartupError, match="identity"):
        fast_adapter_from_environment(
            {
                "PROXYLOOP_FAST_BACKEND": "distilled",
                "PROXYLOOP_FAST_GATEWAY_URL": gateway.url,
            }
        )


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
