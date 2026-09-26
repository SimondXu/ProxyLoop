"""The replay API and the live WebSocket over real fake-session bundles."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tests.serve.conftest import URL, Bundles

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS
from proxyloop.serve import api
from proxyloop.serve.api import create_app


def _lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines()


def _client(*roots: Path) -> TestClient:
    return TestClient(create_app(roots))


def _get(client: TestClient, url: str) -> httpx.Response:
    # TestClient's HTTP side is typed against httpx2, absent here: pyright
    # sees Unknown. At run time it is httpx's Response.
    response: httpx.Response = cast(Any, client).get(url)
    return response


def _frames(client: TestClient, path: str) -> tuple[list[str], int]:
    """All frames until the server closes, and the close code."""
    frames: list[str] = []
    with (
        client.websocket_connect(path) as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        while True:
            frames.append(ws.receive_text())
    return frames, closed.value.code


def _copy(src: Path, root: Path, lines: list[bytes] | None = None) -> Path:
    """A hand-made bundle dir under ``root`` with ``src``'s name: ``lines`` as
    its events (or all of ``src``'s files)."""
    dst = root / src.name
    if lines is None:
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True)
        (dst / EVENTS).write_bytes(b"".join(line + b"\n" for line in lines))
    return dst


def test_bodies_are_byte_equal_to_the_bundle_files(bundles: Bundles) -> None:
    path, client = bundles.root / bundles.plain, _client(bundles.root)
    for name in (MANIFEST, EVENTS, PROMPTS):
        assert b"http" not in (path / name).read_bytes()  # nothing to redact
    base = f"/api/replay/{bundles.plain}"
    for route, name, media in [
        ("manifest", MANIFEST, "application/json"),
        ("events", EVENTS, "application/x-ndjson"),
        ("prompts", PROMPTS, "application/x-ndjson"),
    ]:
        got = _get(client, f"{base}/{route}")
        assert got.status_code == 200
        assert got.headers["content-type"].startswith(media)
        assert got.content == (path / name).read_bytes()
    lines = _lines(path / PROMPTS)
    assert len(lines) > 3
    for line in lines:
        got = _get(client, f"{base}/prompts/{json.loads(line)['sha']}")
        assert (got.status_code, got.content) == (200, line)
        assert got.headers["content-type"] == "application/json"


def test_urls_are_redacted_in_every_body_and_frame(bundles: Bundles) -> None:
    path, client = bundles.root / bundles.url, _client(bundles.root)
    assert URL.encode() in (path / EVENTS).read_bytes()
    assert URL.encode() in (path / PROMPTS).read_bytes()
    base = f"/api/replay/{bundles.url}"
    bodies = [_get(client, f"{base}/{r}").content for r in ("events", "prompts")]
    carrying = [ln for ln in _lines(path / PROMPTS) if URL.encode() in ln]
    sha = json.loads(carrying[0])["sha"]
    bodies.append(_get(client, f"{base}/prompts/{sha}").content)
    frames, code = _frames(client, f"/ws/live/{bundles.url}")
    assert code == 1000
    bodies.append("\n".join(frames).encode())
    for body in bodies:
        assert b"<redacted-url>" in body
        assert b"http://" not in body and b"https://" not in body
        for line in body.splitlines():
            json.loads(line)  # still one JSON document per line
    assert len(bodies[0].splitlines()) == len(_lines(path / EVENTS))


def test_the_listing_marks_live_bundles_and_prefers_the_first_root(
    bundles: Bundles, tmp_path: Path
) -> None:
    runs, evidence = tmp_path / "runs", tmp_path / "evidence"
    events = _lines(bundles.root / bundles.plain / EVENTS)
    _copy(bundles.root / bundles.plain, runs)
    _copy(bundles.root / bundles.url, evidence)
    live = _copy(bundles.root / bundles.url, runs, events[:3])  # same id: runs wins
    (runs / "zz-no-events").mkdir()
    (runs / "zz-file").write_text("not a bundle")
    got = _get(_client(runs, evidence, tmp_path / "missing"), "/api/bundles")
    assert got.status_code == 200
    listed = got.json()["bundles"]
    assert [b["run_id"] for b in listed] == sorted(
        [bundles.plain, bundles.url], reverse=True
    )
    by_id = {b["run_id"]: b for b in listed}
    assert by_id[live.name] == {
        "run_id": live.name,
        "root": "runs",
        "complete": False,
        "task_ref": None,
    }
    assert by_id[bundles.plain]["complete"] is True
    assert by_id[bundles.plain]["task_ref"] == "cp-direct-discount@1"
    client = _client(runs, evidence)
    assert _get(client, f"/api/replay/{live.name}/manifest").status_code == 404
    assert _get(client, f"/api/replay/{live.name}/prompts").status_code == 404
    assert _get(client, f"/api/replay/{live.name}/events").content == b"".join(
        line + b"\n" for line in events[:3]
    )


@pytest.mark.parametrize("from_seq", [0, 5])
def test_the_socket_replays_a_bundle_in_seq_order(
    bundles: Bundles, from_seq: int
) -> None:
    lines = _lines(bundles.root / bundles.plain / EVENTS)
    path = f"/ws/live/{bundles.plain}?from_seq={from_seq}"
    frames, code = _frames(_client(bundles.root), path)
    assert [f.encode() for f in frames] == lines[from_seq:]
    assert [json.loads(f)["seq"] for f in frames] == list(range(from_seq, len(lines)))
    assert json.loads(frames[-1])["type"] == "session.ended"
    assert code == 1000


def test_the_socket_follows_a_live_run_line_by_line(
    bundles: Bundles, tmp_path: Path
) -> None:
    lines = _lines(bundles.root / bundles.plain / EVENTS)
    run = _copy(bundles.root / bundles.plain, tmp_path, lines[:3])
    got: list[bytes] = []
    with (
        _client(tmp_path).websocket_connect(f"/ws/live/{run.name}") as ws,
        (run / EVENTS).open("ab") as log,
    ):
        got += [ws.receive_text().encode() for _ in range(3)]
        half = len(lines[3]) // 2
        log.write(lines[3][:half])  # a partial line waits for its newline
        log.flush()
        time.sleep(3 * api.POLL_S)
        log.write(lines[3][half:] + b"\n")
        log.flush()
        got.append(ws.receive_text().encode())
        for line in lines[4:]:
            log.write(line + b"\n")
            log.flush()
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                got.append(ws.receive_text().encode())
    assert got == lines
    assert closed.value.code == 1000


def test_a_client_leaving_a_live_run_ends_the_stream(
    bundles: Bundles, tmp_path: Path
) -> None:
    lines = _lines(bundles.root / bundles.plain / EVENTS)
    run = _copy(bundles.root / bundles.plain, tmp_path, lines[:2])
    with _client(tmp_path).websocket_connect(f"/ws/live/{run.name}") as ws:
        ws.receive_text()
    # Leaving the block waits for the handler: it returned, not polling on.


def test_a_seq_gap_or_a_bad_line_closes_1011(bundles: Bundles, tmp_path: Path) -> None:
    lines = _lines(bundles.root / bundles.plain / EVENTS)
    gap = _copy(bundles.root / bundles.plain, tmp_path / "gap", [*lines[:2], lines[3]])
    bad = _copy(bundles.root / bundles.plain, tmp_path / "bad", [lines[0], b"{oops"])
    for root, run in ((tmp_path / "gap", gap), (tmp_path / "bad", bad)):
        frames, code = _frames(_client(root), f"/ws/live/{run.name}")
        assert code == 1011
        assert [f.encode() for f in frames] == lines[: len(frames)]


def test_an_unknown_run_closes_4404(bundles: Bundles) -> None:
    assert _frames(_client(bundles.root), "/ws/live/no-such-run") == ([], 4404)
    assert _frames(_client(bundles.root), "/ws/live/.hidden") == ([], 4404)


def test_malformed_or_outside_ids_never_reach_a_file(
    bundles: Bundles, tmp_path: Path
) -> None:
    root, outside = tmp_path / "runs", tmp_path / "secret"
    _copy(bundles.root / bundles.plain, outside)
    root.mkdir()
    (root / "linked").symlink_to(outside / bundles.plain, target_is_directory=True)
    held = root / "held"
    held.mkdir()
    (held / EVENTS).symlink_to(outside / bundles.plain / EVENTS)
    client = _client(root)
    assert _get(client, "/api/bundles").json() == {"bundles": []}
    statuses: dict[str, int] = {
        "/api/replay/../events": 404,
        "/api/replay/..%2Fsecret%2F" + bundles.plain + "/events": 404,
        "/api/replay/.hidden/events": 422,
        "/api/replay/%2Fetc%2Fpasswd/events": 404,
        "/api/replay/a%20b/events": 422,
        f"/api/replay/{'a' * 129}/events": 422,
        f"/api/replay/{bundles.plain}/events": 404,  # it lives outside the root
        "/api/replay/linked/events": 404,
        "/api/replay/held/events": 404,
    }
    for url, status in statuses.items():
        assert _get(client, url).status_code == status, url
    ok = _client(bundles.root)
    base = f"/api/replay/{bundles.plain}/prompts"
    assert _get(ok, f"{base}/{'0' * 64}").status_code == 404
    assert _get(ok, f"{base}/{'A' * 64}").status_code == 422
    assert _get(ok, f"{base}/..%2F..%2Fmanifest.json").status_code == 404


def test_main_binds_localhost_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def run(app: object, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(api.uvicorn, "run", run)
    assert api.main(["--port", "8123"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123}]
