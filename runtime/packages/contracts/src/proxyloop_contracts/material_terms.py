"""The single derivation and hash of an offer's material terms.

Every action intent, approval, executor, and verifier must agree on the same
terms and the same digest bytes. ``proxyloop_telecom_domain`` re-exports both
functions; the digest is order-insensitive (sorted by ``(name, value)``) and
frozen by ``tests/integration/test_offer_policy_authority.py``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .contracts import MaterialTerm, ProviderOffer


def offer_material_terms(offer: ProviderOffer) -> tuple[MaterialTerm, ...]:
    return (
        MaterialTerm(
            name="monthly_price_minor",
            value=str(offer.monthly_price.amount_minor),
        ),
        MaterialTerm(
            name="total_cost_12_months_minor",
            value=str(offer.total_cost.amount_minor),
        ),
        MaterialTerm(name="currency", value=offer.monthly_price.currency),
        MaterialTerm(name="term_months", value=str(offer.term_months)),
        MaterialTerm(name="features", value=",".join(sorted(offer.features))),
        MaterialTerm(name="offer_expires_at", value=_utc_text(offer.expires_at)),
    )


def material_terms_hash(terms: tuple[MaterialTerm, ...]) -> str:
    canonical_terms = sorted(
        (term.model_dump(mode="json") for term in terms),
        key=lambda item: (str(item["name"]), str(item["value"])),
    )
    payload = json.dumps(
        canonical_terms,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = ["material_terms_hash", "offer_material_terms"]
