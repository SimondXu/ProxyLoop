"""Typed Fast<->Slow messages (ARCHITECTURE §7)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from proxyloop.contract.base import FACT_KEY, Frozen, Lane


class GuideMove(StrEnum):
    OPEN_CALL = "open_call"
    IDENTIFY = "identify"
    ASK_DISCOUNT = "ask_discount"
    CITE_COMPETITOR = "cite_competitor"
    MENTION_TENURE = "mention_tenure"
    CANCEL_LEVER = "cancel_lever"
    ASK_READBACK = "ask_readback"
    HOLD_FOR_DECISION = "hold_for_decision"
    DECLINE_OFFER = "decline_offer"
    ASK_FINAL_OFFER = "ask_final_offer"
    DEFLECT_FACT_REQUEST = "deflect_fact_request"
    CLOSE_CALL = "close_call"


OFFER_REF = r"[A-Za-z0-9_-]+"
SLOT_FIELD = r"[a-z_]+(?::[A-Za-z0-9_.:-]+)?"
SLOT_REF = rf"^(?:fact:{FACT_KEY}|offer:{OFFER_REF}(?:\.{SLOT_FIELD})?)$"
# "fact:<key>" | "offer:<ref>" | "offer:<ref>.<field>"; resolved in public state only.
SlotRef = Annotated[str, StringConstraints(pattern=SLOT_REF)]


class Guide(Frozen):
    """GUIDE = enum + slot references; it carries no free text (I4)."""

    move: GuideMove
    slots: tuple[SlotRef, ...] = ()


F2SType = Literal["USER_UPDATE", "CP_UPDATE", "REQUEST", "REVOKE", "NOTE", "HOLD"]
_F2S_LANE: dict[str, Lane] = {
    "USER_UPDATE": "user",
    "REQUEST": "user",
    "REVOKE": "user",
    "CP_UPDATE": "cp",
    "HOLD": "cp",
}


class FastToSlow(Frozen):
    """``f2s.msg``: one typed relay from a Fast lane."""

    msg_id: str
    lane: Lane
    gen_id: str
    utt_ref: str | None  # the partner utterance / user message it came from
    type: F2SType
    facts: tuple[tuple[str, str], ...] = ()
    correction: bool = False
    text: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def _lane_rules(self) -> Self:
        lane = _F2S_LANE.get(self.type)
        if lane is not None and lane != self.lane:
            raise ValueError(f"{self.type} is a {lane}-lane relay")
        if self.correction and self.type != "USER_UPDATE":
            raise ValueError("only USER_UPDATE carries a correction")
        return self


S2FType = Literal["ASK_USER", "TELL_USER", "GUIDE", "APPROVAL_NOTICE", "END"]


class SlowToFast(Frozen):
    """``s2f.msg``; acknowledged by ``s2f.voiced``. The cp lane never gets text."""

    msg_id: str
    lane: Lane
    type: S2FType
    text: str = ""  # user lane only (ASK_USER / TELL_USER)
    guide: Guide | None = None  # cp lane only
    approval_id: str | None = None  # APPROVAL_NOTICE: the card's readback_text

    @model_validator(mode="after")
    def _lane_rules(self) -> Self:
        user_only = self.type in ("ASK_USER", "TELL_USER", "APPROVAL_NOTICE")
        if user_only and self.lane != "user":
            raise ValueError(f"{self.type} is a user-lane message")
        if self.type == "GUIDE" and self.lane != "cp":
            raise ValueError("GUIDE is a cp-lane message")
        if self.lane == "cp" and self.text:
            raise ValueError("the cp lane never receives free text from Slow")
        if self.type in ("ASK_USER", "TELL_USER") and not self.text:
            raise ValueError(f"{self.type} needs text")
        if (self.guide is not None) != (self.type == "GUIDE"):
            raise ValueError("guide is set iff type is GUIDE")
        if (self.approval_id is not None) != (self.type == "APPROVAL_NOTICE"):
            raise ValueError("approval_id is set iff type is APPROVAL_NOTICE")
        return self
