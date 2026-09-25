"""Loopback-only stdlib HTTP server for ``local-fast-wire-v1``.

The wire itself (request decoding, response encoding) is the one owner in
``proxyloop_agent_core.local_fast_wire``, shared with the PR-9a client.
``GET /v1/identity`` answers during a generation (threaded server);
``POST /v1/fast/decide`` is single-flight: a second call while one runs gets
``503 busy``, with no queue.  Every request must carry ``Host:
127.0.0.1:<port>`` or ``Host: localhost:<port>`` (DNS rebinding) and a decide
call ``Content-Type: application/json`` (no browser simple POST); socket
reads time out after
``SOCKET_TIMEOUT_S``.  Error bodies carry a code only.  Logs carry the
endpoint, HTTP status, gateway status, latency and token counts; never the
prompt, the observation, or model text (L9).
"""

from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

from proxyloop_agent_core.local_fast_wire import (
    DECIDE_PATH,
    IDENTITY_PATH,
    LOCAL_FAST_WIRE_VERSION,
    MAX_REQUEST_BYTES,
    DecideResponse,
    WireError,
    decode_decide_request,
    encode_decide_response,
    encode_json,
)

from .gateway_core import GatewayModelError, GatewayResult, LocalFastGatewayCore
from .trained_view import ObservationMismatchError

LOOPBACK_HOST: Final = "127.0.0.1"
ALLOWED_HOST_NAMES: Final = ("127.0.0.1", "localhost")
SOCKET_TIMEOUT_S: Final = 10.0
LOG = logging.getLogger("proxyloop.local_fast.gateway")


def decide_response(identity_fingerprint: str, result: GatewayResult) -> DecideResponse:
    """The wire answer for one core result; ``raw_output`` is never sent."""

    return DecideResponse(
        identity_fingerprint=identity_fingerprint,
        status=result.status,
        output=result.output,
        detail_code=result.detail_code,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        generation_ms=result.generation_ms,
    )


def _error(code: str) -> bytes:
    return encode_json({"wire_version": LOCAL_FAST_WIRE_VERSION, "error": code})


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, port: int, core: LocalFastGatewayCore, *, socket_timeout: float
    ) -> None:
        self.core = core
        self.socket_timeout = socket_timeout
        self.decide_lock = threading.Lock()
        self.identity_body = encode_json(core.identity.to_dict())
        self.identity_fingerprint = core.identity.identity_fingerprint
        super().__init__((LOOPBACK_HOST, port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: GatewayServer

    def setup(self) -> None:
        # Per socket operation (request line, headers, body, response write);
        # the generation itself runs off the socket and is not bounded by it.
        super().setup()
        self.connection.settimeout(self.server.socket_timeout)

    def _host_allowed(self) -> bool:
        """DNS rebinding: only a Host a loopback client of this socket sends.

        The PR-9a client accepts ``127.0.0.1``, ``localhost`` and ``::1``;
        ``http.client`` sends the URL host with the port.  This server binds
        IPv4 ``127.0.0.1`` only, so ``[::1]`` never reaches it, and the two
        names that can are accepted with the bound port.  A rebinding page
        sends its own domain name and is refused.
        """

        port = self.server.server_address[1]
        return self.headers.get("Host") in {
            f"{name}:{port}" for name in ALLOWED_HOST_NAMES
        }

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default request-line log; ``_send`` logs content-free."""

    def _send(
        self, http_status: int, body: bytes, *, started: float, **fields: object
    ) -> None:
        self.send_response(http_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        extra = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        LOG.info(
            "%s %s http=%d latency_ms=%d %s",
            self.command,
            self.path if self.path in (IDENTITY_PATH, DECIDE_PATH) else "other",
            http_status,
            round((time.monotonic() - started) * 1000),
            extra,
        )

    def do_GET(self) -> None:
        started = time.monotonic()
        if not self._host_allowed():
            self._send(400, _error("host_not_allowed"), started=started)
            return
        if self.path != IDENTITY_PATH:
            self._send(404, _error("not_found"), started=started)
            return
        self._send(200, self.server.identity_body, started=started)

    def do_POST(self) -> None:
        started = time.monotonic()
        if not self._host_allowed():
            self._send(400, _error("host_not_allowed"), started=started)
            return
        if self.path != DECIDE_PATH:
            self._send(404, _error("not_found"), started=started)
            return
        # A browser "simple" cross-origin POST cannot send application/json.
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if media_type.strip().lower() != "application/json":
            self._send(415, _error("unsupported_media_type"), started=started)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send(400, _error("request_invalid"), started=started)
            return
        if length > MAX_REQUEST_BYTES:
            self._send(413, _error("request_too_large"), started=started)
            return
        if length < 0:
            self._send(400, _error("request_invalid"), started=started)
            return
        try:
            body = self.rfile.read(length)
        except TimeoutError:
            self._send(408, _error("request_timeout"), started=started)
            return
        try:
            view, observation = decode_decide_request(body)
        except WireError:
            self._send(400, _error("request_invalid"), started=started)
            return
        if not self.server.decide_lock.acquire(blocking=False):
            self._send(503, _error("busy"), started=started)
            return
        try:
            result = self.server.core.decide(view, observation)
        except ObservationMismatchError:
            self._send(400, _error("request_invalid"), started=started)
            return
        except GatewayModelError as error:
            self._send(
                500, _error("gateway_error"), started=started, model_error=error.code
            )
            return
        except Exception as error:  # a server boundary: answer 500, log the type only
            self._send(
                500,
                _error("gateway_error"),
                started=started,
                exception=type(error).__name__,
            )
            return
        finally:
            self.server.decide_lock.release()
        self._send(
            200,
            encode_decide_response(
                decide_response(self.server.identity_fingerprint, result)
            ),
            started=started,
            status=result.status,
            detail_code=result.detail_code,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            generation_ms=result.generation_ms,
        )


def make_server(
    core: LocalFastGatewayCore,
    *,
    host: str,
    port: int,
    socket_timeout: float = SOCKET_TIMEOUT_S,
) -> GatewayServer:
    if host != LOOPBACK_HOST:
        raise ValueError("the local Fast gateway binds 127.0.0.1 only")
    return GatewayServer(port, core, socket_timeout=socket_timeout)


def serve(core: LocalFastGatewayCore, *, host: str, port: int) -> None:
    server = make_server(core, host=host, port=port)
    LOG.info(
        "serving backend=%s identity=%s on %s:%d",
        core.identity.backend,
        core.identity.identity_fingerprint,
        LOOPBACK_HOST,
        server.server_address[1],
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = [
    "DECIDE_PATH",
    "IDENTITY_PATH",
    "LOOPBACK_HOST",
    "GatewayServer",
    "decide_response",
    "make_server",
    "serve",
]
