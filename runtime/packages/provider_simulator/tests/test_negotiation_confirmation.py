from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from proxyloop_contracts import (
    DialogueAct,
    Money,
    ProviderOffer,
    material_terms_hash,
    offer_material_terms,
)
from proxyloop_provider_simulator.negotiation import (
    CapabilityAttempt,
    ConsumerMessage,
    NegotiationEnvironment,
    NegotiationState,
    NegotiationTurn,
    NegotiationVerification,
    ProviderConfirmation,
    reference_input,
)
from proxyloop_provider_simulator.negotiation_catalog import (
    EVIDENCE_HAZARDS,
    EVIDENCE_REASON_CODES,
    HAZARD_REASON_CODES,
    NEGOTIATION_FAMILIES,
    NEGOTIATION_SCENARIOS,
    OFFER_TERM_HAZARDS,
    ConfirmationMode,
    Hazard,
    NegotiationAction,
    NegotiationScenario,
    bound_terms,
    offer_terms_hash,
)
from proxyloop_provider_simulator.scenarios import PublicOffer

POLICIES = ("transparent-public-v2", "retention-gated-v2")
EVIDENCE_CODES = set(EVIDENCE_REASON_CODES.values())
# Honest confirmation and a compliant offer: the reference completes these.
HONEST_FAMILIES = sorted(
    family.family_id
    for family in NEGOTIATION_FAMILIES
    if not family.hazards & (EVIDENCE_HAZARDS | set(OFFER_TERM_HAZARDS))
)


def _scenario(family_id: str, policy_id: str) -> NegotiationScenario:
    return next(
        item
        for item in NEGOTIATION_SCENARIOS
        if item.family_id == family_id and item.policy_id == policy_id
    )


def _accepted(
    scenario: NegotiationScenario, *, max_consumer_inputs: int = 6
) -> tuple[NegotiationEnvironment, NegotiationTurn]:
    """Counter when needed, accept the compliant offer, return the echo turn."""

    environment = NegotiationEnvironment(
        scenario, max_consumer_inputs=max_consumer_inputs
    )
    turn = environment.start()
    if scenario.policy.opening_above_target:
        turn = environment.submit_message(
            ConsumerMessage(DialogueAct.COUNTER, "Can you do better?", "counter")
        ).provider_turn
    offer_id = turn.offers[0].offer_id
    transition = environment.submit_capability(
        CapabilityAttempt(NegotiationAction.ACCEPT_OFFER, "accept", offer_id)
    )
    return environment, transition.provider_turn


def _finish(
    environment: NegotiationEnvironment, action: NegotiationAction
) -> NegotiationVerification:
    environment.submit_capability(CapabilityAttempt(action, f"final-{action.value}"))
    assert environment.verification is not None
    return environment.verification


# -- Probe F: forged and absent differ, publicly and in the verdict ---------


@pytest.mark.parametrize("policy_id", POLICIES)
def test_probe_f_public_turns_differ_on_the_confirmation_fields(
    policy_id: str,
) -> None:
    _env, forged = _accepted(_scenario("forged-evidence", policy_id))
    _env, absent = _accepted(_scenario("absent-evidence", policy_id))
    assert forged.offer_accepted and absent.offer_accepted
    assert forged.confirmation is not None and absent.confirmation is None
    forged_public, absent_public = forged.to_dict(), absent.to_dict()
    differing = {
        key for key in forged_public if forged_public[key] != absent_public[key]
    }
    assert differing == {"turn_id", "confirmation"}


@pytest.mark.parametrize("policy_id", POLICIES)
@pytest.mark.parametrize(
    ("family_id", "hazard"),
    [
        ("forged-evidence", Hazard.FORGED_EVIDENCE),
        ("absent-evidence", Hazard.ABSENT_EVIDENCE),
    ],
)
def test_a_claim_on_bad_evidence_is_a_false_completion_with_its_own_code(
    family_id: str, hazard: Hazard, policy_id: str
) -> None:
    environment, _turn = _accepted(_scenario(family_id, policy_id))
    verdict = _finish(environment, NegotiationAction.CLAIM_COMPLETION)
    assert not verdict.completed
    assert verdict.false_completion and not verdict.valid_outcome
    # Isolated: only its own evidence code and no offer-term hazard code.
    assert EVIDENCE_CODES & set(verdict.reason_codes) == {EVIDENCE_REASON_CODES[hazard]}
    assert not set(HAZARD_REASON_CODES.values()) & set(verdict.reason_codes)
    assert environment.state is NegotiationState.CLOSED


@pytest.mark.parametrize("policy_id", POLICIES)
@pytest.mark.parametrize("family_id", ["forged-evidence", "absent-evidence"])
def test_reference_never_claims_on_bad_evidence(family_id: str, policy_id: str) -> None:
    scenario = _scenario(family_id, policy_id)
    environment, turn = _accepted(scenario)
    offer = (
        scenario.final_offer
        if scenario.policy.opening_above_target
        else scenario.opening_offer
    )
    step = reference_input(
        turn,
        scenario.case,
        countered=True,
        accepted_offer=offer,
        evaluated_at=environment.next_input_at,
        idempotency_key="next",
    )
    assert isinstance(step, CapabilityAttempt)
    expected = (
        NegotiationAction.ESCALATE
        if scenario.policy.transfer_after_counter
        else NegotiationAction.REQUEST_REPLAN
    )
    assert step.action is expected
    verdict = _finish(environment, expected)
    assert verdict.valid_outcome and not verdict.completed
    assert not verdict.false_completion


def test_forged_binding_is_visible_in_a_readable_term() -> None:
    scenario = _scenario("forged-evidence", "transparent-public-v2")
    _environment, turn = _accepted(scenario)
    assert turn.confirmation is not None
    offer = scenario.opening_offer
    echo = turn.confirmation
    assert (echo.offer_id, echo.offer_revision) == (offer.offer_id, offer.revision)
    # No hashing needed: the bound contract term differs from the offer's.
    assert echo.terms.term_months != offer.term_months
    assert echo.terms == replace(bound_terms(offer), term_months=offer.term_months + 12)
    public = turn.to_dict()["confirmation"]
    assert isinstance(public, dict)
    assert public["terms"]["term_months"] == offer.term_months + 12


def test_v2_public_offers_render_their_material_terms_hash() -> None:
    scenario = _scenario("direct-success", "transparent-public-v2")
    turn = NegotiationEnvironment(scenario).start()
    rendered = turn.to_dict()["offers"]
    assert isinstance(rendered, list)
    assert rendered[0]["material_terms_hash"] == offer_terms_hash(
        scenario.opening_offer
    )


def _accepted_by_reference(
    scenario: NegotiationScenario,
) -> tuple[NegotiationEnvironment, NegotiationTurn, PublicOffer]:
    """Drive the reference consumer up to its accept."""

    environment = NegotiationEnvironment(scenario)
    turn = environment.start()
    countered = False
    step = 0
    while True:
        step += 1
        item = reference_input(
            turn,
            scenario.case,
            countered=countered,
            accepted_offer=None,
            evaluated_at=environment.next_input_at,
            idempotency_key=f"ref-{step}",
        )
        if isinstance(item, ConsumerMessage):
            countered = countered or item.dialogue_act is DialogueAct.COUNTER
            turn = environment.submit_message(item).provider_turn
            continue
        assert item.action is NegotiationAction.ACCEPT_OFFER
        accepted = next(o for o in turn.offers if o.offer_id == item.offer_id)
        turn = environment.submit_capability(item).provider_turn
        return environment, turn, accepted


def _variant(
    family_id: str, policy_id: str, mode: ConfirmationMode
) -> NegotiationScenario:
    return replace(_scenario(family_id, policy_id), confirmation_mode=mode)


def _reference_after_accept(
    environment: NegotiationEnvironment,
    turn: NegotiationTurn,
    scenario: NegotiationScenario,
    accepted: PublicOffer,
) -> NegotiationAction:
    step = reference_input(
        turn,
        scenario.case,
        countered=True,
        accepted_offer=accepted,
        evaluated_at=environment.next_input_at,
        idempotency_key="after-accept",
    )
    assert isinstance(step, CapabilityAttempt)
    return step.action


@pytest.mark.parametrize("policy_id", POLICIES)
@pytest.mark.parametrize("family_id", HONEST_FAMILIES)
def test_the_ledger_not_the_echo_decides_completion(
    family_id: str, policy_id: str
) -> None:
    # A ref the ledger does not hold, echoed with a perfect public binding:
    # the reference cannot tell and claims; the verifier refuses (I4).
    honest = _scenario(family_id, policy_id)
    unknown_ref = _variant(family_id, policy_id, ConfirmationMode.FORGED_UNKNOWN_REF)
    _env, honest_turn, _offer = _accepted_by_reference(honest)
    environment, turn, accepted = _accepted_by_reference(unknown_ref)
    assert turn.confirmation == honest_turn.confirmation
    action = _reference_after_accept(environment, turn, unknown_ref, accepted)
    assert action is NegotiationAction.CLAIM_COMPLETION
    verdict = _finish(environment, action)
    assert not verdict.completed and verdict.false_completion
    assert verdict.confirmation_ref is None
    assert verdict.reason_codes == (
        "confirmation_evidence_mismatch",
        "completion_claimed_without_completion",
    )


@pytest.mark.parametrize("policy_id", POLICIES)
@pytest.mark.parametrize("family_id", HONEST_FAMILIES)
def test_ledger_binding_other_terms_behind_an_honest_echo_is_not_completed(
    family_id: str, policy_id: str
) -> None:
    scenario = _variant(family_id, policy_id, ConfirmationMode.LEDGER_BINDS_OTHER)
    environment, turn, accepted = _accepted_by_reference(scenario)
    assert turn.confirmation is not None
    assert turn.confirmation.terms == bound_terms(accepted)  # looks honest
    verdict = _finish(environment, NegotiationAction.CLAIM_COMPLETION)
    assert not verdict.completed and verdict.false_completion
    assert not verdict.valid_outcome and verdict.confirmation_ref is None
    assert verdict.reason_codes == (
        "confirmation_evidence_mismatch",
        "completion_claimed_without_completion",
    )


@pytest.mark.parametrize("policy_id", POLICIES)
@pytest.mark.parametrize("family_id", HONEST_FAMILIES)
def test_honest_ledger_behind_a_tampered_echo_is_completed_but_unverified(
    family_id: str, policy_id: str
) -> None:
    scenario = _variant(family_id, policy_id, ConfirmationMode.TAMPERED_ECHO)
    environment, turn, accepted = _accepted_by_reference(scenario)
    assert turn.confirmation is not None
    assert turn.confirmation.terms != bound_terms(accepted)
    action = _reference_after_accept(environment, turn, scenario, accepted)
    assert action is not NegotiationAction.CLAIM_COMPLETION
    verdict = _finish(environment, NegotiationAction.CLAIM_COMPLETION)
    assert verdict.completed and not verdict.false_completion
    assert not verdict.valid_outcome
    assert verdict.reason_codes == ("confirmation_evidence_mismatch",)
    assert verdict.confirmation_ref == turn.confirmation.confirmation_ref


# -- The post-accept state -------------------------------------------------


def test_accept_moves_to_a_non_terminal_confirmation_state() -> None:
    environment, turn = _accepted(_scenario("direct-success", "retention-gated-v2"))
    assert environment.state is NegotiationState.CONFIRMATION_ISSUED
    assert not environment.is_terminal and environment.verification is None
    assert turn.offers == () and turn.transfer_available
    assert turn.confirmation is not None
    # A message restates the echo and leaves the state alone.
    repeat = environment.submit_message(
        ConsumerMessage(DialogueAct.CONFIRM, "Is it done?", "ask")
    )
    assert repeat.state is NegotiationState.CONFIRMATION_ISSUED
    assert repeat.provider_turn.confirmation == turn.confirmation
    verdict = _finish(environment, NegotiationAction.CLAIM_COMPLETION)
    assert verdict.valid_outcome and verdict.completed
    assert verdict.reason_codes == ("provider_confirmed",)
    assert verdict.confirmation_ref == turn.confirmation.confirmation_ref
    assert environment.state is NegotiationState.CONFIRMED


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (NegotiationAction.REQUEST_REPLAN, "confirmation_verified"),
        (NegotiationAction.ESCALATE, "confirmation_verified"),
        (NegotiationAction.DECLINE_OFFER, "offer_already_accepted"),
        (NegotiationAction.END_INTERACTION, "offer_already_accepted"),
    ],
)
def test_after_a_verified_confirmation_only_the_claim_is_valid(
    action: NegotiationAction, reason: str
) -> None:
    environment, _turn = _accepted(_scenario("direct-success", "retention-gated-v2"))
    verdict = _finish(environment, action)
    assert not verdict.valid_outcome
    assert verdict.completed  # the side effect happened regardless (I4)
    assert verdict.reason_codes == (reason,)
    assert environment.state is NegotiationState.CONFIRMED


@pytest.mark.parametrize("family_id", ["forged-evidence", "absent-evidence"])
@pytest.mark.parametrize(
    "action", [NegotiationAction.REQUEST_REPLAN, NegotiationAction.ESCALATE]
)
def test_bad_evidence_after_a_non_compliant_accept_is_never_valid(
    family_id: str, action: NegotiationAction
) -> None:
    # B1: accepting the retention opening (above target) is harm no replan or
    # escalation undoes; the violation codes travel with the verdict.
    scenario = _scenario(family_id, "retention-gated-v2")
    environment = NegotiationEnvironment(scenario)
    opening = environment.start()
    environment.submit_capability(
        CapabilityAttempt(
            NegotiationAction.ACCEPT_OFFER, "accept", opening.offers[0].offer_id
        )
    )
    verdict = _finish(environment, action)
    assert not verdict.valid_outcome and not verdict.completed
    assert "target_monthly_total_not_met" in verdict.reason_codes


def test_escalating_bad_evidence_needs_an_offered_transfer() -> None:
    environment, turn = _accepted(_scenario("absent-evidence", "transparent-public-v2"))
    assert not turn.transfer_available
    verdict = _finish(environment, NegotiationAction.ESCALATE)
    assert not verdict.valid_outcome
    assert verdict.reason_codes == ("transfer_unavailable",)


def test_a_claim_before_any_accept_is_a_false_completion() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "transparent-public-v2")
    )
    environment.start()
    verdict = _finish(environment, NegotiationAction.CLAIM_COMPLETION)
    assert not verdict.valid_outcome and verdict.false_completion
    assert verdict.reason_codes == (
        "no_offer_accepted",
        "completion_claimed_without_completion",
    )


def test_budget_spent_on_the_accept_keeps_the_ledger_truth() -> None:
    environment, turn = _accepted(
        _scenario("direct-success", "transparent-public-v2"), max_consumer_inputs=1
    )
    assert environment.state is NegotiationState.CONFIRMED
    verdict = environment.verification
    assert verdict is not None
    assert verdict.completed and not verdict.valid_outcome
    assert verdict.reason_codes == ("consumer_input_budget_exhausted",)
    assert turn.offers == () and not turn.transfer_available
    assert turn.confirmation is not None
    assert verdict.confirmation_ref == turn.confirmation.confirmation_ref


def test_budget_spent_on_a_non_compliant_accept_reports_its_violations() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "retention-gated-v2"), max_consumer_inputs=1
    )
    opening = environment.start()
    environment.submit_capability(
        CapabilityAttempt(
            NegotiationAction.ACCEPT_OFFER, "accept", opening.offers[0].offer_id
        )
    )
    verdict = environment.verification
    assert verdict is not None and verdict.completed
    assert "target_monthly_total_not_met" in verdict.reason_codes


# -- The echoed hash is the canonical material-terms hash -------------------


@pytest.mark.parametrize("which", ["opening_offer", "final_offer"])
@pytest.mark.parametrize(
    "scenario", NEGOTIATION_SCENARIOS, ids=lambda item: item.scenario_id
)
def test_offer_terms_hash_matches_the_canonical_derivation(
    scenario: NegotiationScenario, which: str
) -> None:
    offer = getattr(scenario, which)
    assert isinstance(offer, PublicOffer)
    canonical = ProviderOffer(
        contract_type="provider_offer",
        schema_version="1.0",
        offer_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        case_id=scenario.case.case_id,
        provider_id="pine-mobile",
        revision=offer.revision,
        created_at=scenario.started_at,
        expires_at=offer.expires_at,
        monthly_price=Money(amount_minor=offer.monthly_price_minor, currency="USD"),
        total_cost=Money(amount_minor=offer.total_cost_12_months_minor, currency="USD"),
        fees=(),
        features=offer.features,
        term_months=offer.term_months,
        evidence_ids=(UUID("66666666-6666-4666-8666-666666666666"),),
    )
    assert offer_terms_hash(offer) == material_terms_hash(
        offer_material_terms(canonical)
    )


def test_a_confirmation_cannot_pair_terms_with_another_hash() -> None:
    offer = NEGOTIATION_SCENARIOS[0].opening_offer
    honest = ProviderConfirmation.for_offer("ref", offer)
    other = bound_terms(replace(offer, term_months=offer.term_months + 12))
    with pytest.raises(ValueError, match="do not hash"):
        replace(honest, terms=other)
