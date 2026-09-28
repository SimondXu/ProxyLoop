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


WEB_SRC = REP_TEST.parent
# Every name that reads the principal's role card (S1-SYS-65, apps/web/src/liveApi.ts).
CARD = re.compile(
    r"\b(getCaseCard|getTaskCard|useRoleCard|YourRole|caseCard|taskCard)\b"
)


def test_the_rep_page_never_asks_for_the_principal_s_role_card() -> None:
    """I4: only the start page and the principal's live page (``Live``, whose
    ``Composer`` and ``Connection`` the rep page reuses; neither fetches)
    read the card; the rep page's own modules name no card route or reader.
    The rep e2e (``e2e-demo`` "human rep") checks its requests at run time."""
    callers = sorted(
        path.name
        for path in WEB_SRC.rglob("*.ts*")
        if not path.name.endswith(".test.ts") and CARD.search(path.read_text("utf-8"))
    )
    assert callers == ["Live.tsx", "StartPage.tsx", "YourRole.tsx", "liveApi.ts"]
    for name in ("RepPage.tsx", "rep.ts"):
        assert CARD.search((WEB_SRC / name).read_text("utf-8")) is None
