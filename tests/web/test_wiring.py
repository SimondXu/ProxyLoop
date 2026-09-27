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
from tests.support.web_wiring import OPTIONS, WiringStarter
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
    starter: WiringStarter


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Running]:
    sock = socket.socket()
    sock.bind((HOST, 0))
    port = sock.getsockname()[1]
    origin = f"http://{HOST}:{port}"
    app, cases, starter = build(tmp_path, origin, web_dir=None)
    run = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=run.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not run.started:
        assert thread.is_alive() and time.monotonic() < deadline, "no server"
        time.sleep(0.02)
    yield Running(origin, f"ws://{HOST}:{port}", starter)
    run.should_exit = True
    thread.join(10)
    for case in [*cases.values(), *starter.cases]:
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


def test_start_routes_over_the_stub_starter(server: Running) -> None:
    """The stub Starter serves the S1-SYS-33 shapes; a broken options call is
    500 ``options`` with a reason (the page shows it: e2e/start.spec.ts)."""
    with httpx.Client(base_url=server.origin) as http:
        models = http.get("/api/models").json()
        assert [o["id"] for o in models["options"]] == [o.id for o in OPTIONS]
        assert {o["lane"] for o in models["options"] if o["default"]} == {
            "fast_user",
            "fast_cp",
            "slow",
        }
        got = http.get("/start")
        assert (got.status_code, got.headers["location"]) == (303, "/?start")
        own = {"origin": server.origin, "x-csrf-token": got.cookies["pl_op_csrf"]}
        body: dict[str, object] = {
            "task_ref": "wire-start",
            "models": {},
            "rep": "human",
        }
        started = http.post("/api/cases", json=body, headers=own)
        assert (started.status_code, started.json()) == (201, {"case_id": "started-1"})
        assert server.starter.calls == [("wire-start", {}, "human")]
        assert http.get("/live/started-1").status_code == 303
        server.starter.broken_options = True
        broken = http.get("/api/models")
        assert broken.status_code == 500
        assert broken.json()["error"] == "options"
        assert "default" in broken.json()["reason"]
