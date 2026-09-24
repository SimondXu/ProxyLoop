"""The product Fast observation is total; the ML ``build`` path is unchanged (R-19)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from proxyloop_agent_core import (
    FAST_OBSERVATION_REFUSAL_CODES,
    FAST_OBSERVATION_VERSION,
    ObservationRefusal,
    SafeObservation,
    SafeObservationAdapter,
    SafeOffer,
    classify_provider_offer,
    fast_public_observation,
)
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_contracts import (
    Case,
    CaseContextSnapshot,
    LineItem,
    LineItemCategory,
    Money,
    ProviderOffer,
)
from test_b1_9_total_offer_policy import _CreditingProvider

T0 = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
OTHER_CASE = UUID("33333333-3333-4333-8333-333333333333")
assert OTHER_CASE != SCRIPTED_CASE_ID


def _snapshot(
    monkeypatch: pytest.MonkeyPatch | None = None, provider: Any = None
) -> CaseContextSnapshot:
    if monkeypatch is not None and provider is not None:
        monkeypatch.setattr(runtime_module, "FictionalMobileProvider", provider)
    repository = InMemoryCaseRepository()
    ThinAgentRuntime(repository, clock=lambda: T0).create_case(occurred_at=T0)
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state.snapshot


def test_product_observation_is_total_for_contract_valid_offers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # F2 / AC4: a contract-valid credit line raised ValueError on main (P3).
    snapshot = _snapshot(monkeypatch, _CreditingProvider)
    (offer,) = snapshot.offers
    assert sum(item.amount.amount_minor for item in offer.fees) < 0

    refusal = fast_public_observation(snapshot)

    assert refusal == ObservationRefusal(reason_codes=("offer_fee_sum_negative",))


def test_a_duplicate_feature_offer_is_refused_not_raised() -> None:
    # AC4
    snapshot = _snapshot()
    (offer,) = snapshot.offers
    duplicated = offer.model_copy(update={"features": (*offer.features, "x", "x")})
    refusal = fast_public_observation(
        snapshot.model_copy(update={"offers": (duplicated,)})
    )
    assert refusal == ObservationRefusal(reason_codes=("offer_features_duplicate",))


def test_the_product_observation_uses_the_declared_defaults() -> None:
    snapshot = _snapshot()
    observation = fast_public_observation(snapshot)

    assert isinstance(observation, SafeObservation)
    assert FAST_OBSERVATION_VERSION == "fast-observation-v1"
    latest_provider = next(
        event
        for event in reversed(snapshot.visible_events)
        if event.actor.value == "provider"
    )
    (offer,) = snapshot.offers
    assert observation == SafeObservationAdapter.build(
        snapshot.case,
        provider_id=offer.provider_id,
        provider_message=latest_provider.content,
        offers=snapshot.offers,
        observed_at=snapshot.visible_events[-1].occurred_at,
    )
    # D3: the Provider-state signals are constants on the product path.
    assert observation.requested_disclosures == ()
    assert observation.needs_clarification is False
    assert observation.transfer_available is False
    assert observation.approval_current is True
    assert observation.confirmation_evidence_available is True


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("no_bill", "fast_observation_bill_snapshot_missing"),
        ("no_provider_event", "fast_observation_provider_event_missing"),
        ("no_offer", "fast_observation_offer_missing"),
        ("mixed_providers", "fast_observation_mixed_providers"),
        ("duplicate_offer_ids", "fast_observation_duplicate_offer_ids"),
        ("duplicate_goal_tokens", "fast_observation_duplicate_case_tokens"),
        ("foreign_offer", "offer_case_mismatch"),
    ],
)
def test_each_refusal_has_a_code(change: str, code: str) -> None:
    snapshot = _snapshot()
    (offer,) = snapshot.offers
    case = snapshot.case
    if change == "no_bill":
        snapshot = snapshot.model_copy(
            update={"case": case.model_copy(update={"bill_snapshot": None})}
        )
    elif change == "no_provider_event":
        snapshot = snapshot.model_copy(
            update={
                "visible_events": tuple(
                    event
                    for event in snapshot.visible_events
                    if event.actor.value != "provider"
                )
            }
        )
    elif change == "no_offer":
        snapshot = snapshot.model_copy(update={"offers": ()})
    elif change == "mixed_providers":
        other = offer.model_copy(
            update={
                "offer_id": UUID("22222222-2222-4222-8222-222222222222"),
                "provider_id": "another-provider",
            }
        )
        snapshot = snapshot.model_copy(update={"offers": (offer, other)})
    elif change == "duplicate_offer_ids":
        snapshot = snapshot.model_copy(update={"offers": (offer, offer)})
    elif change == "duplicate_goal_tokens":
        goal = case.goal.model_copy(
            update={"required_features": ("mobile_hotspot", "mobile_hotspot")}
        )
        snapshot = snapshot.model_copy(
            update={"case": case.model_copy(update={"goal": goal})}
        )
    elif change == "foreign_offer":
        foreign = offer.model_copy(update={"case_id": OTHER_CASE})
        snapshot = snapshot.model_copy(update={"offers": (foreign,)})
    refusal = fast_public_observation(snapshot)
    assert isinstance(refusal, ObservationRefusal)
    assert refusal.reason_codes[0] == code
    assert set(refusal.reason_codes) <= FAST_OBSERVATION_REFUSAL_CODES


# ---------------------------------------------------------------------------
# A18: differential fuzz of ``SafeObservationAdapter.build`` against the code
# on ``main``. ``_legacy_adapt_offer`` is a verbatim copy of the pre-R-19
# ``SafeObservationAdapter._adapt_offer`` body.
# ---------------------------------------------------------------------------


def _legacy_adapt_offer(
    offer: ProviderOffer | SafeOffer, *, provider_id: str, case_id: str
) -> SafeOffer:
    if isinstance(offer, SafeOffer):
        if offer.provider_id != provider_id:
            raise ValueError("offer provider does not match provider_id")
        return offer
    if not isinstance(offer, ProviderOffer):
        raise TypeError("offers must contain ProviderOffer or SafeOffer values")
    if str(offer.case_id) != case_id or offer.provider_id != provider_id:
        raise ValueError("provider offer does not belong to this public observation")
    return SafeOffer(
        offer_id=str(offer.offer_id),
        provider_id=str(offer.provider_id),
        monthly_price_minor=offer.monthly_price.amount_minor,
        total_cost_12_months_minor=offer.total_cost.amount_minor,
        currency=offer.monthly_price.currency,
        features=tuple(str(value) for value in offer.features),
        fees_minor=sum(item.amount.amount_minor for item in offer.fees),
        term_months=offer.term_months,
        applied_changes=(),
        expires_at=offer.expires_at,
    )


def _legacy_build(case: Case, **kwargs: Any) -> SafeObservation:
    original = SafeObservationAdapter._adapt_offer
    try:
        SafeObservationAdapter._adapt_offer = staticmethod(_legacy_adapt_offer)  # type: ignore[method-assign]
        return SafeObservationAdapter.build(case, **kwargs)
    finally:
        SafeObservationAdapter._adapt_offer = original  # type: ignore[method-assign]


def _outcome(call: Any) -> tuple[str, object]:
    try:
        return "returned", call()
    except (ValueError, TypeError) as error:
        return type(error).__name__, str(error)


_FEATURES = ("mobile_hotspot", "unlimited_talk_text", "roaming", "x")
_CATEGORIES = tuple(LineItemCategory)


def _random_offer(rng: random.Random, case: Case, base: ProviderOffer) -> ProviderOffer:
    currency = base.monthly_price.currency
    fees = tuple(
        LineItem(
            name=f"line {index}",
            category=rng.choice(_CATEGORIES),
            amount=Money(amount_minor=rng.randint(-3_000, 3_000), currency=currency),
        )
        for index in range(rng.randint(0, 3))
    )
    features = tuple(rng.choice(_FEATURES) for _ in range(rng.randint(0, 4)))
    return ProviderOffer.model_validate_json(
        base.model_copy(
            update={
                "offer_id": UUID(int=rng.getrandbits(128), version=4),
                "case_id": case.case_id if rng.random() < 0.9 else OTHER_CASE,
                "provider_id": base.provider_id
                if rng.random() < 0.9
                else "another-provider",
                "monthly_price": Money(
                    amount_minor=rng.randint(0, 20_000), currency=currency
                ),
                "total_cost": Money(
                    amount_minor=rng.randint(0, 240_000), currency=currency
                ),
                "fees": fees,
                "features": features,
                "term_months": rng.randint(0, 36),
            }
        ).model_dump_json()
    )


def test_build_is_unchanged_on_every_contract_valid_input() -> None:
    # A18 / L12: 20k offers; identical returns, identical ValueError messages.
    snapshot = _snapshot()
    case = snapshot.case
    (base,) = snapshot.offers
    rng = random.Random(20260924)
    counts = {"returned": 0, "raised": 0}
    for _ in range(20_000):
        offers = tuple(_random_offer(rng, case, base) for _ in range(rng.randint(1, 2)))
        kwargs = {
            "provider_id": base.provider_id,
            "provider_message": "A fictional Provider offer is available.",
            "offers": offers,
            "observed_at": T0,
        }
        legacy = _outcome(lambda kwargs=kwargs: _legacy_build(case, **kwargs))
        current = _outcome(
            lambda kwargs=kwargs: SafeObservationAdapter.build(case, **kwargs)
        )
        assert current == legacy
        counts["returned" if legacy[0] == "returned" else "raised"] += 1
        for offer in offers:
            classified = classify_provider_offer(
                offer, provider_id=base.provider_id, case_id=str(case.case_id)
            )
            single = _outcome(
                lambda offer=offer: _legacy_adapt_offer(
                    offer, provider_id=base.provider_id, case_id=str(case.case_id)
                )
            )
            if single[0] == "returned":
                assert classified == single[1]
            else:
                # Total: a code, never an exception, where main raised.
                assert isinstance(classified, tuple) and classified
    # Both branches are exercised in volume.
    assert counts["returned"] > 1_000 and counts["raised"] > 1_000


def test_the_classifier_codes_are_ordered_like_the_legacy_checks() -> None:
    snapshot = _snapshot()
    (offer,) = snapshot.offers
    currency = offer.monthly_price.currency
    credit = LineItem(
        name="Credit",
        category=LineItemCategory.CREDIT,
        amount=Money(amount_minor=-10_000, currency=currency),
    )
    bad = ProviderOffer.model_validate_json(
        offer.model_copy(
            update={
                "case_id": OTHER_CASE,
                "fees": (credit,),
                "features": ("x", "x"),
            }
        ).model_dump_json()
    )
    assert classify_provider_offer(
        bad, provider_id="another-provider", case_id=str(snapshot.case.case_id)
    ) == (
        "offer_case_mismatch",
        "offer_provider_mismatch",
        "offer_fee_sum_negative",
        "offer_features_duplicate",
    )
    expires = offer.expires_at + timedelta(days=1)
    assert isinstance(
        classify_provider_offer(
            offer.model_copy(update={"expires_at": expires}),
            provider_id=offer.provider_id,
            case_id=str(snapshot.case.case_id),
        ),
        SafeOffer,
    )
