"""``record_offer`` and the read-back slot table it records by (S1-SYS-28, run
ed5063): each field's role (Guard's ``ROLE_OF``), unit (the ledger's ``UNITS``)
and value form. Slow sends a slot as {field, value, utt_ref}; its role and unit
follow from the field (S1-SYS-45), and a slot that sends them is refused. A slot
Guard's read-back or terms code could never confirm or hash is refused when it
is recorded, with this table; it is never repaired (rule 12)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from proxyloop.contract import base
from proxyloop.contract import state as st
from proxyloop.contract.state import READBACK_FIELD, ReadbackSlot
from proxyloop.guard.declass import numbers, spoken
from proxyloop.guard.readback import (  # the read-back's clauses and cues
    LEXICON,
    ROLE_OF,
    _clauses,  # pyright: ignore[reportPrivateUsage]
    _qualifiers,  # pyright: ignore[reportPrivateUsage]
    said,  # the values one clause states for a field
)
from proxyloop.slow.authority import UNITS
from proxyloop.slow.result import Result, no

SCALE = {"usd_minor": 100, "months": 1}  # minor units and months, as spoken
KEYS = ("field", "value", "utt_ref")  # a slot as Slow sends it

_FORM = {  # the value form of each unit, as the read-back and terms code read it
    "usd_minor": "whole cents",
    "months": "whole months",
    "bool": "true|false",
    "iso": "ISO time with zone, ≤ 24 chars, prefer …Z (2026-10-01T00:00:00Z) or none",
}
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # the read-back matches its day
_WHOLE = re.compile(r"[0-9]+")  # usd_minor and months: plain ASCII integers
_NONE = {"fees_none": "fee", "changes_none": "applied_change"}  # flag: its list


def _unit(kind: str) -> str:
    return UNITS.get(kind, "bool")


def _field(kind: str) -> str:  # "fee" -> "fee:<code>"
    return kind if re.fullmatch(READBACK_FIELD, kind) else f"{kind}:<code>"


# S1-SYS-85 (runs dd5094, f828f1): the code is in the terms hash, so it must be
# the rep's name for the fee or credit, never "activation_fee" for "activation".
# The read-back's own word lists; the examples are codes no family uses (rule 12).
_FEE = (*LEXICON["fee"], "charges", *LEXICON["generic_fee"])
GENERIC = {"fee": _FEE, "credit": (*LEXICON["credit"], *_FEE)}  # by the code's kind
EXAMPLE = {  # the rep's words, the code they name
    "fee": "a porting fee is fee:porting",
    "credit": "a paperless credit is credit:paperless",
}
NAMED = (
    "A fee:<code> or credit:<code> is named by the rep's own words in its cited "
    "line, in lower snake_case: each code word is said there as a whole word "
    "and none is a generic word (such as fee, "
    f"charge, credit): {EXAMPLE['fee']}, never fee:porting_fee; "
    f"{EXAMPLE['credit']}, never credit:paperless_credit"
)
TABLE = (
    "; ".join(
        f"{_field(kind)} → {role}, {_unit(kind)}, {_FORM[_unit(kind)]}"
        for kind, role in ROLE_OF.items()
    )
    + f". {NAMED}"
)


CITE = (  # run 84f731: Slow cited the line after the offer
    "Each slot's utt_ref must cite the utt of the rep line that says it; "
    "money is usd_minor in cents (75.00 → 7500), a term is months"
)


def refused(problems: list[str]) -> str:
    return (
        f"record_offer refused, nothing recorded: {'; '.join(problems)}. Each "
        f"slot is {{{', '.join(KEYS)}}}; by field (field → role, unit, value): "
        f"{TABLE}"
    )


def shape(raw: object) -> str | None:
    """Why a raw slot is not {field, value, utt_ref} with the table's field and
    value text; else None. Before binding: "78.00" is refused here, not as a
    declass. A role or unit Slow sends is refused, never checked or dropped."""
    if not isinstance(raw, Mapping):
        return f"a slot is an object, not {raw!r}"
    m = cast(Mapping[str, Any], raw)
    out: list[str] = []
    if extra := sorted(set(m) - set(KEYS)):
        why = "role and unit follow from field; " if {"role", "unit"} & {*extra} else ""
        out.append(
            f"a slot takes no {', '.join(extra)}: {why}send only {', '.join(KEYS)}"
        )
    if form := _form(m.get("field"), m.get("value")):
        out.append(form)
    if not isinstance(ref := m.get("utt_ref"), str):  # A3: never pydantic's loc
        out.append(f"utt_ref is the utt id of the rep line that says it, not {ref!r}")
    return "; ".join(out) or None


def _form(field: object, v: object) -> str | None:
    if not isinstance(field, str) or not re.fullmatch(READBACK_FIELD, field):
        return f"unknown field {field!r}"
    if len(field) > base.MAX_SLOT_FIELD:
        return f"{field} is over {base.MAX_SLOT_FIELD} chars"
    if not isinstance(v, str) or len(v) > base.MAX_SLOT_VALUE:
        return f"{field} value is text of ≤ {base.MAX_SLOT_VALUE} chars, not {v!r}"
    unit = _unit(field.partition(":")[0])
    if unit in SCALE and not _WHOLE.fullmatch(v):
        return f"{field} is {_FORM[unit]}, not {v!r}"
    return None


def conflicts(raw: Sequence[Mapping[str, Any]]) -> list[str]:
    """Slots that no terms hash could bind together (``shape`` passed):
    none, a repeated field, or a ``*_none=true`` beside a slot of its list."""
    fields = [str(s["field"]) for s in raw]
    out = [] if raw else ["no slots"]
    out += [f"{f} repeats" for f in sorted({f for f in fields if fields.count(f) > 1})]
    for s in raw:
        if (kind := _NONE.get(str(s["field"]))) and s["value"] == "true":
            listed = [f for f in fields if f.partition(":")[0] == kind]
            out += [f"{s['field']}=true with {f}" for f in listed]
    return out


def value(slot: ReadbackSlot) -> str | None:
    """Why a slot's value is not in its unit's form; else None. Money and
    months are bound to the rep's line (``record_offer``), not here."""
    v = slot.value
    if slot.unit == "bool" and v not in ("true", "false"):
        return f"{slot.field} is true or false, not {v!r}"
    if slot.unit == "iso" and v != "none" and not _zoned(v):
        return f"{slot.field} is an ISO time with zone or none, not {v!r}"
    return None


def _zoned(v: str) -> bool:
    try:
        at = datetime.fromisoformat(v)
    except ValueError:
        return False
    return at.utcoffset() is not None and _DAY.match(v) is not None


def record_offer(
    bb: st.Blackboard,
    ref: str,
    raw: Sequence[Mapping[str, Any]],
    t_ms: int,
    wall: datetime,
) -> Result:  # every money or term value is one the rep said
    if bad := [p for s in raw if (p := shape(s))]:
        return _invalid(refused(bad))  # whole: no partial record
    if bad := conflicts(raw):
        return _invalid(f"record_offer refused, nothing recorded: {'; '.join(bad)}")
    slots = [st.ReadbackSlot(source_utt=s.get("utt_ref"), **_slot(s)) for s in raw]
    said = {x.utt_id: x.text for x in bb.channels["cp"].lines if x.speaker == "partner"}
    unbound = [
        f"{s.field}={s.value} is not in rep line {s.source_utt}"
        for s in slots
        if (line := said.get(str(s.source_utt))) is None
        or not _value(s) <= spoken(line, s.unit)
    ]
    if unbound:
        text = f"{'; '.join(unbound)}. {CITE}"
        return no(text, ("declass.denied", {"violations": unbound}))
    if bad := [
        p for s in slots for p in _naming(s, said.get(str(s.source_utt), ""), ref)
    ]:
        return _invalid(refused(bad))
    if bad := [p for s in slots if (p := value(s))]:
        return _invalid(refused(bad))
    prev = bb.public.offers.get(ref)
    if (
        prev is not None
        and prev.status == "open"
        and _terms(prev.slots) == _terms(slots)
    ):  # the same terms: the revision and its read-back request stand
        return Result(True, f"unchanged {ref} r{prev.revision}")
    if prev is None and len(bb.public.offers) >= base.MAX_OFFERS:
        return no("too many offers")
    revision = prev.revision + 1 if prev else 1
    offer = st.OfferPublic(offer_ref=ref, revision=revision, slots=tuple(slots))
    recorded = offer.model_dump(mode="json", include={"offer_ref", "revision", "slots"})
    expires = _expires_ms(slots, t_ms, wall)  # the same instant on both clocks
    recorded |= {"terms_hash": None, "expires_ms": expires}  # Guard binds terms
    text = f"recorded {ref} r{revision}" + (
        f", expires at t={expires} ms" if expires else ""
    )
    return Result(True, text, (("offer.recorded", recorded),))


# S1-SYS-87 D2: the code is hashed byte for byte, so it is the world's form
# (lower snake_case) and each of its words, of any length, is a whole word of
# the cited line. Guard's ``_names`` is a prefix match that skips words of ≤ 2
# chars (the read-back's lenient test), so it cannot say "whole word": this is
# the one local matcher. A number is one word ("20.00": '20' is not a word of
# it); known edge, no amount rule: "$20" and "20 dollars" do say the word '20'.
_CODE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
# S1-SYS-87 D3: guard's ``_qualifiers`` (``_QUALIFIED``) reads the words before
# a fee or credit word; the Mouth's template names it after ("fee porting:
# 5.00"), which that helper cannot see, so this mirror reads the word after.
_AFTER = re.compile(r"\b(?:fees?|charges?|credits?|rebates?)\s+([a-z'-]+)")


def _named(slot: st.ReadbackSlot, line: str) -> list[str]:
    """Why a fee or credit code is not the rep's name for it: not lower
    snake_case, a generic word, or a word its cited line does not say as a
    whole word; else []."""
    kind, _, code = slot.field.partition(":")
    if kind not in ("fee", "credit"):
        return []
    if not _CODE.fullmatch(code):
        snake = re.sub(r"[^a-z0-9]+", "_", code.lower()).strip("_")
        return [f"{slot.field}: a code is lower snake_case ({kind}:{snake})"]
    words, out = set(_TOKEN.findall(line.lower())), list[str]()
    for w in code.split("_"):
        if w in GENERIC[kind]:
            out.append(
                f"{slot.field}: '{w}' is a generic word; name a {kind} by the words "
                f"the rep used for it without '{w}' (e.g. {EXAMPLE[kind]})"
            )
        elif w not in words:
            out.append(
                f"{slot.field}: '{w}' is not in the cited line {slot.source_utt} "
                "as a whole word; use the rep's words"
            )
    return out


def _naming(slot: st.ReadbackSlot, line: str, ref: str) -> list[str]:
    """``_named``'s problems; for a code the line refuses anyway, and a fee or
    credit the rep named only by generic words, the one D3 problem instead.
    D3 never refuses a code on its own."""
    out = _named(slot, line)
    if not out or not _unnamed(slot, line):
        return out
    kind = slot.field.partition(":")[0]
    return [
        f"{slot.field}: the rep did not name this {kind} (only generic words): "
        "record_offer the other slots, then guide_fast(ask_readback, "
        f'["offer:{ref}"]) once more; a {kind} must be named by the rep to be '
        "recorded"
    ]


def _unnamed(slot: st.ReadbackSlot, line: str) -> bool:
    """The clauses of ``line`` that state this slot's amount as a fee or credit
    (guard's ``said``) have no naming word: none before the fee word (guard's
    ``_qualifiers``) nor right after it that is not generic."""
    kind = slot.field.partition(":")[0]
    own = [c for _, _, c in _clauses(line.lower()) if slot.value in said(c, kind)]
    after = {w for c in own for w in _AFTER.findall(c)} - set(GENERIC[kind])
    return bool(own) and not after and not any(_qualifiers(c) for c in own)


def _invalid(text: str) -> Result:  # the slots' form, not the rep's words
    return Result(False, text, code="invalid_args")


def _expires_ms(
    slots: Sequence[st.ReadbackSlot], t_ms: int, now: datetime
) -> int | None:
    """The rep's stated expiry on the session clock; ``None`` for "no expiry",
    none stated, or no timezone-aware ISO time (terms need one, §9.1)."""
    found = [s.value for s in slots if s.field == "expires"]
    try:
        at = datetime.fromisoformat(found[0].replace("Z", "+00:00")) if found else None
    except ValueError:
        return None
    if at is None or at.utcoffset() is None:
        return None
    return max(0, t_ms + int((at - now).total_seconds() * 1000))


def _value(s: st.ReadbackSlot) -> set[Decimal]:  # in the unit as spoken
    if s.unit in SCALE:
        return {Decimal(s.value) / SCALE[s.unit]}
    return numbers(s.value)


def _slot(s: Mapping[str, Any]) -> dict[str, Any]:  # role and unit from field
    kind = str(s["field"]).partition(":")[0]
    return {"field": s["field"], "value": s["value"]} | {
        "unit": _unit(kind),
        "role": ROLE_OF[kind],
    }


def _terms(slots: Sequence[st.ReadbackSlot]) -> list[tuple[str, str, str, str]]:
    return sorted((s.field, s.value, s.unit, s.role) for s in slots)
