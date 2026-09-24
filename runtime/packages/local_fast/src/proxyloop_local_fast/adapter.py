"""The runtime HTTP Fast adapter for the loopback local Fast gateway.

A ``LocalFastHttpAdapter`` is a Fast adapter, an ``ObservingFastAdapter`` and
an ``IdentifiedAdapter``. It sends the coordinator's view and observation over
``local-fast-wire-v1``, validates the answer with the runtime-owned strict
``FastModelOutput``, and compiles it against the trusted view, so no id or pin
is taken from the gateway.

Every outcome other than a compiled decision raises a ``FastAdapterFailure``
with an allow-listed code; the Runtime then delivers the fallback line. There
is no retry, no queue and no second backend (design L6). The client talks to a
loopback origin only, follows no redirect, and carries no credential (L1).
"""

from __future__ import annotations

import http.client
import io
import json
import math
import socket
import time
from collections.abc import Callable
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from proxyloop_agent_core import (
    FAST_OBSERVATION_VERSION,
    FastAdapterFailure,
    FastAdapterResult,
    ModelCallUsage,
    ModelIdentity,
    SafeObservation,
)
from proxyloop_agent_core.local_fast_wire import (
    DECIDE_PATH,
    IDENTITY_PATH,
    MAX_RESPONSE_BYTES,
    GatewayIdentity,
    WireError,
    decode_decide_response,
    decode_identity,
    encode_decide_request,
)
from proxyloop_contracts import FastModelView, FastTurnDecision
from proxyloop_openai_adapter import FastModelOutput, compile_fast_output

Backend = Literal["distilled", "untuned"]
BackendLabel = Literal["local_distilled_candidate", "local_untuned_baseline"]
ADAPTER_MODE_BY_BACKEND: Final[dict[str, BackendLabel]] = {
    "distilled": "local_distilled_candidate",
    "untuned": "local_untuned_baseline",
}
LOCAL_FAST_PROVIDER: Final = "local_mlx_gateway"
LOCAL_FAST_ADAPTER_VERSION: Final = "local-fast-http-v1"
DEFAULT_GATEWAY_URL: Final = "http://127.0.0.1:8765"
# Root amendment 2026-09-24: the default is the cap. PR-9b measured distilled
# calls at p50 21.3 s, max 26.9 s locally; the cap stays under the 30 s
# Temporal activity and Next proxy limits.
DEFAULT_TIMEOUT_S: Final = 25.0
MAX_TIMEOUT_S: Final = 25.0
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
# What the Phase 03C parity was measured on (review M2). The runtime cannot
# import ml/, so these mirror `QWEN3_8B_BF16_SPEC.model` in
# `ml/evaluation/src/proxyloop_evaluation/qwen_spec.py` and the 03C v6 prompt;
# the identity goldens under tests/fixtures/local-fast-wire pin both values.
SERVED_BASE_MODEL: Final = "Qwen/Qwen3-8B-MLX-bf16"
SERVED_PROMPT_VERSION: Final = "v6"


class LocalFastStartupError(RuntimeError):
    """The gateway is absent, invalid, or serves another backend: do not start."""


class _CallFailed(Exception):
    def __init__(self, code: str, detail_code: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail_code = detail_code


def validate_timeout(timeout_s: float) -> float:
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int | float)
        or not math.isfinite(timeout_s)
        or not 0 < timeout_s <= MAX_TIMEOUT_S
    ):
        raise ValueError(f"the local Fast timeout must be in (0, {MAX_TIMEOUT_S:g}]")
    return float(timeout_s)


def parse_loopback_url(base_url: str) -> tuple[str, int]:
    """``(host, port)`` of an ``http://`` loopback origin; anything else refused."""

    parts = urlsplit(base_url)
    if parts.scheme != "http":
        raise ValueError("the local Fast gateway URL must start with http://")
    if parts.username is not None or parts.password is not None:
        raise ValueError("the local Fast gateway URL cannot carry a credential")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("the local Fast gateway URL must be an origin only")
    host = parts.hostname
    if host not in LOOPBACK_HOSTS:
        raise ValueError("the local Fast gateway must be on a loopback address")
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("the local Fast gateway port is invalid") from error
    return host, port if port is not None else 80


class LocalFastHttpAdapter:
    """One loopback gateway and the identity probed at start; a fresh
    connection per call."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        identity: GatewayIdentity,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if host not in LOOPBACK_HOSTS:
            raise ValueError("the local Fast gateway must be on a loopback address")
        self._host = host
        self._port = port
        self._identity = identity
        self._timeout_s = validate_timeout(timeout_s)
        self._monotonic = monotonic
        self._model_identity = ModelIdentity(
            provider=LOCAL_FAST_PROVIDER,
            model=identity.base_model,
            model_version=f"{identity.backend}:{identity.identity_fingerprint[:16]}",
            adapter_version=LOCAL_FAST_ADAPTER_VERSION,
            prompt_version=(
                f"phase-03c-{identity.prompt_version}+{FAST_OBSERVATION_VERSION}"
            ),
        )

    @classmethod
    def connect(
        cls,
        *,
        base_url: str,
        backend: Backend,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> LocalFastHttpAdapter:
        """Probe ``/v1/identity``; refuse to start unless it serves ``backend``."""

        if backend not in ADAPTER_MODE_BY_BACKEND:
            raise ValueError("the local Fast backend must be distilled or untuned")
        host, port = parse_loopback_url(base_url)
        timeout = validate_timeout(timeout_s)
        try:
            status, body = _exchange(host, port, timeout, "GET", IDENTITY_PATH, None)
        except _CallFailed as failure:
            raise LocalFastStartupError(
                "the local Fast gateway is unavailable"
            ) from failure
        if status != 200:
            raise LocalFastStartupError(
                "the local Fast gateway identity request failed"
            )
        try:
            identity = decode_identity(body)
        except WireError as error:
            raise LocalFastStartupError(
                "the local Fast gateway identity is invalid"
            ) from error
        if identity.backend != backend:
            raise LocalFastStartupError(
                f"the local Fast gateway serves backend {identity.backend}, "
                f"not {backend}"
            )
        if (
            identity.prompt_version != SERVED_PROMPT_VERSION
            or identity.base_model != SERVED_BASE_MODEL
        ):
            raise LocalFastStartupError(
                "the local Fast gateway serves another prompt version or base model"
            )
        return cls(host=host, port=port, identity=identity, timeout_s=timeout)

    @property
    def gateway_identity(self) -> GatewayIdentity:
        return self._identity

    @property
    def model_identity(self) -> ModelIdentity:
        return self._model_identity

    @property
    def fast_backend_label(self) -> BackendLabel:
        return ADAPTER_MODE_BY_BACKEND[self._identity.backend]

    def decide(self, view: FastModelView) -> FastAdapterResult:
        # The trained model cannot be prompted without the public observation.
        raise FastAdapterFailure(
            "fast_input_unrenderable", detail_code="observation_required"
        )

    def decide_observed(
        self, view: FastModelView, observation: SafeObservation
    ) -> tuple[FastAdapterResult, ModelCallUsage]:
        started = self._monotonic()
        try:
            status, body = _exchange(
                self._host,
                self._port,
                self._timeout_s,
                "POST",
                DECIDE_PATH,
                encode_decide_request(view, observation),
            )
        except _CallFailed as failure:
            raise FastAdapterFailure(
                failure.code, detail_code=failure.detail_code
            ) from None
        elapsed = max(0.0, self._monotonic() - started)
        # ``_exchange`` bounds the whole call; this re-checks on the injected
        # clock that times the call.
        if elapsed > self._timeout_s:
            raise FastAdapterFailure("fast_adapter_timeout")
        if status == 503:
            raise FastAdapterFailure("fast_adapter_busy")
        if status != 200:
            raise FastAdapterFailure(
                "fast_adapter_protocol_error", detail_code="http_status_unexpected"
            )
        if len(body) > MAX_RESPONSE_BYTES:
            raise FastAdapterFailure(
                "fast_adapter_protocol_error", detail_code="response_too_large"
            )
        try:
            response = decode_decide_response(body)
        except WireError as error:
            raise FastAdapterFailure(
                "fast_adapter_protocol_error", detail_code=error.code
            ) from None
        if response.identity_fingerprint != self._identity.identity_fingerprint:
            raise FastAdapterFailure("fast_adapter_identity_mismatch")
        usage = ModelCallUsage(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=round(elapsed * 1000),
        )
        if response.status == "invalid_output":
            raise FastAdapterFailure(
                "fast_adapter_invalid_output",
                detail_code=response.detail_code,
                usage=usage,
            )
        if response.status == "unrenderable":
            raise FastAdapterFailure(
                "fast_input_unrenderable", detail_code=response.detail_code, usage=usage
            )
        decision = _compile(view, response.output, usage)
        return FastAdapterResult(pins=view.pins, decision=decision), usage


def _compile(
    view: FastModelView, output: object, usage: ModelCallUsage
) -> FastTurnDecision:
    def invalid(detail_code: str) -> FastAdapterFailure:
        return FastAdapterFailure(
            "fast_adapter_invalid_output", detail_code=detail_code, usage=usage
        )

    try:
        # JSON mode: the strict model refuses enum strings in python mode.
        parsed = FastModelOutput.model_validate_json(json.dumps(output))
    except ValueError:
        raise invalid("output_schema_invalid") from None
    # The trained convention is no fact updates; one with provenance the Case
    # cannot see would fail the Consumer's command (L8).
    if parsed.fact_updates:
        raise invalid("fact_updates_not_empty")
    try:
        return compile_fast_output(view, parsed)
    except ValueError:
        raise invalid("output_compile_refused") from None


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the local Fast call deadline passed")
    return remaining


class _DeadlineReader(io.RawIOBase):
    """Each socket read waits at most the call's remaining budget (review M1).

    A socket timeout alone bounds one read, so a gateway that trickles its
    answer could hold the call, and the direct-mode app lock, far past it.
    """

    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self._sock.settimeout(_remaining(self._deadline))
        return self._sock.recv_into(buffer)


class _DeadlineSocket:
    """What ``http.client`` uses of a socket, with every read and write
    bounded by the deadline. Closing is left to ``_exchange``, which owns the
    real socket (``http.client`` closes the connection before reading the
    body of a ``Connection: close`` answer)."""

    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def makefile(self, mode: str, *args: object, **kwargs: object) -> io.BufferedReader:
        return io.BufferedReader(_DeadlineReader(self._sock, self._deadline))

    def sendall(self, data: bytes) -> None:
        self._sock.settimeout(_remaining(self._deadline))
        self._sock.sendall(data)

    def close(self) -> None:
        return None


class _DeadlineConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, deadline: float) -> None:
        super().__init__(host, port, timeout=_remaining(deadline))
        self._deadline = deadline
        self.raw_sock: socket.socket | None = None

    def connect(self) -> None:
        super().connect()
        self.raw_sock = self.sock
        self.sock = _DeadlineSocket(self.raw_sock, self._deadline)


def _exchange(
    host: str,
    port: int,
    timeout_s: float,
    method: str,
    path: str,
    body: bytes | None,
) -> tuple[int, bytes]:
    """One request on a fresh connection, all of it within ``timeout_s``;
    transport errors as ``_CallFailed``."""

    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = _DeadlineConnection(host, port, time.monotonic() + timeout_s)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except TimeoutError:
        raise _CallFailed("fast_adapter_timeout") from None
    except OSError:
        # Refused, reset, or closed without an answer.
        raise _CallFailed("fast_adapter_unavailable") from None
    except http.client.HTTPException:
        raise _CallFailed(
            "fast_adapter_protocol_error", "http_response_invalid"
        ) from None
    finally:
        connection.close()
        if connection.raw_sock is not None:
            connection.raw_sock.close()


__all__ = [
    "ADAPTER_MODE_BY_BACKEND",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_TIMEOUT_S",
    "LOCAL_FAST_ADAPTER_VERSION",
    "LOCAL_FAST_PROVIDER",
    "LOOPBACK_HOSTS",
    "MAX_TIMEOUT_S",
    "SERVED_BASE_MODEL",
    "SERVED_PROMPT_VERSION",
    "Backend",
    "BackendLabel",
    "LocalFastHttpAdapter",
    "LocalFastStartupError",
    "parse_loopback_url",
    "validate_timeout",
]
