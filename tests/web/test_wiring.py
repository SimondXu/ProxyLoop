"""The wiring server at the HTTP level (S1-SYS-18, test i). A page cannot set
Origin, so a foreign Origin is tested here against the running server
(``tests.web.wiring_server`` without the built web, on a free port): every
POST is 403 ``origin``, and both streams' handshakes are refused. The same
requests from the server's own origin pass, so the Origin alone was refused."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from tests.web.wiring_server import build
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Origin

from proxyloop.serve.api import HOST

CASE = "wire-chat"
FOREIGN = "http://evil.example"


@dataclass(frozen=True)
class Running:
    origin: str  # http://127.0.0.1:<port>, the one allowed browser origin
    ws: str


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Running]:
    sock = socket.socket()
    sock.bind((HOST, 0))
    port = sock.getsockname()[1]
    origin = f"http://{HOST}:{port}"
    app, cases = build(tmp_path, origin, web_dir=None)
    run = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=run.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not run.started:
        assert thread.is_alive() and time.monotonic() < deadline, "no server"
        time.sleep(0.02)
    yield Running(origin, f"ws://{HOST}:{port}")
    run.should_exit = True
    thread.join(10)
    for case in cases.values():
        case.close()


def login(http: httpx.Client, page: str) -> str:
    """GET /live or /rep: the role's cookies into the jar; its CSRF token."""
    got = http.get(f"/{page}/{CASE}")
    assert got.status_code == 303, got.text
    return got.cookies["pl_csrf" if page == "live" else "pl_rep_csrf"]


def test_a_foreign_origin_is_403_on_every_post(server: Running) -> None:
    with httpx.Client(base_url=server.origin) as http:
        user, rep = login(http, "live"), login(http, "rep")
        body = {"decision": "granted", "terms_hash": "0" * 64, "authority_epoch": 0}
        for path, sent, token in [
            ("messages", {"text": "hi"}, user),
            ("approvals/apr-o1-r1-e0-0", body, user),
            ("rep", {"text": "hi"}, rep),
        ]:
            url = f"/api/cases/{CASE}/{path}"
            got = http.post(
                url, json=sent, headers={"origin": FOREIGN, "x-csrf-token": token}
            )
            assert (got.status_code, got.json()) == (403, {"error": "origin"}), path
            assert "access-control-allow-origin" not in got.headers
        own = {"origin": server.origin, "x-csrf-token": user}
        got = http.post(f"/api/cases/{CASE}/messages", json={"text": "hi"}, headers=own)
        assert (got.status_code, got.json()) == (200, {"status": "sent"})


@pytest.mark.parametrize("stream", ["live", "rep"])
def test_a_foreign_origin_cannot_open_a_stream(server: Running, stream: str) -> None:
    with httpx.Client(base_url=server.origin) as http:
        login(http, "rep")
        cookie = "; ".join(f"{k}={v}" for k, v in http.cookies.items())
    url, cookies = f"{server.ws}/ws/{stream}/{CASE}", {"cookie": cookie}
    with pytest.raises(InvalidStatus) as refused:
        connect(url, origin=Origin(FOREIGN), additional_headers=cookies, proxy=None)
    assert refused.value.response.status_code == 403
    own = Origin(server.origin)
    with connect(url, origin=own, additional_headers=cookies, proxy=None) as ws:
        assert json.loads(ws.recv(timeout=5))["seq"] == 0
