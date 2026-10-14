"""Read-back slots (ARCHITECTURE §9.2): when a rep line states a slot's value.

Lexical and conservative. A rep line splits into clauses; a clause states a
value for a field only through that field's role cue, and a negation cue
within 4 tokens of the value turns it into "none". A slot is ``heard`` in its
own ``source_utt``, and ``confirmed`` once a rep clause at or after the
read-back request states exactly its value and no later clause states another,
or when one read-back window of the offer confirms every slot (ADR-0020).
The "none" fields are read per sentence: ``guard.negation`` decides by scope
whether it denies fees, changes or an expiry; each clause still contradicts.
``LEXICON`` is the one data table; the root calibrates it against real FastC
cp transcripts, and the Ear audit measures its errors (EVAL §9).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Literal, NamedTuple

from proxyloop.contract.state import Line, OfferPublic, ReadbackSlot
from proxyloop.guard import negation as neg
from proxyloop.guard.negation import continues, denied, scan
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
    "change": ("switch", "switching", "change your", "changing your", "upgrade",
               "upgrading", "downgrade", "move you", "moving you", "adding",
               "remove", "removing", "replace", "replacing"),
    "generic_fee": ("a", "an", "the", "one-time", "one", "time", "upfront",
                    "additional", "extra", "any", "no", "this", "that", "total",
                    "flat", "small", "monthly", "is", "of"),  # not a fee's code
    "expiry": ("expire", "expires", "valid until", "good until", "valid for",
               "good for", "available until"),
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
    # after a closing cue in the utterance: a condition, time limit or concession
    # means the position is not final ("I can't do better unless ...")
    "unless": ("unless", "until", "without", "yet", "except", "before", "but",
               "however", "if", "might", "may", "maybe", "check", "though",
               "although", "supervisor", "manager", "escalate", "approval"),
    "wh": ("what", "which"),  # right before a cue: "what's the best offer"
    "reopen": (  # regex sources, S1-SYS-113: after the closing reply, a rep line
        # that makes or names an offer ("I can waive", "a loyalty promotion")
        r"(?:i|we)(?: can| could|'d| would| will|'ll)(?: also| still| actually)?"
        r" (?:do|offer|give|waive|drop|lower|reduce|apply|add|include|match|try"
        r"|extend|throw)",
        r"waiv(?:e|ed|ing)", r"discounts?", r"promo(?:tion)?s?", r"rebates?",
        r"(?:another|new|better|lower|special|different|loyalty|one more) "
        r"(?:offer|deal|option|plan|price|rate)",
        r"how about", r"what about", r"what if", r"instead",
        # or takes the close back ("actually", "let me check")
        r"actually", r"let me (?:check|see|look|ask|talk|speak|find)",
        r"hold on", r"on second thought", r"reconsider",
    ),
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
_QUALIFIED = re.compile(r"((?:[a-z'-]+\s+){0,2})(?:fees?|charges?|credits?|rebates?)\b")
_MONTHS = re.compile(r"(\d+)\s*-?\s*months?\b", re.I)
_WORD = re.compile(r"[a-z'-]+")


_RAW = ("closing", "reopen")  # their cues are regex sources
_CUES = {
    kind: re.compile(
        "|".join(
            rf"(?<![a-z])(?:{c if kind in _RAW else re.escape(c)})(?![a-z])"
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
    return _CUES[kind].search(text.lower().replace("\u2019", "'")) is not None


def _closing(text: str) -> bool:
    """A closing cue in a sentence that asks nothing (a question states no
    position), with no negation or ``unsure`` word in its clause before it,
    no ``wh`` word right before it, no ``unless`` word after it in the rest
    of the utterance (questions aside), and no ``than <number>`` right after it."""
    t = _IS.sub(r"\1 is", text.lower().replace("\u2019", "'"))
    said = [x for x in _SENTENCE.split(t) if not x.rstrip().endswith("?")]
    for i, sentence in enumerate(said):
        for m in _CUES["closing"].finditer(sentence):
            start = max((b.end() for b in _SPLIT.finditer(sentence, 0, m.start())),
                        default=0)  # fmt: skip
            words = _WORD.findall(sentence[start : m.start()])
            before, after = _tokens(sentence[start : m.start()]), sentence[m.end() :]
            off = set(LEXICON["negation"]) | set(LEXICON["unsure"])
            if (
                not (words and words[-1] in LEXICON["wh"])
                and not any(w in off or w.endswith("n't") for w in before)
                and not _tokens(" ".join([after, *said[i + 1 :]]))
                & set(LEXICON["unless"])
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


_NOUNS = frozenset[str]().union(
    *neg.ROLE_WORDS.values()
)  # the "none" fields' role nouns
_LISTS = frozenset({"or", "nor"})  # a noun before them heads a list item, not a stop


def _stops(words: Sequence[str]) -> bool:
    """Another field's role noun with no "or"/"nor" after it in ``words``."""
    return any(
        w in _NOUNS and not _LISTS & {*words[j + 1 :]} for j, w in enumerate(words)
    )


def _negated(clause: str, start: int, end: int, months: bool = False) -> bool:
    """A negation cue within 4 tokens of the value. A months value is out of
    the reach of a cue before it when another field's role noun stands
    between them ("no fees for a 12-month term", S1-SYS-115), unless a list
    goes on to it ("no fees or 12-month contract")."""
    before, after = _WORD.findall(clause[:start])[-4:], _WORD.findall(clause[end:])[:4]
    no = set(LEXICON["negation"])
    reach = (
        w in no and not (months and _stops(before[k + 1 :]))
        for k, w in enumerate(before)
    )
    return any(reach) or bool(set(after) & no)


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
        found.add("none" if _negated(clause, m.start(), m.end(), months) else value)
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


_QUALIFIED_BY = neg.TIMES | neg.BOUNDS | neg.CONDITIONS | neg.RESTRICTIONS


def _expires(sentence: str) -> set[str]:
    """A sentence's expiry: "none" if it denies one; the day of each clause
    that speaks of one (an expiry cue, a role word it states plainly, or a
    void denial that may still end: "won't expire until Friday"). A void
    denial says nothing (S1-SYS-115), as void fees and changes do, only when
    the sentence has no time, bound, condition or restriction word and no
    clause after the denial's ("no expiry date at the end of the term")."""
    hits = scan(sentence, "expires")
    out = {"none"} if denied(sentence, "expires") else set[str]()
    qualified = bool({*_WORD.findall(sentence.lower())} & _QUALIFIED_BY)
    for start, end, clause in _clauses(sentence):
        mine = {h.state for h in hits if start <= h.start < end}
        rest = _WORD.findall(sentence[end:])  # the clauses after this one
        timed = "void" in mine and (qualified or bool(rest))
        if _DATE.search(clause) and (mine or has_cue(clause, "expiry")):
            out.add(_date(clause))
        elif "plain" in mine or timed or (has_cue(clause, "expiry") and not mine):
            out.add(UNDATED)
    return out


def said(clause: str, field: str, others: Mapping[str, str] | None = None) -> set[str]:
    """The values one rep clause states for ``field``; empty if it is silent.
    For ``NONE_FIELDS`` it is a sentence (``guard.negation``), read per clause.
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
    parts = [part for *_, part in _clauses(c)]
    if field == "fees_none":
        paid = any("one_time" in _roles(p) and _amounts(p, False) - {"none"}
                   for p in parts)  # fmt: skip
        return _flags(denied(c, "fees"), paid)
    if field == "changes_none":
        no = set(LEXICON["negation"])
        changed = any(
            has_cue(p, "change") and not no & set(_WORD.findall(p)) for p in parts
        )
        return _flags(denied(c, "changes"), changed)
    if field == "expires":
        return _expires(c)
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


Stated = list[tuple[int, str, int, int, set[str]]]  # line, utt, span, values
NONE_FIELDS = ("fees_none", "changes_none", "expires")  # read per sentence


def _units(text: str, field: str) -> list[tuple[int, int, str]]:
    """``said``'s spans: clauses, or sentences ("No fees. Except ..." is one)."""
    if field not in NONE_FIELDS:
        return _clauses(text)
    cuts = [0, *(m.start() for m in _SENTENCE.finditer(text)), len(text)]
    out = list[tuple[int, int]]()
    for a, b in ((a, b) for a, b in pairwise(cuts) if a < b):
        out = [*out[:-1], (out[-1][0], b)] if out and continues(text[a:b]) else [
            *out, (a, b)]  # fmt: skip
    return [(a, b, text[a:b]) for a, b in out]


def _stated(
    field: str, lines: Sequence[Line], others: Mapping[str, str] | None = None
) -> Stated:
    """Every rep clause (sentence: NONE_FIELDS) stating ``field``, in order."""
    return [
        (i, line.utt_id, start, end, values)
        for i, line in enumerate(lines)
        if line.speaker == "partner"
        for start, end, clause in _units(line.text, field)
        if (values := said(clause, field, others))
    ]


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
    return _status(slot, _stated(slot.field, lines, others), asked_at)


def _status(slot: ReadbackSlot, stated: Stated, asked_at: int | None) -> Status:
    want = {_key(slot)}
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


def _implied(offer: OfferPublic) -> dict[str, str]:
    """The completeness flags a revision implies without a slot: fees_none is
    false if it lists a fee, changes_none if it lists an applied change."""
    fields = {s.field for s in offer.slots}
    kinds = {f.partition(":")[0] for f in fields}
    flags = (("fees_none", "fee"), ("changes_none", "applied_change"))
    return {f: "false" for f, kind in flags if kind in kinds and f not in fields}


_VALUES = ("monthly_price", "term_months")  # and a named fee's amount ("fee:<code>")


def _theirs(field: str, values: set[str], rivals: Sequence[OfferPublic]) -> bool:
    """A statement about another offer (S1-SYS-115): a value field's one value
    is a rival's for ``field``. Implied flags are never credited (Tier C: the
    fee said may be this offer's own); W1/W3 still need r's exact values."""
    if len(values) != 1 or not (field in _VALUES or field.startswith("fee:")):
        return False
    (value,) = values
    return any(s.field == field and _key(s) == value for o in rivals for s in o.slots)


class Ask(NamedTuple):
    """A read-back request for some revision of an offer."""

    at: int  # the index of the first cp line after it
    terms: Mapping[str, str]  # the asked revision's slots (record_offer's binding)


def _unchanged(ask: Ask, offer: OfferPublic) -> bool:
    """W2': every field the asked revision and ``offer`` both carry has one
    value in both, as Guard recorded them (no lexicon)."""
    return all(ask.terms.get(s.field, s.value) == s.value for s in offer.slots)


def _mine(
    want: str, stated: Stated, field: str, rivals: Sequence[OfferPublic]
) -> Stated:
    """``stated`` without the statements about another offer (W2 only)."""
    return [x for x in stated if x[4] == {want} or not _theirs(field, x[4], rivals)]


def _anchors(
    ask: int,
    slots: Sequence[tuple[str, Stated, Stated]],
    implied: Sequence[tuple[str, Stated]],
) -> bool:
    """W1-W4 for one ask (ADR-0020); ``slots``: (value, stated, stated without
    the statements about another offer); ``implied``: (value, stated). Only W2
    ignores another offer's statements: after the ask every one counts."""
    after = [[(i, v) for i, *_, v in s if i >= ask] for _, s, _ in slots]
    if not after or not all(after):  # W3: every slot restated since the ask
        return False
    top = max(xs[0][0] for xs in after)  # the last slot first stated since
    for (want, _, mine), xs in zip(slots, after, strict=True):
        before = [v for i, *_, v in mine if i < ask]
        if any(v != {want} for _, v in xs):  # W1: stable since the ask
            return False
        if before and before[-1] != {want}:  # W2: no change across the ask
            return False
        if xs[-1][0] < top:  # W3: stated together
            return False
    return all(  # W1, the implied flags
        v == {want} for want, s in implied for i, *_, v in s if i >= ask
    )


def slot_statuses(
    offer: OfferPublic,
    lines: Sequence[Line],
    asked_at: int | None,
    asks: Sequence[Ask] = (),
    rivals: Sequence[OfferPublic] = (),
) -> dict[str, Status]:
    """Each slot's status: today's rule from this revision's ``asked_at``, or
    confirmed with all others by one ask in ``asks`` (every read-back request
    for any revision of the offer in this call) for which W1-W4 and W2' hold,
    if no required field is missing (ADR-0020). ``rivals``: the other recorded
    offers, any status; W2 ignores statements about them (S1-SYS-115).
    Recomputed from the transcript each time."""

    def others(slot: ReadbackSlot) -> dict[str, str]:
        kind = slot.field.partition(":")[0]
        same = [s for s in offer.slots if s.field.partition(":")[0] == kind]
        return {s.field: s.value for s in same if s.field != slot.field}

    def status(slot: ReadbackSlot, stated: Stated) -> Status:
        if ROLE_OF.get(slot.field.partition(":")[0]) != slot.role:
            return "unknown"
        return "confirmed" if window else _status(slot, stated, asked_at)

    stated = [_stated(s.field, lines, others(s)) for s in offer.slots]
    roles = all(ROLE_OF.get(s.field.partition(":")[0]) == s.role for s in offer.slots)
    slots = [
        (_key(s), x, _mine(_key(s), x, s.field, rivals))
        for s, x in zip(offer.slots, stated, strict=True)
    ]
    implied = [(v, _stated(f, lines)) for f, v in _implied(offer).items()]
    window = (
        roles
        and not missing_required(offer)  # a partial revision never takes the window
        and any(_unchanged(a, offer) and _anchors(a.at, slots, implied) for a in asks)
    )
    return {s.field: status(s, x) for s, x in zip(offer.slots, stated, strict=True)}


def readback_update(
    offer: OfferPublic,
    lines: Sequence[Line],
    asked_at: int | None,
    asks: Sequence[Ask] = (),
    rivals: Sequence[OfferPublic] = (),
) -> dict[str, object]:
    """The ``readback.updated`` payload Guard emits on a rep ``utt.final``."""
    return {
        "offer_ref": offer.offer_ref,
        "revision": offer.revision,
        "slot_statuses": slot_statuses(offer, lines, asked_at, asks, rivals),
        "terms_hash": offer_terms_hash(offer),
    }


def missing_required(offer: OfferPublic) -> tuple[str, ...]:
    """The fields a revision must record to be complete. ``expires`` is not
    one (S1-SYS-113, ADR-0033): an offer stays open for the call (ADR-0031);
    an ``expires`` slot that is recorded must still be confirmed."""
    fields = {s.field for s in offer.slots}
    kinds = {f.partition(":")[0] for f in fields}
    out = [f for f in ("monthly_price", "term_months") if f not in fields]
    if "fee" not in kinds and "fees_none" not in fields:
        out.append("fee:*|fees_none")
    if "applied_change" not in kinds and "changes_none" not in fields:
        out.append("applied_change:*|changes_none")
    return tuple(out)


def readback_status(offer: OfferPublic) -> Literal["confirmed", "unconfirmed"]:
    """Confirmed iff the required fields exist, none repeats, and every slot is
    confirmed (a recorded ``expires`` too)."""
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
