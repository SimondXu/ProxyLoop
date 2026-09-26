"""Offer terms and their hashes (ARCHITECTURE §9.1).

``terms_hash`` hashes ``pl.terms/2``: every field of ``Terms``, with list fields
sorted so the hash is order-insensitive. ``terms_hash_v1`` reproduces the v0
six-field ``material_terms_hash`` byte for byte (v0
``proxyloop_contracts/material_terms.py:18-46``); v0 left ``applied_changes``,
fees, credits and the offer id/revision unbound, which ``pl.terms/2`` fixes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Fee:
    """One fee or credit line: a code and a non-negative amount in minor units."""

    code: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class Terms:
    """``pl.terms/2``: the material terms of one offer revision.

    ``credits`` use the same ``{code, amount_minor}`` shape as ``fees``.
    ``total_cost_12m_minor`` is derived by whoever builds the offer (monthly
    price x 12 + fees - credits) and is stored so the hash binds the quoted
    total.
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


def terms_hash(terms: Terms) -> str:
    """sha256 of the canonical JSON of ``terms`` (sorted keys and lists)."""

    return _sha256_json(
        {
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
    )


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
        ("offer_expires_at", _utc_text(offer_expires_at)),
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


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = ["Fee", "Terms", "terms_hash", "terms_hash_v1"]
