"""Shared model-facing Slow proposal and deterministic canonical compiler."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    CapabilityArgument,
    CapabilityProposal,
    CapabilityReference,
    ConstraintClassification,
    MaterialTerm,
    OfferReference,
    ProviderOffer,
    SlowWorkRequest,
    SlowWorkResult,
    StrategyPacket,
    canonical_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement
from pydantic import BaseModel, ConfigDict, Field


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StrategyModelOutput(StrictOutput):
    primary_objective: str = Field(min_length=1, max_length=4000)
    current_subgoal: str = Field(min_length=1, max_length=4000)
    ranked_preference_positions: tuple[Annotated[int, Field(ge=0)], ...] = Field(
        max_length=32
    )
    allowed_disclosures: tuple[str, ...] = Field(max_length=32)
    approval_required_disclosures: tuple[str, ...] = Field(max_length=32)
    concession_ladder: tuple[str, ...] = Field(max_length=32)
    fallback_outcomes: tuple[str, ...] = Field(max_length=32)
    required_completion_evidence: tuple[EvidenceRequirement, ...] = Field(
        min_length=1, max_length=16
    )
    escalation_conditions: tuple[str, ...] = Field(max_length=32)
    replan_conditions: tuple[str, ...] = Field(max_length=32)


class AcceptOfferCapabilityModelOutput(StrictOutput):
    capability: Literal["accept_offer"]
    offer_position: int = Field(ge=0)


class NonOfferCapabilityModelOutput(StrictOutput):
    capability: Literal[
        "request_clarification",
        "escalate",
        "request_replan",
        "refuse_disclosure",
        "decline",
    ]


CapabilityModelOutput = AcceptOfferCapabilityModelOutput | NonOfferCapabilityModelOutput


class SlowModelOutput(StrictOutput):
    strategy: StrategyModelOutput
    next_capability: CapabilityModelOutput | None = None


def compile_slow_output(
    request: SlowWorkRequest,
    output: SlowModelOutput,
) -> SlowWorkResult:
    """Compile inert semantic work against the trusted current Slow view."""

    _validate_semantic_references(request, output)
    strategy_id = _stable_uuid4(
        f"strategy:{request.request_id}:{_canonical(output.strategy)}"
    )
    hard_constraint_ids = tuple(
        item.constraint_id
        for item in request.view.constraints
        if item.classification is ConstraintClassification.HARD
    )
    soft_constraints = tuple(
        item
        for item in request.view.constraints
        if item.classification is ConstraintClassification.SOFT
    )
    _validate_preference_positions(
        output.strategy.ranked_preference_positions, soft_constraints
    )
    strategy = StrategyPacket(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=1,
        strategy_id=strategy_id,
        case_id=request.case_id,
        case_revision=request.pins.case_revision,
        fact_ledger_revision=request.pins.fact_ledger_revision,
        created_at=request.created_at,
        expires_at=request.created_at + timedelta(minutes=30),
        primary_objective=output.strategy.primary_objective,
        current_subgoal=output.strategy.current_subgoal,
        hard_constraint_ids=hard_constraint_ids,
        ranked_preference_ids=tuple(
            soft_constraints[position].constraint_id
            for position in output.strategy.ranked_preference_positions
        ),
        allowed_disclosures=output.strategy.allowed_disclosures,
        approval_required_disclosures=output.strategy.approval_required_disclosures,
        concession_ladder=output.strategy.concession_ladder,
        fallback_outcomes=output.strategy.fallback_outcomes,
        required_completion_evidence=output.strategy.required_completion_evidence,
        escalation_conditions=output.strategy.escalation_conditions,
        replan_conditions=output.strategy.replan_conditions,
    )
    capabilities: list[CapabilityProposal] = []
    actions: list[ActionIntent] = []
    definitions = {
        item.capability_id: item
        for item in request.view.capability_manifest.capabilities
    }
    offers = tuple(request.view.offers)
    proposed = output.next_capability
    if proposed is not None:
        capability_id = f"simulator.{proposed.capability}"
        definition = definitions.get(capability_id)
        if definition is None or len(definition.allowed_action_types) != 1:
            raise ValueError("Slow output proposed an unsupported capability")
        action_type = definition.allowed_action_types[0]
        offer = _selected_offer(proposed, offers)
        if (
            proposed.capability == "accept_offer"
            and action_type is not ActionType.ACCEPT_OFFER
        ):
            raise ValueError("accept_offer capability must map to accept_offer action")
        if (
            proposed.capability != "accept_offer"
            and action_type is ActionType.ACCEPT_OFFER
        ):
            raise ValueError("non-offer capability cannot map to accept_offer action")
        proposal_id = _stable_uuid4(
            f"capability:{request.request_id}:0:{_canonical(proposed)}"
        )
        arguments = (
            (CapabilityArgument(name="offer_id", value=str(offer.offer_id)),)
            if offer is not None
            else ()
        )
        capability = CapabilityProposal(
            proposal_id=proposal_id,
            capability=CapabilityReference(
                namespace="simulator",
                capability_id=definition.capability_id,
                version=definition.version,
            ),
            arguments=arguments,
            created_at=request.created_at,
            expires_at=request.created_at + timedelta(minutes=5),
        )
        terms = _material_terms(offer) if offer is not None else ()
        intent = ActionIntent(
            contract_type="action_intent",
            schema_version="1.0",
            revision=1,
            intent_id=_stable_uuid4(f"intent:{proposal_id}"),
            case_id=request.case_id,
            case_revision=request.pins.case_revision,
            strategy_id=strategy.strategy_id,
            strategy_revision=strategy.revision,
            constraint_set_revision=request.pins.constraint_set_revision,
            action_type=action_type,
            offer_ref=(
                OfferReference(offer_id=offer.offer_id, offer_revision=offer.revision)
                if offer is not None
                else None
            ),
            material_terms=terms,
            material_terms_hash=_material_terms_hash(terms),
            approval_required=(
                action_type
                in request.view.delegated_authority.approval_required_actions
            ),
            idempotency_key=f"slow:{request.request_id}:0",
            created_at=request.created_at,
            expires_at=request.created_at + timedelta(minutes=5),
        )
        capabilities.append(capability)
        actions.append(intent)
    return SlowWorkResult(
        contract_type="slow_work_result",
        schema_version="1.0",
        revision=1,
        result_id=_stable_uuid4(
            f"slow-result:{request.request_id}:{_canonical(output)}"
        ),
        request_id=request.request_id,
        case_id=request.case_id,
        pins=request.pins,
        planning_basis=request.planning_basis,
        strategy_proposal=strategy,
        capability_proposals=tuple(capabilities),
        action_proposals=tuple(actions),
        created_at=request.created_at,
    )


def _validate_semantic_references(
    request: SlowWorkRequest,
    output: SlowModelOutput,
) -> None:
    allowed_disclosures = set(request.view.delegated_authority.allowed_disclosures)
    if not set(output.strategy.allowed_disclosures) <= allowed_disclosures:
        raise ValueError("Slow strategy proposed an unauthorized disclosure")
    if not set(output.strategy.approval_required_disclosures) <= allowed_disclosures:
        raise ValueError("Slow strategy proposed an unknown approval disclosure")


def _validate_preference_positions(
    positions: tuple[int, ...], soft_constraints: tuple[object, ...]
) -> None:
    if len(set(positions)) != len(positions):
        raise ValueError("duplicate preference position")
    if any(position < 0 or position >= len(soft_constraints) for position in positions):
        raise ValueError("preference position is out of range")


def _selected_offer(
    proposed: CapabilityModelOutput,
    offers: tuple[ProviderOffer, ...],
) -> ProviderOffer | None:
    if isinstance(proposed, AcceptOfferCapabilityModelOutput):
        if proposed.offer_position >= len(offers):
            raise ValueError("offer position is out of range")
        return offers[proposed.offer_position]
    return None


def _material_terms(offer: object) -> tuple[MaterialTerm, ...]:
    if not isinstance(offer, ProviderOffer):
        return ()
    return (
        MaterialTerm(name="monthly_price", value=str(offer.monthly_price.amount_minor)),
        MaterialTerm(name="total_cost", value=str(offer.total_cost.amount_minor)),
        MaterialTerm(name="term_months", value=str(offer.term_months)),
    )


def _material_terms_hash(terms: tuple[MaterialTerm, ...]) -> str:
    return canonical_fingerprint(
        tuple(
            sorted(
                terms,
                key=lambda item: (str(item.name), str(item.value)),
            )
        )
    )


def _canonical(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = [
    "AcceptOfferCapabilityModelOutput",
    "CapabilityModelOutput",
    "NonOfferCapabilityModelOutput",
    "SlowModelOutput",
    "StrategyModelOutput",
    "compile_slow_output",
]
