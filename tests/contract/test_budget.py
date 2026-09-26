"""Render bounds: every bounded field at its maximum still fits the budget."""

from __future__ import annotations

import pytest

from proxyloop.contract import base
from proxyloop.contract.messages import Guide, GuideMove, SlowToFast
from proxyloop.contract.protocol import (
    CONTEXT_BUDGET_CHARS,
    OMITTED_LINES,
    render_messages,
)
from proxyloop.contract.state import (
    ApprovalCard,
    CaseStatus,
    HoldState,
    Line,
    OfferPublic,
    PublicFact,
    ReadbackBinding,
    ReadbackSlot,
)
from proxyloop.contract.views import FastView, Trigger


def _offer(i: int) -> OfferPublic:
    ref = f"{i}".rjust(24, "o")
    slots = tuple(
        ReadbackSlot(
            field="fee:" + f"{j}".rjust(36, "x"),
            value="9" * base.MAX_SLOT_VALUE,
            unit="months",
            role="one_time",
            status="confirmed",
        )
        for j in range(base.MAX_SLOTS)
    )
    return OfferPublic(offer_ref=ref, revision=999, slots=slots, status="withdrawn")


OFFERS = tuple(_offer(i) for i in range(base.MAX_OFFERS))
LINES = tuple(
    Line(utt_id=f"l{i}", speaker="partner", text="a long line " * 20)
    for i in range(200)
)
ACTIONS = tuple("an action " * 40 for _ in range(12))
KEYS = [f"k{i}".ljust(base.MAX_SLOT_REF - len("fact:"), "z") for i in range(9)]
FACTS = tuple(
    PublicFact(
        key=k, value="v" * base.MAX_FACT_VALUE, source="shareable", source_ref="t"
    )
    for k in KEYS
)
GUIDES = tuple(
    Guide(move=GuideMove.ASK_READBACK, slots=tuple(f"fact:{k}" for k in KEYS[i::3]))
    for i in range(3)
)
CARD = ApprovalCard(
    approval_id="a1",
    offer_ref="o1",
    revision=1,
    terms_hash="t",
    readback_text="r" * base.MAX_READBACK_TEXT,
    authority_epoch=1,
    expires_ms=1,
    binding=ReadbackBinding(
        offer_ref="o1",
        revision=1,
        account_ref="a",
        principal_ref="p",
        purpose="x",
        authority_epoch=1,
    ),
)
COMMON = {
    "brief": "b" * base.MAX_BRIEF,
    "public_summary": "s" * base.MAX_PUBLIC_TEXT,
    "action_log": ACTIONS,
    "offers": OFFERS,
    "status": CaseStatus.COMMIT_AUTHORIZED,
    "transcript": LINES,
}
SLOW = SlowToFast(msg_id="m", lane="user", type="ASK_USER", text="q" * 400)


@pytest.mark.parametrize(
    ("profile", "fields"),
    [
        (
            "pl_user_v1",
            {
                "lane": "user",
                "private_summary": "p" * base.MAX_PRIVATE_SUMMARY,
                "pending_approval": CARD,
                "trigger": Trigger(kind="approval_card"),
            },
        ),
        (
            "pl_user_v1",
            {
                "lane": "user",
                "private_summary": "p" * base.MAX_PRIVATE_SUMMARY,
                "pending_approval": CARD,
                "trigger": Trigger(kind="slow_msg", msg_id="m"),
                "slow_msg": SLOW,
            },
        ),
        (
            "pl_cp_v1",
            {
                "lane": "cp",
                "public_facts": FACTS,
                "guidance": GUIDES,
                "hold": HoldState(reason="fact_request", since_ms=0),
                "trigger": Trigger(kind="hold_wait", wait_s=10**6),
            },
        ),
    ],
)
def test_maximal_view_fits_with_the_transcript_absorbing_the_rest(
    profile: str, fields: dict[str, object]
) -> None:
    view = FastView.model_validate(COMMON | fields)
    system, user = render_messages(view, profile)
    assert len(system.content) + len(user.content) <= CONTEXT_BUDGET_CHARS
    assert OMITTED_LINES in user.content
    assert "s" * base.MAX_PUBLIC_TEXT in user.content  # bounded fields survive
    assert user.content.count("(revision 999, withdrawn)") == base.MAX_OFFERS


def test_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        FastView.model_validate(
            COMMON
            | {"lane": "cp", "brief": "b" * (base.MAX_BRIEF + 1)}
            | {"trigger": Trigger(kind="rep_spoke")}
        )
    with pytest.raises(ValueError):
        SlowToFast(msg_id="m", lane="user", type="TELL_USER", text="q" * 401)
