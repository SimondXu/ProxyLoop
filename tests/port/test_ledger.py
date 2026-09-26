from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from proxyloop.env.ledger import Ledger, LedgerMode
from proxyloop.guard.terms import Fee, Terms, terms_hash, terms_hash_v1

V0 = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "v0" / "ledger.json").read_text(
        "utf-8"
    )
)


def _terms(offer: dict[str, Any]) -> Terms:
    fees = (Fee("fees", offer["fees_minor"]),) if offer["fees_minor"] else ()
    return Terms(
        monthly_price_minor=offer["monthly_price_minor"],
        currency=offer["currency"],
        term_months=offer["term_months"],
        features=tuple(offer["features"]),
        fees=fees,
        credits=(),
        applied_changes=tuple(offer["applied_changes"]),
        total_cost_12m_minor=offer["total_cost_12_months_minor"],
        offer_id=offer["offer_id"],
        offer_revision=offer["revision"],
        expires_at=datetime.fromisoformat(offer["expires_at"]),
    )


def _v1(terms: Terms) -> str:
    return terms_hash_v1(
        monthly_price_minor=terms.monthly_price_minor,
        total_cost_12_months_minor=terms.total_cost_12m_minor,
        currency=terms.currency,
        term_months=terms.term_months,
        features=terms.features,
        offer_expires_at=terms.expires_at,
    )


@pytest.mark.parametrize(
    "row", V0["rows"], ids=[f"{r['scenario_id']}/{r['mode']}" for r in V0["rows"]]
)
def test_ledger_matches_v0(row: dict[str, Any]) -> None:
    ref = row["confirmation_ref"]
    heard = _terms(row["heard_offer"])
    ledger: Ledger[Terms] = Ledger(LedgerMode(row["mode"]))
    ledger.write(ref, heard)

    assert ledger.lookup(ref + "-other") is None
    bound = ledger.lookup(ref)
    if not row["ledger"]:
        assert bound is None
        return
    assert list(row["ledger"]) == [ref]
    entry = row["ledger"][ref]
    assert bound is not None
    assert (bound.offer_id, bound.offer_revision, _v1(bound)) == (
        entry["offer_id"],
        entry["offer_revision"],
        entry["material_terms_hash"],
    )
    assert bound.term_months == entry["terms"]["term_months"]


def test_modes_bind_heard_other_or_nothing() -> None:
    row = V0["rows"][0]
    heard = _terms(row["heard_offer"])
    bound: dict[LedgerMode, Terms | None] = {}
    for mode in LedgerMode:
        ledger: Ledger[Terms] = Ledger(mode)
        ledger.write("ref-1", heard)
        bound[mode] = ledger.lookup("ref-1")

    assert bound[LedgerMode.HONEST] == heard
    assert bound[LedgerMode.ABSENT] is None
    misquoted = bound[LedgerMode.MISQUOTE]
    assert misquoted is not None
    assert misquoted == replace(heard, term_months=heard.term_months + 12)
    assert terms_hash(misquoted) != terms_hash(heard)
