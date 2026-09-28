"""The web↔API wiring server (S1-SYS-18): the real ``create_app`` serving the
built web same-origin on 127.0.0.1, over a tmp root of stub cases
(``tests.support.web_wiring``) and ``evidence/s0``, read only.

``uv run python -m tests.web.wiring_server [--port N]`` from the repo root; the
Playwright project "wiring" (``apps/web/playwright.wiring.config.ts``) starts
it. Every case in ``CASES`` is seeded at start, one per flow under test, so no
test changes another's case and the server needs no control route. The start
routes (``GET /start``, ``/api/models``, ``POST /api/cases``) run over a
``WiringStarter``, whose task picks the outcome; its real kernel's case lives
under the tmp ``runs`` root. Synthetic events go only under the tmp directory,
removed at exit.

``--replay`` (S1-SYS-30; ``apps/web/playwright.config.ts``) serves replay only,
without cases, over ``PL_BUNDLE_DIR`` (default ``tests/web/fixtures``) and two
held-out decoys that must never be listed (``replay_roots``). The real API's
default roots do not include the fixtures, hence this harness.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

import uvicorn
from fastapi import FastAPI
from tests.support.web_wiring import Mode, WiringCase, WiringStarter

from proxyloop.serve.api import HOST, create_app
from proxyloop.serve.bundles import sealed

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "evidence" / "s0"
WEB = REPO / "apps" / "web" / "dist"
FIXTURES = REPO / "tests" / "web" / "fixtures"  # PL_BUNDLE_DIR's default
SPLIT_TEST = "heldout-split-test"  # a fixture copy whose split is "test"
SEALED_PATH = "heldout-sealed-path"  # a fixture copy under .../evidence/s4/test
PORT = 4180
CASES: dict[str, Mode] = {
    "wire-approve": "ok",
    "wire-stale": "stale",
    "wire-refuse": "refuse",
    "wire-raise": "raise",
    "wire-chat": "ok",
    "wire-csrf": "ok",
    "wire-rep": "ok",
    "wire-authority": "authority",
}


def build(
    tmp: Path, origin: str, web_dir: Path | None = WEB
) -> tuple[FastAPI, dict[str, WiringCase], WiringStarter]:
    """The app, its seeded cases and its starter; ``origin`` is the one allowed
    browser origin."""
    root = tmp / "wiring"
    root.mkdir()
    cases = {
        case_id: WiringCase(root, case_id, mode) for case_id, mode in CASES.items()
    }
    runs = tmp / "runs"  # serve finds live cases only under a root named "runs"
    runs.mkdir()
    starter = WiringStarter(root, runs)
    roots = [root, runs, EVIDENCE]
    app = create_app(roots, [origin], cases=cases.get, web_dir=web_dir, start=starter)
    return app, cases, starter


def _copy(bundle: Path, dest: Path, split: str | None = None) -> None:
    """Copy one bundle; ``split`` rewrites session.started's and the manifest's
    (so the decoys copy file contents: a rewrite never writes through a link)."""
    shutil.copytree(bundle, dest)
    if split is None:
        return
    events = dest / "events.jsonl"
    first, rest = events.read_text().split("\n", 1)
    started = json.loads(first)
    started["payload"]["split"] = split
    events.write_text(json.dumps(started) + "\n" + rest)
    manifest = json.loads((dest / "manifest.json").read_text())
    manifest["split"] = split
    (dest / "manifest.json").write_text(json.dumps(manifest))


def replay_roots(tmp: Path, bundles: Path) -> list[Path]:
    """The replay e2e's roots: ``bundles``, then the decoys, all under ``tmp``
    except a directory of bundles, which is read in place. One bundle is copied
    so that it is the only run listed, and the page opens it. ``bundles`` must
    not be sealed, nor hold a symlink or anything that resolves to a sealed
    path: a copy would carry held-out bytes past the path barrier."""
    inside = [bundles, *bundles.rglob("*")] if bundles.is_dir() else [bundles]
    if any(p.is_symlink() or sealed(p) for p in inside):
        raise SystemExit(f"{bundles} is sealed or holds a symlink (AGENTS rule 11)")
    fixture = next(
        p for p in sorted(FIXTURES.iterdir()) if (p / "events.jsonl").is_file()
    )
    own, held_out = tmp / "replay", tmp / "evidence" / "s4" / "test"
    held_out.mkdir(parents=True)
    _copy(fixture, own / SPLIT_TEST, split="test")
    _copy(fixture, held_out / SEALED_PATH)
    if (bundles / "events.jsonl").is_file():
        shutil.copytree(bundles, own / bundles.name, symlinks=True)  # never follow
        return [own, held_out]
    return [bundles, own, held_out]


def _exit(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.web.wiring_server")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--replay", action="store_true", help="replay only")
    args = parser.parse_args(argv)
    port, origin = args.port, f"http://{HOST}:{args.port}"
    # uvicorn re-raises SIGTERM once it has shut down: exit through the finally
    # blocks, so the tmp directory is removed.
    signal.signal(signal.SIGTERM, _exit)
    with tempfile.TemporaryDirectory(prefix="pl-wiring-") as tmp:
        cases: dict[str, WiringCase] = {}
        started: list[WiringCase] = []  # the starter's own list: it grows
        if args.replay:
            bundles = REPO / os.environ.get("PL_BUNDLE_DIR", str(FIXTURES))
            app = create_app(replay_roots(Path(tmp), bundles), [origin], web_dir=WEB)
        else:
            app, cases, starter = build(Path(tmp), origin)
            started = starter.cases
        try:
            uvicorn.run(app, host=HOST, port=port)
        finally:
            for case in [*cases.values(), *started]:
                case.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
