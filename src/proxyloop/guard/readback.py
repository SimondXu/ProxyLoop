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
                 "doesn't", "won't", "cannot", "can't", "don't", "never"),
    "fees_none": ("no fees", "no fee", "no activation fee", "no one-time fee",
                  "no additional fees", "no extra fees", "no upfront cost", "fee-free"),
    "changes_none": ("no other changes", "nothing else changes", "no changes",
                     "everything else stays the same", "nothing else"),
    "change": ("switch", "switching", "change your", "changing your", "upgrade",
               "upgrading", "downgrade", "move you", "moving you", "adding",
               "remove", "removing", "replace", "replacing"),
    "generic_fee": ("a", "an", "the", "one-time", "one", "time", "upfront",
                    "additional", "extra", "any", "no", "this", "that", "total",
                    "flat", "small", "monthly", "is", "of"),  # not a fee's code
    "expiry": ("expire", "expires", "valid until", "good until", "valid for",
               "good for", "available until"),
    "no_expiry": ("no expiry", "no expiration", "does not expire", "doesn't expire",
                  "never expires", "no deadline"),
    "closing": (  # regex sources: the rep's final position, or the call's end
        r"best and final", r"final offer",  # names the offer as the last one
        # refuses to improve on the offer ("I cannot do any better")
        r"(?:cannot|can't|can not|unable to|not able to) (?:do|go|offer) "
        r"(?:any(?:thing)? )?(?:better|lower)",
        # states the offer is the best there is ("that is our best offer")
        r"is (?:already |really |still )?(?:our|my|the) (?:absolute |very )?best "
        r"(?:available )?(?:offer|rate|price|deal)",
        r"no better", r"nothing more",  # nothing beyond the offer
        r"transfer",  # hands the call on: this rep's position ends
        r"goodbye", r"ending the call", r"have a (?:great|good|nice) day",  # farewell
    ),
    # before a closing cue in its clause: a condition, a hedge, a check still to
    # make or someone else's (or an earlier) words, not the rep's position now
    "unsure": ("if", "whether", "see", "check", "think", "sure", "said", "told",
               "maybe", "might", "may", "earlier", "confirm", "verify", "believe",
               "guess", "perhaps", "probably", "whichever"),
    # after a closing cue in its sentence: a condition, time limit or concession
    # means the position is not final ("I can't do better unless ...")
    "unless": ("unless", "until", "without", "yet", "except", "before", "but",
               "however", "if", "might", "may", "maybe", "check"),
    "wh": ("what", "which"),  # right before a cue: "what's the best offer"
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
UNDATED = "date?"  # a spoken expiry that names no calendar day: matches no slot

_SPLIT = re.compile(
    r"[;!?]|\.(?!\d)|,(?!\d{3})|\b(?:and(?!\s+\d{1,2}\s*cents?)|but|plus|with)\b",
    re.I,
)
_MONEY = re.compile(
    r"(?P<d>\d+)\s*dollars?\s+(?:and\s+)?(?P<c>\d{1,2})\s*cents?\b"
    r"|\$\s?(?P<a>\d+(?:\.\d+)?)|(?P<b>\d+\.\d\d)\b|(?P<e>\d+(?:\.\d+)?)\s*dollars?\b",
    re.I,
)
_MONTH = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
          "dec")  # fmt: skip
_M = rf"(?P<{{}}>{'|'.join(_MONTH)})[a-z]*\.?"
_DATE = re.compile(
    rf"(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})|{_M.format('m1')}\s+(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"|\b(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_M.format('m2')}"
)
_UNTIL = re.compile(r"expir\w*\s+(?:until|till|before)\b")
_QUALIFIED = re.compile(r"((?:[a-z'-]+\s+){0,2})(?:fees?|charges?|credits?|rebates?)\b")
_MONTHS = re.compile(r"(\d+)\s*-?\s*months?\b", re.I)
_WORD = re.compile(r"[a-z'-]+")


_CUES = {
    kind: re.compile(
        "|".join(
            rf"(?<![a-z])(?:{c if kind == 'closing' else re.escape(c)})(?![a-z])"
            for c in cues
        )
    )
    for kind, cues in LEXICON.items()
}
_SENTENCE = re.compile(r"(?<=[!?])|(?<=\.)(?!\d)")
_IS = re.compile(r"\b(that|this|it|here|what)'s\b")  # "that's" is "that is"
_FLOOR = re.compile(r"\s*than\s+\$?\d")  # "can't go lower than 50": a floor


def _tokens(text: str) -> set[str]:
    """Words, with hyphenated ones split too ("double-check" is "check")."""
    return {p for w in _WORD.findall(text) for p in (w, *w.split("-"))}


def has_cue(text: str, kind: str) -> bool:
    if kind == "closing":
        return _closing(text)
    return _CUES[kind].search(text.lower()) is not None


def _closing(text: str) -> bool:
    """A closing cue in a sentence that asks nothing (a question states no
    position), with no negation or ``unsure`` word in its clause before it,
    no ``wh`` word right before it, no ``unless`` word in its sentence after
    it, and no ``than <number>`` right after it."""
    t = _IS.sub(r"\1 is", text.lower().replace("\u2019", "'"))
    for sentence in _SENTENCE.split(t):
        if sentence.rstrip().endswith("?"):
            continue
        for m in _CUES["closing"].finditer(sentence):
            start = max((b.end() for b in _SPLIT.finditer(sentence, 0, m.start())),
                        default=0)  # fmt: skip
            words = _WORD.findall(sentence[start : m.start()])
            before, after = _tokens(sentence[start : m.start()]), sentence[m.end() :]
            off = set(LEXICON["negation"]) | set(LEXICON["unsure"])
            if (
                not (words and words[-1] in LEXICON["wh"])
                and not any(w in off or w.endswith("n't") for w in before)
                and not _tokens(after) & set(LEXICON["unless"])
                and not _FLOOR.match(after)
            ):
                return True
    return False


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
        if months:
            value = m.group(1)
        elif m.group("d"):
            value = str(int(m.group("d")) * 100 + int(m.group("c")))
        else:
            value = str(
                int(Decimal(m.group("a") or m.group("b") or m.group("e")) * 100)
            )
        found.add("none" if _negated(clause, m.start(), m.end()) else value)
    return found


def _date(clause: str) -> str:
    """The calendar day a clause names ("MM-DD"), else ``UNDATED``."""
    days = set[str]()
    for m in _DATE.finditer(clause):
        if m.group("iso"):
            days.add(m.group("iso")[5:])
        else:
            month = _MONTH.index(m.group("m1") or m.group("m2")) + 1
            days.add(f"{month:02d}-{int(m.group('d1') or m.group('d2')):02d}")
    return days.pop() if len(days) == 1 else UNDATED


def _qualifiers(clause: str) -> set[str]:
    """Words naming a fee or credit ("early termination fee"), generic ones out."""
    near = {w for m in _QUALIFIED.finditer(clause) for w in m.group(1).split()}
    return near - set(LEXICON["generic_fee"])


def _words(field: str) -> list[str]:
    code = field.partition(":")[2].lower()
    return [w for w in re.split(r"[_.:-]", code) if len(w) > 2]


def _names(clause: str, field: str) -> bool:
    return all(re.search(rf"\b{re.escape(w)}", clause) for w in _words(field))


def _flags(none_said: bool, contradicted: bool) -> set[str]:
    return {v for v, on in (("true", none_said), ("false", contradicted)) if on}


def said(clause: str, field: str, others: Mapping[str, str] | None = None) -> set[str]:
    """The values one rep clause states for ``field``; empty if it is silent.
    ``others``: the offer's other slots of this kind (field: value). A fee or
    credit clause that names no code ("the fee is $30") speaks to this one
    unless its value is one of the others'."""
    c = re.sub(r"(?<=\d),(?=\d{3}\b)", "", clause.lower())  # $1,068.50
    kind, _, code = field.partition(":")
    words, others = _words(field), others or {}
    negated = bool(set(_WORD.findall(c)) & set(LEXICON["negation"]))
    money = kind in ("fee", "credit")  # generic: it names no fee or credit at all
    generic = money and not _names(c, field) and not _qualifiers(c)
    if code and not generic and not _names(c, field):
        return set()
    if field == "fees_none":
        paid = "one_time" in _roles(c) and _amounts(c, False) - {"none"}
        return _flags(has_cue(c, "fees_none"), bool(paid))
    if field == "changes_none":
        changed = has_cue(c, "change") and not negated
        return _flags(has_cue(c, "changes_none"), changed)
    if field == "expires":
        if has_cue(c, "no_expiry") and not _UNTIL.search(c):
            return {"none"}
        return {_date(c)} if has_cue(c, "expiry") or has_cue(c, "no_expiry") else set()
    if kind in ("applied_change", "feature"):
        return {"false" if negated else "true"} if words else set()
    if field == "term_months":
        return _amounts(c, True)
    if ROLE_OF.get(kind) not in _roles(c):
        return set()
    stated = _amounts(c, False)
    if not stated and negated:
        stated = {"none"}  # "no activation fee"
    return set() if generic and stated <= set(others.values()) else stated


def _key(slot: ReadbackSlot) -> str:
    if slot.field != "expires" or slot.value == "none":
        return slot.value
    day = _DATE.search(slot.value)
    return day.group("iso")[5:] if day and day.group("iso") else UNDATED + "slot"


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
    """Confirmed iff the required fields exist, none repeats, and every slot is
    confirmed."""
    done = all(s.status == "confirmed" for s in offer.slots)
    unique = len({s.field for s in offer.slots}) == len(offer.slots)
    ok = done and unique and not missing_required(offer)
    return "confirmed" if ok else "unconfirmed"


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
