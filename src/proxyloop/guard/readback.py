"""Read-back slots (ARCHITECTURE §9.2): when a rep line states a slot's value.

Lexical and conservative. A rep line splits into clauses; a clause states a
value for a field only through that field's role cue, and a negation cue
within 4 tokens of the value turns it into "none". A slot is ``heard`` in its
own ``source_utt``, and ``confirmed`` once a rep clause at or after the
read-back request states exactly its value and no later clause states another.
``LEXICON`` is the one data table; the root calibrates it against real FastC
cp transcripts, and the Ear audit measures its errors (EVAL §9).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from proxyloop.contract.state import Line, OfferPublic, ReadbackSlot
from proxyloop.guard.terms import offer_terms_hash

Status = Literal["unknown", "heard", "confirmed"]

LEXICON: dict[str, tuple[str, ...]] = {
    "recurring": ("per month", "a month", "/mo", "/month", "monthly", "each month",
                  "every month", "month to month"),
    "one_time": ("one-time", "one time", "activation", "upfront", "setup",
                 "installation"),
    "fee": ("fee", "fees", "charge"),  # one-time unless a recurring cue is present
    "credit": ("credit", "credits", "rebate"),
    "negation": ("no", "not", "without", "waived", "waive", "waiving", "isn't",
                 "doesn't", "won't"),
    "fees_none": ("no fees", "no fee", "no activation fee", "no one-time fee",
                  "no additional fees", "no extra fees", "no upfront cost", "fee-free"),
    "changes_none": ("no other changes", "nothing else changes", "no changes",
                     "everything else stays the same", "nothing else"),
    "expiry": ("expire", "expires", "valid until", "good until", "valid for",
               "good for", "available until"),
    "no_expiry": ("no expiry", "no expiration", "does not expire", "doesn't expire",
                  "never expires", "no deadline"),
    "closing": ("best and final", "final offer", "cannot do better",
                "can't do better", "no better", "nothing more", "transfer",
                "goodbye", "ending the call"),
}  # fmt: skip
ROLE_OF = {  # the role a slot of each field kind must carry
    "monthly_price": "recurring",
    "term_months": "recurring",
    "fee": "one_time",
    "fees_none": "one_time",
    "credit": "credit",
    "applied_change": "change",
    "changes_none": "change",
    "feature": "feature",
    "expires": "expiry",
}
DATED = "dated"  # any non-"none" expiry: a spoken date is not normalised

_SPLIT = re.compile(r"[;!?]|\.(?!\d)|,(?!\d{3})|\b(?:and|but|plus|with)\b", re.I)
_MONEY = re.compile(
    r"\$\s?(\d+(?:\.\d+)?)|(\d+\.\d\d)\b|(\d+(?:\.\d+)?)\s*dollars?\b", re.I
)
_MONTHS = re.compile(r"(\d+)\s*-?\s*months?\b", re.I)
_WORD = re.compile(r"[a-z'-]+")


_CUES = {
    kind: re.compile("|".join(rf"(?<![a-z]){re.escape(c)}(?![a-z])" for c in cues))
    for kind, cues in LEXICON.items()
}


def has_cue(text: str, kind: str) -> bool:
    return _CUES[kind].search(text.lower()) is not None


def _clauses(text: str) -> list[tuple[int, int, str]]:
    out, start = list[tuple[int, int, str]](), 0
    for m in _SPLIT.finditer(text):
        out.append((start, m.start(), text[start : m.start()]))
        start = m.end()
    return [*out, (start, len(text), text[start:])]


def _negated(clause: str, start: int, end: int) -> bool:
    near = _WORD.findall(clause[:start])[-4:] + _WORD.findall(clause[end:])[:4]
    return bool(set(near) & set(LEXICON["negation"]))


def _roles(clause: str) -> set[str]:
    recurring = has_cue(clause, "recurring")
    one_time = has_cue(clause, "one_time") or (has_cue(clause, "fee") and not recurring)
    roles = {"recurring"} if recurring else set[str]()
    roles |= {"one_time"} if one_time else set()
    return roles | ({"credit"} if has_cue(clause, "credit") else set())


def _amounts(clause: str, months: bool) -> set[str]:
    """Values in the clause, in minor units or months; a negated one is "none"."""
    found: set[str] = set()
    for m in (_MONTHS if months else _MONEY).finditer(clause):
        number = Decimal(next(g for g in m.groups() if g))
        value = str(int(number if months else number * 100))
        found.add("none" if _negated(clause, m.start(), m.end()) else value)
    return found


def _words(field: str) -> list[str]:
    code = field.partition(":")[2].lower()
    return [w for w in re.split(r"[_.:-]", code) if len(w) > 2]


def _names(clause: str, field: str) -> bool:
    return all(re.search(rf"\b{re.escape(w)}", clause) for w in _words(field))


def said(clause: str, field: str, others: Mapping[str, str] | None = None) -> set[str]:
    """The values one rep clause states for ``field``; empty if it is silent.
    ``others``: the offer's other slots of this kind (field: value). A fee or
    credit clause that names no code ("the fee is $30") speaks to this one
    unless its value is one of the others'."""
    c, others = clause.lower(), others or {}
    kind, _, code = field.partition(":")
    words = _words(field)
    generic = bool(code) and kind in ("fee", "credit") and not _names(c, field)
    if generic and any(_names(c, f) for f in others):
        return set()
    if code and not generic and not _names(c, field):
        return set()
    if field == "fees_none":
        if has_cue(c, "fees_none"):
            return {"true"}
        paid = "one_time" in _roles(c) and _amounts(c, False) - {"none"}
        return {"false"} if paid else set()
    if field == "changes_none":
        return {"true"} if has_cue(c, "changes_none") else set()
    if field == "expires":
        if has_cue(c, "no_expiry"):
            return {"none"}
        return {DATED} if has_cue(c, "expiry") else set()
    if kind in ("applied_change", "feature"):
        negated = set(_WORD.findall(c)) & set(LEXICON["negation"])
        return {"false" if negated else "true"} if words else set()
    if field == "term_months":
        return _amounts(c, True)
    if ROLE_OF.get(kind) not in _roles(c):
        return set()
    stated = _amounts(c, False)
    if not stated and set(_WORD.findall(c)) & set(LEXICON["negation"]):
        stated = {"none"}  # "no activation fee"
    return set() if generic and stated <= set(others.values()) else stated


def _key(slot: ReadbackSlot) -> str:
    return DATED if slot.field == "expires" and slot.value != "none" else slot.value


def slot_status(
    slot: ReadbackSlot,
    lines: Sequence[Line],
    asked_at: int | None,
    others: Mapping[str, str] | None = None,
) -> Status:
    """``lines`` is the cp transcript; ``asked_at`` the index of its first line
    after the read-back request for this revision (``None``: not asked);
    ``others`` as in ``said``."""
    kind = slot.field.partition(":")[0]
    if ROLE_OF.get(kind) != slot.role:
        return "unknown"
    want = {_key(slot)}
    stated = [
        (i, line.utt_id, start, end, values)
        for i, line in enumerate(lines)
        if line.speaker == "partner"
        for start, end, clause in _clauses(line.text)
        if (values := said(clause, slot.field, others))
    ]
    if asked_at is not None:
        later = [values for i, *_, values in stated if i >= asked_at]
        first = next((n for n, values in enumerate(later) if values == want), None)
        if first is not None and all(values == want for values in later[first:]):
            return "confirmed"
    span = slot.span
    heard = any(
        utt == slot.source_utt and values == want
        and (span is None or start <= span[0] <= end)
        for _, utt, start, end, values in stated
    )  # fmt: skip
    return "heard" if heard else "unknown"


def slot_statuses(
    offer: OfferPublic, lines: Sequence[Line], asked_at: int | None
) -> dict[str, Status]:
    def others(slot: ReadbackSlot) -> dict[str, str]:
        kind = slot.field.partition(":")[0]
        same = [s for s in offer.slots if s.field.partition(":")[0] == kind]
        return {s.field: s.value for s in same if s.field != slot.field}

    return {s.field: slot_status(s, lines, asked_at, others(s)) for s in offer.slots}


def readback_update(
    offer: OfferPublic, lines: Sequence[Line], asked_at: int | None
) -> dict[str, object]:
    """The ``readback.updated`` payload Guard emits on a rep ``utt.final``."""
    return {
        "offer_ref": offer.offer_ref,
        "revision": offer.revision,
        "slot_statuses": slot_statuses(offer, lines, asked_at),
        "terms_hash": offer_terms_hash(offer),
    }


def missing_required(offer: OfferPublic) -> tuple[str, ...]:
    fields = {s.field for s in offer.slots}
    kinds = {f.partition(":")[0] for f in fields}
    out = [f for f in ("monthly_price", "term_months", "expires") if f not in fields]
    if "fee" not in kinds and "fees_none" not in fields:
        out.append("fee:*|fees_none")
    if "applied_change" not in kinds and "changes_none" not in fields:
        out.append("applied_change:*|changes_none")
    return tuple(out)


def readback_status(offer: OfferPublic) -> Literal["confirmed", "unconfirmed"]:
    """Confirmed iff the required fields exist and every slot is confirmed."""
    done = all(s.status == "confirmed" for s in offer.slots)
    return "confirmed" if done and not missing_required(offer) else "unconfirmed"


def _spoken(slot: ReadbackSlot) -> str:
    if slot.unit == "usd_minor" and slot.value.isdigit():
        return f"${int(slot.value) // 100}.{int(slot.value) % 100:02d}"
    if slot.unit == "months":
        return f"{slot.value} months"
    return (
        "no expiry" if slot.field == "expires" and slot.value == "none" else slot.value
    )


def readback_text(offer: OfferPublic) -> str:
    """The terms, as Guard writes them on a card or an accept line."""
    return "; ".join(
        f"{s.field.replace('_', ' ').replace(':', ' ')} {_spoken(s)}"
        for s in offer.slots
    )
