"""The speech screen (ARCHITECTURE §9.3; defence in depth): an exact-match filter
over protected values and mandate numbers not already public, run on cp-lane
Fast sentences before release. A value that is both a public offer and a
private bound is speakable."""

from __future__ import annotations

from decimal import Decimal

from proxyloop.contract.state import Blackboard
from proxyloop.guard.declass import numbers, rep_numbers
from proxyloop.guard.mandate import bound_numbers

_SCALE = {"usd_minor": 100, "months": 1}


def _public(bb: Blackboard) -> set[Decimal]:
    out = rep_numbers(bb) | {
        n for f in bb.public.facts.values() for n in numbers(f.value)
    }
    for offer in bb.public.offers.values():
        out |= {
            Decimal(s.value) / _SCALE[s.unit]
            for s in offer.slots
            if s.unit in _SCALE and s.value.isdigit()
        }
    return out


def screen(text: str, bb: Blackboard) -> tuple[str, ...]:
    """What ``text`` may not say on the cp lane (empty: speakable)."""
    out = [
        f"protected:{key}"
        for key, fact in sorted(bb.private.case_facts.items())
        if fact.protected and fact.value and fact.value in text
    ]
    m = bb.private.mandate
    if m is not None:
        leaked = (numbers(text) & bound_numbers(m)) - _public(bb)
        out += [f"mandate:{n.normalize():f}" for n in sorted(leaked)]
    return tuple(out)
