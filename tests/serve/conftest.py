"""Fixture bundles for the API: real ``run_session`` runs on fakes (one plain,
one whose user mentions a relay URL), made once per test session."""

from __future__ import annotations

import faulthandler
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.support.sessions import act, ear, reply, run

URL = "https://relay.example/v1"
SCRIPTS = {
    "simuser": [reply("Please get me a lower price. I am Dana Reyes.")],
    "fast_user": ["Sure, I will call them now."],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": ["Okay."],
    "fast_cp": ["Could you lower the monthly price?\n@slow: fact monthly_price=75.00"],
    "slow": [
        act("The user wants a lower price.", {"tool": "tell_user", "text": "Calling."}),
        act("Waiting for the call.", {"tool": "wait", "seconds": 5}),
    ],
}
FINISH = act("Done.", {"tool": "finish", "outcome": "info_only", "summary": "ok"})
UNTIL = {"slow": ("] cp_update", FINISH)}  # Slow ends once the call relayed


@dataclass(frozen=True)
class Bundles:
    root: Path  # the "runs" root holding both
    plain: str  # run_id of a bundle without any URL
    url: str  # run_id of a bundle whose events and prompts carry URL


@pytest.fixture(scope="session")
def bundles(tmp_path_factory: pytest.TempPathFactory) -> Bundles:
    root = tmp_path_factory.mktemp("fixtures") / "runs"
    root.mkdir()
    plain = run(root, SCRIPTS, until=UNTIL)
    said = reply(f"My bill is at {URL}. Please get me a lower price.")
    url = run(root, SCRIPTS | {"simuser": [said]}, until=UNTIL)
    assert plain.reason == url.reason == "info_only"
    return Bundles(root, plain.run_id, url.run_id)


@pytest.fixture(autouse=True)
def no_hang() -> Iterator[None]:
    """A stream that never closes would block its test forever: after 20 s the
    run dies with every thread's traceback instead."""
    faulthandler.dump_traceback_later(20, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()
