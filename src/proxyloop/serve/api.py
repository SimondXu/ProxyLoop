"""Bundle listing, replay and the live event stream (ARCHITECTURE §2, §14).

Every body is a bundle file's bytes with one transformation: each http(s) URL
becomes ``<redacted-url>`` (AGENTS rule 15), so a body without a URL is
byte-equal to its file. ``serve`` only reads: it never writes, folds or renders
a prompt (import-linter: "serve is read-only"). Which bundles exist and may be
served, held-out data excluded, is ``serve.bundles``.

Every route checks the Host (127.0.0.1 or localhost, else 400) and, when a
browser sends one, the Origin against a fixed list (else 403, or a WebSocket
closed before accept with 4403); it adds no CORS headers.

``python -m proxyloop.serve.api [--port N] [--allow-origin URL]...`` serves
``runs/`` and each stage directory ``evidence/<stage>/`` (relative to the cwd,
listed at startup) on 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, BinaryIO

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import Path as Param
from fastapi.responses import PlainTextResponse, Response
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, PromptRecord
from proxyloop.contract.events import Event
from proxyloop.serve.bundles import (
    RUN_ID,
    Run,
    default_roots,
    find_run,
    held_out,
    list_runs,
    redact,
)

HOST = "127.0.0.1"  # hard-coded: no flag widens it (§9.6)
HOSTS = ["127.0.0.1", "localhost"]  # accepted Host headers (DNS rebinding)
LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost):[0-9]{1,5}")
POLL_S = 0.05  # how often /ws/live looks for new bytes
CHUNK = 256 * 1024  # the most /ws/live reads and validates per step
SHA = r"^[0-9a-f]{64}$"
JSON, NDJSON = "application/json", "application/x-ndjson"
RunId = Annotated[str, Param(pattern=RUN_ID)]
Sha = Annotated[str, Param(pattern=SHA)]
Close = tuple[int, str]  # a WebSocket close code and reason


class _Origins:
    """A present Origin must be in the fixed list: never derived from Host."""

    def __init__(self, app: ASGIApp, origins: Sequence[str]) -> None:
        self.app, self.origins = app, frozenset(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        origin = Headers(scope=scope).get("origin") if kind != "lifespan" else None
        if origin is None or origin in self.origins:
            await self.app(scope, receive, send)
        elif kind == "websocket":  # before accept: the handshake is refused
            await WebSocketClose(4403, "origin not allowed")(scope, receive, send)
        else:
            await PlainTextResponse("origin not allowed", 403)(scope, receive, send)


def task_ref(run: Run) -> str | None:
    """The manifest's task_ref: a run is complete once its manifest has one."""
    ref = manifest.get("task_ref") if (manifest := run.manifest()) else None
    return ref if isinstance(ref, str) else None


def create_app(roots: Sequence[Path], origins: Sequence[str] = ()) -> FastAPI:
    """The API over bundles under ``roots`` (listed again on every request);
    ``origins`` is the fixed list of browser origins allowed in."""
    roots = tuple(roots)
    app = FastAPI(title="ProxyLoop replay")
    app.add_middleware(_Origins, origins=tuple(origins))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS)

    def find(run_id: str) -> Run:
        if (run := find_run(roots, run_id)) is None:
            raise HTTPException(404, "unknown run")
        return run

    def read(run: Run, name: str) -> bytes:
        if (path := run.file(name)) is None:
            raise HTTPException(404, f"no {name}")
        return path.read_bytes()

    @app.get("/api/bundles")
    def bundles() -> dict[str, list[dict[str, object]]]:
        listed: list[dict[str, object]] = []
        for run_id, run in sorted(list_runs(roots).items(), reverse=True):
            ref, root = task_ref(run), run.root.resolve().name
            listed.append(
                {"run_id": run_id, "root": root, "complete": bool(ref), "task_ref": ref}
            )
        return {"bundles": listed}

    @app.get("/api/replay/{run_id}/manifest")
    def manifest(run_id: RunId) -> Response:
        if task_ref(run := find(run_id)) is None:
            raise HTTPException(404, "the run is not complete")
        return Response(redact(read(run, MANIFEST)), media_type=JSON)

    @app.get("/api/replay/{run_id}/events")
    def events(run_id: RunId) -> Response:
        return Response(redact(read(find(run_id), EVENTS)), media_type=NDJSON)

    @app.get("/api/replay/{run_id}/prompts")
    def prompts(run_id: RunId) -> Response:
        return Response(redact(read(find(run_id), PROMPTS)), media_type=NDJSON)

    @app.get("/api/replay/{run_id}/prompts/{sha}")
    def prompt(run_id: RunId, sha: Sha) -> Response:
        for line in read(find(run_id), PROMPTS).split(b"\n"):
            try:
                record = PromptRecord.model_validate_json(line)
            except ValidationError:  # blank or broken: not the line asked for
                continue
            if record.sha == sha:
                return Response(redact(line), media_type=JSON)
        raise HTTPException(404, "unknown prompt sha")

    def events_file(run_id: str) -> Path | None:
        run = find_run(roots, run_id)
        return run.file(EVENTS) if run else None

    @app.websocket("/ws/live/{run_id}")
    async def live(
        ws: WebSocket, run_id: str, from_seq: Annotated[int, Query(ge=0)] = 0
    ) -> None:
        await ws.accept()  # first, so that the client sees the close code
        if (path := await asyncio.to_thread(events_file, run_id)) is None:
            await ws.close(4404, "unknown run")
            return
        tail = asyncio.create_task(_tail(ws, path, run_id, from_seq))
        gone = asyncio.create_task(_gone(ws))
        try:
            done, _ = await asyncio.wait(
                (tail, gone), return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (tail, gone):
                task.cancel()
            await asyncio.wait((tail, gone))
            if not gone.cancelled():
                gone.exception()  # retrieved: a failed receive means the client left
        if tail.cancelled():
            return
        close = tail.result()  # re-raises a real error
        if close is not None and gone not in done:
            await ws.close(*close)

    return app


async def _gone(ws: WebSocket) -> None:
    """Return when the client disconnects; frames it sends are ignored."""
    while (await ws.receive())["type"] != "websocket.disconnect":
        pass


@dataclass
class _Reader:
    """``events.jsonl`` read, split and validated in bounded steps."""

    file: BinaryIO
    run_id: str
    from_seq: int
    seq: int = 0
    pending: bytes = b""  # a trailing partial line waits for its newline

    def step(self) -> tuple[list[str], Close | None, bool]:
        """One chunk: the frames to send, a close, and whether it was empty."""
        chunk = self.file.read(CHUNK)
        *lines, self.pending = (self.pending + chunk).split(b"\n")
        frames: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = Event.model_validate_json(line)
            except ValidationError:
                return frames, (1011, f"invalid line after seq {self.seq - 1}"), False
            if event.run_id != self.run_id or event.seq != self.seq:
                why = f"seq {event.seq} of {event.run_id}, {self.seq} expected"
                return frames, (1011, why), False
            if held_out(event):  # seq 0: nothing of a test-split run is sent
                return frames, (4404, "unknown run"), False
            self.seq += 1
            if event.seq >= self.from_seq:
                frames.append(redact(line).decode("utf-8"))
            if event.type == "session.ended":
                return frames, (1000, "session ended"), False
        return frames, None, not chunk


async def _tail(ws: WebSocket, path: Path, run_id: str, from_seq: int) -> Close | None:
    """Send each stored line from ``from_seq`` in dense seq order, following the
    file by polling. Reading and validation run in a worker thread, one bounded
    chunk at a time, yielding between chunks. None: the client left."""
    with path.open("rb") as f:
        reader = _Reader(f, run_id, from_seq)
        while True:
            frames, close, empty = await asyncio.to_thread(reader.step)
            for frame in frames:
                try:
                    await ws.send_text(frame)
                except WebSocketDisconnect:
                    return None
            if close is not None:
                return close
            await asyncio.sleep(POLL_S if empty else 0)


def _origin(value: str) -> str:
    if not LOCAL_ORIGIN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"{value!r} is not http://127.0.0.1:<port> or http://localhost:<port>"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.serve.api")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--allow-origin", action="append", default=[], type=_origin, metavar="URL"
    )
    args = parser.parse_args(argv)
    own = [f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"]
    app = create_app(default_roots(Path()), [*own, *args.allow_origin])
    uvicorn.run(app, host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
