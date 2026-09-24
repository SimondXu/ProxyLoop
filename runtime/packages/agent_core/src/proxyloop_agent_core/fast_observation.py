"""The product half of the local Fast model input: a ``SafeObservation``.

The Phase 03C model was trained on a ``SafeObservation`` of the latest Provider
turn; the product ``FastModelView`` carries no offers. The coordinator derives
this observation from the same snapshot it projects the view from, and only
for an ``ObservingFastAdapter``.

The product has no source for the five Provider-state signals, so they are the
declared ``SafeObservationAdapter.build`` defaults (no requested disclosure, no
clarification, no transfer, approval current, confirmation evidence
available), and ``applied_changes`` is always empty. These are recorded E1
caveats (design D3, D4), not product signals.

Total over contract-valid snapshots: anything ``SafeObservation`` cannot
represent is an ``ObservationRefusal`` with codes, never an exception, so the
model is never called with a distorted observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from proxyloop_contracts import CaseContextSnapshot

from .observation import (
    OFFER_CLASSIFICATION_CODES,
    SafeObservation,
    SafeObservationAdapter,
    SafeOffer,
    classify_provider_offer,
)

FAST_OBSERVATION_VERSION: Final = "fast-observation-v1"
_STRUCTURAL_REFUSAL_CODES: Final = (
    "fast_observation_bill_snapshot_missing",
    "fast_observation_provider_event_missing",
    "fast_observation_offer_missing",
    "fast_observation_mixed_providers",
    "fast_observation_duplicate_offer_ids",
    "fast_observation_duplicate_case_tokens",
)
FAST_OBSERVATION_REFUSAL_CODES: Final = frozenset(
    {*_STRUCTURAL_REFUSAL_CODES, *OFFER_CLASSIFICATION_CODES}
)


@dataclass(frozen=True, slots=True)
class ObservationRefusal:
    """Why no faithful observation exists; codes in check order, unique."""

    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes or not set(self.reason_codes) <= (
            FAST_OBSERVATION_REFUSAL_CODES
        ):
            raise ValueError("an observation refusal needs allow-listed codes")


def fast_public_observation(
    snapshot: CaseContextSnapshot,
) -> SafeObservation | ObservationRefusal:
    """The observation of the latest Provider turn, or a refusal with codes."""

    case = snapshot.case
    codes: list[str] = []
    if case.bill_snapshot is None:
        codes.append("fast_observation_bill_snapshot_missing")
    provider_event = next(
        (
            event
            for event in reversed(snapshot.visible_events)
            if event.actor.value == "provider"
        ),
        None,
    )
    if provider_event is None:
        codes.append("fast_observation_provider_event_missing")
    offers = snapshot.offers
    if not offers:
        codes.append("fast_observation_offer_missing")
    if len({offer.provider_id for offer in offers}) > 1:
        codes.append("fast_observation_mixed_providers")
    if len({offer.offer_id for offer in offers}) != len(offers):
        codes.append("fast_observation_duplicate_offer_ids")
    for tokens in (
        case.goal.required_features,
        case.goal.forbidden_changes,
        case.delegated_authority.allowed_disclosures,
    ):
        if len(set(tokens)) != len(tokens):
            codes.append("fast_observation_duplicate_case_tokens")
            break
    if codes:
        return ObservationRefusal(reason_codes=tuple(codes))
    assert provider_event is not None
    provider_id = offers[0].provider_id
    safe_offers: list[SafeOffer] = []
    for offer in offers:
        classified = classify_provider_offer(
            offer, provider_id=provider_id, case_id=str(case.case_id)
        )
        if isinstance(classified, SafeOffer):
            safe_offers.append(classified)
        else:
            codes.extend(code for code in classified if code not in codes)
    if codes:
        return ObservationRefusal(reason_codes=tuple(codes))
    return SafeObservationAdapter.build(
        case,
        provider_id=provider_id,
        provider_message=provider_event.content,
        offers=safe_offers,
        observed_at=snapshot.visible_events[-1].occurred_at,
    )


__all__ = [
    "FAST_OBSERVATION_REFUSAL_CODES",
    "FAST_OBSERVATION_VERSION",
    "ObservationRefusal",
    "fast_public_observation",
]
