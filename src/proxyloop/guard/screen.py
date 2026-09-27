"""The speech screen (ARCHITECTURE §9.3; defence in depth): a filter over
protected values (in any spelling, as declass) and mandate numbers not already
public, run on cp-lane Fast sentences before release. A value that is both a
public offer and a private bound is speakable."""

from __future__ import annotations

from decimal import Decimal

from proxyloop.contract.state import Blackboard
from proxyloop.guard.declass import (
    numbers,
    protected_keys,
    rep_numbers,
    shareable_numbers,
)
from proxyloop.guard.mandate import bound_numbers

_PER_UNIT = {"usd_minor": 100, "months": 1}


def _public(bb: Blackboard) -> set[Decimal]:
    """Rep-said numbers, source-bound offer slots, and shareable values less any
    bound or protected value (the declass rule)."""
    facts = bb.public.facts.values()
    shared = {f.key: f.value for f in facts if f.source == "shareable"}
    said = {n for f in facts if f.source == "cp_utt" for n in numbers(f.value)}
    out = rep_numbers(bb) | said | shareable_numbers(bb, shared)
    for offer in bb.public.offers.values():
        out |= {
            Decimal(s.value) / _PER_UNIT[s.unit]
            for s in offer.slots
            if s.unit in _PER_UNIT and s.value.isdigit()
        }
    return out


def screen(text: str, bb: Blackboard) -> tuple[str, ...]:
    """What ``text`` may not say on the cp lane (empty: speakable)."""
    out = [f"protected:{key}" for key in protected_keys(text, bb)]
    m = bb.private.mandate
    if m is not None:
        leaked = (numbers(text) & bound_numbers(m)) - _public(bb)
        out += [f"mandate:{n.normalize():f}" for n in sorted(leaked)]
    return tuple(out)
