"""The replay e2e's roots (S1-SYS-30) through the real ``create_app``: the
bundle under test is listed and served; neither held-out decoy (split "test",
a path through evidence/s4/test) is listed or served (AGENTS rule 11)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.serve.client import client, get
from tests.web.wiring_server import FIXTURES, SEALED_PATH, SPLIT_TEST, replay_roots

FIXTURE = next(p for p in sorted(FIXTURES.iterdir()) if p.is_dir())


def listed(tmp: Path, bundles: Path) -> tuple[TestClient, list[str]]:
    http = client(*replay_roots(tmp, bundles))
    got = get(http, "/api/bundles")
    assert got.status_code == 200
    return http, [b["run_id"] for b in got.json()["bundles"]]


@pytest.mark.parametrize("bundles", [FIXTURES, FIXTURE], ids=["dir", "one"])
def test_the_bundle_is_listed_and_the_decoys_are_not(
    tmp_path: Path, bundles: Path
) -> None:
    http, runs = listed(tmp_path, bundles)
    assert runs == [FIXTURE.name]
    assert get(http, f"/api/replay/{FIXTURE.name}/events").status_code == 200
    for decoy in (SPLIT_TEST, SEALED_PATH):
        assert any(tmp_path.rglob(decoy)), decoy  # built, then refused
        assert get(http, f"/api/replay/{decoy}/events").status_code == 404


def test_a_sealed_bundle_dir_is_refused_before_any_copy(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="sealed"):
        replay_roots(tmp_path, tmp_path / "evidence" / "s4" / "test" / "x")
    assert not any(tmp_path.iterdir())


def test_a_bundle_of_symlinks_into_a_sealed_dir_is_refused_before_any_copy(
    tmp_path: Path,
) -> None:
    held_out = tmp_path / "data" / "evidence" / "s4" / "test" / "r1"
    held_out.mkdir(parents=True)
    lookalike = tmp_path / "data" / "lookalike"
    lookalike.mkdir()
    for name in ("events.jsonl", "manifest.json", "prompts.jsonl"):
        (held_out / name).write_text("held out\n")
        (lookalike / name).symlink_to(held_out / name)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(SystemExit, match="symlink"):
        replay_roots(out, lookalike)
    assert not any(out.iterdir())
