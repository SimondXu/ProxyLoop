"""The keys-free demo servers (S1-SYS-32): for each port, the real
``create_app`` serving the built web same-origin on 127.0.0.1 over its own tmp
``runs`` root, with its own ``tests.support.web_demo.DemoStarter`` (one live
case per server, as the real one). Nothing is mocked in the browser.

``uv run python -m tests.web.demo_server --port 4190 --port 4191`` from the repo
root; the Playwright project "demo" (``apps/web/playwright.demo.config.ts``)
starts one port per scenario, so no scenario waits for another's case to end.
``--speed`` runs the session clock that many times faster than the wall (a test
clock, tests/support). On SIGTERM each live run is stopped (its bundle closes
``stopped``) and the tmp root is removed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import tempfile
from collections.abc import Generator, Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from tests.support.manual_clock import ScaledClock
from tests.support.web_demo import DemoStarter

from proxyloop.serve.api import HOST, create_app

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "apps" / "web" / "dist"


def build(
    tmp: Path, port: int, speed: float, web_dir: Path | None = WEB
) -> tuple[FastAPI, DemoStarter]:
    """One server's app and starter, over ``tmp/<port>/runs``."""
    runs = tmp / str(port) / "runs"
    runs.mkdir(parents=True)
    clock = ScaledClock(speed)
    starter = DemoStarter(runs, clock=clock, sleep=clock.sleep)
    origin = f"http://{HOST}:{port}"
    return create_app([runs], [origin], web_dir=web_dir, start=starter), starter


@contextlib.contextmanager
def _no_capture() -> Generator[None]:  # the process's handler stops every server
    yield


async def serve(tmp: Path, ports: Sequence[int], speed: float) -> None:
    servers: list[uvicorn.Server] = []
    starters: list[DemoStarter] = []
    for port in ports:
        app, starter = build(tmp, port, speed)
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port))
        server.capture_signals = _no_capture  # type: ignore[method-assign]
        servers.append(server)
        starters.append(starter)

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop)
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        for starter in starters:
            await starter.stop()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.web.demo_server")
    parser.add_argument("--port", type=int, action="append", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="pl-demo-") as tmp:
        asyncio.run(serve(Path(tmp), args.port, args.speed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
