"""S1-SYS-73: the rep's wording fits the moment. An identity strike-out says
its own line (not the timer's "I cannot hear you"), the confirmed line voices
the confirmation number once, and every other template is unchanged."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from tests.env.bus_sink import BusSink

from proxyloop.env.counterparty.mouth import fidelity_ok, template
from proxyloop.env.counterparty.policy import PublicIntent
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.loader import load_task

TASK = load_task("cp-direct-discount")
CP = TASK.counterparty
IDENTITY_LINE = (
    "I'm unable to verify the account, so I'll have to end the call. Goodbye."
)
SILENCE_LINE = "I cannot hear you, so I am ending the call. Goodbye."


def _cls(act: str) -> str:
    call = {
        "call_id": "t",
        "name": "classify",
        "arguments": json.dumps({"acts": [{"act": act}]}),
    }
    return json.dumps({"text": "", "tool_calls": [call]})


def _voiced_as_template(sink: BusSink) -> Any:
    """A Mouth whose model never passes the check: every line is its template."""
    return sink.llm(*[""] * 60)


def test_t1_an_identity_strike_out_says_its_own_line(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    ear = [_cls("smalltalk")] + [_cls("refuse_fact")] * 3
    rep = SimRep(TASK, sink.llm(*ear), _voiced_as_template(sink), sink.world)
    turns: list[RepTurn] = []
    for i, text in enumerate(["Hi there.", "No.", "No.", "Still no."]):
        heard = sink.heard(text)
        utt_id = str(heard.payload["utt_id"])
        turns.append(
            asyncio.run(rep.on_agent_utterance(utt_id, text, heard.event_id, i * 100))
        )
    assert [(t.strikes, t.end) for t in turns] == [
        (0, ""),
        (1, ""),
        (1, ""),
        (1, "hangup"),  # the kernel's ABANDONED path, as before
    ]
    assert turns[-1].lines[0][0] == IDENTITY_LINE
    p = rep.policy
    assert (p.state, p.identity_strikes, p.timer_strikes) == ("ENDED", 3, 0)
    last = sink.of("rep.policy")[-1]
    assert (last.payload["from"], last.payload["to"]) == ("IDENTIFY", "ENDED")
    assert last.payload["intent"] == {
        "kind": "hang_up",
        "offer_ref": None,
        "say": [],
        "ask": [],
        "reason": "identity",
    }


def test_t2_a_silence_strike_out_keeps_the_old_line(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    rep = SimRep(TASK, sink.llm(), _voiced_as_template(sink), sink.world)
    silence = int(CP.patience.silence_s * 1000)
    turns: list[RepTurn] = []
    for n in range(1, CP.patience.strikes + 1):
        rep.floor(True, (n - 1) * 10 * silence)
        turns.append(asyncio.run(rep.tick((n - 1) * 10 * silence + silence)))
    assert [(t.strikes, t.end) for t in turns[:-1]] == [(1, "")] * 2
    assert (turns[-1].strikes, turns[-1].end) == (1, "hangup")
    assert turns[-1].lines[0][0] == SILENCE_LINE
    assert (rep.policy.identity_strikes, rep.policy.timer_strikes) == (0, 3)
    intent = sink.of("rep.policy")[-1].payload["intent"]
    assert intent == {
        "kind": "hang_up",
        "offer_ref": None,
        "say": [],
        "ask": [],
        "reason": None,
    }
    assert template(PublicIntent(kind="hang_up"), "Northwind") == SILENCE_LINE


def test_t3_the_confirmed_line_says_the_number_once() -> None:
    done = PublicIntent(
        kind="confirmed", offer_ref="loyal-1", say=(("confirmation", "048213"),)
    )
    line = template(done, "Northwind")
    assert line == "Done, the offer is accepted. Your confirmation number is 048213."
    assert line.count("048213") == 1 and "confirmation:" not in line
    assert fidelity_ok(line, done)
    assert fidelity_ok("All set, your confirmation number is 048213.", done)
    assert not fidelity_ok("All set, your confirmation number is 48213.", done)


PRICE = (("monthly_price", "75.00"), ("term_months", "12"))
PINNED: list[tuple[PublicIntent, str]] = [
    (
        PublicIntent(kind="greet", ask=("account.holder_name", "account.last4")),
        "Thanks for calling Northwind. First I need to verify your identity. "
        "Please give your account holder name and account last4.",
    ),
    (
        PublicIntent(kind="ask_identity", ask=("account.last4",)),
        "I still need to verify your identity. Please give your account last4.",
    ),
    (
        PublicIntent(kind="how_can_help"),
        "Thanks, you are verified. How can I help today?",
    ),
    (
        PublicIntent(kind="offer", offer_ref="loyal-1", say=PRICE),
        "I can offer you this: monthly price: 75.00; term: 12 months.",
    ),
    (
        PublicIntent(kind="final_offer", offer_ref="loyal-2", say=PRICE),
        "This is my best and final offer: monthly price: 75.00; term: 12 months.",
    ),
    (
        PublicIntent(kind="no_better"),
        "I am afraid I cannot do better than what I offered.",
    ),
    (
        PublicIntent(
            kind="readback",
            offer_ref="loyal-1",
            say=(*PRICE, ("fee:activation", "20.00"), ("fees_none", "true")),
        ),
        "Here are the full terms: monthly price: 75.00; term: 12 months; "
        "fee activation: 20.00; no fees.",
    ),
    (
        PublicIntent(kind="confirm_accept", offer_ref="loyal-1", say=PRICE),
        "To confirm, do you accept these terms? monthly price: 75.00; term: 12 months.",
    ),
    (PublicIntent(kind="ack_decline"), "Understood."),
    (
        PublicIntent(kind="offer_unavailable", offer_ref="loyal-1"),
        "Sorry, that offer is no longer available.",
    ),
    (PublicIntent(kind="offer_expired", offer_ref="loyal-1"), ""),
    (PublicIntent(kind="ok_hold"), "Sure, I will hold."),
    (PublicIntent(kind="check_in"), "Hello, are you still there?"),
    (PublicIntent(kind="transfer"), "Let me transfer you to a supervisor."),
    (PublicIntent(kind="hang_up"), SILENCE_LINE),
    (PublicIntent(kind="clarify"), "Sorry, how can I help with your account?"),
]


@pytest.mark.parametrize(("intent", "line"), PINNED, ids=[i.kind for i, _ in PINNED])
def test_t4_every_other_template_is_unchanged(intent: PublicIntent, line: str) -> None:
    assert template(intent, "Northwind") == line
