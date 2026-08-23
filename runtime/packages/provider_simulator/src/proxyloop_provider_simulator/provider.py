from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ApprovalRequest,
    Case,
    Evidence,
    EvidenceType,
    Money,
    OfferReference,
    ProviderOffer,
)
from proxyloop_telecom_domain import (
    AppliedOfferConfirmation,
    confirmation_hash,
    validate_approval_use,
)


class OfferState(StrEnum):
    AVAILABLE = "available"
    OFFERED = "offered"
    AWAITING_APPROVAL = "awaiting_approval"
    CONFIRMED = "confirmed"


class IllegalOfferTransitionError(RuntimeError):
    """The requested Provider operation is illegal in the current offer state."""


class FictionalMobileProvider:
    provider_id = "pine-mobile"
    plan_id = "pine-value-5g"
    plan_name = "Pine Value 5G"

    def __init__(self) -> None:
        self._state = OfferState.AVAILABLE
        self._state_history = [self._state]
        self._case: Case | None = None
        self._offer: ProviderOffer | None = None
        self._intent: ActionIntent | None = None
        self._confirmation: AppliedOfferConfirmation | None = None
        self._confirmation_evidence: Evidence | None = None

    @property
    def state(self) -> OfferState:
        return self._state

    @property
    def state_history(self) -> tuple[OfferState, ...]:
        return tuple(self._state_history)

    @property
    def confirmation(self) -> AppliedOfferConfirmation | None:
        return self._confirmation

    @property
    def confirmation_evidence(self) -> Evidence | None:
        return self._confirmation_evidence

    def lookup_confirmation(
        self, confirmation_id: str
    ) -> tuple[AppliedOfferConfirmation, Evidence] | None:
        if (
            self._state is not OfferState.CONFIRMED
            or self._confirmation is None
            or self._confirmation_evidence is None
            or confirmation_id != self._confirmation.confirmation_id
        ):
            return None
        return self._confirmation, self._confirmation_evidence

    def _transition(self, expected: OfferState, target: OfferState) -> None:
        if self._state is not expected:
            raise IllegalOfferTransitionError(
                f"cannot transition from {self._state.value} to {target.value}"
            )
        self._state = target
        self._state_history.append(target)

    def issue_offer(
        self, case: Case, *, issued_at: datetime
    ) -> tuple[ProviderOffer, Evidence]:
        if self._state is not OfferState.AVAILABLE:
            raise IllegalOfferTransitionError(
                f"cannot issue an offer while state is {self._state.value}"
            )
        quote_evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            case_id=case.case_id,
            source_type=EvidenceType.PROVIDER_MESSAGE,
            source_ref="pine-mobile:offer:pine-value-5g:v1",
            content_hash=self._quote_hash(case),
            observed_at=issued_at,
            captured_at=issued_at,
            media_type="application/json",
        )
        offer = ProviderOffer(
            contract_type="provider_offer",
            schema_version="1.0",
            offer_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            case_id=case.case_id,
            provider_id=self.provider_id,
            revision=1,
            created_at=issued_at,
            expires_at=issued_at + timedelta(hours=1),
            monthly_price=Money(amount_minor=7200, currency="USD"),
            total_cost=Money(amount_minor=86400, currency="USD"),
            fees=(),
            features=("mobile_hotspot", "unlimited_talk_text"),
            term_months=0,
            evidence_ids=(quote_evidence.evidence_id,),
        )
        self._case = case
        self._offer = offer
        self._transition(OfferState.AVAILABLE, OfferState.OFFERED)
        return offer, quote_evidence

    def await_approval(self, action_intent: ActionIntent) -> None:
        if self._state is not OfferState.OFFERED:
            raise IllegalOfferTransitionError(
                f"cannot await approval while state is {self._state.value}"
            )
        if self._offer is None or action_intent.offer_ref != OfferReference(
            offer_id=self._offer.offer_id,
            offer_revision=self._offer.revision,
        ):
            raise ValueError("action intent does not reference the current offer")
        self._intent = action_intent
        self._transition(OfferState.OFFERED, OfferState.AWAITING_APPROVAL)

    def execute_approved_offer(
        self,
        approval_request: ApprovalRequest,
        *,
        executed_at: datetime,
    ) -> tuple[AppliedOfferConfirmation, Evidence]:
        if self._state is not OfferState.AWAITING_APPROVAL:
            raise IllegalOfferTransitionError(
                f"cannot confirm an offer while state is {self._state.value}"
            )
        if self._case is None or self._offer is None or self._intent is None:
            raise RuntimeError("provider state is incomplete")
        validate_approval_use(
            case=self._case,
            offer=self._offer,
            action_intent=self._intent,
            approval_request=approval_request,
            executed_at=executed_at,
        )
        if self._case.bill_snapshot is None:
            raise ValueError("case requires a bill snapshot")

        confirmation = AppliedOfferConfirmation(
            case_id=self._case.case_id,
            provider_id=self.provider_id,
            confirmation_id="pine-confirmation-0001",
            offer_ref=OfferReference(
                offer_id=self._offer.offer_id,
                offer_revision=self._offer.revision,
            ),
            action_intent_id=self._intent.intent_id,
            approval_id=approval_request.approval_id,
            confirmed_at=executed_at,
            previous_monthly_price=self._case.bill_snapshot.monthly_total,
            new_monthly_price=self._offer.monthly_price,
            total_cost_12_months=self._offer.total_cost,
            plan_id=self.plan_id,
            plan_name=self.plan_name,
            features=self._offer.features,
            removed_add_ons=self._case.bill_snapshot.add_ons,
            applied_changes=(
                "monthly_price_change",
                "plan_change",
                "remove_add_on:premium_data",
            ),
            term_months=self._offer.term_months,
            effective_date=date(2026, 8, 24),
        )
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            case_id=self._case.case_id,
            source_type=EvidenceType.CONFIRMATION,
            source_ref=confirmation.confirmation_id,
            content_hash=confirmation_hash(confirmation),
            observed_at=executed_at,
            captured_at=executed_at,
            media_type="application/json",
        )
        self._confirmation = confirmation
        self._confirmation_evidence = evidence
        self._transition(OfferState.AWAITING_APPROVAL, OfferState.CONFIRMED)
        return confirmation, evidence

    def _quote_hash(self, case: Case) -> str:
        payload = json.dumps(
            {
                "case_id": str(case.case_id),
                "provider_id": self.provider_id,
                "plan_id": self.plan_id,
                "monthly_price_minor": 7200,
                "currency": "USD",
                "features": ["mobile_hotspot", "unlimited_talk_text"],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
