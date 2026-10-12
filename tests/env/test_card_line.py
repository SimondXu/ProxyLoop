"""S1-SYS-103 (ADR-0028): the sim user's chat voice agrees with its own card.

The approver (the button) decides a card or a mandate; ``on_decided`` puts
that answer in the user's chat as a ``Card:`` line, and the SYSTEM prompt keeps
the chat voice to it. Only the scripted stop changes the user's mind.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from tests.env.bus_sink import BusSink
from tests.env.cards import card as _card
from tests.env.cards import offer as _offer

from proxyloop.contract.state import Mandate
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.user.simuser import SYSTEM, SimUser, card_line

APPROVAL = load_task("x-out-of-envelope-approval")  # no stop; a hidden limit
MIND = load_task("x-user-mind-change")  # a plain stop after the card
TERMS = "monthly price $69.00; term months 24 months; fees none true"


def _reply(text: str) -> str:
    args = json.dumps({"text": text, "revealed": {}})
    call = {"call_id": "t", "name": "reply", "arguments": args}
    return json.dumps({"text": "", "tool_calls": [call]})


def _prompts(sink: BusSink) -> list[str]:
    """Each SimUser request's chat message (the user turn), in order."""
    sent = [json.loads(c) for kind, c in sink.prompts.values() if kind == "messages"]
    return [str(r["messages"][1]["content"]) for r in sent]


def _mandate(**bounds: Any) -> Mandate:
    fields = {"mandate_id": "m-1", "mandate_hash": "h", "status": "proposed"}
    return Mandate.model_validate(fields | {"epoch": 0} | bounds)


def _decide_card(user: SimUser, monthly: int, months: int = 24) -> str:
    assert user.approver is not None
    card = _card(readback_text=TERMS)
    post = user.approver.decide(card, _offer(monthly, months))
    user.on_decided(card, post.post)
    return str(post.post.decision)


def _ask(sink: BusSink, user: SimUser, text: str) -> None:
    cause = sink.heard(text, lane="user").event_id
    asyncio.run(user.on_agent_message(text, cause))


def test_a_granted_card_is_in_the_next_requests_chat(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    user = SimUser(APPROVAL, sink.llm(_reply("Thanks.")), sink.world, 7)
    events = len(sink.bus.events)
    assert _decide_card(user, 6900) == "granted"  # $69, within the hidden limit
    assert len(sink.bus.events) == events  # deciding emits nothing
    _ask(sink, user, "Please review the approval card.")
    (prompt,) = _prompts(sink)
    want = f"Card: you approved these terms: {TERMS}"
    assert f"{want}\nAssistant: Please review the approval card." in prompt


def test_a_denied_card_says_declined(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    user = SimUser(APPROVAL, sink.llm(_reply("OK.")), sink.world, 7)
    assert _decide_card(user, 9900) == "denied"  # over every limit
    _ask(sink, user, "The card was declined.")
    assert f"Card: you declined these terms: {TERMS}" in _prompts(sink)[0]


def test_a_mandate_decision_names_its_bounds(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    user = SimUser(APPROVAL, sink.llm(_reply("OK.")), sink.world, 7)
    assert user.approver is not None
    bounds = {"max_monthly_price_minor": 6500, "max_term_months": 24}
    m = _mandate(**bounds | {"max_one_time_fees_minor": 0})
    post = user.approver.decide_mandate(m)  # the stated envelope, exactly
    assert post.post.decision == "granted"
    user.on_decided(m, post.post)
    _ask(sink, user, "Your limits are set.")
    said = "at most $65.00 a month; at most 24 months; at most $0.00 in one-time fees"
    assert f"Card: you approved these limits: {said}" in _prompts(sink)[0]
    loose = user.approver.decide_mandate(_mandate())  # no bound: looser
    assert loose.post.decision == "denied"
    none = "Card: you declined these limits: none stated"
    assert card_line(_mandate(), False) == none


def test_the_system_prompt_keeps_approvals_on_the_card() -> None:
    flat = " ".join(SYSTEM.split())
    assert "only on the approval card, never in chat" in flat
    assert "do not approve or reject an offer in a chat reply" in flat
    assert 'A chat line that starts "Card:" is your own answer' in flat
    assert 'Only an instruction that starts "Now, in this reply:"' in flat


def test_request_stays_pure_with_a_card_line(tmp_path: Path) -> None:
    """The line is chat state; ``request`` reads it only from its arguments."""
    sink = BusSink(tmp_path)
    user = SimUser(APPROVAL, sink.llm(), sink.world, 7)  # never called
    chat = ["Assistant: Hi.", f"Card: you approved these terms: {TERMS}"]
    facts = dict(APPROVAL.profile.facts)
    events = len(sink.bus.events)
    first = user.request(chat, facts, None, "c", 0)
    _decide_card(user, 6900)  # the user's own chat moves; the request does not
    assert user.request(chat, facts, None, "c", 0) == first
    assert len(sink.bus.events) == events and not sink.prompts


def test_the_stop_after_a_card_line_is_still_generated_and_checked(
    tmp_path: Path,
) -> None:
    """x-user-mind-change: the card was granted (its line is in the chat),
    then the scripted stop fires; it must still say a stop cue."""
    sink = BusSink(tmp_path)
    good = "Please stop, keep my current plan."
    responses = (_reply("Sure, go ahead."), _reply(good))
    user = SimUser(MIND, sink.llm(*responses), sink.world, 7)
    assert _decide_card(user, 7600, 12) == "granted"  # $76: over 70, within 78
    cause = sink.heard("(card)", lane="cp").event_id
    stop = asyncio.run(user.on_trigger("after_card", cause))
    assert stop is not None and stop.text == good
    (sim,) = sink.of("user.sim")
    assert sim.payload["stop"] == "stop" and sim.payload["attempts"] == 2
    prompt = _prompts(sink)[-1]
    hint = MIND.stop.text_hint.strip() if MIND.stop else ""
    line = f"Card: you approved these terms: {TERMS}"
    assert prompt.index(line) < prompt.index(f"Now, in this reply: {hint}")
    assert user.approver is not None and user.approver.stopped
