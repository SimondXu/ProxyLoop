"""Slow's system prompt, its one forced tool ``act`` (ADR-0001 Decision 4:
structured output is one forced tool call) and its context notes (§8)."""

from __future__ import annotations

from proxyloop.contract import base
from proxyloop.contract.llm import ToolSpec
from proxyloop.contract.messages import FastToSlow, GuideMove
from proxyloop.contract.views import SlowView

TOOLS = ("ask_user", "tell_user", "wait", "guide_fast", "record_fact", "record_offer")
MAX_TOKENS = 1_500
SYSTEM = """You are the case agent behind an AI assistant that works for a user. \
Two voices act for you: a chat voice that talks with the user, and a phone voice on \
a live call with a company representative. You never hear either conversation. You \
learn what was said only from their relay notes ([USER CHAT] and [REP CALL], each \
with an utt reference) and from your own tool results.

Every turn, call `act` once. `private_summary` (required) is your case digest for \
the user-side voice. `public_summary` (optional) is all the phone voice knows about \
the case: it may contain only numbers the representative said or values of the \
shareable facts you recorded; anything else is refused. `calls` lists your actions:
- ask_user(text) / tell_user(text): the chat voice passes it to the user.
- wait(seconds 1-15): wake me again after that long if nothing else happens.
- guide_fast(move, slots): steer the phone voice; slots are "fact:<key>" or \
"offer:<ref>.<field>" and must already be public.
- record_fact(key, value, utt_ref): a fact with the utterance it came from.
- record_offer(offer_ref, offer_slots): the offer's terms as the representative said \
them, each slot {field, value, unit, role, utt_ref}; money in cents (usd_minor).
- finish(outcome, summary): end the case. Only outcome "info_only" exists here: \
report the offers to the user first, and never accept anything.
Tool results come back as text; a refusal says why."""

Schema = dict[str, object]
S: Schema = {"type": "string"}


def _obj(required: str, **properties: object) -> Schema:
    return {"type": "object", "properties": properties, "required": required.split()}


def _enum(*values: str) -> Schema:
    return {"enum": list(values)}


_UNIT = _enum("usd_minor", "months", "bool", "iso")
_ROLE = _enum("recurring", "one_time", "credit", "change", "feature", "expiry")
_SLOT = _obj(
    "field value unit role", field=S, value=S, unit=_UNIT, role=_ROLE, utt_ref=S
)
_CALL = {
    **dict(text=S, key=S, value=S, utt_ref=S, offer_ref=S, summary=S),
    **dict(tool=_enum(*TOOLS, "finish"), move=_enum(*GuideMove)),
    **dict(slots={"type": "array", "items": S}),
    **dict(offer_slots={"type": "array", "items": _SLOT}),
    **dict(seconds={"type": "integer", "minimum": 1, "maximum": 15}),
    **dict(outcome=_enum("info_only", "completed", "no_deal", "escalate")),
}
ACT = ToolSpec(
    name="act",
    description="Your summaries and actions for this turn.",
    parameters=_obj(
        "private_summary calls",
        private_summary=S | {"maxLength": base.MAX_PRIVATE_SUMMARY},
        public_summary=S | {"maxLength": base.MAX_PUBLIC_TEXT},
        calls={"type": "array", "items": _obj("tool", **_CALL)},
    ),
)


def note(relay: FastToSlow) -> str:
    """One relay as Slow reads it: ``[USER CHAT] <relay> (utt u12)``."""

    where = "USER CHAT" if relay.lane == "user" else "REP CALL"
    facts = "; ".join(f"{k}={v}" for k, v in relay.facts)
    body = " ".join(p for p in (relay.type.lower(), facts, relay.text) if p)
    return f"[{where}] {body} (utt {relay.utt_ref or 'none'})"


def status_bar(view: SlowView) -> str:
    offers = "; ".join(
        f"{o.offer_ref} r{o.revision} {o.status}: "
        + ", ".join(f"{s.field}={s.value} [{s.status}]" for s in o.slots)
        for o in view.offers
    )
    hold = view.cp_hold.reason if view.cp_hold is not None else "none"
    return (
        f"[STATUS] case {view.status.value}; epoch {view.epoch}; "
        f"offers: {offers or 'none'}; hold: {hold}; strikes: {view.cp_strikes}"
    )
