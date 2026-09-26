"""The web replay fixture is a real ``run_session`` bundle on ``test_fake``
clients: it regenerates, it reads, and it holds every lane the viewer shows."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from tests.web.make_fixture import FIXTURES, generate

from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.llm import AdapterKind

MAX_BYTES = 200_000


def _kinds(bundle: Bundle) -> Counter[str]:
    kinds = Counter[str]()
    for e in bundle.events:
        p = e.payload
        if e.type in {"fast.sentence", "utt.delivered"}:
            kinds[f"{e.type}:{p['lane']}"] += 1
        elif e.type == "utt.final":
            kinds[f"utt.final:{p['speaker']}"] += 1
        kinds[e.type] += 1
        kinds[f"actor:{e.actor}"] += 1
        kinds[f"stream:{e.stream}"] += 1
    return kinds


def _assert_viewable(bundle: Bundle) -> None:
    kinds = _kinds(bundle)
    wanted = [
        "user.msg",
        "fast.sentence:user",
        "fast.sentence:cp",
        "utt.delivered:user",
        "utt.delivered:cp",
        "utt.final:partner",
        "f2s.msg",
        "slow.tool",
        "llm.call",
        "actor:guard",
        "stream:world",
    ]
    assert [k for k in wanted if not kinds[k]] == []
    assert set(bundle.manifest.reality.values()) == {AdapterKind.TEST_FAKE}
    for e in bundle.events:
        for key in ("prompt_sha", "response_sha"):
            sha = e.payload.get(key)
            if e.type == "llm.call" and sha:
                assert sha in bundle.prompts, (e.event_id, key)


def test_the_fixture_regenerates_and_reads(tmp_path: Path) -> None:
    _assert_viewable(read_bundle(generate(tmp_path)))


def test_the_committed_fixture_reads_and_stays_small_and_synthetic() -> None:
    (run_dir,) = [p for p in FIXTURES.iterdir() if p.is_dir()]
    bundle = read_bundle(run_dir)
    assert bundle.manifest.run_id == run_dir.name
    _assert_viewable(bundle)
    files = list(run_dir.iterdir())
    assert sum(f.stat().st_size for f in files) < MAX_BYTES
    for f in files:  # no endpoint, and no path from the machine that made it
        text = f.read_text("utf-8")
        assert not [s for s in ("http://", "https://", "/Users/", "/tmp/") if s in text]
