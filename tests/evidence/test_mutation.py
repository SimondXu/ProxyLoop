"""Mutation tests (ARCHITECTURE §14): the delivered text follows the response bytes.

A recorded Fast response is replayed through the contract renderer and parser
into a bundle. Flipping one byte of the recorded response changes the parsed
items and the delivered text; a bundle whose ``prompts.jsonl`` disagrees with
its events fails the check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.recorded import (
    recorded_responses,
    replay_client,
    write_fast_bundle,
)

from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import EVENTS, PROMPTS, read_bundle
from proxyloop.contract.llm import AdapterKind
from proxyloop.evidence.check import check_path

RESPONSE = (
    "Thanks, that helps. Could you read the full offer back to me?\n"
    "@slow: fact offer_discount=20\n"
    "@hold offer"
)
SPOKEN = [i for i, ch in enumerate(RESPONSE.split("\n")[0]) if ch.isalpha()]


def _turn_items(run: Path) -> object:
    return next(
        e.payload["items"] for e in read_bundle(run).events if e.type == "fast.turn"
    )


def _delivered(run: Path) -> str:
    events = read_bundle(run).events
    return " ".join(
        str(e.payload["text_heard"]) for e in events if e.type == "utt.delivered"
    )


@pytest.fixture(scope="module")
def original(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_fast_bundle(tmp_path_factory.mktemp("orig") / "run", RESPONSE)


def test_the_recorded_response_replays(original: Path) -> None:
    client = replay_client(original, "fast_cp")
    assert client.ref.kind is AdapterKind.RECORDED_REPLAY
    assert recorded_responses(original, "fast_cp") == [RESPONSE]
    assert (
        _delivered(original)
        == "Thanks, that helps. Could you read the full offer back to me?"
    )


@pytest.mark.parametrize("position", SPOKEN)
def test_one_flipped_byte_changes_items_and_delivered_text(
    original: Path, tmp_path: Path, position: int
) -> None:
    raw = bytearray(recorded_responses(original, "fast_cp")[0].encode("utf-8"))
    raw[position] ^= 0x20  # swaps the case of one ASCII letter
    mutated = write_fast_bundle(tmp_path / "mutated", raw.decode("utf-8"))
    report = check_path(mutated)
    assert report.ok, report.failures  # a consistent bundle of other bytes
    assert _turn_items(mutated) != _turn_items(original)
    assert _delivered(mutated) != _delivered(original)


def _copy(run: Path, to: Path) -> Path:
    to.mkdir()
    for name in ("manifest.json", EVENTS, PROMPTS):
        (to / name).write_bytes((run / name).read_bytes())
    return to


def _flip_response(run: Path, fix_sha: bool) -> tuple[str, str]:
    """Flip one byte of the stored response; with ``fix_sha``, re-hash it."""

    records = [
        json.loads(line) for line in (run / PROMPTS).read_text("utf-8").splitlines()
    ]
    record = next(r for r in records if r["kind"] == "response")
    old = record["sha"]
    record["content"] = record["content"].replace("Thanks", "thanks", 1)
    if fix_sha:
        record["sha"] = sha256_text(record["content"])
    lines = "".join(json.dumps(r) + "\n" for r in records)
    (run / PROMPTS).write_text(lines, "utf-8")
    return old, record["sha"]


def test_prompts_disagreeing_with_the_events_fail_the_check(
    original: Path, tmp_path: Path
) -> None:
    tampered = _copy(original, tmp_path / "tampered")
    _flip_response(tampered, fix_sha=False)
    failures = check_path(tampered).failures
    assert any("does not hash to its sha" in f for f in failures)
    assert any("not the parse of the recorded response" in f for f in failures)


def test_a_rehashed_response_without_a_new_parse_fails(
    original: Path, tmp_path: Path
) -> None:
    """Even with the llm.call re-pointed at the new bytes, the stored items and
    the delivered text no longer follow from the response."""

    forged = _copy(original, tmp_path / "forged")
    old, new = _flip_response(forged, fix_sha=True)
    events = (forged / EVENTS).read_text("utf-8").replace(old, new)
    (forged / EVENTS).write_text(events, "utf-8")
    failures = check_path(forged).failures
    assert failures == (
        "fast.turn run-test:4: its items are not the parse of the recorded response",
    )
