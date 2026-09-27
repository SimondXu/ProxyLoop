"""The rep page's allow-list test (I4) feeds every event type: its list in
``apps/web/src/rep.test.ts`` must equal the contract registry, so a new event
type cannot reach the human rep untested."""

from __future__ import annotations

import re
from pathlib import Path

from proxyloop.contract.events import EVENT_TYPES

REP_TEST = Path(__file__).parents[2] / "apps" / "web" / "src" / "rep.test.ts"


def test_the_rep_allowlist_test_covers_every_registered_event_type() -> None:
    text = REP_TEST.read_text("utf-8")
    block = re.search(r"const ALL_TYPES = \[(.*?)\];", text, re.S)
    assert block is not None
    listed = re.findall(r'"([a-z_.0-9]+)"', block.group(1))
    assert len(listed) == len(set(listed))
    assert sorted(listed) == sorted(EVENT_TYPES)
