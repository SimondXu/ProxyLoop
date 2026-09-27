"""TestClient helpers for the serve tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from proxyloop.serve.api import create_app


def client(*roots: Path) -> TestClient:
    return TestClient(create_app(roots))


def get(http: TestClient, url: str) -> httpx.Response:
    # TestClient's HTTP side is typed against httpx2, absent here: pyright
    # sees Unknown. At run time it is httpx's Response.
    response: httpx.Response = cast(Any, http).get(url)
    return response


def frames(http: TestClient, path: str) -> tuple[list[str], int]:
    """All frames until the server closes, and the close code."""
    got: list[str] = []
    with (
        http.websocket_connect(path) as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        while True:
            got.append(ws.receive_text())
    return got, closed.value.code
