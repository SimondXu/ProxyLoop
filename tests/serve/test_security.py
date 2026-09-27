"""Host and Origin checks on every route, main()'s fixed origins, and URL
redaction that keeps every line JSON."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect
from tests.serve.client import ORIGIN, client, connect, frames, get
from tests.serve.conftest import Bundles

from proxyloop.serve import api
from proxyloop.serve.bundles import redact

SCHEME = re.compile(rb"https?://", re.IGNORECASE)
CASES: dict[str, tuple[dict[str, str], bytes]] = {  # a payload, and bytes kept
    "uppercase": ({"t": "see HTTPS://RELAY.EXAMPLE/V1 now"}, b" now"),
    "string end": ({"t": "see https://relay.example/v1"}, b'"see '),
    "before \\n": ({"t": "https://relay.example/v1\nnext"}, b"\\nnext"),
    "userinfo": ({"t": "https://user:pass@relay.example/x y"}, b" y"),
    'before \\"': ({"t": 'say "https://relay.example/v1" ok'}, b'\\" ok'),
    "single quotes": ({"t": "'http://relay.example/v1'"}, b"'\""),
    "nested JSON": (
        {"content": json.dumps({"url": "https://relay.example/v1", "n": 1})},
        b'\\", \\"n\\": 1}',
    ),
}


@pytest.mark.parametrize(("payload", "kept"), CASES.values(), ids=CASES.keys())
def test_redaction_removes_every_url_and_keeps_json(
    payload: dict[str, str], kept: bytes
) -> None:
    line = json.dumps(payload).encode()
    out = redact(line)
    assert SCHEME.search(out) is None
    assert b"<redacted-url>" in out and kept in out
    assert b"pass@" not in out
    json.loads(out)  # still one JSON document


def test_a_foreign_host_is_refused_on_http_and_websocket(bundles: Bundles) -> None:
    http = client(bundles.root)
    assert get(http, "/api/bundles", {"host": "evil.example"}).status_code == 400
    assert get(http, "/api/bundles", {"host": "localhost:8000"}).status_code == 200
    with (
        pytest.raises(WebSocketDenialResponse) as denied,
        connect(http, f"/ws/live/{bundles.plain}", {"host": "evil.example"}),
    ):
        pass
    assert cast(Any, denied.value).status_code == 400  # an httpx2-typed Response


@pytest.mark.parametrize("origin", ["http://evil.example", "null", ORIGIN + "0"])
def test_a_foreign_origin_is_refused_without_cors(
    bundles: Bundles, origin: str
) -> None:
    http = client(bundles.root)
    refused = get(http, "/api/bundles", {"origin": origin})
    assert refused.status_code == 403
    assert "access-control-allow-origin" not in refused.headers
    events = f"/api/replay/{bundles.plain}/events"
    assert get(http, events, {"origin": origin}).status_code == 403
    with (  # refused before accept: the handshake itself fails
        pytest.raises(WebSocketDisconnect) as closed,
        connect(http, f"/ws/live/{bundles.plain}", {"origin": origin}),
    ):
        pass
    assert closed.value.code == 4403


@pytest.mark.parametrize("headers", [{"origin": ORIGIN}, {}], ids=["allowed", "absent"])
def test_an_allowed_or_absent_origin_is_served(
    bundles: Bundles, headers: dict[str, str]
) -> None:
    http = client(bundles.root)
    got = get(http, f"/api/replay/{bundles.plain}/events", headers)
    assert got.status_code == 200
    assert "access-control-allow-origin" not in got.headers
    assert frames(http, f"/ws/live/{bundles.plain}", headers)[1] == 1000


def _served(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    """main(argv) with uvicorn.run captured: its app and keywords."""
    served: dict[str, Any] = {}

    def run(app: FastAPI, **kw: Any) -> None:
        served.update(kw, app=app)

    monkeypatch.setattr(api.uvicorn, "run", run)
    assert api.main(argv) == 0
    return served


def test_main_binds_localhost_with_fixed_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    argv = ["--port", "8123", "--allow-origin", "http://localhost:5173"]
    served = _served(monkeypatch, argv)
    assert (served["host"], served["port"]) == ("127.0.0.1", 8123)
    http = TestClient(served["app"], base_url="http://127.0.0.1:8123")
    for origin, status in [
        ("http://127.0.0.1:8123", 200),
        ("http://localhost:8123", 200),
        ("http://localhost:5173", 200),
        ("http://localhost:9999", 403),
        ("http://127.0.0.1:8123.evil.example", 403),
    ]:
        assert get(http, "/api/bundles", {"origin": origin}).status_code == status


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example:5173",
        "https://localhost:5173",
        "http://localhost:5173/",
        "http://localhost",
        "http://0.0.0.0:5173",
    ],
)
def test_main_refuses_a_non_local_extra_origin(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    with pytest.raises(SystemExit) as exited:
        _served(monkeypatch, ["--allow-origin", origin])
    assert exited.value.code == 2


def test_the_built_web_is_mounted_after_the_api(
    bundles: Bundles, tmp_path: Any
) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>ProxyLoop</html>")
    http = client(bundles.root, web_dir=web)
    page = get(http, "/")
    assert (page.status_code, page.text) == (200, "<html>ProxyLoop</html>")
    assert get(http, "/api/bundles").json()["bundles"]  # the API still wins
    assert get(http, "/", {"origin": "http://evil.example"}).status_code == 403
    assert get(client(bundles.root), "/").status_code == 404  # no web_dir


def test_main_mounts_the_web_dir_on_localhost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("ok")
    served = _served(monkeypatch, ["--port", "8124", "--web-dir", "web"])
    assert (served["host"], served["port"]) == ("127.0.0.1", 8124)
    http = TestClient(served["app"], base_url="http://127.0.0.1:8124")
    assert get(http, "/").text == "ok"
