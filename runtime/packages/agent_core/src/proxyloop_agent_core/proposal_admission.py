"""The A-3 coordinator admission check for Slow proposals (PR-13).

A Slow result may carry at most one capability proposal and its action
proposal. ``slow_proposal_violations`` relates the two to each other, to the
snapshot's Capability Manifest, offers, Case bindings and delegated
authority, and returns the ``slow_proposal_*`` codes of every rule the pair
breaks. The product Runtime's coordinator runs it on a Slow result that
passed ``validate_slow_result`` and rejects the whole result on any code.
``validate_slow_result`` itself, which is also the ML evaluator's validity
function, is unchanged.

``standing_proposal_offer`` is the Runtime's use-time admissibility test for
the standing proposal. Offer expiry and compliance stay with deterministic
offer policy; neither function decides them.

The executor (``capabilities.CapabilityExecutor``) still checks the same
joins at execution time and stays authoritative there.

This module imports ``proxyloop_contracts`` only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final

from proxyloop_contracts import (
    ActionType,
    CapabilityDefinition,
    CapabilityManifest,
    CapabilityProposal,
    CapabilityReference,
    CaseContextSnapshot,
    MaterialTerm,
    ProviderOffer,
    SlowWorkResult,
    material_terms_hash,
    offer_material_terms,
)

SLOW_PROPOSAL_CHECK_VERSION: Final = "slow-proposal-v1"
SlowProposalCheck = Callable[
    [SlowWorkResult, CaseContextSnapshot, datetime], tuple[str, ...]
]


def slow_proposal_violations(
    result: SlowWorkResult,
    snapshot: CaseContextSnapshot,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    """The A-3 codes ``result``'s proposals break against ``snapshot``.

    A result with no proposals has none. When the proposals are not exactly
    one pair, only the count and pairing codes are returned.
    """

    capabilities = result.capability_proposals
    actions = result.action_proposals
    if not capabilities and not actions:
        return ()
    shape: list[str] = []
    if len(capabilities) > 1 or len(actions) > 1:
        shape.append("slow_proposal_count_exceeded")
    if len(capabilities) != len(actions):
        shape.append("slow_proposal_unpaired")
    if shape:
        return tuple(shape)

    (capability,), (action,) = capabilities, actions
    manifest = snapshot.capability_manifest
    reasons: list[str] = []
    definition = _definition(manifest, capability.capability)
    if definition is None:
        reasons.append("slow_proposal_capability_unsupported")
    elif action.action_type not in definition.allowed_action_types:
        reasons.append("slow_proposal_capability_action_mismatch")
    if _any_expired(capability, definition, manifest, evaluated_at):
        reasons.append("slow_proposal_capability_expired")
    if capability.created_at < result.created_at:
        reasons.append("slow_proposal_predates_result")
    offer_ids = _offer_id_arguments(capability)
    if (action.offer_ref is None and offer_ids) or (
        action.offer_ref is not None and offer_ids != (str(action.offer_ref.offer_id),)
    ):
        reasons.append("slow_proposal_offer_binding_mismatch")
    offer: ProviderOffer | None = None
    if action.offer_ref is not None:
        reference = action.offer_ref
        offer = next(
            (
                item
                for item in snapshot.offers
                if item.offer_id == reference.offer_id
                and item.revision == reference.offer_revision
            ),
            None,
        )
        if offer is None:
            reasons.append("slow_proposal_offer_not_current")
    if action.material_terms_hash != material_terms_hash(action.material_terms) or (
        offer is not None
        and _sorted_terms(action.material_terms)
        != _sorted_terms(offer_material_terms(offer))
    ):
        reasons.append("slow_proposal_terms_mismatch")
    case = snapshot.case
    strategy = (
        result.strategy_proposal
        if result.strategy_proposal is not None
        else snapshot.strategy
    )
    if (
        action.case_id != case.case_id
        or action.case_revision != case.revision
        or action.constraint_set_revision != case.constraint_set_revision
        or strategy is None
        or action.strategy_id != strategy.strategy_id
        or action.strategy_revision != strategy.revision
    ):
        reasons.append("slow_proposal_intent_binding_mismatch")
    authority = case.delegated_authority
    if (
        action.action_type not in authority.allowed_actions
        and action.action_type not in authority.approval_required_actions
    ):
        reasons.append("slow_proposal_action_not_delegated")
    return tuple(reasons)


def standing_proposal_offer(
    proposal: CapabilityProposal | None,
    snapshot: CaseContextSnapshot,
    *,
    evaluated_at: datetime,
) -> ProviderOffer | None:
    """The current offer the standing proposal names.

    None when there is no proposal or it is not admissible at
    ``evaluated_at``: its capability is not in the manifest or is not the
    accept-offer capability, the proposal, definition or manifest has
    expired, or it does not carry exactly one ``offer_id`` naming a snapshot
    offer.

    The offer is matched by id only: a capability proposal carries no offer
    revision. That relies on the Runtime's precondition that a Case holds
    one deterministic offer whose revision never changes (the storage codec
    refuses any other shape), and the A-3 check bound the action's offer
    revision when the proposal was admitted. A Runtime whose offers can be
    revised must also check the revision before compiling an intent.
    """

    if proposal is None:
        return None
    manifest = snapshot.capability_manifest
    definition = _definition(manifest, proposal.capability)
    # The Runtime compiles only an accept-offer intent.
    if definition is None or definition.allowed_action_types != (
        ActionType.ACCEPT_OFFER,
    ):
        return None
    if _any_expired(proposal, definition, manifest, evaluated_at):
        return None
    offer_ids = _offer_id_arguments(proposal)
    if len(offer_ids) != 1:
        return None
    return next(
        (offer for offer in snapshot.offers if str(offer.offer_id) == offer_ids[0]),
        None,
    )


def _definition(
    manifest: CapabilityManifest, reference: CapabilityReference
) -> CapabilityDefinition | None:
    # The same (id, version) match the executor uses.
    return next(
        (
            item
            for item in manifest.capabilities
            if item.capability_id == reference.capability_id
            and item.version == reference.version
        ),
        None,
    )


def _any_expired(
    proposal: CapabilityProposal,
    definition: CapabilityDefinition | None,
    manifest: CapabilityManifest,
    evaluated_at: datetime,
) -> bool:
    expiries = (
        proposal.expires_at,
        definition.expires_at if definition is not None else None,
        manifest.expires_at,
    )
    return any(item is not None and item <= evaluated_at for item in expiries)


def _offer_id_arguments(proposal: CapabilityProposal) -> tuple[str, ...]:
    return tuple(
        str(argument.value)
        for argument in proposal.arguments
        if argument.name == "offer_id"
    )


def _sorted_terms(terms: tuple[MaterialTerm, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((term.name, term.value) for term in terms))


__all__ = [
    "SLOW_PROPOSAL_CHECK_VERSION",
    "SlowProposalCheck",
    "slow_proposal_violations",
    "standing_proposal_offer",
]
