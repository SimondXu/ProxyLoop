"""Shared model-facing Slow proposal and deterministic canonical compiler."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
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
    hard_constraint_ids: tuple[UUID, ...] = Field(max_length=32)
    ranked_preference_ids: tuple[UUID, ...] = Field(max_length=32)
    allowed_disclosures: tuple[str, ...] = Field(max_length=32)
    approval_required_disclosures: tuple[str, ...] = Field(max_length=32)
    concession_ladder: tuple[str, ...] = Field(max_length=32)
    fallback_outcomes: tuple[str, ...] = Field(max_length=32)
    required_completion_evidence: tuple[EvidenceRequirement, ...] = Field(
        min_length=1, max_length=16
    )
    escalation_conditions: tuple[str, ...] = Field(max_length=32)
    replan_conditions: tuple[str, ...] = Field(max_length=32)


class CapabilityModelOutput(StrictOutput):
    capability_id: str = Field(min_length=1, max_length=256)
    offer_id: UUID | None


class SlowModelOutput(StrictOutput):
    strategy: StrategyModelOutput
    capability_proposals: tuple[CapabilityModelOutput, ...] = Field(max_length=4)


def compile_slow_output(
    request: SlowWorkRequest,
    output: SlowModelOutput,
) -> SlowWorkResult:
    """Compile inert semantic work against the trusted current Slow view."""

    _validate_semantic_references(request, output)
    strategy_id = _stable_uuid4(
        f"strategy:{request.request_id}:{_canonical(output.strategy)}"
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
        **output.strategy.model_dump(mode="python"),
    )
    capabilities: list[CapabilityProposal] = []
    actions: list[ActionIntent] = []
    definitions = {
        item.capability_id: item
        for item in request.view.capability_manifest.capabilities
    }
    offers = {item.offer_id: item for item in request.view.offers}
    for index, proposed in enumerate(output.capability_proposals):
        definition = definitions[proposed.capability_id]
        proposal_id = _stable_uuid4(
            f"capability:{request.request_id}:{index}:{_canonical(proposed)}"
        )
        arguments = (
            (CapabilityArgument(name="offer_id", value=str(proposed.offer_id)),)
            if proposed.offer_id is not None
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
        action_type = definition.allowed_action_types[0]
        offer = offers.get(proposed.offer_id) if proposed.offer_id is not None else None
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
            idempotency_key=f"slow:{request.request_id}:{index}",
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
    hard = {
        item.constraint_id
        for item in request.view.constraints
        if item.classification is ConstraintClassification.HARD
    }
    soft = {
        item.constraint_id
        for item in request.view.constraints
        if item.classification is ConstraintClassification.SOFT
    }
    if not set(output.strategy.hard_constraint_ids) <= hard:
        raise ValueError("Slow strategy invented a hard constraint reference")
    if not set(output.strategy.ranked_preference_ids) <= soft:
        raise ValueError("Slow strategy invented a preference reference")
    allowed_disclosures = set(request.view.delegated_authority.allowed_disclosures)
    if not set(output.strategy.allowed_disclosures) <= allowed_disclosures:
        raise ValueError("Slow strategy proposed an unauthorized disclosure")
    if not set(output.strategy.approval_required_disclosures) <= allowed_disclosures:
        raise ValueError("Slow strategy proposed an unknown approval disclosure")
    definitions = {
        item.capability_id: item
        for item in request.view.capability_manifest.capabilities
    }
    offers = {item.offer_id for item in request.view.offers}
    seen: set[tuple[str, UUID | None]] = set()
    for proposal in output.capability_proposals:
        key = (proposal.capability_id, proposal.offer_id)
        if key in seen:
            raise ValueError("Slow output duplicated a capability proposal")
        seen.add(key)
        definition = definitions.get(proposal.capability_id)
        if definition is None or len(definition.allowed_action_types) != 1:
            raise ValueError("Slow output proposed an unsupported capability")
        action_type = definition.allowed_action_types[0]
        if action_type is ActionType.ACCEPT_OFFER and proposal.offer_id not in offers:
            raise ValueError("accept_offer requires a current canonical offer")
        if action_type is not ActionType.ACCEPT_OFFER and proposal.offer_id is not None:
            raise ValueError("non-offer capability cannot bind an offer")


def _material_terms(offer: object) -> tuple[MaterialTerm, ...]:
    from proxyloop_contracts import ProviderOffer

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
    "CapabilityModelOutput",
    "SlowModelOutput",
    "StrategyModelOutput",
    "compile_slow_output",
]
