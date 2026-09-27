"""Bundle listing, replay and the live event stream (ARCHITECTURE §2, §14).

Every body is a bundle file's bytes with one transformation: each http(s) URL
becomes ``<redacted-url>`` (AGENTS rule 15), so a body without a URL is
byte-equal to its file. ``serve`` only reads: it never writes, folds or renders
a prompt (import-linter: "serve is read-only"). A run is found only through the
roots' listing, never by joining user input onto a path. Held-out data
(``evidence/s4/test``, AGENTS rule 11) is refused at every step: roots, run
directories and files.

``python -m proxyloop.serve.api [--port N]`` serves ``runs/`` and each stage
directory ``evidence/<stage>/`` (relative to the cwd, listed at startup) on
127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import Path as Param
from fastapi.responses import Response
from pydantic import ValidationError

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, PromptRecord
from proxyloop.contract.events import Event

HOST = "127.0.0.1"  # hard-coded: no flag widens it (§9.6)
POLL_S = 0.05  # how often /ws/live looks for new lines
URL = re.compile(rb"""https?://[^\s"'\\<>]+""", re.IGNORECASE)
REDACTED = b"<redacted-url>"
RUN_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
SHA = r"^[0-9a-f]{64}$"
JSON, NDJSON = "application/json", "application/x-ndjson"
RunId = Annotated[str, Param(pattern=RUN_ID)]
Sha = Annotated[str, Param(pattern=SHA)]
Close = tuple[int, str]  # a WebSocket close code and reason
SEALED = ("evidence", "s4", "test")  # held-out bundles, sealed until the report


def sealed(path: Path) -> bool:
    """True if the resolved path runs through ``evidence/s4/test`` (compared
    case-insensitively). It only resolves the path: it never opens a file."""
    parts, n = [part.lower() for part in path.resolve().parts], len(SEALED)
    return any(tuple(parts[i : i + n]) == SEALED for i in range(len(parts) - n + 1))


def redact(data: bytes) -> bytes:
    """Replace URLs; quotes and backslashes end a match, so JSON stays JSON."""
    return URL.sub(REDACTED, data)


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    root: Path
    path: Path

    def file(self, name: str) -> Path | None:
        """The bundle file, if it exists, resolves inside the run's root and is
        not sealed."""
        path = self.path / name
        if sealed(self.path) or sealed(path):
            return None
        inside = path.resolve().is_relative_to(self.root.resolve())
        return path if inside and path.is_file() else None


def list_runs(roots: Sequence[Path]) -> dict[str, Run]:
    """Directories directly under a root holding ``events.jsonl``, by run_id.

    If one run_id exists under two roots, the first configured root wins.
    """
    runs: dict[str, Run] = {}
    for root in roots:
        if sealed(root) or not root.is_dir():
            continue
        for child in root.iterdir():
            run = Run(child.name, root, child)
            if child.name in runs or not re.fullmatch(RUN_ID, child.name):
                continue
            if sealed(child):  # before anything inside it is touched
                continue
            if run.file(EVENTS) is not None:
                runs[child.name] = run
    return runs


def default_roots(base: Path) -> list[Path]:
    """``base/runs`` and each directory ``base/evidence/<stage>``."""
    evidence = base / "evidence"
    stages = [p for p in evidence.iterdir() if p.is_dir()] if evidence.is_dir() else []
    return [base / "runs", *sorted(stages)]


def create_app(roots: Sequence[Path]) -> FastAPI:
    """The API over bundles under ``roots`` (listed again on every request)."""
    roots = tuple(roots)
    app = FastAPI(title="ProxyLoop replay")

    def find(run_id: str) -> Run:
        if (run := list_runs(roots).get(run_id)) is None:
            raise HTTPException(404, "unknown run")
        return run

    def read(run_id: str, name: str) -> bytes:
        if (path := find(run_id).file(name)) is None:
            raise HTTPException(404, f"no {name}")
        return path.read_bytes()

    @app.get("/api/bundles")
    def bundles() -> dict[str, list[dict[str, object]]]:
        listed: list[dict[str, object]] = []
        for run_id, run in sorted(list_runs(roots).items(), reverse=True):
            manifest = run.file(MANIFEST)
            ref = json.loads(manifest.read_bytes())["task_ref"] if manifest else None
            root, done = run.root.resolve().name, manifest is not None
            listed.append(
                {"run_id": run_id, "root": root, "complete": done, "task_ref": ref}
            )
        return {"bundles": listed}

    @app.get("/api/replay/{run_id}/manifest")
    def manifest(run_id: RunId) -> Response:
        return Response(redact(read(run_id, MANIFEST)), media_type=JSON)

    @app.get("/api/replay/{run_id}/events")
    def events(run_id: RunId) -> Response:
        return Response(redact(read(run_id, EVENTS)), media_type=NDJSON)

    @app.get("/api/replay/{run_id}/prompts")
    def prompts(run_id: RunId) -> Response:
        return Response(redact(read(run_id, PROMPTS)), media_type=NDJSON)

    @app.get("/api/replay/{run_id}/prompts/{sha}")
    def prompt(run_id: RunId, sha: Sha) -> Response:
        for line in read(run_id, PROMPTS).split(b"\n"):
            if line.strip() and PromptRecord.model_validate_json(line).sha == sha:
                return Response(redact(line), media_type=JSON)
        raise HTTPException(404, "unknown prompt sha")

    @app.websocket("/ws/live/{run_id}")
    async def live(
        ws: WebSocket, run_id: str, from_seq: Annotated[int, Query(ge=0)] = 0
    ) -> None:
        await ws.accept()  # first, so that the client sees the close code
        run = list_runs(roots).get(run_id)
        if run is None or (path := run.file(EVENTS)) is None:
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
        close = tail.result() if tail in done else None  # re-raises a real error
        if close is not None and gone not in done:
            await ws.close(*close)

    return app


async def _gone(ws: WebSocket) -> None:
    """Return when the client disconnects; frames it sends are ignored."""
    while (await ws.receive())["type"] != "websocket.disconnect":
        pass


async def _tail(ws: WebSocket, path: Path, run_id: str, from_seq: int) -> Close | None:
    """Send each stored line from ``from_seq`` in dense seq order, following the
    file by polling; only complete lines count. None: the client left."""
    seq, pending = 0, b""
    with path.open("rb") as f:
        while True:
            if not (chunk := f.read()):
                await asyncio.sleep(POLL_S)
                continue
            *lines, pending = (pending + chunk).split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = Event.model_validate_json(line)
                except ValidationError:
                    return 1011, f"invalid event line after seq {seq - 1}"
                if event.run_id != run_id or event.seq != seq:
                    return 1011, f"seq {event.seq} of {event.run_id}, {seq} expected"
                seq += 1
                if event.seq >= from_seq:
                    try:
                        await ws.send_text(redact(line).decode("utf-8"))
                    except WebSocketDisconnect:
                        return None
                if event.type == "session.ended":
                    return 1000, "session ended"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.serve.api")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    app = create_app(default_roots(Path()))
    uvicorn.run(app, host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
