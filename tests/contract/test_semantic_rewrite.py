"""ADR-0026: the candidate profiles ``pl_cp_v4`` and ``pl_user_v2``.

A semantic rewrite with no grammar change: the system texts' format examples
parse with zero issues under the production parser and are canonical
(``format_turn`` gives them back byte for byte); ``pl_cp_v4`` is ``pl_cp_v3``
with a new system text and four move texts; ``pl_user_v2`` is ``pl_user_v1``
with a new system text. The texts' sha256 and fingerprints are pinned in the ADR.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from proxyloop.contract.base import Lane, sha256_text
from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.protocol import (
    PROFILES,
    Hold,
    ParseIssue,
    Relay,
    Speech,
    TurnItem,
    fingerprint,
    format_turn,
    parse_turn,
    render_messages,
)
from proxyloop.contract.state import Blackboard, PublicState
from proxyloop.contract.views import Trigger, view_cp

ADR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "decisions"
    / "0026-contract-fast-profile-semantic-rewrite.md"
)
CP, USER = "pl_cp_v4", "pl_user_v2"
CP_TERMS = (
    "Thank you, I have noted that.\n"
    "@slow: fact setup_fee=waived\n"
    "@slow: fact autopay=required\n"
    "@slow: they say the waiver ends if autopay is cancelled"
)
CP_ACCEPT = (
    "I can't agree to that myself. Please hold a moment while I check with my "
    "customer.\n@hold offer"
)
USER_PREFS = (
    "Got it, I'll pass that along.\n"
    "@slow: fact callback_time=mornings\n"
    "@slow: fact paper_bills=no"
)
EXAMPLES: tuple[tuple[str, Lane, str, tuple[TurnItem, ...]], ...] = (
    (
        CP,
        "cp",
        CP_TERMS,
        (
            Speech(text="Thank you, I have noted that."),
            Relay(type="fact", facts=(("setup_fee", "waived"),)),
            Relay(type="fact", facts=(("autopay", "required"),)),
            Relay(type="note", text="they say the waiver ends if autopay is cancelled"),
        ),
    ),
    (
        CP,
        "cp",
        CP_ACCEPT,
        (
            Speech(text="I can't agree to that myself."),
            Speech(text="Please hold a moment while I check with my customer."),
            Hold(reason="offer"),
        ),
    ),
    (
        USER,
        "user",
        USER_PREFS,
        (
            Speech(text="Got it, I'll pass that along."),
            Relay(type="fact", facts=(("callback_time", "mornings"),)),
            Relay(type="fact", facts=(("paper_bills", "no"),)),
        ),
    ),
)
NEW_MOVES = {
    "identify": "Give only the account details given here, so they can verify the "
    "account.",
    "hold_for_decision": "Say you need to check with your customer and ask them to "
    "hold a moment; end with `@hold decision`.",
    "hold_for_fact": "Say you are getting that detail from your customer and ask "
    "them to hold a moment; end with `@hold fact_request`.",
    "close_call": "Thank them and say goodbye; end with `@end_call`.",
}
SYSTEM_SHA256 = {
    CP: "9fceab4ee06c0fc3b2f93c571b29fffcd4a98dfcd8e8c40ec4d51a3ef8958dd3",
    USER: "b118a6b8d70335eb6cb5f832ffb6c10212424bc75a37f07c1c260970e6884fe1",
}


def test_the_examples_close_the_system_texts() -> None:
    cp, user = PROFILES[CP].system, PROFILES[USER].system
    assert cp.endswith(
        "Format examples (the content is only illustrative).\n"
        f"The representative stated two terms:\n{CP_TERMS}\n"
        f"The representative asks you to accept:\n{CP_ACCEPT}"
    )
    assert user.endswith(
        "Format example (the content is only illustrative), the user gives two "
        f"preferences:\n{USER_PREFS}"
    )


@pytest.mark.parametrize(("profile", "lane", "text", "items"), EXAMPLES)
def test_each_example_parses_cleanly_and_is_canonical(
    profile: str, lane: Lane, text: str, items: tuple[TurnItem, ...]
) -> None:
    parsed = parse_turn(text, lane, profile)
    assert not [i for i in parsed if isinstance(i, ParseIssue)]
    assert parsed == items
    assert parse_turn(text, lane) == items  # the base grammar agrees
    assert format_turn(parsed) == text
    assert parse_turn(format_turn(parsed), lane, profile) == parsed


def test_pl_cp_v4_is_pl_cp_v3_with_a_new_system_text_and_four_moves() -> None:
    v3, v4 = PROFILES["pl_cp_v3"], PROFILES[CP]
    assert v4.pause_ends_speech and v4.lane == "cp"
    same = {f.name for f in fields(v3)} - {"name", "system", "moves", "p2_ids_sha256"}
    assert all(getattr(v3, f) == getattr(v4, f) for f in same)
    assert v4.system != v3.system
    assert set(v4.moves) == set(v3.moves) == {m.value for m in GuideMove}
    assert {k: v for k, v in v4.moves.items() if v != v3.moves[k]} == NEW_MOVES


def test_pl_user_v2_is_pl_user_v1_with_a_new_system_text() -> None:
    v1, v2 = PROFILES["pl_user_v1"], PROFILES[USER]
    assert not v2.pause_ends_speech and v2.lane == "user"
    same = {f.name for f in fields(v1)} - {"name", "system", "p2_ids_sha256"}
    assert all(getattr(v1, f) == getattr(v2, f) for f in same)
    assert v2.system != v1.system


@pytest.mark.parametrize(
    "guides",
    [
        (GuideMove.IDENTIFY, GuideMove.HOLD_FOR_DECISION, GuideMove.HOLD_FOR_FACT),
        (GuideMove.CLOSE_CALL,),
    ],
)
def test_the_new_move_texts_render(guides: tuple[GuideMove, ...]) -> None:
    public = PublicState(guidance_cp=tuple(Guide(move=m) for m in guides))
    view = view_cp(Blackboard(public=public), Trigger(kind="guidance"), "b")
    content = render_messages(view, CP)[1].content
    for move in guides:
        assert f"\n- {NEW_MOVES[move.value]}\n" in content


@pytest.mark.parametrize("profile", [CP, USER])
def test_system_sha256_and_fingerprint_are_pinned_in_the_adr(profile: str) -> None:
    system = PROFILES[profile].system
    assert sha256_text(system) == SYSTEM_SHA256[profile]
    adr = ADR.read_text("utf-8")
    assert SYSTEM_SHA256[profile] in adr
    assert fingerprint(profile) in adr
