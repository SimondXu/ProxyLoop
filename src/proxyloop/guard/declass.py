"""Declassification (§5; I4): every public number is source-bound (a rep line or a
shareable value), no protected or non-public mandate value, at most 400 chars."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal

from proxyloop.contract.base import MAX_PUBLIC_TEXT
from proxyloop.contract.state import Blackboard, ChannelState

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers(text: str) -> set[Decimal]:  # 1,068.50 is 1068.50
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {Decimal(m) for m in _NUMBER.findall(text)}


_UNIT = {  # a value of this unit, as a rep says it: "$75", "75.00", "12 months"
    "usd_minor": r"\$\s?(\d+(?:\.\d+)?)|(\d+\.\d\d)\b|(\d+(?:\.\d+)?)\s*dollars?\b",
    "months": r"(\d+)\s*-?\s*months?\b",
}


def spoken(text: str, unit: str) -> set[Decimal]:  # in dollars for usd_minor
    if unit not in _UNIT:
        return numbers(text)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    found = re.finditer(_UNIT[unit], text, re.IGNORECASE)
    return {Decimal(g) for m in found for g in m.groups() if g}


def rep_numbers(bb: Blackboard) -> set[Decimal]:
    lines = bb.channels.get("cp", ChannelState()).lines
    return {
        n for line in lines if line.speaker == "partner" for n in numbers(line.text)
    }


def _bounds(bb: Blackboard) -> set[Decimal]:
    m = bb.private.mandate
    if m is None:
        return set()
    minor = (m.max_monthly_price_minor, m.max_one_time_fees_minor)
    out = {Decimal(v) / 100 for v in minor if v is not None}
    return out | ({Decimal(m.max_term_months)} if m.max_term_months else set())


_LETTERS = re.compile(r"[^\W\d_]+")  # letters of any script


def _words(text: str) -> str:  # "O'Brien" -> "o brien"
    return " ".join(_LETTERS.findall(unicodedata.normalize("NFKC", text).casefold()))


def _letters(text: str) -> str:  # "O'Brien" -> "obrien"
    return _words(text).replace(" ", "")


def _digits(text: str) -> str:  # "77-77", fullwidth 7777 -> "7777"; any script
    text = unicodedata.normalize("NFKC", text)
    return "".join(str(unicodedata.decimal(c)) for c in text if c.isdecimal())


def _overlap(a: str, b: str) -> bool:  # either contains the other
    return bool(a and b and (a in b or b in a))


def _canon(text: str) -> tuple[str, str, str]:
    return _words(text), _letters(text), _digits(text)


def _protected(bb: Blackboard) -> list[tuple[str, tuple[str, str, str]]]:
    facts = sorted(bb.private.case_facts.items())
    return [(key, _canon(f.value)) for key, f in facts if f.protected]


def _shareable_numbers(bb: Blackboard, shareable: Mapping[str, str]) -> set[Decimal]:
    """Numbers of the recorded shareable values, less any mandate bound or protected
    value's digits: a shareable value never whitelists either (#126)."""
    secret = {Decimal(d) for _, (_, _, d) in _protected(bb) if d}
    return {n for v in shareable.values() for n in numbers(v)} - _bounds(bb) - secret


def declassify(
    text: str, bb: Blackboard, shareable: Mapping[str, str]
) -> tuple[str, ...]:  # none: may go public; shareable: recorded values
    out: list[str] = []
    if len(text) > MAX_PUBLIC_TEXT:
        out.append(f"longer than {MAX_PUBLIC_TEXT} characters")
    public = rep_numbers(bb) | _shareable_numbers(bb, shareable)
    said = numbers(text)
    out += [
        f"number {n.normalize():f} is not source-bound" for n in sorted(said - public)
    ]
    leaked = sorted((said & _bounds(bb)) - public)
    out += [f"the private value {n.normalize():f} is not public" for n in leaked]
    words, letters, digits = _canon(text)  # the forms of slow.tools._leaks
    for key, (theirs, their_letters, their_digits) in _protected(bb):
        if (
            _overlap(words, theirs)
            or _overlap(letters, their_letters)
            or _overlap(digits, their_digits)
        ):
            out.append(f"the protected value of {key}")
    return tuple(out)
