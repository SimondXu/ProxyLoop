from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    BillSnapshot,
    Case,
    CasePhase,
    CompletionDecision,
    Constraint,
    ConstraintClassification,
    ConsumerGoal,
    DelegatedAuthority,
    Evidence,
    LineItem,
    LineItemCategory,
    Money,
    OfferReference,
    ProviderOffer,
    UsageProfile,
)
from proxyloop_telecom_domain import (
    AppliedOfferConfirmation,
    CompletionVerification,
    material_terms_hash,
    offer_material_terms,
    verify_completion,
)

from .provider import FictionalMobileProvider, OfferState

CASE_CREATED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OFFER_ISSUED_AT = datetime(2026, 8, 23, 12, 1, tzinfo=UTC)
INTENT_CREATED_AT = datetime(2026, 8, 23, 12, 2, tzinfo=UTC)
APPROVAL_REQUESTED_AT = datetime(2026, 8, 23, 12, 3, tzinfo=UTC)
APPROVAL_DECIDED_AT = datetime(2026, 8, 23, 12, 4, tzinfo=UTC)
APPROVAL_EXPIRES_AT = datetime(2026, 8, 23, 12, 30, tzinfo=UTC)
INTENT_EXPIRES_AT = datetime(2026, 8, 23, 12, 45, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 8, 23, 12, 5, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 23, 12, 6, tzinfo=UTC)


@dataclass(frozen=True)
class EpisodeResult:
    provider_id: str
    case: Case
    offer: ProviderOffer
    offer_evidence: Evidence
    action_intent: ActionIntent
    approval_request: ApprovalRequest
    confirmation: AppliedOfferConfirmation
    confirmation_evidence: Evidence
    completion_decision: CompletionDecision
    offer_state_history: tuple[OfferState, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "case": self.case.model_dump(mode="json"),
            "offer": self.offer.model_dump(mode="json"),
            "offer_evidence": self.offer_evidence.model_dump(mode="json"),
            "action_intent": self.action_intent.model_dump(mode="json"),
            "approval_request": self.approval_request.model_dump(mode="json"),
            "confirmation": self.confirmation.to_dict(),
            "confirmation_evidence": self.confirmation_evidence.model_dump(mode="json"),
            "completion_decision": self.completion_decision.model_dump(mode="json"),
            "offer_state_history": [state.value for state in self.offer_state_history],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class Phase01AEpisode:
    def __init__(self, case: Case) -> None:
        self.case = case
        self.provider = FictionalMobileProvider()
        self.offer: ProviderOffer | None = None
        self.offer_evidence: Evidence | None = None
        self.action_intent: ActionIntent | None = None
        self.approval_request: ApprovalRequest | None = None
        self.confirmation: AppliedOfferConfirmation | None = None
        self.confirmation_evidence: Evidence | None = None
        self.completion_decision: CompletionDecision | None = None

    @classmethod
    def success(cls) -> Phase01AEpisode:
        return cls(_build_case())

    @property
    def offer_state(self) -> OfferState:
        return self.provider.state

    @property
    def offer_state_history(self) -> tuple[OfferState, ...]:
        return self.provider.state_history

    def issue_offer(self) -> ProviderOffer:
        self.offer, self.offer_evidence = self.provider.issue_offer(
            self.case,
            issued_at=OFFER_ISSUED_AT,
        )
        return self.offer

    def request_approval(self) -> ApprovalRequest:
        if self.offer is None:
            raise RuntimeError("an offer must exist before approval is requested")
        terms = offer_material_terms(self.offer)
        self.action_intent = ActionIntent(
            contract_type="action_intent",
            schema_version="1.0",
            intent_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            case_id=self.case.case_id,
            case_revision=self.case.revision,
            strategy_id=UUID("99999999-9999-4999-8999-999999999999"),
            strategy_revision=1,
            constraint_set_revision=self.case.constraint_set_revision,
            revision=1,
            action_type=ActionType.ACCEPT_OFFER,
            offer_ref=OfferReference(
                offer_id=self.offer.offer_id,
                offer_revision=self.offer.revision,
            ),
            material_terms=terms,
            material_terms_hash=material_terms_hash(terms),
            approval_required=True,
            authorization_state="proposed",
            idempotency_key="phase-01a-pine-mobile-accept-0001",
            created_at=INTENT_CREATED_AT,
            expires_at=INTENT_EXPIRES_AT,
        )
        self.provider.await_approval(self.action_intent)
        self.approval_request = ApprovalRequest(
            contract_type="approval_request",
            schema_version="1.0",
            approval_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            case_id=self.case.case_id,
            case_revision=self.case.revision,
            action_intent_id=self.action_intent.intent_id,
            action_intent_revision=self.action_intent.revision,
            action_type=self.action_intent.action_type,
            strategy_id=self.action_intent.strategy_id,
            strategy_revision=self.action_intent.strategy_revision,
            constraint_set_revision=self.action_intent.constraint_set_revision,
            offer_ref=self.action_intent.offer_ref,
            material_terms_hash=self.action_intent.material_terms_hash,
            revision=1,
            requested_at=APPROVAL_REQUESTED_AT,
            expires_at=APPROVAL_EXPIRES_AT,
        )
        return self.approval_request

    def approve(self, *, at: datetime = APPROVAL_DECIDED_AT) -> ApprovalRequest:
        if self.approval_request is None:
            raise RuntimeError("approval must be requested before it is decided")
        pending = self.approval_request
        self.approval_request = ApprovalRequest(
            contract_type=pending.contract_type,
            schema_version=pending.schema_version,
            approval_id=pending.approval_id,
            case_id=pending.case_id,
            case_revision=pending.case_revision,
            action_intent_id=pending.action_intent_id,
            action_intent_revision=pending.action_intent_revision,
            action_type=pending.action_type,
            strategy_id=pending.strategy_id,
            strategy_revision=pending.strategy_revision,
            constraint_set_revision=pending.constraint_set_revision,
            offer_ref=pending.offer_ref,
            material_terms_hash=pending.material_terms_hash,
            revision=pending.revision + 1,
            requested_at=pending.requested_at,
            expires_at=pending.expires_at,
            decision=ApprovalDecision.APPROVED,
            decided_at=at,
        )
        return self.approval_request

    def execute(self, *, at: datetime = EXECUTED_AT) -> Evidence:
        if self.approval_request is None:
            raise RuntimeError("approved request is required before execution")
        self.confirmation, self.confirmation_evidence = (
            self.provider.execute_approved_offer(
                self.approval_request,
                executed_at=at,
            )
        )
        return self.confirmation_evidence

    def verify(self, *, at: datetime = EVALUATED_AT) -> CompletionDecision:
        if (
            self.offer is None
            or self.action_intent is None
            or self.approval_request is None
            or self.confirmation is None
            or self.confirmation_evidence is None
        ):
            raise RuntimeError("episode must execute before completion verification")
        self.completion_decision = verify_completion(
            CompletionVerification(
                completion_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
                case=self.case,
                offer=self.offer,
                action_intent=self.action_intent,
                approval_request=self.approval_request,
                confirmation=self.confirmation,
                evidence=self.confirmation_evidence,
                confirmation_authority=self.provider,
                executed_at=self.confirmation.confirmed_at,
                evaluated_at=at,
            )
        )
        return self.completion_decision

    def result(self) -> EpisodeResult:
        if (
            self.offer is None
            or self.offer_evidence is None
            or self.action_intent is None
            or self.approval_request is None
            or self.confirmation is None
            or self.confirmation_evidence is None
            or self.completion_decision is None
        ):
            raise RuntimeError("episode is not complete")
        return EpisodeResult(
            provider_id=self.provider.provider_id,
            case=self.case,
            offer=self.offer,
            offer_evidence=self.offer_evidence,
            action_intent=self.action_intent,
            approval_request=self.approval_request,
            confirmation=self.confirmation,
            confirmation_evidence=self.confirmation_evidence,
            completion_decision=self.completion_decision,
            offer_state_history=self.offer_state_history,
        )


def run_success_episode() -> EpisodeResult:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    return episode.result()


def _build_case() -> Case:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    return Case(
        contract_type="case",
        schema_version="1.0",
        case_id=case_id,
        consumer_id=UUID("22222222-2222-4222-8222-222222222222"),
        phase=CasePhase.INITIATED,
        revision=1,
        constraint_set_revision=1,
        created_at=CASE_CREATED_AT,
        updated_at=CASE_CREATED_AT,
        goal=ConsumerGoal(
            contract_type="consumer_goal",
            schema_version="1.0",
            goal_id=UUID("33333333-3333-4333-8333-333333333333"),
            case_id=case_id,
            revision=1,
            created_at=CASE_CREATED_AT,
            updated_at=CASE_CREATED_AT,
            desired_outcome=(
                "Reduce the recurring bill without losing mobile hotspot access."
            ),
            target_monthly_total=Money(amount_minor=7500, currency="USD"),
            required_features=("mobile_hotspot",),
            forbidden_changes=("device_financing_change",),
            deadline=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        ),
        constraints=(
            Constraint(
                contract_type="constraint",
                schema_version="1.0",
                constraint_id=UUID("44444444-4444-4444-8444-444444444444"),
                case_id=case_id,
                revision=1,
                classification=ConstraintClassification.HARD,
                statement="Do not change device financing.",
                source="consumer_input",
                valid_from=CASE_CREATED_AT,
            ),
        ),
        delegated_authority=DelegatedAuthority(
            allowed_actions=(ActionType.SEND_MESSAGE, ActionType.REQUEST_CLARIFICATION),
            approval_required_actions=(ActionType.ACCEPT_OFFER,),
            allowed_disclosures=("current_monthly_total", "required_features"),
        ),
        bill_snapshot=BillSnapshot(
            contract_type="bill_snapshot",
            schema_version="1.0",
            snapshot_id=UUID("55555555-5555-4555-8555-555555555555"),
            case_id=case_id,
            revision=1,
            captured_at=CASE_CREATED_AT,
            monthly_total=Money(amount_minor=9200, currency="USD"),
            line_items=(
                LineItem(
                    name="Postpaid mobile service",
                    category=LineItemCategory.SERVICE,
                    amount=Money(amount_minor=8200, currency="USD"),
                ),
                LineItem(
                    name="Premium data add-on",
                    category=LineItemCategory.ADDON,
                    amount=Money(amount_minor=1000, currency="USD"),
                ),
            ),
            add_ons=("premium_data",),
            term_months=0,
            usage=UsageProfile(
                voice_minutes=420,
                sms_count=120,
                data_megabytes=24576,
            ),
            evidence_ids=(UUID("66666666-6666-4666-8666-666666666666"),),
        ),
    )
