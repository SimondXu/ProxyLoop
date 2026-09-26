"""Declassification (§5; I4): every public number is source-bound (a rep line or a
shareable value), no protected or non-public mandate value, at most 400 chars."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

from proxyloop.contract.base import MAX_PUBLIC_TEXT
from proxyloop.contract.state import Blackboard, ChannelState

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers(text: str) -> set[Decimal]:  # 1,068.50 is 1068.50
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {Decimal(m) for m in _NUMBER.findall(text)}


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


def declassify(
    text: str, bb: Blackboard, shareable: Mapping[str, str]
) -> tuple[str, ...]:  # none: may go public; shareable: recorded values
    out: list[str] = []
    if len(text) > MAX_PUBLIC_TEXT:
        out.append(f"longer than {MAX_PUBLIC_TEXT} characters")
    public = rep_numbers(bb) | {n for v in shareable.values() for n in numbers(v)}
    said = numbers(text)
    out += [
        f"number {n.normalize():f} is not source-bound" for n in sorted(said - public)
    ]
    leaked = sorted((said & _bounds(bb)) - public)
    out += [f"the private value {n.normalize():f} is not public" for n in leaked]
    for key, fact in sorted(bb.private.case_facts.items()):
        if fact.protected and fact.value in text:
            out.append(f"the protected value of {key}")
    return tuple(out)
