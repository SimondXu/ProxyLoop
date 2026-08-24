from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from ._base import (
    Confidence,
    ContractModel,
    CurrencyCode,
    EntityId,
    ExternalRef,
    HumanText,
    NonNegativeInt,
    PositiveInt,
    Revision,
    SchemaVersion,
    Sha256,
    UtcDateTime,
    VersionedContract,
    require_time_order,
    uuid_strings,
)


class ActionType(StrEnum):
    SEND_MESSAGE = "send_message"
    REQUEST_CLARIFICATION = "request_clarification"
    DISCLOSE_INFORMATION = "disclose_information"
    ACCEPT_OFFER = "accept_offer"
    END_INTERACTION = "end_interaction"


class CasePhase(StrEnum):
    INITIATED = "initiated"
    STRATEGY = "strategy"
    NEGOTIATING = "negotiating"
    AWAITING_APPROVAL = "awaiting_approval"
    CANDIDATE_COMPLETE = "candidate_complete"
    COMPLETE = "complete"
    CLOSED = "closed"


class ConstraintClassification(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class LineItemCategory(StrEnum):
    SERVICE = "service"
    ADDON = "addon"
    FEE = "fee"
    TAX = "tax"
    CREDIT = "credit"


class FactStatus(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"


class DialogueAct(StrEnum):
    CLARIFY = "clarify"
    COUNTER = "counter"
    CONFIRM = "confirm"
    CHALLENGE = "challenge"
    ESCALATE = "escalate"
    CLOSE = "close"


class EvidenceType(StrEnum):
    PROVIDER_MESSAGE = "provider_message"
    PROVIDER_EVENT = "provider_event"
    CONFIRMATION = "confirmation"
    BILL = "bill"
    SIMULATOR_TRANSITION = "simulator_transition"


class CompletionOutcome(StrEnum):
    CONTINUE = "continue"
    NEEDS_USER = "needs_user"
    NEEDS_REPLAN = "needs_replan"
    CANDIDATE_COMPLETE = "candidate_complete"
    COMPLETE = "complete"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ModelResult(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class RoutingOutcome(StrEnum):
    TERMINAL = "terminal"
    VERIFY_ONLY = "verify_only"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    SLOW_REFRESH = "slow_refresh"
    FAST_NOW_AND_SLOW_REFRESH = "fast_now_and_slow_refresh"
    FAST_NOW = "fast_now"


class EventActor(StrEnum):
    CONSUMER = "consumer"
    PROVIDER = "provider"
    SYSTEM = "system"


class Money(ContractModel):
    amount_minor: int
    currency: CurrencyCode


class LineItem(ContractModel):
    name: HumanText
    category: LineItemCategory
    amount: Money


class UsageProfile(ContractModel):
    voice_minutes: NonNegativeInt
    sms_count: NonNegativeInt
    data_megabytes: NonNegativeInt


class DelegatedAuthority(ContractModel):
    allowed_actions: tuple[ActionType, ...]
    approval_required_actions: tuple[ActionType, ...]
    allowed_disclosures: tuple[ExternalRef, ...]

    @model_validator(mode="after")
    def action_sets_must_be_disjoint(self) -> DelegatedAuthority:
        overlap = set(self.allowed_actions) & set(self.approval_required_actions)
        if overlap:
            raise ValueError("allowed and approval-required actions must be disjoint")
        return self


class OfferReference(ContractModel):
    offer_id: EntityId
    offer_revision: Revision


class MaterialTerm(ContractModel):
    name: ExternalRef
    value: HumanText


class EvidenceRequirement(ContractModel):
    evidence_type: EvidenceType
    description: HumanText


class ConsumerGoal(VersionedContract):
    contract_type: Literal["consumer_goal"]
    goal_id: EntityId
    case_id: EntityId
    created_at: UtcDateTime
    updated_at: UtcDateTime
    desired_outcome: HumanText
    target_monthly_total: Money | None = None
    required_features: tuple[ExternalRef, ...]
    forbidden_changes: tuple[ExternalRef, ...]
    deadline: UtcDateTime | None = None

    @model_validator(mode="after")
    def timestamps_must_be_ordered(self) -> ConsumerGoal:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.deadline is not None and self.deadline <= self.created_at:
            raise ValueError("deadline must be after created_at")
        if (
            self.target_monthly_total is not None
            and self.target_monthly_total.amount_minor < 0
        ):
            raise ValueError("target monthly total must be non-negative")
        return self


class Constraint(VersionedContract):
    contract_type: Literal["constraint"]
    constraint_id: EntityId
    case_id: EntityId
    classification: ConstraintClassification
    statement: HumanText
    source: ExternalRef
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None
    priority: PositiveInt | None = None

    @model_validator(mode="after")
    def classification_and_validity_must_agree(self) -> Constraint:
        if self.valid_until is not None:
            require_time_order(self.valid_from, self.valid_until, "valid_until")
        if (
            self.classification is ConstraintClassification.SOFT
            and self.priority is None
        ):
            raise ValueError("soft constraint requires a priority")
        if (
            self.classification is ConstraintClassification.HARD
            and self.priority is not None
        ):
            raise ValueError("hard constraint cannot have a priority")
        return self


class BillSnapshot(VersionedContract):
    contract_type: Literal["bill_snapshot"]
    snapshot_id: EntityId
    case_id: EntityId
    captured_at: UtcDateTime
    monthly_total: Money
    line_items: tuple[LineItem, ...]
    add_ons: tuple[ExternalRef, ...]
    term_months: NonNegativeInt
    usage: UsageProfile
    evidence_ids: tuple[EntityId, ...]

    @model_validator(mode="after")
    def totals_and_evidence_must_be_supported(self) -> BillSnapshot:
        if not self.evidence_ids:
            raise ValueError("bill snapshot requires external evidence")
        currencies = {self.monthly_total.currency}
        currencies.update(item.amount.currency for item in self.line_items)
        if len(currencies) != 1:
            raise ValueError("bill snapshot cannot mix currencies")
        if sum(item.amount.amount_minor for item in self.line_items) != (
            self.monthly_total.amount_minor
        ):
            raise ValueError("line items must sum to monthly total")
        if self.monthly_total.amount_minor < 0:
            raise ValueError("monthly total must be non-negative")
        return self


type FactValue = Money | str | int | bool


class FactRecord(ContractModel):
    fact_id: EntityId
    key: ExternalRef
    value: FactValue
    status: FactStatus
    source_message_id: ExternalRef | None = None
    evidence_ids: tuple[EntityId, ...] = ()
    confidence: Confidence
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def provenance_must_support_status(self) -> FactRecord:
        if self.status is FactStatus.CANDIDATE and self.source_message_id is None:
            raise ValueError("candidate fact requires a source message")
        if self.status is FactStatus.VERIFIED and not self.evidence_ids:
            raise ValueError("verified fact requires external evidence")
        return self


class FactLedger(VersionedContract):
    contract_type: Literal["fact_ledger"]
    ledger_id: EntityId
    case_id: EntityId
    created_at: UtcDateTime
    updated_at: UtcDateTime
    entries: tuple[FactRecord, ...]

    @model_validator(mode="after")
    def ledger_snapshot_must_be_consistent(self) -> FactLedger:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        fact_ids = tuple(entry.fact_id for entry in self.entries)
        if len(uuid_strings(fact_ids)) != len(fact_ids):
            raise ValueError("fact ledger cannot contain duplicate fact ids")
        return self


class StrategyPacket(VersionedContract):
    contract_type: Literal["strategy_packet"]
    strategy_id: EntityId
    case_id: EntityId
    case_revision: Revision
    fact_ledger_revision: Revision
    created_at: UtcDateTime
    expires_at: UtcDateTime
    primary_objective: HumanText
    current_subgoal: HumanText
    hard_constraint_ids: tuple[EntityId, ...]
    ranked_preference_ids: tuple[EntityId, ...]
    allowed_disclosures: tuple[ExternalRef, ...]
    approval_required_disclosures: tuple[ExternalRef, ...]
    concession_ladder: tuple[HumanText, ...]
    fallback_outcomes: tuple[HumanText, ...]
    required_completion_evidence: tuple[EvidenceRequirement, ...]
    escalation_conditions: tuple[HumanText, ...]
    replan_conditions: tuple[HumanText, ...]

    @model_validator(mode="after")
    def strategy_window_and_disclosures_must_be_valid(self) -> StrategyPacket:
        require_time_order(self.created_at, self.expires_at, "expires_at")
        overlap = set(self.allowed_disclosures) & set(
            self.approval_required_disclosures
        )
        if overlap:
            raise ValueError("disclosure cannot be both allowed and approval-required")
        if not self.required_completion_evidence:
            raise ValueError("strategy requires completion evidence requirements")
        return self


class ProviderOffer(VersionedContract):
    contract_type: Literal["provider_offer"]
    offer_id: EntityId
    case_id: EntityId
    provider_id: ExternalRef
    created_at: UtcDateTime
    expires_at: UtcDateTime
    monthly_price: Money
    total_cost: Money
    fees: tuple[LineItem, ...]
    features: tuple[ExternalRef, ...]
    term_months: NonNegativeInt
    evidence_ids: tuple[EntityId, ...]

    @model_validator(mode="after")
    def offer_terms_must_be_supported(self) -> ProviderOffer:
        require_time_order(self.created_at, self.expires_at, "expires_at")
        if not self.evidence_ids:
            raise ValueError("provider offer requires external evidence")
        currencies = {self.monthly_price.currency, self.total_cost.currency}
        currencies.update(item.amount.currency for item in self.fees)
        if len(currencies) != 1:
            raise ValueError("provider offer cannot mix currencies")
        if self.monthly_price.amount_minor < 0 or self.total_cost.amount_minor < 0:
            raise ValueError("offer prices must be non-negative")
        return self


class ActionIntent(VersionedContract):
    model_config = ConfigDict(
        json_schema_extra={
            "dependentSchemas": {
                "action_type": {
                    "if": {"properties": {"action_type": {"const": "accept_offer"}}},
                    "then": {
                        "properties": {
                            "approval_required": {"const": True},
                            "material_terms": {"minItems": 1},
                            "offer_ref": {"not": {"type": "null"}},
                        },
                        "required": ["offer_ref"],
                    },
                }
            }
        }
    )
    contract_type: Literal["action_intent"]
    intent_id: EntityId
    case_id: EntityId
    case_revision: Revision
    strategy_id: EntityId
    strategy_revision: Revision
    constraint_set_revision: Revision
    action_type: ActionType
    offer_ref: OfferReference | None = None
    material_terms: tuple[MaterialTerm, ...]
    material_terms_hash: Sha256
    approval_required: bool
    authorization_state: Literal["proposed"] = "proposed"
    idempotency_key: ExternalRef
    created_at: UtcDateTime
    expires_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def consequential_action_must_be_bound(self) -> ActionIntent:
        if self.expires_at is not None:
            require_time_order(self.created_at, self.expires_at, "expires_at")
        if self.action_type is ActionType.ACCEPT_OFFER:
            if self.offer_ref is None:
                raise ValueError("accept_offer requires an exact offer reference")
            if not self.material_terms:
                raise ValueError("accept_offer requires material terms")
            if not self.approval_required:
                raise ValueError("accept_offer requires consumer approval")
        return self


class ApprovalRequest(VersionedContract):
    model_config = ConfigDict(
        json_schema_extra={
            "dependentSchemas": {
                "action_type": {
                    "if": {"properties": {"action_type": {"const": "accept_offer"}}},
                    "then": {
                        "properties": {"offer_ref": {"not": {"type": "null"}}},
                        "required": ["offer_ref"],
                    },
                },
                "decision": {
                    "allOf": [
                        {
                            "if": {"properties": {"decision": {"const": "pending"}}},
                            "then": {"properties": {"decided_at": {"type": "null"}}},
                        },
                        {
                            "if": {
                                "properties": {
                                    "decision": {"enum": ["approved", "rejected"]}
                                }
                            },
                            "then": {
                                "properties": {"decided_at": {"not": {"type": "null"}}},
                                "required": ["decided_at"],
                            },
                        },
                    ]
                },
            }
        }
    )
    contract_type: Literal["approval_request"]
    approval_id: EntityId
    case_id: EntityId
    case_revision: Revision
    action_intent_id: EntityId
    action_intent_revision: Revision
    action_type: ActionType
    strategy_id: EntityId
    strategy_revision: Revision
    constraint_set_revision: Revision
    offer_ref: OfferReference | None = None
    material_terms_hash: Sha256
    requested_at: UtcDateTime
    expires_at: UtcDateTime
    decision: ApprovalDecision = ApprovalDecision.PENDING
    decided_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def approval_must_bind_exact_action_state(self) -> ApprovalRequest:
        require_time_order(self.requested_at, self.expires_at, "expires_at")
        if self.action_type is ActionType.ACCEPT_OFFER and self.offer_ref is None:
            raise ValueError("accept_offer approval requires an exact offer reference")
        if self.decision is ApprovalDecision.PENDING and self.decided_at is not None:
            raise ValueError("pending approval cannot have decided_at")
        if self.decision in {ApprovalDecision.APPROVED, ApprovalDecision.REJECTED}:
            if self.decided_at is None:
                raise ValueError("decided approval requires decided_at")
            if self.decided_at < self.requested_at:
                raise ValueError("decided_at must not precede requested_at")
            if self.decided_at >= self.expires_at:
                raise ValueError("approval decision must precede expiry")
        return self


class Evidence(ContractModel):
    contract_type: Literal["evidence"]
    schema_version: SchemaVersion
    evidence_id: EntityId
    case_id: EntityId
    source_type: EvidenceType
    source_ref: ExternalRef
    content_hash: Sha256
    observed_at: UtcDateTime
    captured_at: UtcDateTime
    media_type: ExternalRef | None = None

    @model_validator(mode="after")
    def capture_must_follow_observation(self) -> Evidence:
        if self.captured_at < self.observed_at:
            raise ValueError("captured_at must not precede observed_at")
        return self


class CompletionDecision(VersionedContract):
    model_config = ConfigDict(
        json_schema_extra={
            "dependentSchemas": {
                "decision": {
                    "if": {
                        "properties": {"decision": {"const": "complete"}},
                    },
                    "then": {
                        "properties": {
                            "evidence_ids": {"minItems": 1},
                            "missing_evidence": {"maxItems": 0},
                        }
                    },
                }
            }
        }
    )
    contract_type: Literal["completion_decision"]
    completion_id: EntityId
    case_id: EntityId
    case_revision: Revision
    decision: CompletionOutcome
    verifier_name: ExternalRef
    verifier_version: ExternalRef
    evaluated_at: UtcDateTime
    evidence_ids: tuple[EntityId, ...]
    missing_evidence: tuple[ExternalRef, ...]
    reason_codes: tuple[ExternalRef, ...]
    candidate_model_trace_id: EntityId | None = None

    @model_validator(mode="after")
    def final_completion_requires_external_evidence(self) -> CompletionDecision:
        if self.decision is CompletionOutcome.COMPLETE and (
            not self.evidence_ids or self.missing_evidence
        ):
            raise ValueError(
                "complete requires external evidence and no missing evidence"
            )
        return self


class ModelTrace(VersionedContract):
    contract_type: Literal["model_trace"]
    trace_id: EntityId
    case_id: EntityId
    started_at: UtcDateTime
    completed_at: UtcDateTime
    provider: ExternalRef
    model: ExternalRef
    model_version: ExternalRef
    adapter_version: ExternalRef
    prompt_version: ExternalRef
    input_schema_version: ExternalRef
    output_schema_version: ExternalRef
    latency_ms: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    result: ModelResult
    output_ref: ExternalRef | None = None
    safety_flags: tuple[ExternalRef, ...]

    @model_validator(mode="after")
    def trace_window_must_be_valid(self) -> ModelTrace:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class FactUpdate(ContractModel):
    key: ExternalRef
    value: FactValue
    source_message_id: ExternalRef
    confidence: Confidence
    status: Literal["candidate"] = "candidate"


class ReasonerRequest(ContractModel):
    needed: bool
    reason_code: ExternalRef


class CompletionClaim(ContractModel):
    status: Literal["not_done", "candidate"]
    evidence_message_ids: tuple[ExternalRef, ...]


class FastTurnDecision(ContractModel):
    contract_type: Literal["fast_turn_decision"]
    schema_version: SchemaVersion
    decision_id: EntityId
    case_id: EntityId
    case_revision: Revision
    strategy_id: EntityId
    strategy_revision: Revision
    created_at: UtcDateTime
    dialogue_act: DialogueAct
    fact_updates: tuple[FactUpdate, ...]
    reasoner_request: ReasonerRequest
    completion_claim: CompletionClaim
    response_text: HumanText
    action_intent: ActionIntent | None = None


class Case(VersionedContract):
    contract_type: Literal["case"]
    case_id: EntityId
    consumer_id: EntityId
    phase: CasePhase
    constraint_set_revision: Revision
    created_at: UtcDateTime
    updated_at: UtcDateTime
    goal: ConsumerGoal
    constraints: tuple[Constraint, ...]
    delegated_authority: DelegatedAuthority
    bill_snapshot: BillSnapshot | None = None

    @model_validator(mode="after")
    def aggregate_references_must_match_case(self) -> Case:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.goal.case_id != self.case_id:
            raise ValueError("goal must reference the containing case")
        if any(item.case_id != self.case_id for item in self.constraints):
            raise ValueError("constraints must reference the containing case")
        if (
            self.bill_snapshot is not None
            and self.bill_snapshot.case_id != self.case_id
        ):
            raise ValueError("bill snapshot must reference the containing case")
        constraint_ids = tuple(item.constraint_id for item in self.constraints)
        if len(uuid_strings(constraint_ids)) != len(constraint_ids):
            raise ValueError("case cannot contain duplicate constraint ids")
        return self


class ModelInputPins(VersionedContract):
    """The complete version pin set accepted by a model adapter."""

    contract_type: Literal["model_input_pins"]
    case_id: EntityId
    case_revision: Revision
    constraint_set_revision: Revision
    fact_ledger_revision: Revision
    strategy_id: EntityId | None = None
    strategy_revision: NonNegativeInt = 0
    planning_basis_fingerprint: Sha256
    event_cursor: NonNegativeInt
    provider_config_ref: ExternalRef
    capability_manifest_version: ExternalRef

    @model_validator(mode="after")
    def strategy_identity_must_be_explicit(self) -> ModelInputPins:
        if (self.strategy_id is None) != (self.strategy_revision == 0):
            raise ValueError(
                "strategy_id and strategy_revision must both be empty or versioned"
            )
        return self


class PlanningBasis(VersionedContract):
    """Strongly typed fingerprints for every material strategy input."""

    contract_type: Literal["planning_basis"]
    goal_fingerprint: Sha256
    constraints_fingerprint: Sha256
    delegated_authority_fingerprint: Sha256
    verified_facts_fingerprint: Sha256
    material_offers_fingerprint: Sha256
    approval_state_fingerprint: Sha256
    provider_config_fingerprint: Sha256
    capability_manifest_fingerprint: Sha256
    planning_basis_fingerprint: Sha256

    @model_validator(mode="after")
    def aggregate_fingerprint_must_bind_every_component(self) -> PlanningBasis:
        expected = planning_basis_fingerprint(
            goal_fingerprint=self.goal_fingerprint,
            constraints_fingerprint=self.constraints_fingerprint,
            delegated_authority_fingerprint=self.delegated_authority_fingerprint,
            verified_facts_fingerprint=self.verified_facts_fingerprint,
            material_offers_fingerprint=self.material_offers_fingerprint,
            approval_state_fingerprint=self.approval_state_fingerprint,
            provider_config_fingerprint=self.provider_config_fingerprint,
            capability_manifest_fingerprint=self.capability_manifest_fingerprint,
        )
        if self.planning_basis_fingerprint != expected:
            raise ValueError(
                "planning_basis_fingerprint must bind every material component"
            )
        return self


def planning_basis_fingerprint(
    *,
    goal_fingerprint: str,
    constraints_fingerprint: str,
    delegated_authority_fingerprint: str,
    verified_facts_fingerprint: str,
    material_offers_fingerprint: str,
    approval_state_fingerprint: str,
    provider_config_fingerprint: str,
    capability_manifest_fingerprint: str,
) -> str:
    """Compute the canonical aggregate hash for material strategy state."""

    payload = {
        "approval_state_fingerprint": approval_state_fingerprint,
        "capability_manifest_fingerprint": capability_manifest_fingerprint,
        "constraints_fingerprint": constraints_fingerprint,
        "delegated_authority_fingerprint": delegated_authority_fingerprint,
        "goal_fingerprint": goal_fingerprint,
        "material_offers_fingerprint": material_offers_fingerprint,
        "provider_config_fingerprint": provider_config_fingerprint,
        "verified_facts_fingerprint": verified_facts_fingerprint,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_fingerprint(value: Any) -> str:
    """Hash a canonical JSON-safe contract value or collection of values."""

    def json_value(item: Any) -> Any:
        if isinstance(item, ContractModel):
            return item.model_dump(mode="json")
        if isinstance(item, (tuple, list)):
            return [json_value(child) for child in item]
        if isinstance(item, dict):
            return {str(key): json_value(child) for key, child in item.items()}
        return item

    canonical = json.dumps(
        json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class VisibleCaseEvent(VersionedContract):
    """A leakage-safe event that may be projected to a model."""

    contract_type: Literal["visible_case_event"]
    event_id: EntityId
    case_id: EntityId
    event_cursor: NonNegativeInt
    occurred_at: UtcDateTime
    actor: EventActor
    event_type: ExternalRef
    content: HumanText


class CapabilityDefinition(ContractModel):
    """One simulator capability advertised by a manifest."""

    capability_id: ExternalRef
    version: ExternalRef
    description: HumanText
    namespace: Literal["simulator"] = "simulator"
    allowed_action_types: tuple[ActionType, ...]
    expires_at: UtcDateTime | None = None


class CapabilityReference(ContractModel):
    namespace: Literal["simulator"]
    capability_id: ExternalRef
    version: ExternalRef

    @model_validator(mode="after")
    def capability_must_be_simulator_owned(self) -> CapabilityReference:
        if not self.capability_id.startswith("simulator."):
            raise ValueError("capability id must belong to the simulator namespace")
        return self


class CapabilityArgument(ContractModel):
    name: ExternalRef
    value: FactValue


class CapabilityProposal(ContractModel):
    """A model proposal; it has no authorization or execution authority."""

    proposal_id: EntityId
    capability: CapabilityReference
    arguments: tuple[CapabilityArgument, ...] = ()
    created_at: UtcDateTime
    expires_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def proposal_window_and_arguments_must_be_valid(self) -> CapabilityProposal:
        argument_names = tuple(item.name for item in self.arguments)
        if len(set(argument_names)) != len(argument_names):
            raise ValueError("capability proposal cannot contain duplicate arguments")
        if self.expires_at is not None:
            require_time_order(self.created_at, self.expires_at, "expires_at")
        return self


class CapabilityManifest(VersionedContract):
    """The sole, simulator-only action vocabulary visible to models."""

    contract_type: Literal["capability_manifest"]
    namespace: Literal["simulator"]
    manifest_version: ExternalRef
    issued_at: UtcDateTime
    expires_at: UtcDateTime
    capabilities: tuple[CapabilityDefinition, ...]

    @model_validator(mode="after")
    def capabilities_must_be_unique_and_current(self) -> CapabilityManifest:
        require_time_order(self.issued_at, self.expires_at, "expires_at")
        ids = tuple(item.capability_id for item in self.capabilities)
        if len(set(ids)) != len(ids):
            raise ValueError(
                "capability manifest cannot contain duplicate capability ids"
            )
        for capability in self.capabilities:
            if not capability.capability_id.startswith("simulator."):
                raise ValueError("capability id must belong to the simulator namespace")
            if capability.expires_at is not None:
                require_time_order(
                    self.issued_at,
                    capability.expires_at,
                    "capability expires_at",
                )
                if capability.expires_at > self.expires_at:
                    raise ValueError(
                        "capability expires_at cannot exceed manifest expiry"
                    )
        return self


class CaseContextSnapshot(VersionedContract):
    """Immutable model-external Case state at one event cursor."""

    contract_type: Literal["case_context_snapshot"]
    case: Case
    fact_ledger: FactLedger
    strategy: StrategyPacket | None = None
    offers: tuple[ProviderOffer, ...] = ()
    action_intents: tuple[ActionIntent, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    completion_decision: CompletionDecision | None = None
    visible_events: tuple[VisibleCaseEvent, ...] = ()
    event_cursor: NonNegativeInt
    planning_basis: PlanningBasis
    pins: ModelInputPins
    provider_config_ref: ExternalRef
    capability_manifest: CapabilityManifest
    pending_slow_work: bool = False
    pending_execution: bool = False

    @model_validator(mode="after")
    def snapshot_references_must_match(self) -> CaseContextSnapshot:
        case_id = self.case.case_id
        if self.fact_ledger.case_id != case_id:
            raise ValueError("fact ledger must reference the containing case")
        if self.strategy is not None and self.strategy.case_id != case_id:
            raise ValueError("strategy must reference the containing case")
        if any(item.case_id != case_id for item in self.offers):
            raise ValueError("offers must reference the containing case")
        if any(item.case_id != case_id for item in self.action_intents):
            raise ValueError("action intents must reference the containing case")
        if any(item.case_id != case_id for item in self.approval_requests):
            raise ValueError("approval requests must reference the containing case")
        if any(item.case_id != case_id for item in self.evidence):
            raise ValueError("evidence must reference the containing case")
        if (
            self.completion_decision is not None
            and self.completion_decision.case_id != case_id
        ):
            raise ValueError("completion decision must reference the containing case")
        if any(item.case_id != case_id for item in self.visible_events):
            raise ValueError("visible events must reference the containing case")

        cursors = tuple(item.event_cursor for item in self.visible_events)
        if any(current <= previous for previous, current in pairwise(cursors)):
            raise ValueError("visible event cursors must be strictly increasing")
        if self.visible_events and cursors[-1] != self.event_cursor:
            raise ValueError("event_cursor must equal the latest visible event cursor")
        if not self.visible_events and self.event_cursor != 0:
            raise ValueError("empty visible event history must have event_cursor zero")
        times = tuple(item.occurred_at for item in self.visible_events)
        if any(current < previous for previous, current in pairwise(times)):
            raise ValueError("visible event timestamps must be ordered")

        expected = {
            "case_id": case_id,
            "case_revision": self.case.revision,
            "constraint_set_revision": self.case.constraint_set_revision,
            "fact_ledger_revision": self.fact_ledger.revision,
            "strategy_id": self.strategy.strategy_id if self.strategy else None,
            "strategy_revision": self.strategy.revision if self.strategy else 0,
            "event_cursor": self.event_cursor,
            "provider_config_ref": self.provider_config_ref,
            "capability_manifest_version": self.capability_manifest.manifest_version,
            "planning_basis_fingerprint": (
                self.planning_basis.planning_basis_fingerprint
            ),
        }
        actual = {
            "case_id": self.pins.case_id,
            "case_revision": self.pins.case_revision,
            "constraint_set_revision": self.pins.constraint_set_revision,
            "fact_ledger_revision": self.pins.fact_ledger_revision,
            "strategy_id": self.pins.strategy_id,
            "strategy_revision": self.pins.strategy_revision,
            "event_cursor": self.pins.event_cursor,
            "provider_config_ref": self.pins.provider_config_ref,
            "capability_manifest_version": self.pins.capability_manifest_version,
            "planning_basis_fingerprint": self.pins.planning_basis_fingerprint,
        }
        if actual != expected:
            raise ValueError("snapshot pins must exactly match snapshot state")

        verified_facts = tuple(
            sorted(
                (
                    item
                    for item in self.fact_ledger.entries
                    if item.status is FactStatus.VERIFIED
                ),
                key=lambda item: str(item.fact_id),
            )
        )
        planning_components = {
            "goal_fingerprint": canonical_fingerprint(self.case.goal),
            "constraints_fingerprint": canonical_fingerprint(
                tuple(
                    sorted(
                        self.case.constraints,
                        key=lambda item: str(item.constraint_id),
                    )
                )
            ),
            "delegated_authority_fingerprint": canonical_fingerprint(
                self.case.delegated_authority
            ),
            "verified_facts_fingerprint": canonical_fingerprint(verified_facts),
            "material_offers_fingerprint": canonical_fingerprint(
                tuple(sorted(self.offers, key=lambda item: str(item.offer_id)))
            ),
            "approval_state_fingerprint": canonical_fingerprint(
                tuple(
                    sorted(
                        self.approval_requests,
                        key=lambda item: str(item.approval_id),
                    )
                )
            ),
            "provider_config_fingerprint": canonical_fingerprint(
                self.provider_config_ref
            ),
            "capability_manifest_fingerprint": canonical_fingerprint(
                self.capability_manifest
            ),
        }
        actual_components = {
            key: getattr(self.planning_basis, key) for key in planning_components
        }
        if actual_components != planning_components:
            raise ValueError(
                "planning basis components must match material snapshot state"
            )
        return self


class FastModelView(VersionedContract):
    """Explicit allowlist for the low-latency model."""

    contract_type: Literal["fast_model_view"]
    case_id: EntityId
    pins: ModelInputPins
    planning_basis: PlanningBasis
    goal: ConsumerGoal
    constraints: tuple[Constraint, ...]
    verified_facts: tuple[FactRecord, ...]
    strategy: StrategyPacket | None = None
    recent_events: tuple[VisibleCaseEvent, ...] = ()
    latest_provider_event: VisibleCaseEvent | None = None
    pending_slow_work: bool = False
    allowed_dialogue_acts: tuple[DialogueAct, ...]
    allowed_disclosures: tuple[ExternalRef, ...]

    @model_validator(mode="after")
    def view_must_be_current_and_verified(self) -> FastModelView:
        if self.case_id != self.pins.case_id:
            raise ValueError("Fast view case_id must match pins")
        if self.goal.case_id != self.case_id:
            raise ValueError("Fast view goal must reference the containing case")
        if any(item.case_id != self.case_id for item in self.constraints):
            raise ValueError("Fast view constraints must reference the containing case")
        if (
            self.pins.planning_basis_fingerprint
            != self.planning_basis.planning_basis_fingerprint
        ):
            raise ValueError("Fast view planning basis must match pins")
        if any(item.status is not FactStatus.VERIFIED for item in self.verified_facts):
            raise ValueError("Fast view may expose verified facts only")
        if self.strategy is None and self.pins.strategy_id is not None:
            raise ValueError("Fast view must include the strategy named by its pins")
        if self.strategy is not None and (
            self.strategy.case_id != self.case_id
            or self.strategy.strategy_id != self.pins.strategy_id
            or self.strategy.revision != self.pins.strategy_revision
        ):
            raise ValueError("Fast view strategy must match current pins")
        return self


class SlowReasonerView(VersionedContract):
    """Explicit allowlist for the bounded Slow reasoner."""

    contract_type: Literal["slow_reasoner_view"]
    case_id: EntityId
    pins: ModelInputPins
    planning_basis: PlanningBasis
    goal: ConsumerGoal
    constraints: tuple[Constraint, ...]
    delegated_authority: DelegatedAuthority
    verified_facts: tuple[FactRecord, ...]
    offers: tuple[ProviderOffer, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    strategy: StrategyPacket | None = None
    recent_events: tuple[VisibleCaseEvent, ...] = ()
    capability_manifest: CapabilityManifest
    provider_config_ref: ExternalRef
    reason_code: ExternalRef

    @model_validator(mode="after")
    def view_must_be_current_and_verified(self) -> SlowReasonerView:
        if self.case_id != self.pins.case_id:
            raise ValueError("Slow view case_id must match pins")
        if self.goal.case_id != self.case_id:
            raise ValueError("Slow view goal must reference the containing case")
        if any(item.case_id != self.case_id for item in self.constraints):
            raise ValueError("Slow view constraints must reference the containing case")
        if self.provider_config_ref != self.pins.provider_config_ref:
            raise ValueError("Slow view provider config must match pins")
        if (
            self.capability_manifest.manifest_version
            != self.pins.capability_manifest_version
        ):
            raise ValueError("Slow view capability manifest must match pins")
        if (
            self.pins.planning_basis_fingerprint
            != self.planning_basis.planning_basis_fingerprint
        ):
            raise ValueError("Slow view planning basis must match pins")
        if any(item.status is not FactStatus.VERIFIED for item in self.verified_facts):
            raise ValueError("Slow view may expose verified facts only")
        if any(item.case_id != self.case_id for item in self.offers):
            raise ValueError("Slow view offers must reference the containing case")
        if any(item.case_id != self.case_id for item in self.approval_requests):
            raise ValueError("Slow view approvals must reference the containing case")
        if self.strategy is None and self.pins.strategy_id is not None:
            raise ValueError("Slow view must include the strategy named by its pins")
        if self.strategy is not None and (
            self.strategy.case_id != self.case_id
            or self.strategy.strategy_id != self.pins.strategy_id
            or self.strategy.revision != self.pins.strategy_revision
        ):
            raise ValueError("Slow view strategy must match current pins")
        return self


class RoutingDecision(VersionedContract):
    contract_type: Literal["routing_decision"]
    outcome: RoutingOutcome
    reason_codes: tuple[ExternalRef, ...]
    pins: ModelInputPins
    created_at: UtcDateTime

    @model_validator(mode="after")
    def reason_codes_must_be_unique(self) -> RoutingDecision:
        if not self.reason_codes:
            raise ValueError("routing decision requires deterministic reason codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("routing decision cannot contain duplicate reason codes")
        return self


class SlowWorkRequest(VersionedContract):
    contract_type: Literal["slow_work_request"]
    request_id: EntityId
    case_id: EntityId
    pins: ModelInputPins
    planning_basis: PlanningBasis
    view: SlowReasonerView
    reason_code: ExternalRef
    created_at: UtcDateTime

    @model_validator(mode="after")
    def request_must_echo_current_state(self) -> SlowWorkRequest:
        if self.case_id != self.pins.case_id or self.case_id != self.view.case_id:
            raise ValueError("Slow request case references must match")
        if (
            self.pins.planning_basis_fingerprint
            != self.planning_basis.planning_basis_fingerprint
        ):
            raise ValueError("Slow request planning basis must match pins")
        if self.view.pins != self.pins:
            raise ValueError("Slow request view must echo current pins")
        return self


class SlowWorkResult(VersionedContract):
    contract_type: Literal["slow_work_result"]
    result_id: EntityId
    request_id: EntityId
    case_id: EntityId
    pins: ModelInputPins
    planning_basis: PlanningBasis
    strategy_proposal: StrategyPacket | None = None
    capability_proposals: tuple[CapabilityProposal, ...] = ()
    action_proposals: tuple[ActionIntent, ...] = ()
    created_at: UtcDateTime

    @model_validator(mode="after")
    def result_must_be_a_version_bound_proposal(self) -> SlowWorkResult:
        if self.case_id != self.pins.case_id:
            raise ValueError("Slow result case_id must match pins")
        if (
            self.pins.planning_basis_fingerprint
            != self.planning_basis.planning_basis_fingerprint
        ):
            raise ValueError("Slow result planning basis must match pins")
        if (
            self.strategy_proposal is not None
            and self.strategy_proposal.case_id != self.case_id
        ):
            raise ValueError("strategy proposal must reference the containing case")
        proposal_ids = tuple(item.proposal_id for item in self.capability_proposals)
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("Slow result cannot duplicate capability proposals")
        action_ids = tuple(item.intent_id for item in self.action_proposals)
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("Slow result cannot duplicate action proposals")
        expected_strategy_id = (
            self.strategy_proposal.strategy_id
            if self.strategy_proposal is not None
            else self.pins.strategy_id
        )
        expected_strategy_revision = (
            self.strategy_proposal.revision
            if self.strategy_proposal is not None
            else self.pins.strategy_revision
        )
        for action in self.action_proposals:
            if action.case_id != self.case_id:
                raise ValueError("action proposal must reference the containing case")
            if action.authorization_state != "proposed":
                raise ValueError("Slow result cannot authorize an action")
            if action.case_revision != self.pins.case_revision:
                raise ValueError("action proposal case revision must match pins")
            if action.constraint_set_revision != self.pins.constraint_set_revision:
                raise ValueError("action proposal constraint revision must match pins")
            if (
                action.strategy_id != expected_strategy_id
                or action.strategy_revision != expected_strategy_revision
            ):
                raise ValueError(
                    "action proposal strategy must match the current "
                    "or proposed strategy"
                )
        return self


CANONICAL_MODELS: tuple[type[ContractModel], ...] = (
    Case,
    ConsumerGoal,
    Constraint,
    BillSnapshot,
    FactLedger,
    StrategyPacket,
    FastTurnDecision,
    ProviderOffer,
    ActionIntent,
    ApprovalRequest,
    Evidence,
    CompletionDecision,
    ModelTrace,
    ModelInputPins,
    PlanningBasis,
    VisibleCaseEvent,
    CapabilityManifest,
    CaseContextSnapshot,
    FastModelView,
    SlowReasonerView,
    RoutingDecision,
    SlowWorkRequest,
    SlowWorkResult,
)

ContractDocument = Annotated[
    Case
    | ConsumerGoal
    | Constraint
    | BillSnapshot
    | FactLedger
    | StrategyPacket
    | FastTurnDecision
    | ProviderOffer
    | ActionIntent
    | ApprovalRequest
    | Evidence
    | CompletionDecision
    | ModelTrace
    | ModelInputPins
    | PlanningBasis
    | VisibleCaseEvent
    | CapabilityManifest
    | CaseContextSnapshot
    | FastModelView
    | SlowReasonerView
    | RoutingDecision
    | SlowWorkRequest
    | SlowWorkResult,
    Field(discriminator="contract_type"),
]
CONTRACT_ADAPTER: TypeAdapter[ContractDocument] = TypeAdapter(ContractDocument)


def validate_contract_json(data: str | bytes) -> ContractDocument:
    return CONTRACT_ADAPTER.validate_json(data)


def contract_json_schema() -> dict[str, Any]:
    return CONTRACT_ADAPTER.json_schema(
        ref_template="#/$defs/{model}",
        union_format="any_of",
    )
