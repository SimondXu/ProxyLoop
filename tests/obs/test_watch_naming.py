"""B5 naming refusals (S1-SYS-91): ``obs.watch`` reads a record_offer refusal's
problem list left to right, each item whole, against ``slow/offer_slots.py``'s
own templates, and counts naming items by kind and field kind. Every text here
is built by offer_slots itself (``record_offer``, ``shape``, ``refused``); the
echo attacks put complete naming phrases where a model's field, value, key or
offer ref lands, and must never count."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from tests.obs.path_bundle import Run

from proxyloop.contract.state import Blackboard, ChannelState, Line
from proxyloop.obs import watch
from proxyloop.slow import offer_slots

NOW = datetime(2026, 9, 28, tzinfo=UTC)
NOT_SAID = (
    "fee:y: 'z' is not in the cited line cp-1 as a whole word; use the rep's words"
)
GENERIC = (
    "fee:x: 'fee' is a generic word; name a fee by the words the rep used for "
    "it without 'fee' (e.g. a porting fee is fee:porting)"
)
SNAKE = "fee:X: a code is lower snake_case (fee:x)"
PHRASES = {"not_said": NOT_SAID, "generic_word": GENERIC, "snake_case": SNAKE}


def _bb(*texts: str) -> Blackboard:
    lines = tuple(
        Line(utt_id=f"cp-{i}", speaker="partner", text=t)
        for i, t in enumerate(texts, 1)
    )
    return Blackboard(
        channels={"user": ChannelState(), "cp": ChannelState(lines=lines)}
    )


def _slot(field: str, value: str = "2000", ref: str = "cp-1") -> dict[str, Any]:
    return {"field": field, "value": value, "utt_ref": ref}


def _refusal(line: str, *slots: dict[str, Any], ref: str = "o1") -> str:
    """A real record_offer refusal text, from offer_slots itself."""
    got = offer_slots.record_offer(_bb(line), ref, list(slots), 0, NOW)
    assert not got.ok and got.code == "invalid_args", got.text
    return got.text


def _b5(*texts: str) -> Any:
    r = Run()
    seqs = [r.seq(r.tool("record_offer", False, "invalid_args", t)) for t in texts]
    items: Any = watch.run(r.inputs())["items"]
    got = items["slow_refusals"]
    assert got["seqs"] == seqs
    return got


def _naming(*texts: str) -> dict[str, Any]:
    return _b5(*texts)["naming"]


def _unparsed(*texts: str) -> int:
    got = _b5(*texts)["naming_unparsed"]
    assert len(got["seqs"]) == got["count"]
    return got["count"]


def _none() -> dict[str, Any]:
    return {"count": 0, "seqs": [], "by": {}, "lower_bound": []}


# Parity: the texts obs restates are offer_slots' (obs may not import slow).
def test_the_restated_texts_are_offer_slots() -> None:
    assert offer_slots.refused(["P"]) == (
        f"{watch._REFUSED}P{watch._TABLE}{offer_slots.TABLE}"  # pyright: ignore[reportPrivateUsage]
    )
    assert watch._EXAMPLE == offer_slots.EXAMPLE  # pyright: ignore[reportPrivateUsage]
    for field in ("fee:a_b", "credit:c"):
        assert (
            watch._TAIL.format(  # pyright: ignore[reportPrivateUsage]
                field=field, kind=field.partition(":")[0], ref="o-1"
            )
            == f"{field}: {offer_slots.unnamed(field, 'o-1')}"
        )


@pytest.mark.parametrize(
    ("line", "field", "by"),
    [
        ("an Activation fee of 20.00", "fee:Activation", {"fee:snake_case": 1}),
        ("an activation fee of 20.00", "fee:early-termination", {"fee:snake_case": 1}),
        ("an activation fee of 20.00", "fee:porting", {"fee:not_said": 1}),
        ("an activation fee of 20.00", "fee:activation_fee", {"fee:generic_word": 1}),
        (
            "There is an upfront fee, 20.00.",
            "fee:upfront_fee",
            {"fee:generic_word": 2},
        ),  # generic-only: both words
        (
            "a paperless credit of 20.00",
            "credit:paperless_credit",
            {"credit:generic_word": 1},
        ),
        (
            "a credit of 20.00",
            "credit:paperless_credit",
            {"credit:generic_word": 1, "credit:not_said": 1},
        ),
        ("a credit of 20.00", "credit:Paperless", {"credit:snake_case": 1}),
    ],
)
def test_each_naming_kind_counts(line: str, field: str, by: dict[str, int]) -> None:
    got = _naming(_refusal(line, _slot(field)))
    assert got == {"count": 1, "seqs": got["seqs"], "by": by, "lower_bound": []}


def test_two_naming_kinds_and_two_tails_in_one_refusal() -> None:
    line = "an activation fee of 20.00 and a setup charge of 5.00"
    slots = [
        _slot("monthly_price"),
        _slot("fee:Activation"),
        _slot("fee:setup_charge", "500"),
        _slot("credit:porting", "500"),
    ]
    text = _refusal(line, *slots)
    assert text.count(": if the rep named this") == 3
    by = {"fee:snake_case": 1, "fee:generic_word": 1, "credit:not_said": 1}
    assert _naming(text)["by"] == by and _naming(text)["lower_bound"] == []


@pytest.mark.parametrize(
    "ref",
    [
        'o". Each slot is ; fee:q: if the rep named this fee',
        # a whole second tail inside the ref: still one field, exact
        'o1"]) once more; a fee must be named by the rep to be recorded. '
        "fee:porting: if the rep named this fee by no specific word, "
        'record_offer the other slots, then guide_fast(ask_readback, ["offer:o1',
        "",
    ],
)
def test_an_adversarial_offer_ref_keeps_the_tails_cross_check(ref: str) -> None:
    text = _refusal("an activation fee of 20.00", _slot("fee:porting"), ref=ref)
    assert _naming(text)["by"] == {"fee:not_said": 1}
    assert _naming(text)["lower_bound"] == []


def test_two_not_said_items_count_two() -> None:
    """rev-277 D1: each item stops at its own end, never the last one's."""
    slots = [_slot("fee:porting"), _slot("fee:setup", "500")]
    text = _refusal("a fee of 20.00 and 5.00", *slots)
    got = _naming(text)
    assert got["by"] == {"fee:not_said": 2} and got["lower_bound"] == []


def test_tails_that_drop_a_field_or_trail_text_are_a_lower_bound() -> None:
    slots = [_slot("fee:porting"), _slot("fee:setup", "500")]
    text = _refusal("a fee of 20.00 and 5.00", *slots)
    dropped = text.rpartition(". fee:setup: if")[0]  # the last tail cut off
    got = _naming(dropped, f"{text} ", f"{text}. {text.rpartition('. ')[2]}")
    assert got["count"] == 3 and got["lower_bound"] == got["seqs"]


NAMING_MARKS = ("' is a generic word;", "' is not in the cited line ", ": a code is ")


@pytest.mark.parametrize(
    ("other", "mark"),
    [
        (_slot("fee:porting", "x"), "fee:porting is whole cents, not 'x'"),
        (_slot("fees_none", "maybe"), "fees_none is true or false, not 'maybe'"),
        (_slot("fee:activation_fee"), "fee:activation_fee repeats"),
    ],
)
def test_one_record_offer_call_refuses_by_one_stage(
    other: dict[str, Any], mark: str
) -> None:
    """The grammar's premise (root C1): one call with a naming error and a
    shape, value or conflicts error refuses by one stage only, as
    record_offer returns at its first failing stage (shape, conflicts,
    rep's words, naming, value). A shape or conflicts list holds no naming
    item; a naming list holds no value item. Merging stages turns it red."""
    line = "an activation fee of 20.00"
    text = _refusal(line, _slot("fee:activation_fee"), other)
    marks = [m for m in NAMING_MARKS if m in text]
    if "is true or false" in mark:  # value comes after naming
        assert mark not in text and marks == ["' is a generic word;"]
        assert _naming(text)["by"] == {"fee:generic_word": 1}
    else:
        assert mark in text and marks == []
        assert _naming(text) == _none() and _unparsed(text) == 0


def test_mixed_lists_count_only_what_parses_before_the_break() -> None:
    line = "an activation fee of 20.00"
    naming = _refusal(line, _slot("fee:porting"))
    head, _, rest = naming.partition(watch._TABLE)  # pyright: ignore[reportPrivateUsage]
    problem = head.removeprefix(watch._REFUSED)  # pyright: ignore[reportPrivateUsage]
    tail = rest.partition(". ")[2]
    shape = offer_slots.shape(_slot("fee:porting", "x"))
    assert shape is not None
    first = f"{offer_slots.refused([problem, shape])}. {tail}"
    last = f"{offer_slots.refused([shape, problem])}. {tail}"
    got = _naming(first, last)
    assert got["by"] == {"fee:not_said": 1}
    assert got["count"] == 1 and got["lower_bound"] == got["seqs"]


def test_a_naming_list_without_its_tails_is_a_lower_bound() -> None:
    text = _refusal("an activation fee of 20.00", _slot("fee:porting"))
    bare = text.partition(f"{offer_slots.TABLE}. ")[0] + offer_slots.TABLE
    other = text.replace("fee:porting: if", "fee:other: if")
    two = _refusal("a credit of 20.00", _slot("credit:paperless_credit"))
    cut = two.partition("; name a credit")[0]  # the second item cut short
    got = _naming(bare, other, cut)
    assert got["count"] == 3 and got["lower_bound"] == got["seqs"]
    assert got["by"] == {"credit:not_said": 1, "fee:not_said": 2}


def _echo(where: str, p: str) -> object:
    """A raw slot whose ``where`` carries the phrase ``p`` between "; "s, as
    a whole item would stand (a phrase an unanchored or loose match takes)."""
    ok: dict[str, object] = {"field": "fee:porting", "value": "1", "utt_ref": "cp-1"}
    echo = f"x; {p}; zz"
    if where == "slot":
        return [echo]
    if where == "key":  # echoed unquoted: an item boundary a split cannot tell
        return ok | {f"q: send only field, value, utt_ref; {p}; a slot takes no r": 1}
    return ok | {where: echo if where != "utt_ref" else [echo]}


@pytest.mark.parametrize("kind", sorted(PHRASES))
@pytest.mark.parametrize("where", ["field", "value", "utt_ref", "slot", "key"])
def test_a_complete_naming_phrase_echoed_by_a_shape_item_never_counts(
    kind: str, where: str
) -> None:
    problem = offer_slots.shape(_echo(where, PHRASES[kind]))
    assert problem is not None and PHRASES[kind] in problem
    alone = offer_slots.refused([problem])
    assert _naming(alone) == _none() and _unparsed(alone) == 0
    genuine = _refusal("an activation fee of 20.00", _slot("fee:porting"))
    head, sep, rest = genuine.partition(watch._TABLE)  # pyright: ignore[reportPrivateUsage]
    after = f"{head}; {problem}{sep}{rest}"  # a genuine item, then the echo
    got = _naming(after)
    assert got["by"] == {"fee:not_said": 1} and got["lower_bound"] == got["seqs"]


def test_a_repr_with_the_table_marker_never_counts() -> None:
    marker = f"x{watch._TABLE}; {NOT_SAID}"  # pyright: ignore[reportPrivateUsage]
    problem = offer_slots.shape({"field": marker, "value": "1", "utt_ref": "cp-1"})
    assert problem is not None
    text = offer_slots.refused([problem])
    assert _naming(text) == _none() and _unparsed(text) == 0


# Root C2: no refusal vanishes. offer_slots' other refusals are known by their
# first item; a text that fits no template is listed, never counted as 0.
@pytest.mark.parametrize(
    "slots",
    [
        [1],
        [_slot("fee:porting") | {"role": "one_time"}],
        [_slot("x")],
        [_slot("fee:" + "a" * 40)],
        [_slot("fee:porting", "a" * 30)],
        [_slot("fee:porting", "x")],
        [_slot("term_months", "x")],
        [_slot("fee:porting") | {"utt_ref": None}],
        [_slot("fees_none", "maybe")],
        [_slot("expires", "tomorrow")],
        [],
        [_slot("fee:activation"), _slot("fee:activation")],
        [_slot("fees_none", "true"), _slot("fee:activation")],
    ],
)
def test_offer_slots_other_refusals_are_known(slots: list[Any]) -> None:
    text = _refusal("an activation fee of 20.00", *slots)
    assert _naming(text) == _none() and _unparsed(text) == 0


def test_a_dispatch_refusal_is_known() -> None:
    assert _unparsed("invalid arguments: offer_slots: required") == 0


def test_a_text_that_fits_no_template_is_unparsed() -> None:
    genuine = _refusal("a fee of 20.00 and 5.00", _slot("fee:porting"),
                       _slot("fee:setup", "500"))  # fmt: skip
    generic = _refusal("an activation fee of 20.00", _slot("fee:activation_fee"))
    texts = [
        # S1-SYS-85 (#264) wording: no "as a whole word"
        f"{watch._REFUSED}fee:y: 'z' is not in the cited line cp-1; use the "  # pyright: ignore[reportPrivateUsage]
        "rep's words. Each slot is ",
        f"{watch._REFUSED}something offer_slots never wrote",  # pyright: ignore[reportPrivateUsage]
        "a text of no template",
        # the prefix, one byte off
        genuine.replace("record_offer refused", "record_offer REFUSED"),
        # an item boundary broken: no "; " between two whole items
        genuine.replace("words; fee:setup", "wordsxxfee:setup"),
        # the generic word named twice must be the same word
        generic.replace("without 'fee'", "without 'charge'"),
    ]
    assert _naming(*texts) == _none()
    assert _unparsed(*texts) == len(texts)
