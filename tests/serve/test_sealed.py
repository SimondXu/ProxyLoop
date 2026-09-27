"""Held-out bundles under ``evidence/s4/test`` are refused everywhere and never
opened (AGENTS rule 11), whichever root leads to them."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from tests.serve.client import client, frames, get
from tests.serve.conftest import Bundles

from proxyloop.contract.bundle import PROMPTS
from proxyloop.serve.api import default_roots, sealed

_touched: list[str] = []  # paths opened or listed inside the sealed dir
_watch: list[str] = []  # the sealed dir and its alias while a test runs


def _audit(event: str, args: tuple[object, ...]) -> None:
    if _watch and event in ("open", "os.scandir", "os.listdir") and args:
        path = args[0]
        if isinstance(path, str | Path) and str(path).startswith(tuple(_watch)):
            _touched.append(f"{event} {path}")


sys.addaudithook(_audit)  # process-wide and permanent; inert unless _watch is set

Roots = Callable[[Path], list[Path]]
ROOTS: dict[str, Roots] = {
    "the sealed dir": lambda base: [base / "evidence" / "s4" / "test"],
    "its stage": lambda base: [base / "evidence" / "s4"],
    "main's roots": default_roots,
    "a link to it": lambda base: [base / "alias"],
}


@pytest.fixture
def held_out(bundles: Bundles, tmp_path: Path) -> Iterator[Path]:
    """A complete bundle at evidence/s4/test/<run>, unreadable (chmod 000), and
    an open stage bundle at evidence/s0/<run>."""
    run = tmp_path / "evidence" / "s4" / "test" / bundles.plain
    shutil.copytree(bundles.root / bundles.plain, run)
    shutil.copytree(
        bundles.root / bundles.url, tmp_path / "evidence" / "s0" / bundles.url
    )
    (tmp_path / "alias").symlink_to(run.parent, target_is_directory=True)
    locked = [*run.iterdir(), run]
    for path in locked:
        path.chmod(0)
    _watch.extend([str(run.parent.resolve()), str(tmp_path / "alias")])
    try:
        yield tmp_path
    finally:
        _watch.clear()
        for path in reversed(locked):  # the directory first, then its files
            path.chmod(0o700)


@pytest.mark.parametrize("roots", ROOTS.values(), ids=ROOTS.keys())
def test_a_held_out_bundle_is_never_served_nor_opened(
    bundles: Bundles, held_out: Path, roots: Roots
) -> None:
    _touched.clear()
    api, run_id = client(*roots(held_out)), bundles.plain
    listed = [b["run_id"] for b in get(api, "/api/bundles").json()["bundles"]]
    assert run_id not in listed
    if roots is default_roots:
        assert listed == [bundles.url]  # the open stage is served
    line = (bundles.root / run_id / PROMPTS).read_bytes().splitlines()[0]
    sha = json.loads(line)["sha"]
    for route in ("manifest", "events", "prompts", f"prompts/{sha}"):
        assert get(api, f"/api/replay/{run_id}/{route}").status_code == 404, route
    assert frames(api, f"/ws/live/{run_id}") == ([], 4404)
    assert _touched == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("evidence/s4/test", True),
        ("evidence/s4/test/run-1/events.jsonl", True),
        ("x/Evidence/S4/Test/run-1", True),
        ("evidence/s4/dev/run-1", False),
        ("evidence/s4test/run-1", False),
        ("evidence/s4", False),
        ("test/s4/evidence", False),
    ],
)
def test_sealed_matches_the_consecutive_parts(
    tmp_path: Path, path: str, expected: bool
) -> None:
    assert sealed(tmp_path / path) is expected  # nothing needs to exist
