"""TestClient helpers for the serve tests: requests come from 127.0.0.1, and
every WebSocket receive is bounded, so a stream that never closes fails its
test instead of hanging it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import anyio
import httpx
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.types import Message

from proxyloop.serve.api import create_app

ORIGIN = "http://localhost:5173"  # the one browser origin the test apps allow
TIMEOUT_S = 5.0


def client(*roots: Path, origins: Sequence[str] = (ORIGIN,)) -> TestClient:
    return TestClient(create_app(roots, origins), base_url="http://127.0.0.1")


def get(
    http: TestClient, url: str, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    # TestClient's HTTP side is typed against httpx2, absent here: pyright
    # sees Unknown. At run time it is httpx's Response.
    response: httpx.Response = cast(Any, http).get(url, headers=headers)
    return response


def connect(
    http: TestClient, path: str, headers: Mapping[str, str] | None = None
) -> WebSocketTestSession:
    # websocket_connect joins a relative path onto ws://testserver.
    return http.websocket_connect(f"ws://127.0.0.1{path}", headers=dict(headers or {}))


def receive(ws: WebSocketTestSession) -> Message:
    """The next message from the app, or TimeoutError after TIMEOUT_S."""

    async def one() -> Message:
        with anyio.fail_after(TIMEOUT_S):
            return await ws._send_rx.receive()  # pyright: ignore[reportPrivateUsage]

    return ws.portal.call(one)


def frames(
    http: TestClient, path: str, headers: Mapping[str, str] | None = None
) -> tuple[list[str], int]:
    """All frames until the server closes, and the close code."""
    got: list[str] = []
    with connect(http, path, headers) as ws:
        while (message := receive(ws))["type"] != "websocket.close":
            got.append(message["text"])
    return got, message["code"]
