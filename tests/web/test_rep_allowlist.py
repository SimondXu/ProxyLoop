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


# S1-SYS-92 (root condition 1): the rep page's own sources, pinned. What it imports,
# name by name; its stream's frames reach the view only through rep.ts's repLine and
# callState; it posts only through postRep. A new import or name is an allow-list
# change and goes through the root.
REP_IMPORTS = {
    "react": {"useMemo", "useState"},
    "./Live": {"Composer", "Connection", "StreamAlert"},
    "./liveState": {"unechoed", "Sent"},
    "./liveApi": {"postRep", "Failed"},
    "./rep": {"callState", "parseRepFrame", "repLine", "RepLine"},
    "./ui/Chip": {"Chip"},
    "./ui/Icon": {"Icon"},
    "./useEventStream": {"useEventStream"},
}
REP_STYLES = {"./live/live.css", "./rep.css"}
# rep.test.ts's Proxy watch: the frame and payload keys repLine and callState may read.
REP_KEYS = {
    "REP_FRAME_KEYS": '["actor", "payload", "seq", "stream", "type"]',
    "OTHER_KEYS": '["lane"]',
}
REP_PAYLOAD = {
    "utt.delivered": ["interrupted", "lane", "text_heard"],
    "utt.final": ["lane", "speaker", "text"],
    "chan.opened": ["lane"],
    "chan.closed": ["lane"],
}


def test_the_rep_page_reads_only_its_allow_listed_sources() -> None:
    text = (WEB_SRC / "RepPage.tsx").read_text("utf-8")
    named = {
        m.group(2): {
            n.strip().removeprefix("type ").strip()
            for n in m.group(1).split(",")
            if n.strip()
        }
        for m in re.finditer(r'^import \{([^}]*)\} from "([^"]+)";', text, re.M)
    }
    styles = set(re.findall(r'^import "([^"]+)";', text, re.M))
    assert named == REP_IMPORTS
    assert styles == REP_STYLES
    assert len(re.findall(r"^import ", text, re.M)) == len(named) + len(styles)
    # Every use of the stream, outside comments, is one of these; nothing else names it
    # or its events (no destructuring, no alias, no spread).
    rest = re.sub(r"//[^\n]*", "", text)
    for allowed in (
        "const { stream, reconnect } = useEventStream(",
        "stream.events.map(repLine)",
        "callState(stream.events)",
        "[stream.events]",
        "stream.next",
        "stream={stream}",
    ):
        rest = rest.replace(allowed, "")
    assert re.search(r"\bstream\b", rest) is None
    assert re.search(r"\bevents\b", rest) is None
    assert re.search(r"<Connection[^>]*\bcount\b", text) is None  # no raw event count
    assert re.findall(r"\bpost\w*\(", text) == ["postRep("]


def test_the_rep_data_source_pin_is_not_loosened() -> None:
    text = REP_TEST.read_text("utf-8")
    for name, value in REP_KEYS.items():
        assert f"const {name} = {value};" in text
    block = re.search(
        r"const REP_PAYLOAD_KEYS: Record<string, string\[\]> = \{(.*?)\};", text, re.S
    )
    assert block is not None
    pinned = {
        m.group(1): re.findall(r'"([a-z_]+)"', m.group(2))
        for m in re.finditer(r'"([a-z_.]+)": \[([^\]]*)\]', block.group(1))
    }
    assert pinned == REP_PAYLOAD
