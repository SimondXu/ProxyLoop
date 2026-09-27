"""The chain re-parses a turn under the profile its ``fast.request`` names
(ADR-0017): ``pl_cp_v3``'s grammar for a v3 turn, the old one for v1/v2."""

from __future__ import annotations

import json
from pathlib import Path

from tests.support.recorded import write_fast_bundle

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.protocol import parse_turn
from proxyloop.evidence.check import check_path

# Speech, a hold, then a line v2 drops silently and v3 counts: no Speech
# differs, so the delivered lines are the same under both grammars.
RESPONSE = "Thanks, one moment.\n@hold offer\nTHEN:"


def _edit(run: Path, type_: str, **update: object) -> None:
    lines = (run / EVENTS).read_text("utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    for e in events:
        if e["type"] == type_:
            e["payload"] |= update
    (run / EVENTS).write_text("".join(json.dumps(e) + "\n" for e in events), "utf-8")


def test_the_grammars_differ_on_this_response() -> None:
    assert parse_turn(RESPONSE, "cp", "pl_cp_v2") != parse_turn(
        RESPONSE, "cp", "pl_cp_v3"
    )


def test_a_v2_turn_verifies_under_v2_and_not_under_v3(tmp_path: Path) -> None:
    run = write_fast_bundle(tmp_path / "run", RESPONSE)  # pl_cp_v2
    assert check_path(run).ok, check_path(run).failures
    _edit(run, "fast.request", profile="pl_cp_v3")
    failures = check_path(run).failures
    assert any(
        "items are not the parse of the recorded response" in f for f in failures
    )


def test_a_v3_turn_verifies_under_v3(tmp_path: Path) -> None:
    run = write_fast_bundle(tmp_path / "run", RESPONSE)
    v3 = parse_turn(RESPONSE, "cp", "pl_cp_v3")
    _edit(run, "fast.request", profile="pl_cp_v3")
    _edit(run, "fast.turn", items=[i.model_dump(mode="json") for i in v3])
    report = check_path(run)
    assert report.ok, report.failures


def test_an_unknown_or_other_lane_profile_is_a_failure(tmp_path: Path) -> None:
    run = write_fast_bundle(tmp_path / "run", RESPONSE)
    for profile in ("pl_cp_v9", "pl_user_v1"):
        _edit(run, "fast.request", profile=profile)
        failures = check_path(run).failures
        assert any(f"names profile '{profile}', no cp profile" in f for f in failures)
