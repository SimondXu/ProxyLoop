"""S1-SYS-88 Part 2: the Mouth's code-word fidelity (from #264). A coded term
(``fee:``, ``feature:``, ``applied_change:``) is faithful only when each word
of its code is said as a whole word, the same whole word as Slow's
``record_offer`` needs (slow/offer_slots.py ``_TOKEN``, S1-SYS-87 D2); else the
Mouth regenerates, then says its template, flagged."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.env.bus_sink import BusSink

from proxyloop.env.counterparty import mouth as mouth_module
from proxyloop.env.counterparty.mouth import Mouth, fidelity_ok, template
from proxyloop.env.counterparty.policy import PublicIntent
from proxyloop.env.tasks.loader import FAMILIES, load_task
from proxyloop.slow import offer_slots

CP = load_task("cp-direct-discount").counterparty
READBACK = PublicIntent(
    kind="readback",
    offer_ref="loyal-1",
    say=(
        ("monthly_price", "75.00"),
        ("term_months", "12"),
        ("fee:activation", "20.00"),
    ),
)


def test_the_whole_word_is_the_one_slow_binds_by() -> None:
    """Implemented locally (env never imports slow), pinned to Slow's rule."""
    word = mouth_module._WORD  # pyright: ignore[reportPrivateUsage]
    token = offer_slots._TOKEN  # pyright: ignore[reportPrivateUsage]
    assert word.pattern == token.pattern


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("It's $75 a month for 12 months, plus a $20 activation fee.", True),
        ("$75 a month for 12 months, and a one-time ACTIVATION charge of $20.", True),
        ("$75 a month for 12 months; activation-fee: $20.", True),  # '-' splits
        ("It's $75 a month for 12 months, plus a one-time $20 fee.", False),
        ("$75 a month for 12 months, plus $20 for activating the line.", False),
        ("$75 a month for 12 months, plus a $20 reactivation fee.", False),
        ("$75 a month for 12 months, plus $20 in activations.", False),
    ],
)
def test_a_fee_code_word_must_be_said_as_a_whole_word(text: str, ok: bool) -> None:
    assert fidelity_ok(text, READBACK) is ok


def test_every_word_of_a_multi_word_code_is_needed() -> None:
    intent = PublicIntent(
        kind="readback",
        say=(("fee:early_termination", "150.00"), ("applied_change:plan_swap", "true")),
    )
    both = "There's a $150 early termination fee, and we apply a plan swap."
    assert fidelity_ok(both, intent)
    assert not fidelity_ok("There's a $150 termination fee and a plan swap.", intent)
    assert not fidelity_ok("A $150 early termination fee, and a swap.", intent)
    assert fidelity_ok(template(intent, "Northwind"), intent)


def test_a_feature_code_word_is_needed_too() -> None:
    intent = PublicIntent(kind="readback", say=(("feature:hotspot", "true"),))
    assert fidelity_ok("It includes a hotspot.", intent)
    assert not fidelity_ok("It includes tethering.", intent)


def test_uncoded_terms_need_no_word() -> None:
    """Only coded keys: the price, the term and ``*_none`` flags keep the
    number rule alone (``test_world``)."""
    intent = PublicIntent(
        kind="readback",
        say=(("monthly_price", "75.00"), ("fees_none", "true"), ("expires", "none")),
    )
    assert fidelity_ok("Just $75 a month, nothing else.", intent)


def _coded_offers() -> list[tuple[str, PublicIntent]]:
    out: list[tuple[str, PublicIntent]] = []
    for path in sorted(FAMILIES.glob("*.yaml")):
        base = load_task(path.stem)
        modes = [None, *(m for m in ("full", "info_only") if m != base.mode)]
        for mode in modes:
            try:
                task = load_task(path.stem, mode=mode)
            except ValueError:  # no such variant
                continue
            for spec in task.counterparty.ladder:
                if any(":" in k for k in spec.all_terms):
                    say = tuple(spec.all_terms.items())
                    intent = PublicIntent(kind="readback", say=say)
                    out.append((f"{task.id}/{spec.offer_ref}", intent))
    return out


def test_the_template_says_every_family_code_word() -> None:
    """The fallback itself passes: every coded term of every family offer."""
    offers = _coded_offers()
    codes = {k for _, i in offers for k, _ in i.say if ":" in k}
    assert {"fee:activation", "fee:installation"} <= codes  # not vacuous
    for where, intent in offers:
        assert fidelity_ok(template(intent, CP.company), intent), where


def test_a_rephrasing_without_the_code_word_is_regenerated(tmp_path: Path) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("ok").event_id
    lines = [
        "It's $75 a month for 12 months, with a one-time $20 fee.",
        "It's $75 a month for 12 months, with a $20 activation fee.",
    ]
    mouth = Mouth(sink.llm(*lines), sink.world, CP)
    text, _ = asyncio.run(mouth.say(READBACK, "ok", cause))
    (rep_mouth,) = sink.of("rep.mouth")
    assert text == lines[1]
    assert (rep_mouth.payload["fidelity_ok"], rep_mouth.payload["attempts"]) == (
        True,
        2,
    )


def test_never_saying_the_code_word_falls_back_to_the_flagged_template(
    tmp_path: Path,
) -> None:
    sink = BusSink(tmp_path)
    cause = sink.heard("ok").event_id
    line = "It's $75 a month for 12 months, with a one-time $20 fee."
    mouth = Mouth(sink.llm(*[line] * 3), sink.world, CP)
    text, _ = asyncio.run(mouth.say(READBACK, "ok", cause))
    (rep_mouth,) = sink.of("rep.mouth")
    assert text == template(READBACK, CP.company)
    assert "fee activation: 20.00" in text
    assert (rep_mouth.payload["fidelity_ok"], rep_mouth.payload["attempts"]) == (
        False,
        3,
    )
