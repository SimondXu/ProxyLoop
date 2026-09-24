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
import json
import math
import time
from collections.abc import Callable
from typing import Final, Literal
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
BACKEND_LABELS: Final[dict[str, BackendLabel]] = {
    "distilled": "local_distilled_candidate",
    "untuned": "local_untuned_baseline",
}
LOCAL_FAST_PROVIDER: Final = "local_mlx_gateway"
LOCAL_FAST_ADAPTER_VERSION: Final = "local-fast-http-v1"
DEFAULT_GATEWAY_URL: Final = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT_S: Final = 20.0
MAX_TIMEOUT_S: Final = 25.0
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})


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

        if backend not in BACKEND_LABELS:
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
        return cls(host=host, port=port, identity=identity, timeout_s=timeout)

    @property
    def gateway_identity(self) -> GatewayIdentity:
        return self._identity

    @property
    def model_identity(self) -> ModelIdentity:
        return self._model_identity

    @property
    def fast_backend_label(self) -> BackendLabel:
        return BACKEND_LABELS[self._identity.backend]

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
        # Socket timeouts bound each read; the deadline bounds the whole call.
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


def _exchange(
    host: str,
    port: int,
    timeout_s: float,
    method: str,
    path: str,
    body: bytes | None,
) -> tuple[int, bytes]:
    """One request on a fresh connection; transport errors as ``_CallFailed``."""

    connection = http.client.HTTPConnection(host, port, timeout=timeout_s)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
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


__all__ = [
    "BACKEND_LABELS",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_TIMEOUT_S",
    "LOCAL_FAST_ADAPTER_VERSION",
    "LOCAL_FAST_PROVIDER",
    "LOOPBACK_HOSTS",
    "MAX_TIMEOUT_S",
    "Backend",
    "BackendLabel",
    "LocalFastHttpAdapter",
    "LocalFastStartupError",
    "parse_loopback_url",
    "validate_timeout",
]
