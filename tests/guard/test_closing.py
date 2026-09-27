"""S1-SYS-55: Guard's closing cues match the rep's real closing lines, and
neither questions nor negated forms. The lines are verbatim from runs
``20260927T064626Z-f828f1`` (f8) and ``20260927T205319Z-45d7ed`` (45)."""

from __future__ import annotations

import pytest
from tests.guard.build import board, confirm, offer, rep

from proxyloop.guard.readback import has_cue
from proxyloop.guard.verify import verify_no_deal

REAL = (
    # f8, after ask_final_offer
    "That is our best offer, and I am afraid I cannot do any better.",  # cp-25
    "I'm afraid that is our best offer, and I cannot do any better than what "
    "I've offered.",  # cp-26
    "I am afraid that is our best offer, and I cannot do any better than what "
    "I offered.",  # cp-27
    "I'm afraid I can't do any better than what I've already offered.",  # cp-29
    # f8, earlier
    "I'm afraid that is already the best offer I can provide, and I cannot go "
    "any lower.",  # cp-11
    "I'm afraid that is already our best available offer, and I can't go any "
    "lower.",  # cp-12
    "I'm afraid I really cannot do any better than what I have offered.",  # cp-15
    # 45
    "I'm afraid what I offered is already the best rate I can provide.",  # cp-12
    "I am afraid this is our best offer. I cannot do any better than what I "
    "offered.",  # cp-17
    "That is our best offer. I am unable to do any better than what I "
    "presented.",  # cp-18
    "I'm afraid that is the absolute best offer I'm able to provide.",  # cp-19
    "I am afraid that really is the best offer I can provide.",  # cp-49
    "Understood, have a great day.",  # cp-57
)
OLD = (  # every cue before S1-SYS-55 stays one
    "best and final", "final offer", "cannot do better", "can't do better",
    "no better", "nothing more", "transfer", "goodbye", "ending the call",
)  # fmt: skip
SYNTHETIC = (
    "that's our best and final offer",
    "This is my final offer.",
    "I am not able to go any lower.",
    "Goodbye.",
)
NEVER = (
    "I can't say that's our best offer",  # negated
    "that's not our final offer",  # negated
    "It is not that I cannot do any better.",  # the refusal itself negated
    "is that your best offer?",  # questions state no position
    "Can you do any better?",
    "Is that really the best offer you can provide?",
    "Is this your best and final offer?",
    "I apologize, but that offer is no longer available.",  # f8 cp-24/cp-30
    "The full terms are 75.00 per month for 12 months, with a 20.00 activation "
    "fee.",  # f8 cp-23, a read-back
    "I understand, and thank you for your time today.",  # 45 cp-25
    "thank you for your time",
    "I can offer a monthly price of 75.00 with a term of 12 months.",  # f8 cp-10
    "Let me see what the best offer is.",
    # hedges, conditions, checks and reported speech (review of PR #197)
    "Let me check what's the best offer I can give you.",
    "I'll check whether this is the best rate we have.",
    "I'll see if this is the best rate available.",
    "If this is the best deal for you, I can set it up today.",
    "My manager said that's our best offer, but let me ask again.",
    "I don't think that this really is our best offer.",
    "I can't honestly say that this is our best offer.",
    "I am not entirely sure whether this is the best deal.",
    "Earlier I told you I can't go any lower, but actually I can do 55.",
    "Tell me what is the best offer for you.",
    "I can't go any lower, but actually I can do 55.",
    # a condition, time limit, concession or floor after the cue (round 3)
    "I am unable to do any better unless you commit to 24 months.",
    "I cannot do any better without my supervisor.",
    "I cannot do any better yet.",
    "That is our best offer, unless my supervisor approves more.",
    "That is our best offer right now, but let me check with my manager.",
    "That is the best deal I can do before I talk to my supervisor.",
    "I cannot offer better than that until the promotion starts next week.",
    "I can't do any better than 60 but I could do 58 on the annual plan.",
    "I cannot do any better on the monthly price, but I can waive the activation fee.",
    "I cannot go any lower than 50.",
    "I can't do any better than 55 dollars.",
    # more hedges before the cue, and hyphenated ones
    "Let me confirm that this is our best offer.",
    "I need to verify this is the best rate.",
    "I believe that is our best offer.",
    "I guess that is the best deal.",
    "Perhaps this is our final offer.",
    "That probably is our best offer.",
    "I will give you whichever is the best price.",
    "Let me double-check that this is our best offer.",
)


@pytest.mark.parametrize("text", REAL + OLD + SYNTHETIC)
def test_a_closing_line_matches(text: str) -> None:
    assert has_cue(text, "closing")


@pytest.mark.parametrize("text", NEVER)
def test_a_question_negation_or_near_miss_does_not(text: str) -> None:
    assert not has_cue(text, "closing")


def test_a_closing_sentence_still_counts_beside_a_question() -> None:
    assert has_cue("That is our best offer. Is there anything else?", "closing")
    assert has_cue("That\u2019s our best offer.", "closing")  # a typographic '


def test_no_deal_takes_a_real_closing_reply_and_not_a_question() -> None:
    declined = confirm(offer()).model_copy(update={"status": "declined"})
    asked = (rep("c1", "I can offer $68 a month."),)  # ask_final_offer after c1
    real = rep("c2", "I can't do any better than what I've already offered.")
    assert verify_no_deal(board(declined, cp=(*asked, real)), 1).verdict == "ok"
    for text in ("Can you do any better?", "that's not our final offer"):
        bb = board(declined, cp=(*asked, rep("c2", text)))
        assert verify_no_deal(bb, 1).reasons == ("no_closing_reply",)
