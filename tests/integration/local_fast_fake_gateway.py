"""An in-test ``local-fast-wire-v1`` gateway on ``127.0.0.1:0`` (no model).

It decodes every request with the shared wire module, records what it got, and
answers with one scripted ``behaviour``. CI uses only this fake; the real MLX
gateway is PR-9b's and runs by hand.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from proxyloop_agent_core import SafeObservation
from proxyloop_agent_core.local_fast_wire import (
    DECIDE_PATH,
    IDENTITY_PATH,
    LOCAL_FAST_WIRE_VERSION,
    DecideResponse,
    WireError,
    canonical_sha256,
    decode_decide_request,
    encode_decide_response,
    encode_json,
)
from proxyloop_contracts import FastModelView

WIRE_FIXTURES: Final = Path(__file__).parents[1] / "fixtures" / "local-fast-wire"
GATE_PASSING_TEXT: Final = "Could you say which part of the offer worries you most?"
BEHAVIOURS: Final = frozenset(
    {
        "success",
        "slow",
        "busy",
        "server_error",
        "malformed",
        "oversize",
        "wrong_wire_version",
        "invalid_output",
        "unrenderable",
        "identity_flip",
        "drop",
        "detail_not_text",
        "trickle_head",
        "trickle_body",
    }
)


def fixture_bytes(name: str) -> bytes:
    """A golden wire body: the file minus its one trailing newline."""

    raw = (WIRE_FIXTURES / name).read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    return raw[:-1]


def identity_document(backend: str) -> dict[str, Any]:
    """The golden identity PR-9b's generator-backed gateway serves."""

    document: dict[str, Any] = json.loads(fixture_bytes(f"identity-{backend}.json"))
    return document


def model_output(**update: Any) -> dict[str, Any]:
    output: dict[str, Any] = {
        "dialogue_act": "clarify",
        "fact_updates": [],
        "reasoner_request": {"needed": False, "reason_code": "none"},
        "completion_claim": {"status": "not_done", "evidence_message_ids": []},
        "response_text": GATE_PASSING_TEXT,
        "action_intent": None,
    }
    output.update(update)
    return output


class FakeGateway:
    """Context manager: ``with FakeGateway(backend="distilled") as gateway``."""

    def __init__(self, backend: str = "distilled") -> None:
        self.backend = backend
        self.identity = identity_document(backend)
        self.identity_body = encode_json(self.identity)
        self.behaviour = "success"
        self.output: dict[str, Any] = model_output()
        self.delay_s = 1.0
        self.requests: list[tuple[FastModelView, SafeObservation]] = []
        self.raw_requests: list[bytes] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def fingerprint(self) -> str:
        return str(self.identity["identity_fingerprint"])

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> FakeGateway:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                """Silent: tests assert on content-free surfaces."""

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path != IDENTITY_PATH:
                    self._send(404, _error("not_found"))
                    return
                self._send(200, gateway.identity_body)

            def do_POST(self) -> None:
                if self.path != DECIDE_PATH:
                    self._send(404, _error("not_found"))
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                gateway.raw_requests.append(body)
                try:
                    gateway.requests.append(decode_decide_request(body))
                except WireError:
                    self._send(400, _error("request_invalid"))
                    return
                status, answer = gateway.answer()
                if status is None:
                    self.close_connection = True
                    return
                if gateway.behaviour.startswith("trickle"):
                    self._trickle(answer)
                    return
                self._send(status, answer)

            def _trickle(self, body: bytes) -> None:
                # A byte every 0.1 s: each socket read is quick, the whole
                # answer is not (review M1).
                head = (
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n\r\n"
                ).encode()
                self.close_connection = True
                if gateway.behaviour == "trickle_body":
                    self.wfile.write(head)
                    head = b""
                try:
                    for byte in (head + body)[:40]:
                        time.sleep(0.1)
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                except OSError:
                    return  # the client gave up, as it should

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        server = self._server
        self._thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02), daemon=True
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def answer(self) -> tuple[int | None, bytes]:
        behaviour = self.behaviour
        assert behaviour in BEHAVIOURS
        if behaviour == "drop":
            return None, b""
        if behaviour == "busy":
            return 503, _error("busy")
        if behaviour == "server_error":
            return 500, _error("gateway_error")
        if behaviour == "malformed":
            return 200, b'{"wire_version": "local-fast-wire-v1", '
        if behaviour == "oversize":
            return 200, encode_json({"padding": "x" * (64 * 1024)})
        if behaviour == "slow":
            time.sleep(self.delay_s)
        if behaviour == "invalid_output":
            return 200, self._response("invalid_output", None, "invalid_json")
        if behaviour == "unrenderable":
            return 200, self._response("unrenderable", None, "prompt_render_refused")
        body = self._response("succeeded", self.output, None)
        if behaviour == "wrong_wire_version":
            document = json.loads(body)
            document["wire_version"] = "local-fast-wire-v0"
            body = encode_json(document)
        if behaviour == "detail_not_text":
            # Review I1: a list where a detail code belongs.
            document = json.loads(self._response("invalid_output", None, "x"))
            document["detail_code"] = ["x"]
            body = encode_json(document)
        if behaviour == "identity_flip":
            document = json.loads(body)
            document["identity_fingerprint"] = canonical_sha256("another identity")
            body = encode_json(document)
        return 200, body

    def _response(
        self, status: Any, output: dict[str, Any] | None, detail: str | None
    ) -> bytes:
        return encode_decide_response(
            DecideResponse(
                identity_fingerprint=self.fingerprint,
                status=status,
                output=output,
                detail_code=detail,
                input_tokens=1_830,
                output_tokens=41,
                generation_ms=2_345,
            )
        )


def _error(code: str) -> bytes:
    return encode_json({"wire_version": LOCAL_FAST_WIRE_VERSION, "error": code})


__all__ = [
    "BEHAVIOURS",
    "GATE_PASSING_TEXT",
    "WIRE_FIXTURES",
    "FakeGateway",
    "fixture_bytes",
    "identity_document",
    "model_output",
]
