"""Bundle listing, replay and the live event stream (ARCHITECTURE §2, §14).

Every body is a bundle file's bytes with one transformation,
``serve.bundles.redact`` (AGENTS rule 15): each http(s) URL becomes
``<redacted-url>`` and each bare credential (an ``sk-`` token, a ``key=``,
``token=`` or ``secret=`` value) ``<redacted>``, in replay bodies and WebSocket
frames alike, so a body without either is byte-equal to its file. ``serve``
only reads: it never writes, folds or renders a prompt (import-linter: "serve
is read-only"). Which bundles exist and may be served, held-out data
excluded, is ``serve.bundles``.

Every route checks the Host (127.0.0.1 or localhost, else 400) and, when a
browser sends one, the Origin against a fixed list (else 403
``{"error": "origin"}``, or a WebSocket closed before accept with 4403); every
POST and /ws/rep must send an Origin. It adds no CORS headers. Live cases
(``serve.cases``, ``serve.rep``) are served only when ``create_app`` gets a
``cases`` lookup or a ``start`` (``serve.start``: the cases it started are
looked up first); a built web (``web_dir``) is mounted at "/" after every API
route.

``python -m proxyloop.serve.api [--port N] [--allow-origin URL]...
[--web-dir PATH]`` serves ``runs/`` and each stage directory
``evidence/<stage>/`` (relative to the cwd, listed at startup) on 127.0.0.1
only, without live cases.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi import Path as Param
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, PromptRecord
from proxyloop.serve.bundles import (
    RUN_ID,
    Run,
    default_roots,
    find_run,
    list_runs,
    redact,
)
from proxyloop.serve.cases import Case, Cases, Starter, add_case_routes
from proxyloop.serve.csrf import Csrf
from proxyloop.serve.rep import add_rep_route
from proxyloop.serve.start import add_start_routes
from proxyloop.serve.stream import follow

HOST = "127.0.0.1"  # hard-coded: no flag widens it (§9.6)
HOSTS = ["127.0.0.1", "localhost"]  # accepted Host headers (DNS rebinding)
LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost):[0-9]{1,5}")
SAFE = ("GET", "HEAD")  # methods that may come without an Origin
SHA = r"^[0-9a-f]{64}$"
JSON, NDJSON = "application/json", "application/x-ndjson"
RunId = Annotated[str, Param(pattern=RUN_ID)]
Sha = Annotated[str, Param(pattern=SHA)]


class _Origins:
    """A present Origin must be in the fixed list: never derived from Host. A
    POST (any method but GET and HEAD) and /ws/rep must send one."""

    def __init__(self, app: ASGIApp, origins: Sequence[str]) -> None:
        self.app, self.origins = app, frozenset(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "lifespan":
            await self.app(scope, receive, send)
            return
        origin = Headers(scope=scope).get("origin")
        needed = (kind == "http" and scope["method"] not in SAFE) or (
            kind == "websocket" and scope["path"].startswith("/ws/rep/")
        )
        if origin in self.origins or (origin is None and not needed):
            await self.app(scope, receive, send)
        elif kind == "websocket":  # before accept: the handshake is refused
            await WebSocketClose(4403, "origin not allowed")(scope, receive, send)
        else:
            await JSONResponse({"error": "origin"}, 403)(scope, receive, send)


def task_ref(run: Run) -> str | None:
    """The manifest's task_ref: a run is complete once its manifest has one."""
    ref = manifest.get("task_ref") if (manifest := run.manifest()) else None
    return ref if isinstance(ref, str) else None


def create_app(
    roots: Sequence[Path],
    origins: Sequence[str] = (),
    *,
    cases: Cases | None = None,
    web_dir: Path | None = None,
    start: Starter | None = None,
    start_timeout_s: float = 60.0,
) -> FastAPI:
    """The API over bundles under ``roots`` (listed again on every request);
    ``origins`` is the fixed list of browser origins allowed in; ``cases``
    finds a live case by id (None: replay only); ``web_dir`` is a built web;
    ``start`` starts live cases (None: no start routes), each bounded by
    ``start_timeout_s`` (``serve.start``)."""
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
            ref = redact(ref.encode()).decode() if ref else ref
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
        await follow(ws, path, run_id, from_seq)

    csrf = Csrf()
    started = add_start_routes(app, roots, start, csrf, start_timeout_s)

    def lookup(case_id: str) -> Case | None:
        found = started(case_id)
        return found if found is not None or cases is None else cases(case_id)

    any_case = lookup if cases is not None or start is not None else None
    add_case_routes(app, roots, any_case, csrf)
    add_rep_route(app, roots, any_case, csrf)
    if web_dir is not None:  # last: every API route matches first
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


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
    parser.add_argument("--web-dir", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    own = [f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"]
    origins = [*own, *args.allow_origin]
    app = create_app(default_roots(Path()), origins, web_dir=args.web_dir)
    uvicorn.run(app, host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
