"""``card_blocks`` (S1-SYS-28, #166 round 3c): the pure form of the pending-card
check ``request_approval`` makes, which Slow's status bar also asks."""

from __future__ import annotations

import pytest

from proxyloop.contract.state import ApprovalCard, OfferPublic, ReadbackBinding
from proxyloop.guard.authorize import card_blocks

H = "a" * 64
OFFER = OfferPublic(offer_ref="save-2", revision=1, terms_hash=H)
BINDING = ReadbackBinding(
    offer_ref="save-2", revision=1, account_ref="c/account",
    principal_ref="c/principal", purpose="accept_offer", authority_epoch=1,
)  # fmt: skip
CARD = ApprovalCard(
    approval_id="apr-save-2-r1-e1-0", offer_ref="save-2", revision=1,
    terms_hash=H, readback_text="monthly price $69.00", authority_epoch=1,
    expires_ms=120_000, binding=BINDING,
)  # fmt: skip


@pytest.mark.parametrize(
    ("offer", "epoch", "t_ms", "blocks"),
    [
        (OFFER, 1, 0, True),  # pending, current: blocks a card for any offer
        (OFFER, 1, 120_000, False),  # expired
        (OFFER, 2, 0, False),  # a stale epoch
        (OFFER.model_copy(update={"revision": 2}), 1, 0, False),  # superseded
        (OFFER.model_copy(update={"terms_hash": "b" * 64}), 1, 0, False),
        (None, 1, 0, False),  # its offer is gone
    ],
)
def test_a_pending_card_blocks_only_while_current_live_and_of_this_epoch(
    offer: OfferPublic | None, epoch: int, t_ms: int, blocks: bool
) -> None:
    assert card_blocks(CARD, offer, epoch, t_ms) is blocks


def test_no_card_blocks_nothing() -> None:
    assert not card_blocks(None, OFFER, 1, 0)
