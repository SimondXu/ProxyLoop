"""``pl.terms/3``: fee and change completeness is explicit and hashed
(S1-SYS-19). Terms whose completeness is unstated or contradictory are unknown,
so they can be neither authorised nor bound by a ledger."""

from __future__ import annotations

import hashlib
import json

import pytest
from tests.guard.build import CASE, board, confirm, mandate, offer, slot

from proxyloop.contract.state import OfferPublic
from proxyloop.guard.authorize import accept_offer
from proxyloop.guard.readback import readback_status
from proxyloop.guard.terms import offer_terms, offer_terms_hash, terms_hash_v2

FEES_NONE = slot("fees_none", "true", "bool", "one_time")
CHANGES_NONE = slot("changes_none", "true", "bool", "change")


def _with(o: OfferPublic, *extra: object, drop: tuple[str, ...] = ()) -> OfferPublic:
    kept = tuple(s for s in o.slots if s.field not in drop)
    return o.model_copy(update={"slots": (*kept, *extra)})


def _sha256(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_hash_states_fee_and_change_completeness() -> None:
    """sha256 of the canonical JSON of every ``pl.terms/2`` field plus the
    ``fees_none`` and ``changes_none`` booleans."""
    base: dict[str, object] = {
        "monthly_price_minor": 6800,
        "currency": "USD",
        "term_months": 24,
        "features": [],
        "credits": [],
        "offer_id": "o1",
        "offer_revision": 1,
        "expires_at": "9999-12-31T23:59:59Z",
    }
    fee = {"fees": [{"code": "activation", "amount_minor": 2000}], "fees_none": False}
    listed = base | fee | {"applied_changes": [], "changes_none": True}
    assert offer_terms_hash(offer()) == _sha256(
        listed | {"total_cost_12m_minor": 83600}
    )
    none: dict[str, object] = {"fees": [], "fees_none": True}
    changed = none | {"applied_changes": ["plan_swap"], "changes_none": False}
    o = offer(fee=None, change="plan_swap")
    assert offer_terms_hash(o) == _sha256(
        base | changed | {"total_cost_12m_minor": 81600}
    )


def test_the_v2_hash_is_kept_byte_for_byte() -> None:
    """``terms_hash_v2`` is the ``pl.terms/2`` hash as it was before v3."""
    v2 = [
        (offer(), "a2f19a63647843947faef427c8c84de58655016141e991a628488ec74f885548"),
        (
            offer(fee=None, change="plan_swap"),
            "dea074d33be3656f3bfe97c50317e41724a401eada7831513323531ecfa38365",
        ),
    ]
    for o, pinned in v2:
        terms = offer_terms(o)
        assert terms is not None
        assert terms_hash_v2(terms) == pinned != offer_terms_hash(o)


NOT = {"value": "false"}
UNAPPLIED = slot("applied_change:plan_swap", "false", "bool", "change")


@pytest.mark.parametrize(
    ("why", "o"),
    [
        ("fees unstated", _with(offer(fee=None), drop=("fees_none",))),
        ("changes unstated", _with(offer(), drop=("changes_none",))),
        ("only an unapplied change", _with(offer(), UNAPPLIED, drop=("changes_none",))),
        ("an unrecorded fee", _with(
            offer(), FEES_NONE.model_copy(update=NOT), drop=("fee:activation",))),
        ("an unrecorded change", _with(
            offer(), CHANGES_NONE.model_copy(update=NOT), drop=("changes_none",))),
        ("no fees, yet a fee", _with(offer(), FEES_NONE)),
        ("no changes, yet a change", _with(offer(change="plan_swap"), CHANGES_NONE)),
        ("not a boolean", _with(
            offer(fee=None), FEES_NONE.model_copy(update={"value": "yes"}),
            drop=("fees_none",))),
        *((f"an applied change {v!r}", _with(
            offer(), slot("applied_change:plan_swap", v, "bool", "change")))
          for v in ("True", "yes", "1", "")),
        ("a feature 'True'", _with(
            offer(), slot("feature:hotspot", "True", "bool", "feature"))),
    ],
)  # fmt: skip
def test_unstated_or_contradictory_completeness_has_no_terms(
    why: str, o: OfferPublic
) -> None:
    assert offer_terms(o) is None, why
    assert offer_terms_hash(o) is None, why


def test_a_listed_fee_or_change_states_completeness() -> None:
    """As in the §9.2 required fields: at least one ``fee:*`` or ``fees_none``,
    at least one applied ``applied_change:*`` or ``changes_none``."""
    listed = offer(change="plan_swap")
    stated = _with(
        listed, FEES_NONE.model_copy(update=NOT), CHANGES_NONE.model_copy(update=NOT)
    )
    assert offer_terms_hash(listed) == offer_terms_hash(stated) is not None


def test_completeness_never_read_back_is_never_authorised() -> None:
    """An unconfirmed ``fees_none`` slot keeps the read-back unconfirmed; a
    completeness never stated leaves the terms unknown."""
    done = confirm(offer(fee=None))
    fees = next(s for s in done.slots if s.field == "fees_none")
    unread = _with(
        done, fees.model_copy(update={"status": "heard"}), drop=("fees_none",)
    )
    assert readback_status(unread) == "unconfirmed"
    unstated = confirm(_with(offer(), UNAPPLIED, drop=("changes_none",)))
    assert readback_status(unstated) == "confirmed" and unstated.terms_hash is None
    for o in (unread, unstated):
        denial = accept_offer(board(o, mandate=mandate()), "o1", CASE)
        assert getattr(denial, "reason", None) == "readback_not_confirmed"
