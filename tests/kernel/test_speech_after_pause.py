"""ADR-0017 on the product path: FastC's garbage after ``@hold`` is a counted
``speech_after_pause`` issue in the kernel's ``fast.turn`` and is never voiced,
and the bundle verifies (the chain re-parses under the request's profile)."""

from __future__ import annotations

from pathlib import Path

from tests.kernel.test_session import FINISH, SCRIPTS
from tests.support.sessions import only_bundle, run

from proxyloop.evidence.check import check_path
from proxyloop.kernel.lanes import PROFILE

GARBAGE = "}} garbage"
FAST_CP = f"Ok.\n@hold offer\n{GARBAGE}"
UNTIL = {"slow": ("] hold ", FINISH)}  # Slow ends once the hold relayed


def test_garbage_after_a_hold_is_an_issue_and_never_heard(tmp_path: Path) -> None:
    assert PROFILE["cp"] == "pl_cp_v3"
    result = run(tmp_path, SCRIPTS | {"fast_cp": [FAST_CP]}, until=UNTIL)
    events = only_bundle(tmp_path).events
    turns = [e for e in events if e.type == "fast.turn" and e.payload["lane"] == "cp"]
    assert turns
    for turn in turns:
        assert turn.payload["items"] == [
            {"kind": "speech", "text": "Ok."},
            {"kind": "hold", "reason": "offer"},
            {"kind": "issue", "reason": "speech_after_pause", "text": GARBAGE},
        ]
    spoken = [
        str(e.payload.get(k))
        for e in events
        if e.type in ("fast.sentence", "utt.delivered")
        for k in ("text", "text_generated", "text_heard")
    ]
    assert "Ok." in spoken and not any("garbage" in s or "}}" in s for s in spoken)
    report = check_path(result.path, "offline")
    assert report.ok, report.failures
