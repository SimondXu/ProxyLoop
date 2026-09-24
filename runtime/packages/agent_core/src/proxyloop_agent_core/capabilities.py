"""Current-state policy and idempotent simulator-only capability execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID

from proxyloop_contracts import (
    ActionIntent,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityDefinition,
    CapabilityProposal,
    CaseContextSnapshot,
    Evidence,
    EvidenceType,
    MaterialTerm,
    ModelInputPins,
    ProviderOffer,
    material_terms_hash,
)

from .interfaces import PreparedSimulatorExecution, SimulatorCapabilityAdapter

TermsDerivation = Callable[[ProviderOffer], tuple[MaterialTerm, ...]]


class CapabilityExecutionStatus(StrEnum):
    EXECUTED = "executed"
    REUSED = "reused"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CapabilityExecutionRequest:
    snapshot: CaseContextSnapshot
    source_pins: ModelInputPins
    proposal: CapabilityProposal
    action_intent: ActionIntent
    approval: ApprovalRequest | None
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilityExecutionOutcome:
    status: CapabilityExecutionStatus
    reason_codes: tuple[str, ...]
    evidence: Evidence | None = None


class CapabilityExecutor:
    """The sole side-effect lane for fictional Provider capabilities.

    Two process-local at-most-once rules hold on top of request validation:

    - one ``idempotency_key`` maps to one execution: the same request binding
      reuses the recorded Evidence, a different binding is rejected
      (``idempotency_key_reuse_mismatch``);
    - one APPROVED ``ApprovalRequest`` is consumed by one execution: the same
      approval under any other binding or idempotency key is rejected
      (``approval_already_consumed``).

    Both records are written only after the adapter's ``commit()`` returns.
    Before ``commit()`` the executor claims the idempotency key and the
    approval; a ``commit`` that raises may already have mutated the adapter, so
    its claims stay and any later request for that key or approval is
    rejected (``execution_outcome_unknown``) instead of executing again.
    Reconciling such an execution is the caller's job, against the adapter's
    own state; the executor never clears the unresolved mark. The runtime
    reconciles through its ``provider.confirmation`` short-circuit before it
    calls the executor at all.

    ``terms_derivation`` optionally recomputes the material terms of the
    snapshot offer so an offer whose terms changed under an unchanged
    revision is rejected (``current_offer_terms_mismatch``). The runtime
    injects the telecom-domain derivation; this package does not depend on it.
    """

    def __init__(
        self,
        adapter: SimulatorCapabilityAdapter,
        *,
        terms_derivation: TermsDerivation | None = None,
    ) -> None:
        self._adapter = adapter
        self._terms_derivation = terms_derivation
        self._lock = RLock()
        self._evidence_by_idempotency_key: dict[str, tuple[str, Evidence]] = {}
        self._consumed_approvals: dict[UUID, tuple[str, Evidence]] = {}
        self._unresolved_keys: set[str] = set()
        self._unresolved_approvals: set[UUID] = set()

    def execute(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionOutcome:
        with self._lock:
            return self._execute_serialized(request)

    def _execute_serialized(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionOutcome:
        key = request.action_intent.idempotency_key
        approval_id = (
            request.approval.approval_id if request.approval is not None else None
        )
        if key in self._unresolved_keys or approval_id in self._unresolved_approvals:
            return CapabilityExecutionOutcome(
                status=CapabilityExecutionStatus.REJECTED,
                reason_codes=("execution_outcome_unknown",),
            )
        binding = _request_binding(request)
        prior = self._evidence_by_idempotency_key.get(key)
        if prior is not None:
            prior_binding, prior_evidence = prior
            if binding != prior_binding:
                return CapabilityExecutionOutcome(
                    status=CapabilityExecutionStatus.REJECTED,
                    reason_codes=("idempotency_key_reuse_mismatch",),
                )
            return CapabilityExecutionOutcome(
                status=CapabilityExecutionStatus.REUSED,
                reason_codes=("idempotent_evidence_reused",),
                evidence=prior_evidence,
            )
        if request.approval is not None:
            consumed = self._consumed_approvals.get(request.approval.approval_id)
            if consumed is not None:
                consumed_binding, consumed_evidence = consumed
                if binding != consumed_binding or key != consumed_evidence.source_ref:
                    return CapabilityExecutionOutcome(
                        status=CapabilityExecutionStatus.REJECTED,
                        reason_codes=("approval_already_consumed",),
                    )
                return CapabilityExecutionOutcome(
                    status=CapabilityExecutionStatus.REUSED,
                    reason_codes=("idempotent_evidence_reused",),
                    evidence=consumed_evidence,
                )

        reasons = self._validate(request)
        if reasons:
            return CapabilityExecutionOutcome(
                status=CapabilityExecutionStatus.REJECTED,
                reason_codes=reasons,
            )

        prepared_object: object = self._adapter.prepare(
            request.proposal, idempotency_key=key
        )
        if not isinstance(prepared_object, PreparedSimulatorExecution):
            return CapabilityExecutionOutcome(
                status=CapabilityExecutionStatus.REJECTED,
                reason_codes=("evidence_missing_or_invalid",),
            )
        evidence = prepared_object.evidence
        evidence_reasons = self._validate_evidence(evidence, request)
        if evidence_reasons:
            return CapabilityExecutionOutcome(
                status=CapabilityExecutionStatus.REJECTED,
                reason_codes=evidence_reasons,
            )
        self._unresolved_keys.add(key)
        if approval_id is not None:
            self._unresolved_approvals.add(approval_id)
        prepared_object.commit()
        self._unresolved_keys.discard(key)
        self._evidence_by_idempotency_key[key] = (binding, evidence)
        if approval_id is not None:
            self._unresolved_approvals.discard(approval_id)
            self._consumed_approvals[approval_id] = (binding, evidence)
        return CapabilityExecutionOutcome(
            status=CapabilityExecutionStatus.EXECUTED,
            reason_codes=("simulator_capability_executed",),
            evidence=evidence,
        )

    def _validate(self, request: CapabilityExecutionRequest) -> tuple[str, ...]:
        snapshot = request.snapshot
        intent = request.action_intent
        approval = request.approval
        reasons: list[str] = []

        try:
            CaseContextSnapshot.model_validate(snapshot.model_dump(mode="python"))
        except ValueError:
            reasons.append("snapshot_integrity_invalid")

        if request.source_pins != snapshot.pins:
            reasons.append("stale_capability_proposal")
        if request.executed_at >= snapshot.capability_manifest.expires_at:
            reasons.append("capability_manifest_expired")
        if request.proposal.created_at > request.executed_at:
            reasons.append("capability_proposal_not_current")
        if (
            request.proposal.expires_at is not None
            and request.executed_at >= request.proposal.expires_at
        ):
            reasons.append("capability_proposal_expired")
        capability = _find_capability(request)
        if capability is None:
            reasons.append("unsupported_capability")
        elif intent.action_type not in capability.allowed_action_types:
            reasons.append("capability_action_mismatch")
        elif (
            capability.expires_at is not None
            and request.executed_at >= capability.expires_at
        ):
            reasons.append("capability_expired")

        if intent.case_id != snapshot.case.case_id:
            reasons.append("action_case_mismatch")
        if intent.case_revision != snapshot.case.revision:
            reasons.append("action_case_revision_mismatch")
        if intent.constraint_set_revision != snapshot.case.constraint_set_revision:
            reasons.append("action_constraint_revision_mismatch")
        if snapshot.strategy is None or (
            intent.strategy_id != snapshot.strategy.strategy_id
            or intent.strategy_revision != snapshot.strategy.revision
        ):
            reasons.append("action_strategy_mismatch")
        if intent.expires_at is not None and request.executed_at >= intent.expires_at:
            reasons.append("action_intent_expired")
        if intent.material_terms_hash != material_terms_hash(intent.material_terms):
            reasons.append("action_material_terms_hash_mismatch")

        authority = snapshot.case.delegated_authority
        requires_approval = intent.action_type in authority.approval_required_actions
        directly_allowed = intent.action_type in authority.allowed_actions
        if not directly_allowed and not requires_approval:
            reasons.append("delegated_authority_denied")
        if requires_approval or intent.approval_required:
            reasons.extend(_approval_reasons(request))
        elif approval is not None:
            reasons.append("unexpected_approval")

        if intent.offer_ref is not None:
            proposal_offer_ids = tuple(
                str(argument.value)
                for argument in request.proposal.arguments
                if argument.name == "offer_id"
            )
            if proposal_offer_ids != (str(intent.offer_ref.offer_id),):
                reasons.append("capability_offer_binding_mismatch")
            offer = next(
                (
                    item
                    for item in snapshot.offers
                    if item.offer_id == intent.offer_ref.offer_id
                ),
                None,
            )
            if offer is None or offer.revision != intent.offer_ref.offer_revision:
                reasons.append("current_offer_mismatch")
            else:
                if request.executed_at >= offer.expires_at:
                    reasons.append("current_offer_expired")
                if self._terms_derivation is not None and _sorted_terms(
                    intent.material_terms
                ) != _sorted_terms(self._terms_derivation(offer)):
                    reasons.append("current_offer_terms_mismatch")
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _validate_evidence(
        evidence: Evidence,
        request: CapabilityExecutionRequest,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if evidence.case_id != request.snapshot.case.case_id:
            reasons.append("evidence_case_mismatch")
        if evidence.source_ref != request.action_intent.idempotency_key:
            reasons.append("evidence_execution_binding_mismatch")
        if evidence.source_type not in {
            EvidenceType.CONFIRMATION,
            EvidenceType.PROVIDER_EVENT,
            EvidenceType.SIMULATOR_TRANSITION,
        }:
            reasons.append("evidence_not_simulator_owned")
        if evidence.observed_at > request.executed_at:
            reasons.append("evidence_from_future")
        if evidence.captured_at > request.executed_at:
            reasons.append("evidence_capture_from_future")
        return tuple(reasons)


def _find_capability(
    request: CapabilityExecutionRequest,
) -> CapabilityDefinition | None:
    reference = request.proposal.capability
    for capability in request.snapshot.capability_manifest.capabilities:
        if (
            capability.capability_id == reference.capability_id
            and capability.version == reference.version
        ):
            return capability
    return None


def _approval_reasons(request: CapabilityExecutionRequest) -> list[str]:
    approval = request.approval
    intent = request.action_intent
    if approval is None:
        return ["approval_missing"]

    reasons: list[str] = []
    if approval.decision is not ApprovalDecision.APPROVED:
        reasons.append("approval_not_approved")
    if approval.decided_at is None or approval.decided_at > request.executed_at:
        reasons.append("approval_decision_not_current")
    if request.executed_at >= approval.expires_at:
        reasons.append("approval_expired")
    exact_bindings = (
        approval.case_id == intent.case_id,
        approval.case_revision == intent.case_revision,
        approval.action_intent_id == intent.intent_id,
        approval.action_intent_revision == intent.revision,
        approval.action_type == intent.action_type,
        approval.strategy_id == intent.strategy_id,
        approval.strategy_revision == intent.strategy_revision,
        approval.constraint_set_revision == intent.constraint_set_revision,
        approval.offer_ref == intent.offer_ref,
        approval.material_terms_hash == intent.material_terms_hash,
    )
    if not all(exact_bindings):
        reasons.append("approval_material_binding_mismatch")
    return reasons


def _request_binding(request: CapabilityExecutionRequest) -> str:
    payload = {
        "action_intent": request.action_intent.model_dump(mode="json"),
        "approval": (
            request.approval.model_dump(mode="json")
            if request.approval is not None
            else None
        ),
        "proposal": request.proposal.model_dump(mode="json"),
        "source_pins": request.source_pins.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sorted_terms(terms: tuple[MaterialTerm, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((term.name, term.value) for term in terms))


__all__ = [
    "CapabilityExecutionOutcome",
    "CapabilityExecutionRequest",
    "CapabilityExecutionStatus",
    "CapabilityExecutor",
    "TermsDerivation",
]
