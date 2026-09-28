"""S1-SYS-74: Slow's playbook identifies before the rep asks (T5), and the
status bar's identify line (the identify's delivery, from Slow's own GUIDEs
and their fates: state, never transcript text). Generic wording only: no
world terms (rule 12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.slow import prompt, state

# the world's rep policy and the S0 family: none may reach Slow's words
WORLD = (
    *("GREET", "IDENTIFY", "DISCOVER", "provide_fact", "ask_identity"),
    *("how_can_help", "refuse_fact", "identity strike", "patience"),
    *("Northwind", "Dana", "Reyes", "4821"),
)
REACTIVE = "In the call, when the representative asks for a public fact, guide_fast"


@pytest.mark.parametrize("mode", list(SlowViewMode), ids=str)
def test_t5_the_playbook_identifies_first_without_being_asked(
    mode: SlowViewMode,
) -> None:
    system = prompt.system(mode)
    flat = " ".join(system.split())
    assert REACTIVE not in flat  # the reactive-only rule is gone
    rule = flat[flat.index("Once the call is open") :]
    first = 'your first phone action is guide_fast(identify, slots=["fact:<key>"'
    assert first in rule and "without waiting to be asked" in rule
    before = rule[: rule.index("For a fact the representative asks for")]
    assert "until the representative has verified the account" in before
    assert "no open_call, no lever, no offer request" in before
    assert "identify line" in before  # once: the status bar says it was sent
    # D1: with no readiness fact public, no identify: hold when asked
    none = "If no readiness fact is public, send no identify: when the representative"
    assert none in before
    hold = "asks for one, ask_user for it (with keys) and guide_fast(hold_for_fact)."
    assert f"{none} {hold}" in before
    # D3: a fact said to be wrong is corrected before identifying again
    wrong = "for a fact the representative says is wrong, ask_user for the correct"
    assert f"{wrong} value, record_fact it, then identify again" in before
    assert "or says one is wrong" not in flat
    # kept: a missing fact is asked and held for; deflect only what must not go
    assert "ask_user for it (with keys) and guide_fast(hold_for_fact)" in rule
    assert "Use deflect_fact_request only for a fact that must not be given" in rule


def test_t5_no_world_terms_in_what_slow_reads() -> None:
    texts = [*prompt.PLAYBOOK.values(), *(prompt.system(m) for m in SlowViewMode)]
    texts += [x for s in state.LIVE if (x := state.identify_line(s))]
    assert len(texts) == len(prompt.PLAYBOOK) + len(SlowViewMode) + 3
    for text in texts:
        assert not [w for w in WORLD if w in text], text


def test_the_identify_line_shows_the_identify_s_delivery() -> None:
    assert state.identify_line(None) is None  # not sent: the playbook's first act
    assert state.identify_line("failed") is None  # never heard: as not sent
    waiting = state.identify_line("waiting")
    assert waiting == "identify: sent, not heard yet (wait; do not send it again)"
    heard, answered = state.identify_line("heard"), state.identify_line("answered")
    assert heard is not None and heard.startswith("identify: heard by the rep")
    assert answered is not None and answered.startswith("identify: heard by the rep")


IDENTIFY = {"tool": "guide_fast", "move": "identify", "slots": ["fact:account.last4"]}


def test_the_identify_line_follows_the_newest_identify_sent(tmp_path: Path) -> None:
    """D2: once one identify was answered, a second one on its way shows as
    on its way (wait; do not send it again), not as the first one's answer."""
    h = Host(tmp_path)
    said = h.emit("user.msg", "kernel", {"text": "My last 4 are 4821."})
    record = {"tool": "record_fact", "key": "account.last4", "value": "4821"}
    h.act(record | {"utt_ref": said.event_id})
    h.call()
    h.act(IDENTIFY)
    h.voice()  # heard whole
    h.rep("cp-1", "Thanks, one moment.")
    first = state.bar(h.bb, "full", h.tools)
    assert first.identify == "answered"
    assert "identify: heard by the rep, who has answered since" in first.lines()
    (again,) = h.act(IDENTIFY)
    assert "sent" in again  # queued, not voiced yet
    second = state.bar(h.bb, "full", h.tools)
    assert second.identify == "waiting"
    line = "identify: sent, not heard yet (wait; do not send it again)"
    assert line in second.lines()
