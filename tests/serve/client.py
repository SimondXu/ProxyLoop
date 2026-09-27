"""TestClient helpers for the serve tests: requests come from 127.0.0.1, and
every WebSocket receive is bounded, so a stream that never closes fails its
test instead of hanging it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import anyio
import httpx
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.types import Message

from proxyloop.serve.api import create_app
from proxyloop.serve.cases import Case

ORIGIN = "http://localhost:5173"  # the one browser origin the test apps allow
TIMEOUT_S = 5.0
NAMES = {"user": ("pl_session", "pl_csrf"), "rep": ("pl_rep_session", "pl_rep_csrf")}
PAGE = {"user": "live", "rep": "rep"}
OMIT = "<omit>"  # a header left out


def client(
    *roots: Path,
    origins: Sequence[str] = (ORIGIN,),
    cases: Callable[[str], Case | None] | None = None,
    web_dir: Path | None = None,
) -> TestClient:
    app = create_app(roots, origins, cases=cases, web_dir=web_dir)
    return TestClient(app, base_url="http://127.0.0.1")


def get(
    http: TestClient,
    url: str,
    headers: Mapping[str, str] | None = None,
    follow: bool = True,
) -> httpx.Response:
    # TestClient's HTTP side is typed against httpx2, absent here: pyright
    # sees Unknown. At run time it is httpx's Response.
    response: httpx.Response = cast(Any, http).get(
        url, headers=headers, follow_redirects=follow
    )
    return response


def post(
    http: TestClient, url: str, body: object, headers: Mapping[str, str]
) -> httpx.Response:
    response: httpx.Response = cast(Any, http).post(url, json=body, headers=headers)
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


def login(http: TestClient, role: str, case_id: str) -> dict[str, str]:
    """GET /live or /rep: the role's two cookies (the client's jar is emptied,
    so every later request carries exactly the cookies a test names)."""
    got = get(http, f"/{PAGE[role]}/{case_id}", follow=False)
    assert got.status_code == 303, got.text
    assert got.headers["location"] == f"/?{PAGE[role]}={case_id}"
    cookies = dict(got.cookies)
    assert set(cookies) == set(NAMES[role])
    cast(Any, http).cookies.clear()
    return cookies


def headers(
    cookies: dict[str, str], token: str | None = None, origin: str = ORIGIN
) -> dict[str, str]:
    """``token`` None echoes the csrf cookie (whichever role's is present)."""
    csrf = next((v for k, v in cookies.items() if k.endswith("csrf")), "")
    out = {"cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
    if (token := csrf if token is None else token) != OMIT:
        out["x-csrf-token"] = token
    if origin != OMIT:
        out["origin"] = origin
    return out
