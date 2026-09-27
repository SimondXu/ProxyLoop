"""A run whose split is ``test``, or not yet known, is never served, wherever it
lives (AGENTS rule 11): the second barrier next to ``sealed``. Fixtures are
rewritten copies of the fake-session bundle (only the split's JSON text)."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from tests.serve.client import client, frames, get
from tests.serve.conftest import Bundles

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS
from proxyloop.serve.api import _Reader  # pyright: ignore[reportPrivateUsage]

TRAIN, TEST = b'"split":"train"', b'"split":"test"'  # session.started (compact)
M_TRAIN, M_TEST = '"split": "train"', '"split": "test"'  # manifest (indented)


def _bundle(bundles: Bundles, root: Path) -> Path:
    run = root / bundles.plain
    shutil.copytree(bundles.root / bundles.plain, run)
    return run


def _rewrite(
    run: Path, *, manifest: str | None = None, started: bytes | None = None
) -> None:
    if manifest is not None:
        text = (run / MANIFEST).read_text()
        assert M_TRAIN in text
        (run / MANIFEST).write_text(text.replace(M_TRAIN, manifest))
    if started is not None:
        first, rest = (run / EVENTS).read_bytes().split(b"\n", 1)
        assert TRAIN in first
        (run / EVENTS).write_bytes(first.replace(TRAIN, started) + b"\n" + rest)


def _refused(bundles: Bundles, root: Path) -> None:
    """Not listed, every replay route 404, and /ws/live 4404 with no frame."""
    api, run_id = client(root), bundles.plain
    assert get(api, "/api/bundles").json() == {"bundles": []}
    line = (bundles.root / run_id / PROMPTS).read_bytes().splitlines()[0]
    sha = json.loads(line)["sha"]
    for route in ("manifest", "events", "prompts", f"prompts/{sha}"):
        assert get(api, f"/api/replay/{run_id}/{route}").status_code == 404, route
    assert frames(api, f"/ws/live/{run_id}") == ([], 4404)


def test_a_complete_test_split_run_is_refused(bundles: Bundles, tmp_path: Path) -> None:
    _rewrite(_bundle(bundles, tmp_path), manifest=M_TEST, started=TEST)
    _refused(bundles, tmp_path)


def test_a_live_test_split_run_is_refused(bundles: Bundles, tmp_path: Path) -> None:
    run = _bundle(bundles, tmp_path)
    (run / MANIFEST).unlink()
    (run / PROMPTS).unlink()
    _rewrite(run, started=TEST)
    _refused(bundles, tmp_path)


@pytest.mark.parametrize(
    ("manifest", "started"),
    [(M_TEST, None), (None, TEST), ("{", TEST)],
    ids=["manifest says test", "session.started says test", "broken manifest"],
)
def test_either_source_saying_test_refuses_the_run(
    bundles: Bundles, tmp_path: Path, manifest: str | None, started: bytes | None
) -> None:
    run = _bundle(bundles, tmp_path)
    if manifest == "{":
        (run / MANIFEST).write_text("{")
        manifest = None
    _rewrite(run, manifest=manifest, started=started)
    _refused(bundles, tmp_path)


def test_a_run_is_listed_only_once_its_split_is_known(
    bundles: Bundles, tmp_path: Path
) -> None:
    lines = (bundles.root / bundles.plain / EVENTS).read_bytes().splitlines()
    run = tmp_path / bundles.plain
    run.mkdir()
    (run / EVENTS).write_bytes(b"")
    _refused(bundles, tmp_path)
    (run / EVENTS).write_bytes(lines[1] + b"\n")  # not session.started: unknown
    _refused(bundles, tmp_path)
    (run / EVENTS).write_bytes(lines[0][:40])  # a partial first line
    _refused(bundles, tmp_path)
    (run / EVENTS).write_bytes(lines[0] + b"\n")
    listed = get(client(tmp_path), "/api/bundles").json()["bundles"]
    assert [b["run_id"] for b in listed] == [bundles.plain]


def test_the_tail_never_sends_a_test_split_run(bundles: Bundles) -> None:
    # Even if the file changed after the check: seq 0 itself closes 4404.
    first = (bundles.root / bundles.plain / EVENTS).read_bytes().splitlines()[0]
    log = io.BytesIO(first.replace(TRAIN, TEST) + b"\n")
    assert _Reader(log, bundles.plain, 0).step() == ([], (4404, "unknown run"), False)
