from __future__ import annotations

import pytest
from proxyloop_contracts import Case
from proxyloop_provider_simulator.episode import build_case
from proxyloop_provider_simulator.negotiation_catalog import (
    HAZARD_REASON_CODES,
    MULTI_HAZARD,
    NEGOTIATION_FAMILIES,
    NEGOTIATION_SCENARIOS,
    NEGOTIATION_STARTED_AT,
    OFFER_TERM_HAZARDS,
    OFFER_TTL,
    PROVIDER_POLICIES_V2,
    RETENTION_GATED_V2,
    TRANSPARENT_PUBLIC_V2,
    ConfirmationMode,
    Hazard,
    apply_offer_hazards,
    base_offer,
    build_negotiation_catalog,
    build_negotiation_scenario,
    compliance_context,
    default_negotiation_case,
    offer_violations,
)
from proxyloop_provider_simulator.scenarios import DEFAULT_PARAMS, PublicOffer

CASE = default_negotiation_case()
CONTEXT = compliance_context(CASE, NEGOTIATION_STARTED_AT)


def _base() -> PublicOffer:
    return base_offer(
        CASE,
        offer_id="offer",
        monthly_price_minor=7_200,
        expires_at=NEGOTIATION_STARTED_AT + OFFER_TTL,
    )


def _case_with(**changes: object) -> Case:
    payload = CASE.model_dump()
    goal = changes.pop("goal", None)
    authority = changes.pop("delegated_authority", None)
    if isinstance(goal, dict):
        payload["goal"].update(goal)
    if isinstance(authority, dict):
        payload["delegated_authority"].update(authority)
    return Case.model_validate(payload)


def test_catalogue_is_every_family_under_both_policies_in_its_namespace() -> None:
    assert len(NEGOTIATION_SCENARIOS) == len(NEGOTIATION_FAMILIES) * 2
    ids = [scenario.scenario_id for scenario in NEGOTIATION_SCENARIOS]
    assert len(ids) == len(set(ids)) and ids == sorted(ids)
    for scenario in NEGOTIATION_SCENARIOS:
        assert scenario.scenario_id == (
            f"negotiation-v1::{scenario.family_id}@1.0::{scenario.policy_id}@1.0"
        )
    assert {policy.policy_id for policy in PROVIDER_POLICIES_V2} == {
        "transparent-public-v2",
        "retention-gated-v2",
    }
    assert build_negotiation_catalog() == NEGOTIATION_SCENARIOS


def test_public_ids_do_not_carry_family_or_policy_names() -> None:
    for scenario in NEGOTIATION_SCENARIOS:
        public = (
            scenario.episode_ref,
            scenario.opening_offer.offer_id,
            scenario.final_offer.offer_id,
        )
        for value in public:
            assert scenario.family_id not in value
            assert scenario.policy_id not in value
            assert "negotiation-v1" not in value


def test_i6_each_offer_hazard_fails_alone_and_multi_is_a_superset() -> None:
    base = _base()
    assert offer_violations(base, CONTEXT) == ()
    singles = {}
    for hazard in OFFER_TERM_HAZARDS:
        single = apply_offer_hazards(base, {hazard}, CASE)
        codes = offer_violations(single, CONTEXT)
        assert HAZARD_REASON_CODES[hazard] in codes, hazard
        singles[hazard] = set(codes)
    multi = set(
        offer_violations(
            apply_offer_hazards(base, MULTI_HAZARD, CASE),
            CONTEXT,
        )
    )
    assert {Hazard.FEE_TRAP, Hazard.FEATURE_LOSS, Hazard.FORBIDDEN_TERM} == MULTI_HAZARD
    for hazard in MULTI_HAZARD:
        assert singles[hazard] <= multi
        # Removing any one hazard still leaves every other one failing.
        rest = MULTI_HAZARD - {hazard}
        remaining = set(
            offer_violations(
                apply_offer_hazards(base, rest, CASE),
                CONTEXT,
            )
        )
        assert {HAZARD_REASON_CODES[item] for item in rest} <= remaining


def test_hazard_truth_derives_from_the_case_not_module_constants() -> None:
    # D1-4 seam: a different Case target moves every price with it.
    lower = _case_with(
        goal={"target_monthly_total": {"amount_minor": 6_000, "currency": "USD"}}
    )
    scenarios = build_negotiation_catalog(lower)
    context = compliance_context(lower, NEGOTIATION_STARTED_AT)
    for scenario in scenarios:
        final = offer_violations(scenario.final_offer, context)
        offer_hazards = scenario.hazards.intersection(OFFER_TERM_HAZARDS)
        assert bool(final) == bool(offer_hazards), scenario.scenario_id
        if scenario.policy is RETENTION_GATED_V2:
            opening = offer_violations(scenario.opening_offer, context)
            assert "target_monthly_total_not_met" in opening
    # The default-Case success offer would miss this Case's target.
    default_success = next(
        item
        for item in NEGOTIATION_SCENARIOS
        if item.family_id == "direct-success" and item.policy is TRANSPARENT_PUBLIC_V2
    )
    assert "target_monthly_total_not_met" in offer_violations(
        default_success.final_offer, context
    )


def test_builder_rejects_a_case_that_cannot_carry_the_hazard_truth() -> None:
    families = {family.family_id: family for family in NEGOTIATION_FAMILIES}
    no_authority = _case_with(delegated_authority={"allowed_disclosures": ()})
    with pytest.raises(ValueError, match="allowed fact"):
        build_negotiation_scenario(
            families["clarification-required"], TRANSPARENT_PUBLIC_V2, no_authority
        )
    pin_allowed = _case_with(
        delegated_authority={
            "allowed_disclosures": ("current_monthly_total", "account_pin")
        }
    )
    with pytest.raises(ValueError, match="protected fact"):
        build_negotiation_scenario(
            families["disclosure-restriction"], TRANSPARENT_PUBLIC_V2, pin_allowed
        )
    no_target = _case_with(goal={"target_monthly_total": None})
    with pytest.raises(ValueError, match="target"):
        build_negotiation_scenario(
            families["direct-success"], RETENTION_GATED_V2, no_target
        )


def test_i7_every_family_reference_trajectory_differs_between_policies() -> None:
    by_family: dict[str, dict[str, object]] = {}
    for scenario in NEGOTIATION_SCENARIOS:
        by_family.setdefault(scenario.family_id, {})[scenario.policy_id] = (
            scenario.expected_steps
        )
    assert set(by_family) == {family.family_id for family in NEGOTIATION_FAMILIES}
    for family_id, steps in by_family.items():
        assert steps["transparent-public-v2"] != steps["retention-gated-v2"], family_id


def test_transfer_is_a_policy_property_not_a_hazard() -> None:
    assert not TRANSPARENT_PUBLIC_V2.transfer_after_counter
    assert RETENTION_GATED_V2.transfer_after_counter
    assert {hazard.value for hazard in Hazard}.isdisjoint({"transfer", "refusal"})


def test_f2_every_single_hazard_family_fails_only_its_own_hazard_code() -> None:
    hazard_codes = set(HAZARD_REASON_CODES.values())
    for scenario in NEGOTIATION_SCENARIOS:
        offer_hazards = scenario.hazards.intersection(OFFER_TERM_HAZARDS)
        codes = set(offer_violations(scenario.final_offer, CONTEXT)) & hazard_codes
        assert codes == {HAZARD_REASON_CODES[item] for item in offer_hazards}
    assert CASE.goal.forbidden_changes == ("remove_add_on:international_roaming",)


def test_f2_builder_rejects_a_forbidden_change_that_is_also_unsupported() -> None:
    # The V1 fixture forbids ``device_financing_change``, which is outside the
    # supported change set, so the forbidden-term offer would fail twice.
    v1_case = build_case(DEFAULT_PARAMS)
    family = next(
        item for item in NEGOTIATION_FAMILIES if item.family_id == "forbidden-term"
    )
    with pytest.raises(ValueError, match="not isolated"):
        build_negotiation_scenario(family, TRANSPARENT_PUBLIC_V2, v1_case)


def test_catalogue_emits_only_family_confirmation_modes() -> None:
    # The test-only modes must never reach the catalogue, splits, or leakage.
    assert {scenario.confirmation_mode for scenario in NEGOTIATION_SCENARIOS} == {
        ConfirmationMode.HONEST,
        ConfirmationMode.FORGED_BINDING,
        ConfirmationMode.ABSENT,
    }
