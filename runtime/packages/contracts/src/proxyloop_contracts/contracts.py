from __future__ import annotations

from enum import StrEnum
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
    | ModelTrace,
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
