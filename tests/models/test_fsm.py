"""The FSM talker (condition F): conformance, the view it reads, its policy."""

from __future__ import annotations

import asyncio
import re

import pytest
from tests.contract.llm_conformance import assert_text_conformance
from tests.models.views import goldens, request, view
from tests.support.manual_clock import ManualClock

from proxyloop.contract.llm import AdapterKind, LLMCallRecord, ModelRef, ToolRequest
from proxyloop.contract.protocol import (
    EndCall,
    Hold,
    ParseIssue,
    Relay,
    Speech,
    TurnItem,
    Wait,
    parse_turn,
)
from proxyloop.contract.state import CaseStatus
from proxyloop.contract.views import FastView
from proxyloop.models.fsm import (
    CHECKING,
    NOTED,
    READBACK,
    FsmTalker,
    read_view,
    respond,
)
from proxyloop.models.registry import resolve

FSM = resolve("fsm")
GOLDENS = goldens()


def _talker(records: list[LLMCallRecord] | None = None) -> FsmTalker:
    sink: list[LLMCallRecord] = [] if records is None else records
    return FsmTalker(FSM, ManualClock().monotonic_ms, sink.append)


def _turn(v: FastView) -> tuple[TurnItem, ...]:
    text = respond(read_view(request(v).messages))
    return parse_turn(text, v.lane)


def _kinds(items: tuple[TurnItem, ...]) -> list[str]:
    return [i.kind if not isinstance(i, Relay) else f"relay:{i.type}" for i in items]


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_conformance_on_every_golden(name: str) -> None:
    records: list[LLMCallRecord] = []
    _, messages = GOLDENS[name]
    record = asyncio.run(assert_text_conformance(_talker(records), request(messages)))
    assert records == [record]  # the sink gets the record the stream yields
    assert record.adapter_kind is AdapterKind.BASELINE


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_reads_back_what_the_renderer_wrote(name: str) -> None:
    v, messages = GOLDENS[name]
    seen = read_view(messages)
    assert (seen.lane, seen.trigger, seen.status) == (v.lane, v.trigger.kind, v.status)
    assert seen.hold == (v.hold.reason if v.hold else None)
    assert [o.ref for o in seen.offers] == [o.offer_ref for o in v.offers]
    assert [len(o.slots) for o in seen.offers] == [len(o.slots) for o in v.offers]
    assert [m for m, _ in seen.guides] == [g.move.value for g in v.guidance]
    kept = [(x.speaker, x.text) for x in v.transcript][
        len(v.transcript) - len(seen.lines) :
    ]
    assert list(seen.lines) == kept


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_every_golden_turn_parses_cleanly(name: str) -> None:
    v, messages = GOLDENS[name]
    items = parse_turn(respond(read_view(messages)), v.lane)
    assert items and not [i for i in items if isinstance(i, ParseIssue)]


def test_an_offer_gets_the_readback_request_a_relay_and_a_hold() -> None:
    items = _turn(view("cp", "I can do $65 a month for 12 months, plus a $30 fee."))
    assert items[0] == Speech(text=READBACK)
    relay = next(i for i in items if isinstance(i, Relay))
    assert relay.type == "fact"
    assert ("monthly_price", "$65") in relay.facts
    assert ("term_months", "12") in relay.facts
    assert items[-1] == Hold(reason="offer")


def test_an_ask_to_accept_holds_for_a_decision() -> None:
    items = _turn(view("cp", "Great, shall I go ahead and lock that in for you?"))
    assert items[-1] == Hold(reason="decision")
    assert not any("accept" in i.text.lower() for i in items if isinstance(i, Speech))


def test_a_pin_request_is_deflected_and_held() -> None:
    items = _turn(view("cp", "Before we continue, what is the account PIN?"))
    assert items[0] == Speech(text="I'm sorry, I can't share that detail.")
    assert items[-1] == Hold(reason="fact_request")


def test_close_call_guidance_ends_the_call() -> None:
    guide = {"move": "close_call", "slots": ()}
    items = _turn(view("cp", trigger="guidance", guidance=(guide,)))
    assert _kinds(items)[-1] == "end_call" and isinstance(items[-1], EndCall)


def test_a_hold_is_kept_while_the_rep_waits() -> None:
    hold = {"reason": "offer", "since_ms": 0}
    items = _turn(view("cp", "Sure, take your time.", hold=hold))
    assert items[-1] == Hold(reason="offer")


def test_user_facts_are_relayed_typed_and_exact() -> None:
    items = _turn(view("user", "My account number is 5501-2234 and I am Dana Reyes."))
    relay = next(i for i in items if isinstance(i, Relay))
    assert relay.type == "fact"
    assert relay.facts == (("account_number", "5501-2234"), ("name", "Dana Reyes"))


def test_a_user_stop_is_relayed_as_a_revoke() -> None:
    items = _turn(view("user", "Actually, stop. Don't accept anything."))
    assert _kinds(items)[-1] == "relay:revoke"


def test_a_user_correction_is_relayed_as_one_correction() -> None:
    items = _turn(view("user", "Sorry, my account number is 5501-2299."))
    relay = next(i for i in items if isinstance(i, Relay))
    assert (relay.type, relay.facts) == (
        "correction",
        (("account_number", "5501-2299"),),
    )


@pytest.mark.parametrize("status", list(CaseStatus))
def test_never_claims_completion_unless_verified(status: CaseStatus) -> None:
    said = " ".join(
        i.text
        for i in _turn(view("user", "Is it done yet?", status=status))
        if isinstance(i, Speech)
    )
    assert ("verified complete" in said) == (status is CaseStatus.VERIFIED_COMPLETE)


def _voiced(text: str, status: CaseStatus) -> list[str]:
    msg = {"msg_id": "s1", "lane": "user", "type": "TELL_USER", "text": text}
    v = view("user", trigger="slow_msg", slow_msg=msg, status=status)
    return [i.text for i in _turn(v) if isinstance(i, Speech)]


IN_PROGRESS = "The case is still in progress, and nothing is complete yet."


@pytest.mark.parametrize(
    "text",
    [
        "Your plan change is complete. Enjoy the lower price.",
        "I've switched your plan to $50 a month.",
        "All done!",
        "The new price is locked in.",
        "Your cancellation has been processed.",
        "The rep is checking for a better offer. Your plan is switched.",
    ],
)
def test_a_completion_claim_from_slow_is_never_voiced_unverified(text: str) -> None:
    assert _voiced(text, CaseStatus.IN_CALL) == [IN_PROGRESS]  # status line only
    assert _voiced(text, CaseStatus.VERIFIED_COMPLETE) == _say_all(text)


def _say_all(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]


def test_other_slow_sentences_are_kept_without_a_status_line() -> None:
    text = "The rep is checking for a better offer."
    assert _voiced(text, CaseStatus.IN_CALL) == [text]
    two = "Would a 12-month term at $65.00 a month work? Let me know."
    assert _voiced(two, CaseStatus.IN_CALL) == _say_all(two)


@pytest.mark.parametrize("move", ["identify", "cite_competitor", "mention_tenure"])
def test_a_slot_move_without_slot_values_is_skipped(move: str) -> None:
    guide = {"move": move, "slots": ()}
    assert _turn(view("cp", trigger="guidance", guidance=(guide,))) == (Wait(),)
    later = _turn(view("cp", "Sure, go on.", guidance=(guide,)))
    assert later[0] == Speech(text=NOTED)


@pytest.mark.parametrize(
    "heard",
    [
        "Should I process that for you?",
        "I can put it through right away.",
        "Would you like the new plan?",
        "Do you want me to switch the plan?",
        "Shall I make the change?",
        "We can go ahead with that.",
    ],
)
def test_asks_to_decide_hold_for_a_decision(heard: str) -> None:
    items = _turn(view("cp", heard))
    assert items[0] == Speech(text=CHECKING)
    assert items[-1] == Hold(reason="decision")


def test_any_rep_question_with_an_open_offer_holds_for_a_decision() -> None:
    offer = {"offer_ref": "o1", "revision": 1}
    items = _turn(view("cp", "Is there anything else?", offers=(offer,)))
    assert items[-1] == Hold(reason="decision")
    items = _turn(view("cp", "Is there anything else?"))
    assert not [i for i in items if isinstance(i, Hold)]


def test_the_acknowledgement_never_assents() -> None:
    items = _turn(view("cp", "Our plans changed a lot this year."))
    assert items[0] == Speech(text=NOTED)


def test_an_amount_alone_is_not_an_offer() -> None:
    items = _turn(view("cp", "Your current bill is $120."))
    assert items[0] == Speech(text=NOTED)
    assert not [i for i in items if isinstance(i, Hold)]


def test_an_approval_request_in_chat_is_sent_to_the_card() -> None:
    items = _turn(view("user", "Yes, go ahead and accept it."))
    said = " ".join(i.text for i in items if isinstance(i, Speech))
    assert "approval card" in said
    assert "approved" not in said.lower()


def test_only_baseline_refs_and_rendered_views() -> None:
    real = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="x")
    with pytest.raises(ValueError, match="baseline"):
        FsmTalker(real, ManualClock().monotonic_ms, list[LLMCallRecord]().append)
    _, messages = GOLDENS["c02_rep_offer"]
    edited = (messages[0].model_copy(update={"content": "You are a bot."}), messages[1])
    with pytest.raises(ValueError, match="profile"):
        asyncio.run(
            assert_text_conformance(
                _talker(), request(messages).model_copy(update={"messages": edited})
            )
        )


def test_no_tools() -> None:
    tool = ToolRequest.model_validate(
        {
            "call_id": "t",
            "role": "fast_cp",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "x", "description": "", "parameters": {}}],
            "max_tokens": 8,
        }
    )
    with pytest.raises(TypeError):
        asyncio.run(_talker().chat_tools(tool))
