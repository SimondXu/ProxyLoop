"""V2 reference consumer vs the agent_core oracle under V2_OFFER_FIRST.

On every public turn the V2 reference visits, the negotiation turn is mapped
to a ``SafeObservation`` and both policies decide.  They must agree, or the
disagreement must be one of the documented intended differences below: the
V2 reference acts inside a multi-turn dialogue that the one-shot oracle
vocabulary cannot express.
"""

from __future__ import annotations

from proxyloop_agent_core import (
    OraclePrecedence,
    SafeObservation,
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_contracts import DialogueAct
from proxyloop_provider_simulator.negotiation import (
    ConsumerMessage,
    NegotiationEnvironment,
    NegotiationTurn,
    reference_input,
)
from proxyloop_provider_simulator.negotiation_catalog import (
    NEGOTIATION_SCENARIOS,
    NegotiationAction,
    NegotiationScenario,
    bound_terms,
    offer_terms_hash,
)
from proxyloop_provider_simulator.scenarios import PublicOffer

ORACLE = ScriptedOracleConsumer(precedence=OraclePrecedence.V2_OFFER_FIRST)

# (reference step, oracle action) -> why the two intentionally differ.
INTENDED_DIFFERENCES = {
    ("clarify", "request_clarification"): (
        "an allowed fact request: the reference answers it from the Case; the "
        "oracle asks the principal"
    ),
    ("challenge", "refuse_disclosure"): (
        "a protected fact request: both refuse; the reference keeps negotiating"
    ),
    ("counter", "decline"): (
        "no compliant offer yet: the reference counters once before walking away"
    ),
    ("claim_completion", "decline"): (
        "after an accept with a binding confirmation: the reference claims "
        "completion, which the oracle vocabulary cannot express"
    ),
    ("claim_completion", "escalate"): (
        "the same post-accept claim while the policy keeps a transfer open"
    ),
}
AGREEMENT = {
    "accept_offer": "accept_offer",
    "decline_offer": "decline",
    "escalate": "escalate",
    "request_replan": "request_replan",
}


def _echo_binds(turn: NegotiationTurn, accepted: PublicOffer | None) -> bool:
    echo = turn.confirmation
    return (
        accepted is not None
        and echo is not None
        and echo.offer_id == accepted.offer_id
        and echo.offer_revision == accepted.revision
        and echo.terms == bound_terms(accepted)
        and echo.material_terms_hash == offer_terms_hash(accepted)
    )


def _observation(
    scenario: NegotiationScenario,
    environment: NegotiationEnvironment,
    turn: NegotiationTurn,
    accepted: PublicOffer | None,
) -> SafeObservation:
    allowed = {
        str(item) for item in scenario.case.delegated_authority.allowed_disclosures
    }
    answerable = bool(turn.requested_facts) and set(turn.requested_facts) <= allowed
    return SafeObservationAdapter.build(
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
        requested_disclosures=() if answerable else turn.requested_facts,
        needs_clarification=answerable,
        transfer_available=turn.transfer_available,
        # V2 has no approval state; before an accept every offer comes with
        # Provider confirmation, after it the echo must bind the accept.
        approval_current=True,
        confirmation_evidence_available=(
            _echo_binds(turn, accepted) if turn.offer_accepted else True
        ),
        # The instant the Provider will evaluate the next input.
        observed_at=environment.next_input_at,
    )


def _decision_pairs() -> list[tuple[str, str, bool]]:
    """(reference step, oracle action, same offer) for every visited turn."""

    pairs: list[tuple[str, str, bool]] = []
    for scenario in NEGOTIATION_SCENARIOS:
        environment = NegotiationEnvironment(scenario)
        turn = environment.start()
        countered = False
        accepted: PublicOffer | None = None
        step = 0
        while not environment.is_terminal:
            step += 1
            oracle = ORACLE.decide(_observation(scenario, environment, turn, accepted))
            item = reference_input(
                turn,
                scenario.case,
                countered=countered,
                accepted_offer=accepted,
                evaluated_at=environment.next_input_at,
                idempotency_key=f"step-{step}",
            )
            if isinstance(item, ConsumerMessage):
                pairs.append((item.dialogue_act.value, oracle.action.value, True))
                countered = countered or item.dialogue_act is DialogueAct.COUNTER
                turn = environment.submit_message(item).provider_turn
                continue
            pairs.append(
                (
                    item.action.value,
                    oracle.action.value,
                    item.offer_id == oracle.offer_id,
                )
            )
            if item.action is NegotiationAction.ACCEPT_OFFER:
                accepted = next(o for o in turn.offers if o.offer_id == item.offer_id)
            turn = environment.submit_capability(item).provider_turn
    return pairs


def test_reference_agrees_with_the_v2_oracle_or_differs_as_documented() -> None:
    pairs = _decision_pairs()
    unexplained = [
        (reference, oracle)
        for reference, oracle, same_offer in pairs
        if not (AGREEMENT.get(reference) == oracle and same_offer)
        and (reference, oracle) not in INTENDED_DIFFERENCES
    ]
    assert unexplained == []
    observed = {(reference, oracle) for reference, oracle, _same in pairs}
    # Every documented difference actually occurs, and so does agreement.
    assert set(INTENDED_DIFFERENCES) <= observed
    agreed = {
        reference
        for reference, oracle, same in pairs
        if AGREEMENT.get(reference) == oracle and same
    }
    assert agreed == set(AGREEMENT)


def test_intended_differences_are_only_steps_outside_the_oracle_vocabulary() -> None:
    # Whenever the reference takes an action the oracle can also take (accept,
    # decline, escalate, replan), the two must agree; differences are limited
    # to dialogue steps and the post-accept claim.
    for reference, oracle in INTENDED_DIFFERENCES:
        assert reference not in AGREEMENT
        assert oracle != "accept_offer"
