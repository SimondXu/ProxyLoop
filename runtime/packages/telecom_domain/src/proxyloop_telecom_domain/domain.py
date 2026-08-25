from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    Case,
    CompletionDecision,
    CompletionOutcome,
    Evidence,
    EvidenceType,
    MaterialTerm,
    Money,
    OfferReference,
    ProviderOffer,
)

from .offer_policy import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
)


class ApprovalUseError(ValueError):
    """An approval cannot authorize the requested execution."""


class ApprovalExpiredError(ApprovalUseError):
    """An approval, action intent, or referenced offer is no longer current."""


class ApprovalBindingError(ApprovalUseError):
    """An approval does not bind to the exact proposed action."""


@dataclass(frozen=True)
class AppliedOfferConfirmation:
    case_id: UUID
    provider_id: str
    confirmation_id: str
    offer_ref: OfferReference
    action_intent_id: UUID
    approval_id: UUID
    confirmed_at: datetime
    previous_monthly_price: Money
    new_monthly_price: Money
    total_cost_12_months: Money
    plan_id: str
    plan_name: str
    features: tuple[str, ...]
    removed_add_ons: tuple[str, ...]
    applied_changes: tuple[str, ...]
    term_months: int
    effective_date: date

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": str(self.case_id),
            "provider_id": self.provider_id,
            "confirmation_id": self.confirmation_id,
            "offer_ref": self.offer_ref.model_dump(mode="json"),
            "action_intent_id": str(self.action_intent_id),
            "approval_id": str(self.approval_id),
            "confirmed_at": _utc_text(self.confirmed_at),
            "previous_monthly_price": self.previous_monthly_price.model_dump(
                mode="json"
            ),
            "new_monthly_price": self.new_monthly_price.model_dump(mode="json"),
            "total_cost_12_months": self.total_cost_12_months.model_dump(mode="json"),
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "features": list(self.features),
            "removed_add_ons": list(self.removed_add_ons),
            "applied_changes": list(self.applied_changes),
            "term_months": self.term_months,
            "effective_date": self.effective_date.isoformat(),
        }


class ConfirmationAuthority(Protocol):
    def lookup_confirmation(
        self, confirmation_id: str
    ) -> tuple[AppliedOfferConfirmation, Evidence] | None: ...


@dataclass(frozen=True)
class CompletionVerification:
    completion_id: UUID
    case: Case
    offer: ProviderOffer
    action_intent: ActionIntent
    approval_request: ApprovalRequest
    confirmation: AppliedOfferConfirmation
    evidence: Evidence
    confirmation_authority: ConfirmationAuthority
    executed_at: datetime
    evaluated_at: datetime


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def offer_material_terms(offer: ProviderOffer) -> tuple[MaterialTerm, ...]:
    return (
        MaterialTerm(
            name="monthly_price_minor",
            value=str(offer.monthly_price.amount_minor),
        ),
        MaterialTerm(
            name="total_cost_12_months_minor",
            value=str(offer.total_cost.amount_minor),
        ),
        MaterialTerm(name="currency", value=offer.monthly_price.currency),
        MaterialTerm(name="term_months", value=str(offer.term_months)),
        MaterialTerm(name="features", value=",".join(sorted(offer.features))),
        MaterialTerm(name="offer_expires_at", value=_utc_text(offer.expires_at)),
    )


def material_terms_hash(terms: tuple[MaterialTerm, ...]) -> str:
    canonical_terms = sorted(
        (term.model_dump(mode="json") for term in terms),
        key=lambda item: (str(item["name"]), str(item["value"])),
    )
    return _sha256_json(canonical_terms)


def confirmation_hash(confirmation: AppliedOfferConfirmation) -> str:
    return _sha256_json(confirmation.to_dict())


def validate_approval_use(
    *,
    case: Case,
    offer: ProviderOffer,
    action_intent: ActionIntent,
    approval_request: ApprovalRequest,
    executed_at: datetime,
) -> None:
    if executed_at >= approval_request.expires_at:
        raise ApprovalExpiredError("approval expired before execution")
    if executed_at >= offer.expires_at:
        raise ApprovalExpiredError("referenced offer expired before execution")
    if action_intent.expires_at is not None and executed_at >= action_intent.expires_at:
        raise ApprovalExpiredError("action intent expired before execution")
    if approval_request.decision is not ApprovalDecision.APPROVED:
        raise ApprovalBindingError("approval decision is not approved")
    if approval_request.decided_at is None:
        raise ApprovalBindingError("approved request is missing decided_at")
    if executed_at < approval_request.decided_at:
        raise ApprovalBindingError("execution precedes the approval decision")

    expected_offer_ref = OfferReference(
        offer_id=offer.offer_id,
        offer_revision=offer.revision,
    )
    mismatches = (
        action_intent.case_id != case.case_id,
        action_intent.action_type is not ActionType.ACCEPT_OFFER,
        ActionType.ACCEPT_OFFER
        not in case.delegated_authority.approval_required_actions,
        action_intent.case_revision != case.revision,
        action_intent.constraint_set_revision != case.constraint_set_revision,
        action_intent.offer_ref != expected_offer_ref,
        action_intent.material_terms != offer_material_terms(offer),
        action_intent.material_terms_hash
        != material_terms_hash(action_intent.material_terms),
        approval_request.case_id != case.case_id,
        approval_request.case_revision != case.revision,
        approval_request.action_intent_id != action_intent.intent_id,
        approval_request.action_intent_revision != action_intent.revision,
        approval_request.action_type != action_intent.action_type,
        approval_request.strategy_id != action_intent.strategy_id,
        approval_request.strategy_revision != action_intent.strategy_revision,
        approval_request.constraint_set_revision
        != action_intent.constraint_set_revision,
        approval_request.offer_ref != action_intent.offer_ref,
        approval_request.material_terms_hash != action_intent.material_terms_hash,
        approval_request.requested_at < action_intent.created_at,
    )
    if any(mismatches):
        raise ApprovalBindingError("approval does not bind to the exact action")


def verify_completion(request: CompletionVerification) -> CompletionDecision:
    reason_codes: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reason_codes:
            reason_codes.append(reason)

    try:
        validate_approval_use(
            case=request.case,
            offer=request.offer,
            action_intent=request.action_intent,
            approval_request=request.approval_request,
            executed_at=request.executed_at,
        )
    except ApprovalExpiredError:
        reject("approval_expired")
    except ApprovalBindingError:
        reject("approval_binding_mismatch")

    if request.evaluated_at < request.executed_at:
        reject("evaluation_precedes_execution")

    bill_snapshot = request.case.bill_snapshot
    if bill_snapshot is None:
        reject("missing_bill_snapshot")
    else:
        target = request.case.goal.target_monthly_total
        policy_context = OfferComplianceContext(
            evaluated_at=request.evaluated_at,
            current_monthly_minor=bill_snapshot.monthly_total.amount_minor,
            currency=bill_snapshot.monthly_total.currency,
            target_monthly_minor=target.amount_minor if target is not None else None,
            target_currency=target.currency if target is not None else None,
            required_features=tuple(
                str(value) for value in request.case.goal.required_features
            ),
            forbidden_changes=tuple(
                str(value) for value in request.case.goal.forbidden_changes
            ),
        )
        policy_terms = OfferComplianceTerms(
            monthly_price_minor=request.offer.monthly_price.amount_minor,
            total_cost_12_months_minor=request.offer.total_cost.amount_minor,
            currency=request.offer.monthly_price.currency,
            fees_minor=sum(item.amount.amount_minor for item in request.offer.fees),
            features=tuple(str(value) for value in request.offer.features),
            applied_changes=request.confirmation.applied_changes,
            expires_at=request.offer.expires_at,
        )
        policy_reason_map = {
            "forbidden_change_present": "forbidden_change_applied",
        }
        for violation in offer_compliance_violations(policy_context, policy_terms):
            reject(policy_reason_map.get(violation, violation))

    expected_offer_ref = OfferReference(
        offer_id=request.offer.offer_id,
        offer_revision=request.offer.revision,
    )
    confirmation = request.confirmation
    if (
        confirmation.case_id != request.case.case_id
        or confirmation.provider_id != request.offer.provider_id
        or confirmation.offer_ref != expected_offer_ref
        or confirmation.action_intent_id != request.action_intent.intent_id
        or confirmation.approval_id != request.approval_request.approval_id
        or confirmation.new_monthly_price != request.offer.monthly_price
        or confirmation.total_cost_12_months != request.offer.total_cost
        or confirmation.features != request.offer.features
        or confirmation.term_months != request.offer.term_months
        or confirmation.confirmed_at != request.executed_at
    ):
        reject("confirmation_state_mismatch")

    evidence = request.evidence
    authoritative_record = request.confirmation_authority.lookup_confirmation(
        confirmation.confirmation_id
    )
    if authoritative_record != (confirmation, evidence):
        reject("provider_confirmation_mismatch")
    if evidence.case_id != request.case.case_id:
        reject("evidence_case_mismatch")
    if evidence.source_type is not EvidenceType.CONFIRMATION:
        reject("evidence_type_mismatch")
    if evidence.source_ref != confirmation.confirmation_id:
        reject("evidence_reference_mismatch")
    if evidence.content_hash != confirmation_hash(confirmation):
        reject("evidence_hash_mismatch")
    if evidence.observed_at != confirmation.confirmed_at:
        reject("evidence_timestamp_mismatch")
    if evidence.captured_at > request.evaluated_at:
        reject("evidence_not_available_at_evaluation")

    is_complete = not reason_codes
    return CompletionDecision(
        contract_type="completion_decision",
        schema_version="1.0",
        completion_id=request.completion_id,
        case_id=request.case.case_id,
        case_revision=request.case.revision,
        revision=1,
        decision=(
            CompletionOutcome.COMPLETE
            if is_complete
            else CompletionOutcome.NEEDS_REPLAN
        ),
        verifier_name="phase_01a_deterministic_verifier",
        verifier_version="1.0",
        evaluated_at=request.evaluated_at,
        evidence_ids=(evidence.evidence_id,) if is_complete else (),
        missing_evidence=() if is_complete else ("valid_provider_confirmation",),
        reason_codes=tuple(reason_codes) if reason_codes else ("verified_complete",),
    )
