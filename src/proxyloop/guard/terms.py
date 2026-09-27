"""Offer terms and their hashes (ARCHITECTURE §9.1).

``terms_hash`` hashes ``pl.terms/3``: every field of ``Terms``, with list fields
sorted so the hash is order-insensitive, plus explicit fee and change
completeness (``fees_none``, ``changes_none``). ``terms_hash_v1`` reproduces the
v0 six-field ``material_terms_hash`` byte for byte (v0
``proxyloop_contracts/material_terms.py:18-46``); v0 left ``applied_changes``,
fees, credits and the offer id/revision unbound, which ``pl.terms/2`` fixed.
``terms_hash_v2`` keeps the ``pl.terms/2`` hash, which left completeness
unbound: a ledger with an unrecorded fee or change hashed as the accepted terms.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from proxyloop.contract.state import OfferPublic

NO_EXPIRY = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)  # "it does not expire"


@dataclass(frozen=True, slots=True)
class Fee:
    """One fee or credit line: a code and a non-negative amount in minor units."""

    code: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class Terms:
    """The material terms of one offer revision (``pl.terms/2`` fields).

    ``credits`` use the same ``{code, amount_minor}`` shape as ``fees``. List
    fields are multisets: the hash sorts them and keeps duplicates.
    ``expires_at`` must be timezone-aware and is normalised to UTC;
    ``NO_EXPIRY`` stands for the rep's explicit "no expiry".
    ``total_cost_12m_minor`` is stored as quoted; stored vs derived is deferred
    to S0-CON-01, which owns the terms types.
    """

    monthly_price_minor: int
    currency: str
    term_months: int
    features: tuple[str, ...]
    fees: tuple[Fee, ...]
    credits: tuple[Fee, ...]
    applied_changes: tuple[str, ...]
    total_cost_12m_minor: int
    offer_id: str
    offer_revision: int
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))


def terms_hash(terms: Terms) -> str:
    """``pl.terms/3``: sha256 of the canonical JSON of ``terms`` (sorted keys
    and lists) and its explicit completeness. ``offer_terms`` yields terms only
    when that completeness was stated, so the fee and change lists are all of
    them: ``fees_none`` iff there is no fee, ``changes_none`` iff no change."""

    complete = {
        "fees_none": not terms.fees,
        "changes_none": not terms.applied_changes,
    }
    return _sha256_json(_v2_fields(terms) | complete)


def terms_hash_v2(terms: Terms) -> str:
    """The ``pl.terms/2`` hash, byte for byte: completeness unbound."""

    return _sha256_json(_v2_fields(terms))


def _v2_fields(terms: Terms) -> dict[str, object]:
    return {
        "monthly_price_minor": terms.monthly_price_minor,
        "currency": terms.currency,
        "term_months": terms.term_months,
        "features": sorted(terms.features),
        "fees": _fee_lines(terms.fees),
        "credits": _fee_lines(terms.credits),
        "applied_changes": sorted(terms.applied_changes),
        "total_cost_12m_minor": terms.total_cost_12m_minor,
        "offer_id": terms.offer_id,
        "offer_revision": terms.offer_revision,
        "expires_at": _utc_text(terms.expires_at),
    }


def offer_terms(offer: OfferPublic) -> Terms | None:
    """``pl.terms/3`` of an offer's read-back slots (USD), or ``None`` while
    the price, the term or the expiry is missing or malformed, a field repeats,
    or fee or change completeness is unstated or contradictory (§9.2: at least
    one ``fee:*`` or ``fees_none``, at least one applied ``applied_change:*``
    or ``changes_none``; a ``*_none`` slot is ``true`` iff its list is empty).
    Whether a slot is confirmed is ``readback_status``'s rule, not this one."""

    by = {s.field: s.value for s in offer.slots}
    if len(by) != len(offer.slots):  # a repeated field has no single value
        return None
    coded = [(*f.split(":", 1), v) for f, v in by.items() if ":" in f]
    try:
        fees = tuple(Fee(code, int(v)) for kind, code, v in coded if kind == "fee")
        credits = tuple(Fee(c, int(v)) for kind, c, v in coded if kind == "credit")
        monthly, expires = int(by["monthly_price"]), by["expires"]
        changes = tuple(c for k, c, v in coded if k == "applied_change" and v == "true")
        if not (
            _stated(by.get("fees_none"), fees)
            and _stated(by.get("changes_none"), changes)
        ):
            return None
        return Terms(
            monthly_price_minor=monthly,
            currency="USD",
            term_months=int(by["term_months"]),
            features=tuple(c for k, c, v in coded if k == "feature" and v == "true"),
            fees=fees,
            credits=credits,
            applied_changes=changes,
            total_cost_12m_minor=monthly * 12
            + sum(f.amount_minor for f in fees)
            - sum(c.amount_minor for c in credits),
            offer_id=offer.offer_ref,
            offer_revision=offer.revision,
            expires_at=NO_EXPIRY
            if expires == "none"
            else datetime.fromisoformat(expires),
        )
    except (KeyError, ValueError):
        return None


def _stated(none: str | None, listed: Sequence[object]) -> bool:
    """Completeness is stated: a ``*_none`` slot that is ``true`` iff nothing
    is listed, or, without one, at least one listed line."""
    if none is None:
        return bool(listed)
    return none in ("true", "false") and (none == "true") == (not listed)


def offer_terms_hash(offer: OfferPublic) -> str | None:
    terms = offer_terms(offer)
    return None if terms is None else terms_hash(terms)


def terms_hash_v1(
    *,
    monthly_price_minor: int,
    total_cost_12_months_minor: int,
    currency: str,
    term_months: int,
    features: Sequence[str],
    offer_expires_at: datetime,
) -> str:
    """The v0 ``material_terms_hash`` over the six v0 material terms.

    Values are stripped and must be 1..4000 characters, as v0 ``MaterialTerm``
    enforced; v0 raised on an empty feature list, and so does this.
    """

    terms = (
        ("monthly_price_minor", str(monthly_price_minor)),
        ("total_cost_12_months_minor", str(total_cost_12_months_minor)),
        ("currency", currency),
        ("term_months", str(term_months)),
        ("features", ",".join(sorted(features))),
        ("offer_expires_at", _v0_utc_text(offer_expires_at)),
    )
    # v0 sorted by (name, value) after pydantic had stripped the values.
    canonical = sorted((name, _v1_text(value)) for name, value in terms)
    return _sha256_json([{"name": name, "value": value} for name, value in canonical])


def _v1_text(value: str) -> str:
    """v0 ``MaterialTerm.value`` (``HumanText``): stripped, 1..4000 chars."""

    stripped = value.strip()
    if not 1 <= len(stripped) <= 4000:
        raise ValueError("a v1 material term value must be 1..4000 characters")
    return stripped


def _fee_lines(lines: tuple[Fee, ...]) -> list[dict[str, object]]:
    return [
        {"code": line.code, "amount_minor": line.amount_minor}
        for line in sorted(lines, key=lambda line: (line.code, line.amount_minor))
    ]


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _v0_utc_text(value: datetime) -> str:  # v0's form, microseconds included
    return value.isoformat().replace("+00:00", "Z")


def _utc_text(value: datetime) -> str:
    """UTC with whole seconds: 20 characters, within ``MAX_SLOT_VALUE``."""
    return _v0_utc_text(value.astimezone(UTC).replace(microsecond=0))


expiry_text = _utc_text  # an ``expires`` read-back slot's value

__all__ = [
    "NO_EXPIRY",
    "Fee",
    "Terms",
    "expiry_text",
    "offer_terms",
    "offer_terms_hash",
    "terms_hash",
    "terms_hash_v1",
    "terms_hash_v2",
]
