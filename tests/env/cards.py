"""Guard-shaped approval cards and public offers for the approver tests."""

from __future__ import annotations

from typing import Any

from proxyloop.contract.state import (
    ApprovalCard,
    OfferPublic,
    ReadbackBinding,
    ReadbackSlot,
)


def offer(monthly: int, months: int = 24, **fees: int) -> OfferPublic:
    def slot(field: str, value: str, unit: str, role: str) -> ReadbackSlot:
        return ReadbackSlot.model_validate(
            {"field": field, "value": value, "unit": unit, "role": role}
            | {"status": "confirmed"}
        )

    slots = [
        slot("monthly_price", str(monthly), "usd_minor", "recurring"),
        slot("term_months", str(months), "months", "recurring"),
        *(slot(f"fee:{c}", str(v), "usd_minor", "one_time") for c, v in fees.items()),
        slot("changes_none", "true", "bool", "change"),
        slot("expires", "none", "iso", "expiry"),
    ]
    if not fees:
        slots.append(slot("fees_none", "true", "bool", "one_time"))
    return OfferPublic(offer_ref="save-2", revision=1, slots=tuple(slots))


def card(epoch: int = 3, **kw: Any) -> ApprovalCard:
    binding = ReadbackBinding(
        offer_ref="save-2",
        revision=1,
        account_ref="acct",
        principal_ref="p",
        purpose="accept_offer",
        authority_epoch=epoch,
    )
    fields = {"approval_id": "apr-1", "offer_ref": "save-2", "revision": 1}
    fields |= {"terms_hash": "h1", "readback_text": "…", "authority_epoch": epoch}
    return ApprovalCard.model_validate(
        fields | {"expires_ms": 90_000, "binding": binding} | kw
    )
