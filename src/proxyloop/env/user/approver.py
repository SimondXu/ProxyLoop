"""The deterministic sim approver: the principal's approval button
(ARCHITECTURE §10.2, §9.6).

It decides an ``ApprovalCard`` or a proposed ``Mandate`` from the principal's
hidden constraints (``Task.principal``) and returns the ``ApprovalPost`` the
approval endpoint would receive, with a delay sampled from
``principal.approver_delay_s`` (its own seeded stream). A card is granted iff
it shows every required slot (else ``incomplete_card``), all confirmed (else
``unconfirmed``), with terms within the limits; a mandate iff each bound the user
stated is bounded no looser. After a stop every decision is a denial; after a
mind change the changed facts are the envelope, and the limits drop to it.

The kernel's side (S1-SYS-02/05), not wired here: on ``approval.requested``
call ``decide(card, bb.public.offers[card.offer_ref])`` (the card's terms as
slots: ``readback_text`` is their rendering), and on ``mandate.proposed``
``decide_mandate(mandate)``; ``delay_s`` later emit ``approval.post`` (actor
``sim_approver``) with ``post``, into the queue the endpoint feeds, where the
kernel re-decides it and emits ``approval.decided{by: sim_approver}``. The
approver emits no event: a post is agent-stream ingress, not a world event.
``SimUser.approver`` is the instance shared with the user's chat voice, so that
``after_card`` and a mind change see the same principal.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import ApprovalCard, Mandate, OfferPublic
from proxyloop.env.tasks.schema import Limits, Task


@dataclass(frozen=True, slots=True)
class Bounds:
    """Minor units and months; ``None`` is unbounded."""

    monthly_minor: int | None = None
    term_months: int | None = None
    fees_minor: int | None = None


@dataclass(frozen=True, slots=True)
class Post:
    post: ApprovalPost
    delay_s: float
    reasons: tuple[str, ...]  # why it was denied; empty on a grant


def minor(usd: str) -> int:
    return int(Decimal(usd) * 100)


def bounds(limits: Limits) -> Bounds:
    price, fees = limits.max_monthly_price_usd, limits.max_one_time_fees_usd
    return Bounds(
        None if price is None else minor(price),
        limits.max_term_months,
        None if fees is None else minor(fees),
    )


def violations(
    b: Bounds, monthly_minor: int, term_months: int, fees_minor: int
) -> tuple[str, ...]:
    over = (
        ("monthly_price", b.monthly_minor, monthly_minor),
        ("term_months", b.term_months, term_months),
        ("one_time_fees", b.fees_minor, fees_minor),
    )
    return tuple(f"{n}_over" for n, bound, v in over if bound is not None and v > bound)


def terms_violations(b: Bounds, terms: Mapping[str, str]) -> tuple[str, ...]:
    """World terms as the rep says them (dollars, months) against ``b``."""

    fees = sum(minor(v) for k, v in terms.items() if k.startswith("fee:"))
    return violations(b, minor(terms["monthly_price"]), int(terms["term_months"]), fees)


def missing_required(fields: Collection[str]) -> list[str]:
    """Required read-back fields (ARCHITECTURE §9.2) absent from ``fields``: a
    missing fee is never "no fee"."""

    kinds = {f.partition(":")[0] for f in fields}
    out = [f for f in ("monthly_price", "term_months", "expires") if f not in fields]
    if "fee" not in kinds and "fees_none" not in fields:
        out.append("fee:*|fees_none")
    if "applied_change" not in kinds and "changes_none" not in fields:
        out.append("applied_change:*|changes_none")
    return out


def _slot(offer: OfferPublic, field: str, unit: str) -> int:
    found = [s for s in offer.slots if s.field == field]
    if len(found) != 1 or found[0].unit != unit or not found[0].value.isdigit():
        raise ValueError(f"the card's offer needs one {unit} {field} slot")
    return int(found[0].value)


class Approver:
    def __init__(self, task: Task, seed: int) -> None:
        if task.principal is None:
            raise ValueError(f"{task.id} has no principal to approve")
        self._principal = task.principal
        self.facts = dict(task.profile.facts)  # as the user changed them
        self.changed = self.stopped = False
        self._rng = random.Random(f"approver:{seed}")

    def envelope(self) -> Bounds:
        stated = {b: self.facts[k] for b, k in self._principal.envelope.items()}
        return bounds(Limits.model_validate(stated))

    def limits(self) -> Bounds:
        hidden = self._principal.limits
        return self.envelope() if self.changed or hidden is None else bounds(hidden)

    def stop(self, change: Mapping[str, str] | None) -> None:
        """The user said stop (``None``) or changed these facts."""

        if change is None:
            self.stopped = True
        else:
            self.facts |= change
            self.changed = True

    def decide(self, card: ApprovalCard, offer: OfferPublic) -> Post:
        if (offer.offer_ref, offer.revision) != (card.offer_ref, card.revision):
            raise ValueError("the offer is not the card's offer and revision")
        fields = [s.field for s in offer.slots]
        reasons = ("incomplete_card",) if missing_required(fields) else ()
        if any(s.status != "confirmed" for s in offer.slots):
            reasons += ("unconfirmed",)  # Guard's read-back stays authoritative
        if not reasons:
            monthly = _slot(offer, "monthly_price", "usd_minor")
            months = _slot(offer, "term_months", "months")
            fees = sum(
                _slot(offer, f, "usd_minor") for f in fields if f.startswith("fee:")
            )
            reasons = violations(self.limits(), monthly, months, fees)
        return self._post(
            "approval", card.approval_id, card.terms_hash, card.authority_epoch, reasons
        )

    def decide_mandate(self, m: Mandate) -> Post:
        asked = Bounds(
            m.max_monthly_price_minor, m.max_term_months, m.max_one_time_fees_minor
        )
        reasons: list[str] = []
        for name in ("monthly_minor", "term_months", "fees_minor"):
            stated, got = getattr(self.envelope(), name), getattr(asked, name)
            if stated is not None and (got is None or got > stated):
                reasons.append(f"{name}_looser")
        return self._post(
            "mandate", m.mandate_id, m.mandate_hash, m.epoch, tuple(reasons)
        )

    def _post(
        self,
        subject: str,
        subject_id: str,
        hash_: str,
        epoch: int,
        reasons: tuple[str, ...],
    ) -> Post:
        reasons = ("stopped", *reasons) if self.stopped else reasons
        post = ApprovalPost.model_validate(
            {
                "subject": subject,
                "subject_id": subject_id,
                "decision": "denied" if reasons else "granted",
                "subject_hash": hash_,
                "authority_epoch": epoch,
            }
        )
        delay = round(self._rng.uniform(*self._principal.approver_delay_s.range), 3)
        return Post(post, delay, reasons)
