"""Golden blackboards for P1/P2: every case is a (blackboard, trigger, brief).

The private values below (PIN, account number, mandate bounds) must never
appear in a cp golden (the allow-list test).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proxyloop.contract.messages import Guide, GuideMove, SlowToFast
from proxyloop.contract.state import (
    ApprovalCard,
    Blackboard,
    CaseStatus,
    ChannelState,
    Fact,
    HoldState,
    Line,
    Mandate,
    OfferPublic,
    PrivateState,
    PublicFact,
    PublicState,
    ReadbackBinding,
    ReadbackSlot,
)
from proxyloop.contract.views import FastView, Trigger, view_cp, view_user

GOLDEN = Path(__file__).resolve().parent
PIN = "4921"
ACCOUNT = "5501-2234-7788"
MANDATE = Mandate(
    mandate_id="m1",
    mandate_hash="9f2c",
    status="granted",
    epoch=1,
    max_monthly_price_minor=7150,
    max_term_months=36,
    max_one_time_fees_minor=2750,
    required_features=("unlimited_data",),
    forbidden_changes=("contract_extension",),
    decided_by="ui",
)
PRIVATE = PrivateState(
    summary="Dana wants a lower bill: at most $71.50 a month, at most $27.50 in "
    "one-time fees, no contract extension. Account PIN 4921 is on file.",
    case_facts={
        "account.pin": Fact(key="account.pin", value=PIN, protected=True),
        "account.number": Fact(key="account.number", value=ACCOUNT, protected=True),
        "user.name": Fact(key="user.name", value="Dana Reyes", source_ref="u1"),
    },
    mandate=MANDATE,
)
USER_BRIEF = "Help Dana Reyes lower her Contoso Mobile bill. Keep her informed."
CP_BRIEF = "You are calling Contoso Mobile to ask for a lower monthly price."


def _slot(field: str, value: str, unit: str, role: str, status: str) -> ReadbackSlot:
    return ReadbackSlot.model_validate(
        {"field": field, "value": value, "unit": unit, "role": role, "status": status}
    )


OFFER = OfferPublic(
    offer_ref="o1",
    revision=1,
    slots=(
        _slot("monthly_price", "6500", "usd_minor", "recurring", "heard"),
        _slot("term_months", "12", "months", "recurring", "heard"),
        _slot("fee:activation", "3000", "usd_minor", "one_time", "heard"),
        _slot("changes_none", "true", "bool", "change", "unknown"),
        _slot("expires", "2026-10-15", "iso", "expiry", "unknown"),
    ),
    terms_hash="c0ffee",
)
CONFIRMED = OFFER.model_copy(
    update={
        "slots": tuple(
            s.model_copy(update={"status": "confirmed"}) for s in OFFER.slots
        )
    }
)
PUBLIC = PublicState(
    summary="The rep offered $65.00 a month for 12 months, with a $30.00 activation "
    "fee.",
    facts={
        "competitor_quote": PublicFact(
            key="competitor_quote",
            value="$55.00 a month from Northwind",
            source="shareable",
            source_ref="task",
        ),
        "rep.name": PublicFact(
            key="rep.name", value="Jordan", source="cp_utt", source_ref="c2"
        ),
    },
    offers={"o1": OFFER},
    action_log=("opened the call", "recorded an offer", "asked for a read-back"),
    status=CaseStatus.IN_CALL,
)
USER_LINES = (
    Line(utt_id="u1", speaker="partner", text="Hi, my phone bill is too high."),
    Line(
        utt_id="a1", speaker="agent", text="I can help with that. Let me get started."
    ),
    Line(utt_id="u2", speaker="partner", text="Did they offer anything yet?"),
)
CP_LINES = (
    Line(
        utt_id="c1", speaker="agent", text="Hi, I'm an AI assistant calling for Dana."
    ),
    Line(utt_id="c2", speaker="partner", text="Hi, this is Jordan. How can I help?"),
    Line(
        utt_id="c3",
        speaker="partner",
        text="I can do $65 a month for 12 months, plus a $30 activation fee.",
    ),
)
CARD = ApprovalCard(
    approval_id="a17",
    offer_ref="o1",
    revision=1,
    terms_hash="c0ffee",
    readback_text="$65.00 a month for 12 months, a $30.00 one-time activation fee, "
    "no other changes, offer expires 2026-10-15",
    authority_epoch=1,
    expires_ms=600_000,
    binding=ReadbackBinding(
        offer_ref="o1",
        revision=1,
        account_ref="acct-1",
        principal_ref="dana",
        purpose="lower monthly bill",
        authority_epoch=1,
    ),
)


def _bb(
    user: tuple[Line, ...] = USER_LINES,
    cp: tuple[Line, ...] = CP_LINES,
    **update: object,
) -> Blackboard:
    bb = Blackboard(
        seq=40,
        t_ms=90_000,
        epoch=1,
        public=PUBLIC,
        private=PRIVATE,
        channels={"user": ChannelState(lines=user), "cp": ChannelState(lines=cp)},
    )
    return bb.model_copy(update=update)


def _long(prefix: str, n: int) -> tuple[Line, ...]:
    return tuple(
        Line(
            utt_id=f"{prefix}{i}",
            speaker="partner" if i % 2 else "agent",
            text="We keep talking about the plan, the price and the fees.",
        )
        for i in range(n)
    )


def _ask(kind: str, text: str) -> dict[str, object]:
    msg = SlowToFast.model_validate(
        {"msg_id": "s1", "lane": "user", "type": kind, "text": text}
    )
    return {"s2f_pending": {"user": (msg,)}}


GUIDES = (
    Guide(move=GuideMove.CITE_COMPETITOR, slots=("fact:competitor_quote",)),
    Guide(move=GuideMove.ASK_READBACK, slots=("offer:o1",)),
    Guide(
        move=GuideMove.HOLD_FOR_DECISION,
        slots=("offer:o1.monthly_price", "offer:o1.fee:activation"),
    ),
)
ACTIONS = tuple(
    f"action number {i}: " + "recorded a fact and a note. " * 32 for i in range(12)
)


@dataclass(frozen=True)
class Case:
    name: str
    profile: str
    bb: Blackboard
    trigger: Trigger
    brief: str

    def view(self) -> FastView:
        build = view_user if self.profile == "pl_user_v1" else view_cp
        return build(self.bb, self.trigger, self.brief)


def _user(name: str, bb: Blackboard, trigger: Trigger) -> Case:
    return Case(name, "pl_user_v1", bb, trigger, USER_BRIEF)


def _cp(name: str, bb: Blackboard, trigger: Trigger, brief: str = CP_BRIEF) -> Case:
    return Case(name, "pl_cp_v1", bb, trigger, brief)


def _public(**update: object) -> PublicState:
    return PUBLIC.model_copy(update=update)


CASES = (
    _user("u01_empty", Blackboard(), Trigger(kind="session_start")),
    _user("u02_user_msg", _bb(), Trigger(kind="user_msg")),
    _user(
        "u03_ask_user",
        _bb().model_copy(
            update=_ask("ASK_USER", "Would a 12-month term at $65.00 a month work?")
        ),
        Trigger(kind="slow_msg", msg_id="s1"),
    ),
    _user(
        "u04_tell_user",
        _bb().model_copy(
            update=_ask("TELL_USER", "The rep is checking for a better offer.")
        ),
        Trigger(kind="slow_msg", msg_id="s1"),
    ),
    _user(
        "u05_approval_card",
        _bb(
            public=_public(
                offers={"o1": CONFIRMED}, status=CaseStatus.AWAITING_APPROVAL
            ),
            private=PRIVATE.model_copy(update={"pending_approval": CARD}),
        ),
        Trigger(kind="approval_card"),
    ),
    _user("u06_over_budget", _bb(user=_long("u", 300)), Trigger(kind="user_msg")),
    _cp("c01_empty", Blackboard(), Trigger(kind="call_connected")),
    _cp("c02_rep_offer", _bb(), Trigger(kind="rep_spoke")),
    _cp(
        "c03_guidance",
        _bb(public=_public(guidance_cp=GUIDES)),
        Trigger(kind="guidance"),
    ),
    _cp(
        "c04_hold_wait",
        _bb(public=_public(cp_hold=HoldState(reason="decision", since_ms=80_000))),
        Trigger(kind="hold_wait", wait_s=10),
    ),
    _cp(
        "c05_readback_confirmed",
        _bb(public=_public(offers={"o1": CONFIRMED})),
        Trigger(kind="rep_spoke"),
    ),
    _cp("c06_over_budget", _bb(cp=_long("c", 300)), Trigger(kind="rep_spoke")),
    _cp(
        "c07_over_budget_actions",
        _bb(public=_public(action_log=ACTIONS)),
        Trigger(kind="rep_spoke"),
    ),
)
