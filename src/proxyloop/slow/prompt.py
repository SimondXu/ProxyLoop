"""Slow's system prompt, its one forced tool ``act`` (ADR-0001 Decision 4:
structured output is one forced tool call) and its context notes (§8)."""

from __future__ import annotations

from proxyloop.contract import base
from proxyloop.contract.llm import ToolSpec
from proxyloop.contract.messages import FastToSlow, GuideMove
from proxyloop.contract.state import OfferPublic
from proxyloop.contract.views import SlowView
from proxyloop.guard.readback import missing_required, readback_status
from proxyloop.slow.tools import identity_hint

TOOLS = (
    *("ask_user", "tell_user", "wait", "guide_fast", "record_fact", "record_offer"),
    *("share_fact", "propose_mandate", "tighten_mandate", "revoke"),
    *("request_approval", "accept_offer", "decline_offer", "check_account", "finish"),
)
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
"offer:<ref>.<field>" and must already be public. It takes no text: the phone \
voice never gets free text from you.
- record_fact(key, value, utt_ref): a fact with the utt of the relay it came from. \
Use the canonical key from SHAREABLE FACT KEYS when the fact is one of them, \
whatever the relay called it. A value the representative said in that utt becomes \
public. From the user, only a *.last4 key (exactly 4 digits) or a *.holder_name key \
(the name as the user wrote it) from SHAREABLE FACT KEYS becomes public, when the \
cited user message contains exactly that value; anything else stays private.
- share_fact(key): make a recorded shareable fact public, by the rule of record_fact.
- record_offer(offer_ref, offer_slots): the offer's terms as the representative said \
them, each slot {field, value, unit, role, utt_ref}; money in cents (usd_minor). \
Then guide_fast(ask_readback, ["offer:<ref>"]) for that revision: its slots turn \
[confirmed] in the status bar when the representative repeats them after it. Only a \
confirmed offer can be approved or accepted.
- propose_mandate(envelope): the limits the user stated (max_monthly_price_minor, \
max_term_months, max_one_time_fees_minor, required_features, forbidden_changes); it \
grants nothing until the user decides it.
- tighten_mandate(changes): stricter limits, never looser; the user re-grants them. \
revoke(reason): withdraw every grant at once, e.g. when the user says stop.
- request_approval(offer_ref): ask the user to approve a confirmed offer; the chat \
voice shows the card. accept_offer(offer_ref): accept a confirmed offer that a \
granted mandate covers or the user approved; the phone voice says a fixed line. \
decline_offer(offer_ref, reason): decline it.
- check_account(confirmation_id): after the representative confirms an accept, \
look up the confirmation id they said, exactly as a [REP CALL] relay gave it.
- finish(outcome, summary): end the case. "completed" once the account binds the \
accepted terms; "no_deal" after guide_fast(ask_final_offer) and the \
representative's final answer, with every offer declined; "info_only" when the task \
is only to report the offers to the user (accept nothing); "escalate" when a failed \
accept cannot be replanned.
Calls run in order, so a guide_fast may cite a fact recorded earlier in the same act.
Identity: when the representative asks for a fact the user has not given yet (e.g. \
the account holder name or last 4), ask_user for it and guide_fast(hold_for_fact) \
so the representative waits while the phone voice gets it from the user. As soon as \
the user gives it, record_fact it and, in the same act, guide_fast(identify, \
slots=["fact:<key>", ...]). Use deflect_fact_request only for a fact that must not \
be given: the representative hears a refusal and may hang up.
A rep_turn or heartbeat wake without a new [REP CALL] note means nothing was \
relayed; read the status bar and act or wait.
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
_WHOLE = {"type": "integer", "minimum": 0}
_WORDS = {"type": "array", "items": S}
_ENVELOPE: Schema = {
    "type": "object",
    "properties": {
        **dict.fromkeys(
            ("max_monthly_price_minor", "max_term_months", "max_one_time_fees_minor"),
            _WHOLE,
        ),
        **dict.fromkeys(("required_features", "forbidden_changes"), _WORDS),
    },
}
_CALL = {
    **dict(text=S, key=S, value=S, utt_ref=S, offer_ref=S, summary=S, reason=S),
    **dict(confirmation_id=S),
    **dict(envelope=_ENVELOPE, changes=_ENVELOPE),
    **dict(tool=_enum(*TOOLS), move=_enum(*GuideMove)),
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


def note(relay: FastToSlow) -> str:  # [USER CHAT] <relay> (utt u12)
    where = "USER CHAT" if relay.lane == "user" else "REP CALL"
    facts = "; ".join(f"{k}={v}" for k, v in relay.facts)
    body = " ".join(p for p in (relay.type.lower(), facts, relay.text) if p)
    return f"[{where}] {body} (utt {relay.utt_ref or 'none'})"


def status_bar(view: SlowView, keys: frozenset[str], now_ms: int) -> str:
    """Case status, epoch, offers (slot statuses, read-back, TTL), mandate,
    approvals, fences, hold and strikes, and the facts Slow recorded (§8)."""

    def secs(t_ms: int) -> str:
        return f"{max(0, t_ms - now_ms) // 1000} s"

    def offer(o: OfferPublic) -> str:
        ttl = "" if o.expires_ms is None else f", expires in {secs(o.expires_ms)}"
        gaps = missing_required(o)
        gap = f", missing {' '.join(gaps)}" if gaps else ""
        slots = ", ".join(f"{s.field}={s.value} [{s.status}]" for s in o.slots)
        state = f"{o.status}, read-back {readback_status(o)}{ttl}{gap}"
        return f"{o.offer_ref} r{o.revision} ({state}): {slots}"

    facts = "; ".join(
        [f"{f.key}={f.value} [public]" for f in view.public_facts]
        + [f"{f.key}={f.value} [private]" for f in view.case_facts]
    )
    m = view.mandate
    mandate = "none" if m is None else f"{m.mandate_id} {m.status} (epoch {m.epoch})"
    card = view.pending_approval
    approvals = [f"{a.approval_id} {a.decision}" for a in view.approvals]
    if card is not None:
        approvals.append(
            f"{card.approval_id} for {card.offer_ref} r{card.revision} pending, "
            f"expires in {secs(card.expires_ms)}"
        )
    hold = view.cp_hold
    held = (
        "none"
        if hold is None
        else f"{hold.reason} for {(now_ms - hold.since_ms) // 1000} s"
    )
    public = {f.key for f in view.public_facts}
    private = {f.key for f in view.case_facts}
    hint = identity_hint(public, keys, private)
    return (
        f"[STATUS] case {view.status.value}; epoch {view.epoch}; "
        f"offers: {'; '.join(map(offer, view.offers)) or 'none'}; "
        f"mandate: {mandate}; approvals: {', '.join(approvals) or 'none'}; "
        f"fences raised: {len(view.fences)}; facts: {facts or 'none'}; "
        f"hold: {held}; strikes: {view.cp_strikes}"
    ) + (f"; {hint}" if hint else "")
