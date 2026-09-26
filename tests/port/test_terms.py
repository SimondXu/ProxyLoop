from __future__ import annotations

import json
import string
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from proxyloop.guard.terms import Fee, Terms, terms_hash, terms_hash_v1

V0 = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "v0" / "terms_hash_v1.json"
    ).read_text("utf-8")
)


def test_fixture_covers_every_v0_catalogue_scenario() -> None:
    covered: dict[str, set[str]] = {}
    for row in V0["rows"]:
        if row["catalogue"] == "synthetic":
            continue
        covered.setdefault(row["catalogue"], set()).add(row["scenario_id"])
    assert {name: len(ids) for name, ids in covered.items()} == V0["scenario_counts"]
    assert V0["scenario_counts"] == {"negotiation-v1": 22, "benchmark-v1": 26}
    assert V0["benchmark_v1_scenarios_without_offer"] == 6


@pytest.mark.parametrize(
    "row", V0["rows"], ids=[f"{r['scenario_id']}/{r['offer']}" for r in V0["rows"]]
)
def test_terms_hash_v1_equals_v0_material_terms_hash(row: dict[str, Any]) -> None:
    inputs = row["inputs"]

    def digest() -> str:
        return terms_hash_v1(
            monthly_price_minor=inputs["monthly_price_minor"],
            total_cost_12_months_minor=inputs["total_cost_12_months_minor"],
            currency=inputs["currency"],
            term_months=inputs["term_months"],
            features=inputs["features"],
            offer_expires_at=datetime.fromisoformat(inputs["offer_expires_at"]),
        )

    if "error" in row:
        with pytest.raises(ValueError):
            digest()
    else:
        assert digest() == row["material_terms_hash"]


_tokens = st.text(alphabet=string.ascii_lowercase + "_:,", min_size=1, max_size=8)
# Lists are multisets: no ``unique=True``, so duplicates are drawn too.
_fee_lines = st.lists(st.builds(Fee, _tokens, st.integers(0, 10**6)), max_size=3).map(
    tuple
)
_offsets = st.integers(-14 * 60, 14 * 60).map(lambda m: timezone(timedelta(minutes=m)))
terms_strategy = st.builds(
    Terms,
    monthly_price_minor=st.integers(0, 10**6),
    currency=st.sampled_from(["USD", "EUR", "GBP"]),
    term_months=st.integers(0, 36),
    features=st.lists(_tokens, max_size=4).map(tuple),
    fees=_fee_lines,
    credits=_fee_lines,
    applied_changes=st.lists(_tokens, max_size=4).map(tuple),
    total_cost_12m_minor=st.integers(0, 10**7),
    offer_id=_tokens,
    offer_revision=st.integers(0, 10),
    expires_at=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2040, 1, 1),
        timezones=_offsets,
    ),
)

# One or more single-field mutations per ``Terms`` field; "~" is outside the
# token alphabet, so an added item is always new.
_NEW = "~new"


def _duplicate(new: object) -> Callable[[Any], Any]:
    """Repeat the first item (a multiset change), or add ``new`` if empty."""

    return lambda v: (*v, v[0]) if v else (new,)


_MUTATIONS: dict[str, list[Callable[[Any], Any]]] = {
    "monthly_price_minor": [lambda v: v + 1],
    "currency": [lambda v: "JPY" if v != "JPY" else "USD"],
    "term_months": [lambda v: v + 1],
    "features": [lambda v: (*v, _NEW), _duplicate(_NEW)],
    "fees": [
        lambda v: (*v, Fee(_NEW, 1)),
        _duplicate(Fee(_NEW, 1)),
        lambda v: (
            (replace(v[0], amount_minor=v[0].amount_minor + 1), *v[1:])
            if v
            else (Fee(_NEW, 0),)
        ),
    ],
    "credits": [
        lambda v: (*v, Fee(_NEW, 1)),
        _duplicate(Fee(_NEW, 1)),
        lambda v: (
            (replace(v[0], amount_minor=v[0].amount_minor + 1), *v[1:])
            if v
            else (Fee(_NEW, 0),)
        ),
    ],
    "applied_changes": [lambda v: (*v, _NEW), _duplicate(_NEW)],
    "total_cost_12m_minor": [lambda v: v + 1],
    "offer_id": [lambda v: v + "~"],
    "offer_revision": [lambda v: v + 1],
    "expires_at": [lambda v: v + timedelta(seconds=1)],
}


def test_every_terms_field_has_a_mutation() -> None:
    assert set(_MUTATIONS) == {field.name for field in fields(Terms)}


@given(terms_strategy)
def test_changing_any_single_field_changes_the_hash(terms: Terms) -> None:
    original = terms_hash(terms)
    for name, mutations in _MUTATIONS.items():
        for mutate in mutations:
            changed = replace(terms, **{name: mutate(getattr(terms, name))})
            assert terms_hash(changed) != original, name


@given(terms_strategy, st.data())
def test_hash_is_order_insensitive(terms: Terms, data: st.DataObject) -> None:
    shuffled = replace(
        terms,
        features=tuple(data.draw(st.permutations(terms.features))),
        fees=tuple(data.draw(st.permutations(terms.fees))),
        credits=tuple(data.draw(st.permutations(terms.credits))),
        applied_changes=tuple(data.draw(st.permutations(terms.applied_changes))),
    )
    assert terms_hash(shuffled) == terms_hash(terms)


_BASE = Terms(
    monthly_price_minor=7_200,
    currency="USD",
    term_months=12,
    features=("mobile_hotspot",),
    fees=(),
    credits=(),
    applied_changes=("plan_change",),
    total_cost_12m_minor=86_400,
    offer_id="offer-1",
    offer_revision=1,
    expires_at=datetime(2026, 8, 23, 13, 0, tzinfo=UTC),
)


def test_fees_and_credits_are_distinct() -> None:
    line = Fee("activation", 500)
    assert terms_hash(replace(_BASE, fees=(line,))) != terms_hash(
        replace(_BASE, credits=(line,))
    )


def test_naive_expires_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_BASE, expires_at=datetime(2026, 8, 23, 13, 0))


def test_same_instant_in_any_offset_hashes_identically() -> None:
    plus_two = _BASE.expires_at.astimezone(timezone(timedelta(hours=2)))
    shifted = replace(_BASE, expires_at=plus_two)
    assert shifted.expires_at.tzinfo is UTC
    assert shifted == _BASE
    assert terms_hash(shifted) == terms_hash(_BASE)
