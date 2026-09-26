"""Declassification: what may enter public state (ARCHITECTURE §5; I4).

Text written into public state (a ``public_summary``, a public fact, an offer
slot) passes only if every number in it is source-bound (said by the rep in a
cp ``utt.final``, or the value of an allow-listed shareable fact), it carries
no protected value and no mandate bound that is not already public, and it is
at most 400 characters. Semantic leakage without numbers is measured, not
blocked (EVAL §7).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

from proxyloop.contract.base import MAX_PUBLIC_TEXT
from proxyloop.contract.state import Blackboard, ChannelState

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers(text: str) -> set[Decimal]:
    """The numbers written as digits (``1,068.50`` is 1068.50), as values."""

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
) -> tuple[str, ...]:
    """The violations; empty when ``text`` may enter public state.
    ``shareable``: the recorded values of allow-listed shareable facts."""

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
