"""The web↔API wiring server (S1-SYS-18): the real ``create_app`` serving the
built web same-origin on 127.0.0.1, over a tmp root of stub cases
(``tests.support.web_wiring``) and ``evidence/s0``, read only.

``uv run python -m tests.web.wiring_server [--port N]`` from the repo root; the
Playwright project "wiring" (``apps/web/playwright.wiring.config.ts``) starts
it. Every case in ``CASES`` is seeded at start, one per flow under test, so no
test changes another's case and the server needs no control route. Synthetic
events go only under the tmp directory, removed at exit.
"""

from __future__ import annotations

import argparse
import signal
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI
from tests.support.web_wiring import Mode, WiringCase

from proxyloop.serve.api import HOST, create_app

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "evidence" / "s0"
WEB = REPO / "apps" / "web" / "dist"
PORT = 4180
CASES: dict[str, Mode] = {
    "wire-approve": "ok",
    "wire-stale": "stale",
    "wire-refuse": "refuse",
    "wire-raise": "raise",
    "wire-chat": "ok",
    "wire-rep": "ok",
}


def build(
    tmp: Path, origin: str, web_dir: Path | None = WEB
) -> tuple[FastAPI, dict[str, WiringCase]]:
    """The app and its seeded cases; ``origin`` is the one allowed browser origin."""
    root = tmp / "wiring"
    root.mkdir()
    cases = {
        case_id: WiringCase(root, case_id, mode) for case_id, mode in CASES.items()
    }
    app = create_app([root, EVIDENCE], [origin], cases=cases.get, web_dir=web_dir)
    return app, cases


def _exit(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.web.wiring_server")
    parser.add_argument("--port", type=int, default=PORT)
    port = parser.parse_args(argv).port
    # uvicorn re-raises SIGTERM once it has shut down: exit through the finally
    # blocks, so the tmp directory is removed.
    signal.signal(signal.SIGTERM, _exit)
    with tempfile.TemporaryDirectory(prefix="pl-wiring-") as tmp:
        app, cases = build(Path(tmp), f"http://{HOST}:{port}")
        try:
            uvicorn.run(app, host=HOST, port=port)
        finally:
            for case in cases.values():
                case.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
