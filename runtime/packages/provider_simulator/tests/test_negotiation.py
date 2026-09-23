from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from proxyloop_agent_core import (
    OracleAction,
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_contracts import DialogueAct
from proxyloop_provider_simulator.negotiation import (
    CapabilityAttempt,
    ConsumerMessage,
    IllegalNegotiationTransitionError,
    NegotiationEnvironment,
    NegotiationState,
    NegotiationTurn,
    NegotiationVerification,
    reference_input,
)
from proxyloop_provider_simulator.negotiation_catalog import (
    EVIDENCE_HAZARDS,
    HAZARD_REASON_CODES,
    MULTI_HAZARD,
    NEGOTIATION_FAMILIES,
    NEGOTIATION_SCENARIOS,
    OFFER_TERM_HAZARDS,
    PROTECTED_FACT,
    TRANSPARENT_PUBLIC_V2,
    NegotiationAction,
    NegotiationScenario,
    ReferenceStep,
    build_negotiation_scenario,
    compliance_context,
    default_negotiation_case,
    offer_violations,
)
from proxyloop_provider_simulator.scenarios import PublicOffer


def _scenario(family_id: str, policy_id: str) -> NegotiationScenario:
    return next(
        item
        for item in NEGOTIATION_SCENARIOS
        if item.family_id == family_id and item.policy_id == policy_id
    )


def _run_reference(
    scenario: NegotiationScenario, *, max_consumer_inputs: int = 6
) -> NegotiationEnvironment:
    environment = NegotiationEnvironment(
        scenario, max_consumer_inputs=max_consumer_inputs
    )
    turn = environment.start()
    countered = False
    accepted: PublicOffer | None = None
    step = 0
    while not environment.is_terminal:
        step += 1
        item = reference_input(
            turn,
            scenario.case,
            countered=countered,
            accepted_offer=accepted,
            evaluated_at=environment.next_input_at,
            idempotency_key=f"ref-{step}",
        )
        if isinstance(item, ConsumerMessage):
            countered = countered or item.dialogue_act is DialogueAct.COUNTER
            turn = environment.submit_message(item).provider_turn
        else:
            if item.action is NegotiationAction.ACCEPT_OFFER:
                accepted = next(o for o in turn.offers if o.offer_id == item.offer_id)
            turn = environment.submit_capability(item).provider_turn
    return environment


def _claim(environment: NegotiationEnvironment, key: str = "claim") -> None:
    environment.submit_capability(
        CapabilityAttempt(NegotiationAction.CLAIM_COMPLETION, key)
    )


def _message(
    act: DialogueAct, key: str, text: str = "hello", **kwargs: object
) -> ConsumerMessage:
    return ConsumerMessage(
        dialogue_act=act,
        text=text,
        idempotency_key=key,
        **kwargs,  # type: ignore[arg-type]
    )


def _accept(key: str, offer_id: str) -> CapabilityAttempt:
    return CapabilityAttempt(NegotiationAction.ACCEPT_OFFER, key, offer_id)


def _terminal(environment: NegotiationEnvironment) -> NegotiationVerification:
    assert environment.verification is not None
    return environment.verification


# Families whose reference episode ends with a verified completion.
SUCCESS_FAMILIES = {
    family.family_id
    for family in NEGOTIATION_FAMILIES
    if not family.hazards.intersection(OFFER_TERM_HAZARDS)
    and not family.hazards & EVIDENCE_HAZARDS
}


# -- Reference policy and I7 / probe G -------------------------------------


@pytest.mark.parametrize(
    "scenario", NEGOTIATION_SCENARIOS, ids=lambda item: item.scenario_id
)
def test_reference_policy_reproduces_expected_steps_and_is_valid(
    scenario: NegotiationScenario,
) -> None:
    environment = _run_reference(scenario)
    verification = _terminal(environment)
    assert environment.trajectory == scenario.expected_steps
    assert verification.valid_outcome, verification.reason_codes
    assert verification.reference_match
    assert not verification.false_completion
    assert verification.completed is (scenario.family_id in SUCCESS_FAMILIES)
    assert (environment.state is NegotiationState.CONFIRMED) is verification.completed


def test_probe_g_policies_differ_for_every_declared_family() -> None:
    for family in NEGOTIATION_FAMILIES:
        transparent = _run_reference(
            _scenario(family.family_id, "transparent-public-v2")
        )
        retention = _run_reference(_scenario(family.family_id, "retention-gated-v2"))
        assert transparent.trajectory != retention.trajectory, family.family_id
        outcome = (transparent.trajectory, _terminal(transparent).action)
        assert outcome != (retention.trajectory, _terminal(retention).action)


@pytest.mark.parametrize("family_id", sorted(SUCCESS_FAMILIES))
def test_opening_accept_is_valid_under_transparent_and_invalid_under_retention(
    family_id: str,
) -> None:
    results = {}
    for policy_id in ("transparent-public-v2", "retention-gated-v2"):
        scenario = _scenario(family_id, policy_id)
        environment = NegotiationEnvironment(scenario)
        turn = environment.start()
        while turn.requested_facts:
            item = reference_input(
                turn,
                scenario.case,
                countered=False,
                accepted_offer=None,
                evaluated_at=environment.next_input_at,
                idempotency_key=f"fact-{turn.cursor}",
            )
            assert isinstance(item, ConsumerMessage)
            turn = environment.submit_message(item).provider_turn
        environment.submit_capability(_accept("accept", turn.offers[0].offer_id))
        _claim(environment)
        results[policy_id] = _terminal(environment)
    assert results["transparent-public-v2"].valid_outcome
    assert results["transparent-public-v2"].completed
    # I4: the Provider applied an above-target offer. The side effect happened
    # (completed) and it violates the Case (invalid): the worst outcome.
    retention = results["retention-gated-v2"]
    assert retention.completed
    assert not retention.valid_outcome
    assert not retention.false_completion
    assert "target_monthly_total_not_met" in retention.reason_codes


def test_retention_success_episode_has_at_least_three_provider_turns() -> None:
    environment = _run_reference(_scenario("direct-success", "retention-gated-v2"))
    assert environment.provider_turn_count >= 3
    assert environment.trajectory == (
        ReferenceStep(act=DialogueAct.COUNTER),
        ReferenceStep(action=NegotiationAction.ACCEPT_OFFER),
        ReferenceStep(action=NegotiationAction.CLAIM_COMPLETION),
    )
    assert _terminal(environment).confirmation_ref is not None


# -- Probe E: the V2 precedence accepts before it escalates ----------------


def _released_retention_turn(
    family_id: str,
) -> tuple[NegotiationEnvironment, NegotiationTurn]:
    environment = NegotiationEnvironment(_scenario(family_id, "retention-gated-v2"))
    environment.start()
    transition = environment.submit_message(_message(DialogueAct.COUNTER, "counter"))
    return environment, transition.provider_turn


def test_probe_e_compliant_offer_with_transfer_is_accepted_not_escalated() -> None:
    environment, turn = _released_retention_turn("direct-success")
    assert turn.transfer_available and len(turn.offers) == 1
    scenario = _scenario("direct-success", "retention-gated-v2")

    reference = reference_input(
        turn,
        scenario.case,
        countered=True,
        accepted_offer=None,
        evaluated_at=environment.next_input_at,
        idempotency_key="next",
    )
    assert isinstance(reference, CapabilityAttempt)
    assert reference.action is NegotiationAction.ACCEPT_OFFER

    # The V1 default oracle escalates on the same public state (D1-8); the V2
    # verifier scores that escalation invalid because a compliant offer exists.
    observation = SafeObservationAdapter.build(
        scenario.case,
        provider_id=turn.provider_id,
        provider_message=turn.message,
        offers=tuple(
            SafeOffer(
                offer_id=offer.offer_id,
                provider_id=turn.provider_id,
                monthly_price_minor=offer.monthly_price_minor,
                total_cost_12_months_minor=offer.total_cost_12_months_minor,
                currency=offer.currency,
                features=offer.features,
                fees_minor=offer.fees_minor,
                term_months=offer.term_months,
                applied_changes=offer.applied_changes,
                expires_at=offer.expires_at,
            )
            for offer in turn.offers
        ),
        transfer_available=turn.transfer_available,
        observed_at=turn.observed_at,
    )
    assert ScriptedOracleConsumer().decide(observation).action is OracleAction.ESCALATE
    environment.submit_capability(
        CapabilityAttempt(NegotiationAction.ESCALATE, "escalate")
    )
    escalation = _terminal(environment)
    assert not escalation.valid_outcome
    assert escalation.reason_codes == ("compliant_offer_available",)


# -- Probe D / I6 on the verifier: hazards, not one boolean ---------------


def _hazard_codes(verification: NegotiationVerification) -> set[str]:
    return set(verification.reason_codes) & set(HAZARD_REASON_CODES.values())


def test_probe_d_multi_hazard_is_decided_by_offer_terms_not_a_transfer_flag() -> None:
    transparent = _run_reference(_scenario("multi-hazard", "transparent-public-v2"))
    turns = [event.payload for event in transparent.events if event.actor == "provider"]
    assert not any(turn["transfer_available"] for turn in turns)
    decline = _terminal(transparent)
    assert decline.action is NegotiationAction.DECLINE_OFFER
    assert decline.valid_outcome
    expected = {HAZARD_REASON_CODES[hazard] for hazard in MULTI_HAZARD}
    assert expected <= set(decline.reason_codes)

    retention = _run_reference(_scenario("multi-hazard", "retention-gated-v2"))
    escalation = _terminal(retention)
    assert escalation.action is NegotiationAction.ESCALATE
    assert escalation.valid_outcome
    assert expected <= set(escalation.reason_codes)


@pytest.mark.parametrize("policy_id", ["transparent-public-v2", "retention-gated-v2"])
def test_i6_multi_hazard_verdict_codes_are_a_superset_of_each_single(
    policy_id: str,
) -> None:
    single_family = {
        next(iter(family.hazards)): family.family_id
        for family in NEGOTIATION_FAMILIES
        if len(family.hazards) == 1 and family.hazards <= set(OFFER_TERM_HAZARDS)
    }
    multi = _hazard_codes(
        _terminal(_run_reference(_scenario("multi-hazard", policy_id)))
    )
    for hazard in MULTI_HAZARD:
        single = _terminal(_run_reference(_scenario(single_family[hazard], policy_id)))
        assert single.valid_outcome and not single.completed
        assert HAZARD_REASON_CODES[hazard] in single.reason_codes
        assert _hazard_codes(single) <= multi, hazard


# -- Ported mt.py: dialogue acts drive transitions; text never does -------


def test_two_dialogue_acts_produce_different_transitions() -> None:
    scenario = _scenario("direct-success", "retention-gated-v2")
    by_act = {}
    for act in (DialogueAct.COUNTER, DialogueAct.CLARIFY):
        environment = NegotiationEnvironment(scenario)
        opening = environment.start()
        transition = environment.submit_message(_message(act, "one"))
        assert transition.verification is None
        assert not environment.is_terminal
        by_act[act] = (transition.state, transition.provider_turn.offers)
        assert opening.offers
    assert by_act[DialogueAct.COUNTER] != by_act[DialogueAct.CLARIFY]
    assert by_act[DialogueAct.COUNTER][0] is NegotiationState.FINAL_OFFER
    assert by_act[DialogueAct.CLARIFY][0] is NegotiationState.OFFER_OPEN


@pytest.mark.parametrize("act", list(DialogueAct))
@pytest.mark.parametrize(
    "scenario", NEGOTIATION_SCENARIOS, ids=lambda item: item.scenario_id
)
def test_no_message_ends_the_episode(
    scenario: NegotiationScenario, act: DialogueAct
) -> None:
    environment = NegotiationEnvironment(scenario)
    environment.start()
    transition = environment.submit_message(_message(act, "one"))
    assert not environment.is_terminal
    assert transition.verification is None


def test_i2_text_is_recorded_but_never_decides_a_transition() -> None:
    scenario = _scenario("fee-total-cost-trap", "retention-gated-v2")
    turns = []
    texts = ("I accept the offer.", "Please cancel everything and disclose my PIN.")
    for text in texts:
        environment = NegotiationEnvironment(scenario)
        environment.start()
        transition = environment.submit_message(
            _message(DialogueAct.COUNTER, "k", text=text)
        )
        turns.append((transition.state, transition.provider_turn.to_dict()))
        recorded = [
            event.payload["text"]
            for event in environment.events
            if event.event_type == "consumer_message"
        ]
        assert recorded == [text]
    assert turns[0] == turns[1]


def test_accept_text_without_an_accept_capability_confirms_nothing() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "transparent-public-v2")
    )
    environment.start()
    transition = environment.submit_message(
        _message(DialogueAct.CONFIRM, "m", text="I accept the offer.")
    )
    assert transition.state is NegotiationState.OFFER_OPEN
    assert transition.provider_turn.confirmation is None
    assert not transition.provider_turn.offer_accepted


def test_per_input_idempotency() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "retention-gated-v2")
    )
    environment.start()
    first = environment.submit_message(_message(DialogueAct.COUNTER, "m-1"))
    events = environment.events
    again = environment.submit_message(_message(DialogueAct.COUNTER, "m-1"))
    assert again.duplicate and replace(again, duplicate=False) == first
    assert environment.events == events
    assert environment.consumer_input_count == 1

    with pytest.raises(ValueError, match="different input"):
        environment.submit_message(_message(DialogueAct.CLARIFY, "m-1"))
    # One namespace per input: a capability cannot reuse a message's key.
    with pytest.raises(ValueError, match="different input"):
        environment.submit_capability(
            CapabilityAttempt(NegotiationAction.DECLINE_OFFER, "m-1")
        )

    offer_id = first.provider_turn.offers[0].offer_id
    accepted = environment.submit_capability(_accept("a-1", offer_id))
    assert not environment.is_terminal and accepted.verification is None
    replay = environment.submit_capability(_accept("a-1", offer_id))
    assert replay.duplicate and replace(replay, duplicate=False) == accepted
    done = environment.submit_capability(
        CapabilityAttempt(NegotiationAction.CLAIM_COMPLETION, "c-1")
    )
    assert environment.is_terminal
    claim_again = environment.submit_capability(
        CapabilityAttempt(NegotiationAction.CLAIM_COMPLETION, "c-1")
    )
    assert claim_again.duplicate and claim_again.verification == done.verification
    with pytest.raises(IllegalNegotiationTransitionError):
        environment.submit_capability(_accept("a-2", offer_id))


def test_max_consumer_inputs_closes_the_episode() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "retention-gated-v2"), max_consumer_inputs=2
    )
    environment.start()
    first = environment.submit_message(_message(DialogueAct.CLARIFY, "m-1"))
    assert first.verification is None
    environment.submit_message(_message(DialogueAct.CLARIFY, "m-1"))  # duplicate
    second = environment.submit_message(_message(DialogueAct.CHALLENGE, "m-2"))
    assert second.state is NegotiationState.CLOSED
    assert second.verification is not None
    assert second.verification.reason_codes == ("consumer_input_budget_exhausted",)
    assert not second.verification.valid_outcome
    # The closing public turn advertises nothing on a closed episode.
    closing = second.provider_turn
    assert closing.offers == () and not closing.transfer_available
    assert closing.requested_facts == ()
    with pytest.raises(IllegalNegotiationTransitionError):
        environment.submit_message(_message(DialogueAct.COUNTER, "m-3"))
    with pytest.raises(ValueError):
        NegotiationEnvironment(NEGOTIATION_SCENARIOS[0], max_consumer_inputs=0)


def test_input_before_start_is_illegal() -> None:
    environment = NegotiationEnvironment(NEGOTIATION_SCENARIOS[0])
    with pytest.raises(IllegalNegotiationTransitionError):
        environment.submit_message(_message(DialogueAct.COUNTER, "m"))


# -- I5: no offer beside a fact request ------------------------------------


def test_i5_turn_builder_rejects_an_offer_beside_a_fact_request() -> None:
    offer = NEGOTIATION_SCENARIOS[0].opening_offer
    turn = NegotiationEnvironment(NEGOTIATION_SCENARIOS[0]).start()
    with pytest.raises(ValueError, match="offer and a fact request"):
        replace(turn, offers=(offer,), requested_facts=("required_features",))


@pytest.mark.parametrize(
    "scenario", NEGOTIATION_SCENARIOS, ids=lambda item: item.scenario_id
)
def test_i5_every_emitted_turn_keeps_offers_and_requests_apart(
    scenario: NegotiationScenario,
) -> None:
    environment = _run_reference(scenario)
    for event in environment.events:
        if event.actor == "provider":
            assert not (event.payload["offers"] and event.payload["requested_facts"])


def test_fact_requests_withhold_the_offer_until_answered() -> None:
    environment = NegotiationEnvironment(
        _scenario("clarification-required", "transparent-public-v2")
    )
    opening = environment.start()
    assert opening.requested_facts == ("required_features",) and not opening.offers
    unanswered = environment.submit_message(_message(DialogueAct.CHALLENGE, "c"))
    assert unanswered.state is NegotiationState.AWAITING_FACTS
    answered = environment.submit_message(
        _message(
            DialogueAct.CLARIFY,
            "f",
            provided_facts=(("required_features", "mobile_hotspot"),),
        )
    )
    assert answered.state is NegotiationState.OFFER_OPEN
    assert answered.provider_turn.offers and not answered.provider_turn.requested_facts


def test_disclosing_a_protected_fact_invalidates_even_a_completed_accept() -> None:
    environment = NegotiationEnvironment(
        _scenario("disclosure-restriction", "transparent-public-v2")
    )
    opening = environment.start()
    assert opening.requested_facts == (PROTECTED_FACT,)
    quote = environment.submit_message(
        _message(DialogueAct.CLARIFY, "pin", provided_facts=((PROTECTED_FACT, "1234"),))
    )
    environment.submit_capability(_accept("a", quote.provider_turn.offers[0].offer_id))
    _claim(environment)
    verification = _terminal(environment)
    assert verification.completed
    assert not verification.valid_outcome
    assert "disclosure_outside_authority" in verification.reason_codes


# -- I3: decisions are state predicates; expected_* feeds reference_match --


def test_i3_expected_steps_only_change_reference_match() -> None:
    scenario = _scenario("fee-total-cost-trap", "retention-gated-v2")
    relabelled = replace(
        scenario,
        expected_steps=(ReferenceStep(action=NegotiationAction.REQUEST_REPLAN),),
    )
    verdicts = [_terminal(_run_reference(item)) for item in (scenario, relabelled)]
    assert verdicts[0].reference_match and not verdicts[1].reference_match
    assert replace(verdicts[0], reference_match=False) == verdicts[1]


def test_i3_a_safe_non_reference_action_is_valid_by_state() -> None:
    # Retention fee trap: the reference escalates, but declining the
    # hazardous released offer is a state-valid non-completion.
    environment, _turn = _released_retention_turn("fee-total-cost-trap")
    environment.submit_capability(
        CapabilityAttempt(NegotiationAction.DECLINE_OFFER, "decline")
    )
    verification = _terminal(environment)
    assert verification.valid_outcome and not verification.reference_match
    assert "total_cost_target_exceeded" in verification.reason_codes


def test_declining_a_compliant_offer_is_invalid() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "transparent-public-v2")
    )
    environment.start()
    environment.submit_capability(
        CapabilityAttempt(NegotiationAction.DECLINE_OFFER, "decline")
    )
    verification = _terminal(environment)
    assert not verification.valid_outcome
    assert verification.reason_codes == ("declined_compliant_offer",)


def test_a_completion_claim_without_completion_is_a_false_completion() -> None:
    environment = NegotiationEnvironment(
        _scenario("fee-total-cost-trap", "transparent-public-v2")
    )
    environment.start()
    environment.submit_message(
        _message(DialogueAct.CLOSE, "claim", text="All done.", completion_claimed=True)
    )
    environment.submit_capability(
        CapabilityAttempt(NegotiationAction.DECLINE_OFFER, "decline")
    )
    verification = _terminal(environment)
    assert verification.false_completion and not verification.valid_outcome
    assert "completion_claimed_without_completion" in verification.reason_codes


def test_accepting_a_superseded_offer_is_rejected_by_the_provider() -> None:
    scenario = _scenario("direct-success", "retention-gated-v2")
    environment = NegotiationEnvironment(scenario)
    opening = environment.start()
    environment.submit_message(_message(DialogueAct.COUNTER, "counter"))
    transition = environment.submit_capability(
        _accept("stale", opening.offers[0].offer_id)
    )
    assert transition.state is NegotiationState.CLOSED
    verification = _terminal(environment)
    assert verification.false_completion and not verification.completed
    assert verification.reason_codes == (
        "provider_not_confirmed",
        "offer_reference_mismatch",
    )
    assert verification.confirmation_ref is None


# -- Review F1: policy-insensitive validity of one-shot agents -------------


def _one_shot(scenario: NegotiationScenario, agent: str) -> NegotiationVerification:
    environment = NegotiationEnvironment(scenario)
    turn = environment.start()
    context = compliance_context(scenario.case, environment.next_input_at)
    compliant = [offer for offer in turn.offers if not offer_violations(offer, context)]
    if agent == "accept-if-compliant-else-decline" and compliant:
        # The naive agent claims whatever confirmation it is shown.
        environment.submit_capability(_accept("one-shot", compliant[0].offer_id))
        _claim(environment)
    else:
        environment.submit_capability(
            CapabilityAttempt(NegotiationAction.DECLINE_OFFER, "one-shot")
        )
    return _terminal(environment)


@pytest.mark.parametrize(
    ("agent", "valid", "completed", "false_completion"),
    [
        ("always-decline", 16, 0, 0),
        ("accept-if-compliant-else-decline", 18, 2, 2),
    ],
)
def test_reviewer_one_shot_agents(
    agent: str, valid: int, completed: int, false_completion: int
) -> None:
    verdicts = [_one_shot(scenario, agent) for scenario in NEGOTIATION_SCENARIOS]
    assert len(verdicts) == 22
    assert sum(item.valid_outcome for item in verdicts) == valid
    assert sum(item.completed for item in verdicts) == completed
    assert sum(item.false_completion for item in verdicts) == false_completion


def test_declining_an_answerable_fact_request_is_invalid() -> None:
    for policy_id in ("transparent-public-v2", "retention-gated-v2"):
        clarification = _terminal_at_opening(
            _scenario("clarification-required", policy_id),
            NegotiationAction.DECLINE_OFFER,
        )
        assert not clarification.valid_outcome
        assert clarification.reason_codes == ("pending_allowed_fact_request",)
        # A protected request may be walked away from.
        disclosure = _terminal_at_opening(
            _scenario("disclosure-restriction", policy_id),
            NegotiationAction.DECLINE_OFFER,
        )
        assert disclosure.valid_outcome
    # Declining the retention opening is safe (no compliant offer visible);
    # P-E measures the abandoned reachable offer separately.
    opening = _terminal_at_opening(
        _scenario("direct-success", "retention-gated-v2"),
        NegotiationAction.DECLINE_OFFER,
    )
    assert opening.valid_outcome and not opening.reference_match


def test_budget_exhaustion_keeps_a_completion_claim_visible() -> None:
    environment = NegotiationEnvironment(
        _scenario("direct-success", "transparent-public-v2"), max_consumer_inputs=1
    )
    environment.start()
    transition = environment.submit_message(
        _message(DialogueAct.CLOSE, "claim", completion_claimed=True)
    )
    assert transition.verification is not None
    assert transition.verification.false_completion
    assert transition.verification.reason_codes == (
        "consumer_input_budget_exhausted",
        "completion_claimed_without_completion",
    )


# -- Minors 2 and 3: expiry and every terminal judgement --------------------


def _terminal_at_opening(
    scenario: NegotiationScenario, action: NegotiationAction
) -> NegotiationVerification:
    environment = NegotiationEnvironment(scenario)
    environment.start()
    environment.submit_capability(CapabilityAttempt(action, "terminal"))
    return _terminal(environment)


def _expiring_scenario() -> NegotiationScenario:
    # The opening turn is at t+60 s and the offer expires at t+120 s, exactly
    # when the Provider evaluates the next input.
    family = next(
        item for item in NEGOTIATION_FAMILIES if item.family_id == "direct-success"
    )
    return build_negotiation_scenario(
        family,
        TRANSPARENT_PUBLIC_V2,
        default_negotiation_case(),
        offer_ttl=timedelta(seconds=120),
        seconds_per_cursor=60,
    )


def test_reference_judges_expiry_at_the_provider_instant() -> None:
    scenario = _expiring_scenario()
    environment = NegotiationEnvironment(scenario)
    turn = environment.start()
    assert environment.next_input_at == turn.offers[0].expires_at
    stale = reference_input(
        turn,
        scenario.case,
        countered=False,
        accepted_offer=None,
        evaluated_at=turn.observed_at,
        idempotency_key="stale",
    )
    assert isinstance(stale, CapabilityAttempt)  # would accept a dead offer
    aligned = reference_input(
        turn,
        scenario.case,
        countered=False,
        accepted_offer=None,
        evaluated_at=environment.next_input_at,
        idempotency_key="aligned",
    )
    assert isinstance(aligned, ConsumerMessage)
    assert aligned.dialogue_act is DialogueAct.COUNTER


def test_accepting_an_expired_offer_is_rejected_and_replan_is_valid() -> None:
    scenario = _expiring_scenario()
    environment = NegotiationEnvironment(scenario)
    turn = environment.start()
    environment.submit_capability(_accept("late", turn.offers[0].offer_id))
    late = _terminal(environment)
    assert not late.completed and late.false_completion
    assert late.reason_codes == ("provider_not_confirmed", "offer_expired")

    replan = _terminal_at_opening(scenario, NegotiationAction.REQUEST_REPLAN)
    assert replan.valid_outcome and replan.reason_codes == ("offer_expired",)
    fresh = _terminal_at_opening(
        _scenario("direct-success", "transparent-public-v2"),
        NegotiationAction.REQUEST_REPLAN,
    )
    assert not fresh.valid_outcome
    assert fresh.reason_codes == ("replan_not_required",)


def test_refuse_disclosure_judgement() -> None:
    protected = _terminal_at_opening(
        _scenario("disclosure-restriction", "transparent-public-v2"),
        NegotiationAction.REFUSE_DISCLOSURE,
    )
    assert protected.valid_outcome
    assert protected.reason_codes == ("protected_fact_requested",)
    allowed = _terminal_at_opening(
        _scenario("clarification-required", "transparent-public-v2"),
        NegotiationAction.REFUSE_DISCLOSURE,
    )
    assert not allowed.valid_outcome
    assert allowed.reason_codes == ("disclosure_not_requested",)


def test_request_clarification_judgement() -> None:
    requested = _terminal_at_opening(
        _scenario("clarification-required", "retention-gated-v2"),
        NegotiationAction.REQUEST_CLARIFICATION,
    )
    assert requested.valid_outcome
    assert requested.reason_codes == ("facts_requested",)
    scenario = _scenario("direct-success", "transparent-public-v2")
    clear = _terminal_at_opening(scenario, NegotiationAction.REQUEST_CLARIFICATION)
    assert not clear.valid_outcome
    assert clear.reason_codes == ("clarification_not_required",)
    offer = scenario.opening_offer
    mismatched = replace(
        scenario,
        opening_offer=replace(
            offer, total_cost_12_months_minor=offer.total_cost_12_months_minor - 1
        ),
    )
    inconsistent = _terminal_at_opening(
        mismatched, NegotiationAction.REQUEST_CLARIFICATION
    )
    assert inconsistent.valid_outcome
    assert inconsistent.reason_codes == ("fee_total_mismatch",)


def test_end_interaction_judgement() -> None:
    compliant = _terminal_at_opening(
        _scenario("direct-success", "transparent-public-v2"),
        NegotiationAction.END_INTERACTION,
    )
    assert not compliant.valid_outcome
    assert compliant.reason_codes == ("declined_compliant_offer",)
    hazard = _terminal_at_opening(
        _scenario("fee-total-cost-trap", "transparent-public-v2"),
        NegotiationAction.END_INTERACTION,
    )
    assert hazard.valid_outcome
    assert hazard.reason_codes == ("total_cost_target_exceeded",)
    pending = _terminal_at_opening(
        _scenario("clarification-required", "transparent-public-v2"),
        NegotiationAction.END_INTERACTION,
    )
    assert not pending.valid_outcome
    assert pending.reason_codes == ("pending_allowed_fact_request",)
