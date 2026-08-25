"""The local, simulator-backed Thin Agent Runtime vertical slice."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import UUID

from proxyloop_agent_core import (
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    CoordinatorStatus,
    FastAdapter,
    PreparedSimulatorExecution,
    RouteRequest,
    ScriptedFastAdapter,
    ScriptedSlowAdapter,
    SlowAdapter,
)
from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityArgument,
    CapabilityDefinition,
    CapabilityManifest,
    CapabilityProposal,
    CapabilityReference,
    Case,
    CaseContextSnapshot,
    CasePhase,
    CompletionDecision,
    CompletionOutcome,
    EventActor,
    Evidence,
    EvidenceType,
    FactLedger,
    FactStatus,
    FastTurnDecision,
    ModelInputPins,
    OfferReference,
    PlanningBasis,
    ProviderOffer,
    RoutingDecision,
    StrategyPacket,
    VisibleCaseEvent,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.provider import FictionalMobileProvider
from proxyloop_telecom_domain import (
    CompletionVerification,
    OfferComplianceContext,
    OfferComplianceTerms,
    material_terms_hash,
    offer_compliance_violations,
    offer_material_terms,
    verify_completion,
)

from .repository import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRepository,
    CaseRuntimeState,
    InMemoryCaseRepository,
)

RuntimeDecision = Literal["approved", "rejected"]
RUNTIME_PROVIDER_CONFIG = "pine-mobile:runtime-v1"
RUNTIME_MANIFEST_VERSION = "phase-04a-runtime-v1"


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    snapshot: CaseContextSnapshot
    route: RoutingDecision | str
    fast_decision: FastTurnDecision | None = None
    approval: ApprovalRequest | None = None
    evidence: tuple[Evidence, ...] = ()
    execution_count: int = 0


class ModelRuntimeError(RuntimeError):
    """A model proposal was rejected before deterministic policy could act."""

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(f"{source} model result was rejected safely")


class _PreparedProviderExecution:
    def __init__(
        self,
        provider: FictionalMobileProvider,
        approval: ApprovalRequest,
        executed_at: datetime,
        evidence: Evidence,
    ) -> None:
        self._provider = provider
        self._approval = approval
        self._executed_at = executed_at
        self._evidence = evidence

    @property
    def evidence(self) -> Evidence:
        return self._evidence

    def commit(self) -> None:
        self._provider.execute_approved_offer(
            self._approval,
            executed_at=self._executed_at,
        )


class _ProviderCapabilityAdapter:
    """Prepare executor Evidence, committing the Provider only on ``commit``."""

    def __init__(
        self,
        provider: FictionalMobileProvider,
        approval: ApprovalRequest,
        executed_at: datetime,
    ) -> None:
        self._provider = provider
        self._approval = approval
        self._executed_at = executed_at

    def prepare(
        self,
        proposal: CapabilityProposal,
        *,
        idempotency_key: str,
    ) -> PreparedSimulatorExecution:
        del proposal
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=_stable_uuid(f"executor-evidence:{idempotency_key}"),
            case_id=self._approval.case_id,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            observed_at=self._executed_at,
            captured_at=self._executed_at,
            media_type="application/json",
        )
        prepared = _PreparedProviderExecution(
            self._provider,
            self._approval,
            self._executed_at,
            evidence,
        )
        return PreparedSimulatorExecution(
            evidence=prepared.evidence,
            commit=prepared.commit,
        )


class ThinAgentRuntime:
    """Compose deterministic routing, adapters, policy, execution and evidence."""

    def __init__(
        self,
        repository: CaseRepository | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        fast: FastAdapter | None = None,
        slow: SlowAdapter | None = None,
    ) -> None:
        self.repository = (
            repository if repository is not None else InMemoryCaseRepository()
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._slow = slow if slow is not None else ScriptedSlowAdapter()
        self._fast = fast if fast is not None else ScriptedFastAdapter()
        self._lanes_lock = RLock()
        self._lanes: dict[UUID, RLock] = {}
        self._executors: dict[UUID, CapabilityExecutor] = {}

    def create_case(self) -> RuntimeResult:
        created_at = self._clock_now()
        episode = Phase01AEpisode.success()
        case = _case_at(episode.case, created_at)
        provider = FictionalMobileProvider()
        offer, offer_evidence = provider.issue_offer(
            case,
            issued_at=created_at,
        )
        provider_event = _event(
            case.case_id,
            cursor=1,
            occurred_at=created_at,
            event_type="provider_offer",
            content="A fictional Provider offer is available.",
            seed="offer",
        )
        snapshot = _snapshot(
            case=case,
            ledger=_ledger(case.case_id, created_at),
            strategy=None,
            offers=(offer,),
            action_intents=(),
            approvals=(),
            evidence=(offer_evidence,),
            completion=None,
            events=(provider_event,),
            snapshot_revision=1,
            phase=CasePhase.INITIATED,
            manifest=_manifest(created_at),
        )
        state = CaseRuntimeState(
            snapshot=snapshot,
            events=(provider_event,),
            provider=provider,
        )
        outcome = CaseCoordinator(snapshot=snapshot).advance(
            RouteRequest(
                snapshot=snapshot,
                created_at=provider_event.occurred_at,
                triggering_event=provider_event,
                bounded_acknowledgement_allowed=True,
            ),
            slow=self._slow,
        )
        if (
            outcome.status is not CoordinatorStatus.ACCEPTED
            or outcome.slow_result is None
            or outcome.slow_result.strategy_proposal is None
        ):
            raise ModelRuntimeError("slow")
        strategy_snapshot = _snapshot(
            case=case,
            ledger=snapshot.fact_ledger,
            strategy=outcome.slow_result.strategy_proposal,
            offers=snapshot.offers,
            action_intents=(),
            approvals=(),
            evidence=snapshot.evidence,
            completion=None,
            events=(provider_event,),
            snapshot_revision=2,
            phase=CasePhase.STRATEGY,
            manifest=snapshot.capability_manifest,
        )
        self.repository.create(
            CaseRuntimeState(
                snapshot=strategy_snapshot,
                events=(provider_event,),
                provider=state.provider,
            )
        )
        return RuntimeResult(
            snapshot=strategy_snapshot,
            route=outcome.route,
            execution_count=0,
        )

    def append_event(
        self,
        case_id: UUID,
        *,
        content: str,
        event_type: str = "consumer_message",
        expected_revision: int | None = None,
    ) -> RuntimeResult:
        with self._lane(case_id):
            return self._append_event_serialized(
                case_id,
                content=content,
                event_type=event_type,
                expected_revision=expected_revision,
            )

    def _append_event_serialized(
        self,
        case_id: UUID,
        *,
        content: str,
        event_type: str,
        expected_revision: int | None,
    ) -> RuntimeResult:
        state = self._require(case_id)
        snapshot = state.snapshot
        _check_expected_revision(snapshot, expected_revision)
        if snapshot.completion_decision is not None or snapshot.case.phase in {
            CasePhase.COMPLETE,
            CasePhase.CLOSED,
        }:
            raise CaseConflictError("case is terminal")
        if snapshot.pending_execution:
            raise CaseConflictError("case execution is pending")
        if any(
            approval.decision is ApprovalDecision.PENDING
            for approval in snapshot.approval_requests
        ):
            raise CaseConflictError("case is awaiting approval")
        if any(
            approval.decision is not ApprovalDecision.PENDING
            for approval in snapshot.approval_requests
        ):
            raise CaseConflictError("case approval is terminal")
        occurred_at = self._event_time(snapshot)
        event = _event(
            case_id,
            cursor=snapshot.event_cursor + 1,
            occurred_at=occurred_at,
            event_type=event_type,
            content=content,
            seed=f"{snapshot.event_cursor + 1}:{event_type}:{content}",
        )
        event_snapshot = _snapshot(
            case=snapshot.case,
            ledger=snapshot.fact_ledger,
            strategy=snapshot.strategy,
            offers=snapshot.offers,
            action_intents=snapshot.action_intents,
            approvals=snapshot.approval_requests,
            evidence=snapshot.evidence,
            completion=None,
            events=(*snapshot.visible_events, event),
            snapshot_revision=snapshot.revision + 1,
            phase=snapshot.case.phase,
            manifest=snapshot.capability_manifest,
        )
        outcome = CaseCoordinator(snapshot=event_snapshot).advance(
            RouteRequest(
                snapshot=event_snapshot,
                created_at=occurred_at,
                triggering_event=event,
            ),
            fast=self._fast,
        )
        if (
            outcome.status is not CoordinatorStatus.ACCEPTED
            or outcome.fast_decision is None
        ):
            raise ModelRuntimeError("fast")
        policy_snapshot = event_snapshot
        approval: ApprovalRequest | None = None
        if event_snapshot.offers and not offer_compliance_violations_for_case(
            event_snapshot.case,
            event_snapshot.offers[0],
            evaluated_at=occurred_at,
        ):
            intent, approval = _build_approval(
                event_snapshot.case,
                event_snapshot.strategy,
                event_snapshot.offers[0],
                requested_at=occurred_at,
            )
            policy_snapshot = _snapshot(
                case=event_snapshot.case,
                ledger=event_snapshot.fact_ledger,
                strategy=event_snapshot.strategy,
                offers=event_snapshot.offers,
                action_intents=(intent,),
                approvals=(approval,),
                evidence=event_snapshot.evidence,
                completion=None,
                events=event_snapshot.visible_events,
                snapshot_revision=event_snapshot.revision + 1,
                phase=CasePhase.AWAITING_APPROVAL,
                manifest=event_snapshot.capability_manifest,
            )
        route = (
            CaseCoordinator(snapshot=policy_snapshot)
            .advance(
                RouteRequest(
                    snapshot=policy_snapshot,
                    created_at=occurred_at,
                    triggering_event=event,
                )
            )
            .route
        )
        updated = CaseRuntimeState(
            snapshot=policy_snapshot,
            events=(*state.events, event),
            provider=state.provider,
            execution_count=state.execution_count,
            execution_source_pins=state.execution_source_pins,
        )
        if approval is not None:
            # Persist the pending approval before changing Provider state.  A
            # failed CAS therefore cannot leave the Provider in a new state.
            self.repository.replace(
                case_id,
                expected_revision=snapshot.revision,
                state=updated,
            )
            try:
                state.provider.await_approval(
                    _intent_for_approval(policy_snapshot, approval)
                )
            except Exception:
                self.repository.replace(
                    case_id,
                    expected_revision=policy_snapshot.revision,
                    state=state,
                )
                raise
        else:
            self.repository.replace(
                case_id,
                expected_revision=snapshot.revision,
                state=updated,
            )
        return RuntimeResult(
            snapshot=policy_snapshot,
            route=route,
            fast_decision=outcome.fast_decision,
            approval=approval,
            execution_count=updated.execution_count,
        )

    def approve(
        self,
        case_id: UUID,
        approval_id: UUID,
        *,
        decision: RuntimeDecision = "approved",
        expected_revision: int | None = None,
        expected_case_revision: int | None = None,
        expected_action_intent_revision: int | None = None,
    ) -> RuntimeResult:
        with self._lane(case_id):
            return self._approve_serialized(
                case_id,
                approval_id,
                decision=decision,
                expected_revision=expected_revision,
                expected_case_revision=expected_case_revision,
                expected_action_intent_revision=expected_action_intent_revision,
            )

    def _approve_serialized(
        self,
        case_id: UUID,
        approval_id: UUID,
        *,
        decision: RuntimeDecision,
        expected_revision: int | None,
        expected_case_revision: int | None,
        expected_action_intent_revision: int | None,
    ) -> RuntimeResult:
        state = self._require(case_id)
        snapshot = state.snapshot
        _check_expected_revision(snapshot, expected_revision)
        approval = next(
            (
                item
                for item in snapshot.approval_requests
                if item.approval_id == approval_id
            ),
            None,
        )
        if approval is None:
            raise CaseNotFoundError("approval not found")
        if expected_case_revision is not None and (
            expected_case_revision != approval.case_revision
        ):
            raise CaseConflictError("approval case revision is stale")
        if expected_action_intent_revision is not None and (
            expected_action_intent_revision != approval.action_intent_revision
        ):
            raise CaseConflictError("approval action revision is stale")
        if approval.decision is ApprovalDecision.APPROVED:
            if decision != "approved":
                raise CaseConflictError("approval is already terminal")
            now = self._clock_now()
            if snapshot.pending_execution:
                return self._execute_claim(state, evaluated_at=now)
            return self._repeat_approved(state, approval)
        if approval.decision is not ApprovalDecision.PENDING:
            self._clock_now()
            raise CaseConflictError("approval is already terminal")
        decided_at = self._approval_time(snapshot)
        offer = _offer_for_approval(snapshot, approval)
        if decided_at >= approval.expires_at or decided_at >= offer.expires_at:
            raise CaseConflictError("approval expired")
        if decision == "rejected":
            return self._record_rejection(state, approval, decided_at)
        decided = approval.model_copy(
            update={
                "revision": approval.revision + 1,
                "decision": ApprovalDecision.APPROVED,
                "decided_at": decided_at,
            }
        )
        event = _event(
            case_id,
            cursor=snapshot.event_cursor + 1,
            occurred_at=decided_at,
            event_type="approval_decision",
            content="The Consumer approved the exact proposed offer.",
            seed=f"approval:{approval.approval_id}:approved",
        )
        pre_execution = _snapshot(
            case=snapshot.case,
            ledger=snapshot.fact_ledger,
            strategy=snapshot.strategy,
            offers=snapshot.offers,
            action_intents=snapshot.action_intents,
            approvals=(decided,),
            evidence=snapshot.evidence,
            completion=None,
            events=(*snapshot.visible_events, event),
            snapshot_revision=snapshot.revision + 1,
            phase=CasePhase.NEGOTIATING,
            manifest=snapshot.capability_manifest,
            pending_execution=True,
        )
        offer = _offer_for_approval(pre_execution, decided)
        intent = _intent_for_approval(pre_execution, decided)
        proposal = _capability_proposal(offer, created_at=decided_at)
        claim_state = CaseRuntimeState(
            snapshot=pre_execution,
            events=(*state.events, event),
            provider=state.provider,
            execution_count=state.execution_count,
            execution_source_pins=pre_execution.pins,
            execution_intent=intent,
            execution_approval=decided,
            execution_proposal=proposal,
        )
        self.repository.replace(
            case_id,
            expected_revision=snapshot.revision,
            state=claim_state,
        )
        return self._execute_claim(claim_state, evaluated_at=decided_at)

    def _execute_claim(
        self,
        state: CaseRuntimeState,
        *,
        evaluated_at: datetime,
    ) -> RuntimeResult:
        snapshot = state.snapshot
        case_id = snapshot.case.case_id
        approval = state.execution_approval or next(
            item
            for item in snapshot.approval_requests
            if item.decision is ApprovalDecision.APPROVED
        )
        intent = state.execution_intent or _intent_for_approval(snapshot, approval)
        offer = _offer_for_approval(snapshot, approval)
        proposal = state.execution_proposal or _capability_proposal(
            offer,
            created_at=approval.decided_at or evaluated_at,
        )
        adapter = _ProviderCapabilityAdapter(
            state.provider,
            approval,
            approval.decided_at or evaluated_at,
        )
        executor = self._executors.setdefault(
            case_id,
            CapabilityExecutor(adapter),
        )
        execution = executor.execute(
            CapabilityExecutionRequest(
                snapshot=snapshot,
                source_pins=state.execution_source_pins or snapshot.pins,
                proposal=proposal,
                action_intent=intent,
                approval=approval,
                executed_at=approval.decided_at or evaluated_at,
            )
        )
        if execution.status not in {
            CapabilityExecutionStatus.EXECUTED,
            CapabilityExecutionStatus.REUSED,
        }:
            raise CaseConflictError("deterministic capability execution was rejected")
        if execution.evidence is None:
            raise RuntimeError("executor returned no Evidence after execution")
        confirmation = state.provider.confirmation
        confirmation_evidence = state.provider.confirmation_evidence
        if confirmation is None or confirmation_evidence is None:
            raise RuntimeError("Provider commit returned no confirmation Evidence")
        completion = verify_completion(
            CompletionVerification(
                completion_id=_stable_uuid(f"completion:{case_id}"),
                case=snapshot.case,
                offer=offer,
                action_intent=intent,
                approval_request=approval,
                confirmation=confirmation,
                evidence=confirmation_evidence,
                confirmation_authority=state.provider,
                executed_at=confirmation.confirmed_at,
                evaluated_at=evaluated_at,
            )
        )
        final_phase = (
            CasePhase.COMPLETE
            if completion.decision is CompletionOutcome.COMPLETE
            else CasePhase.CANDIDATE_COMPLETE
        )
        final_snapshot = _snapshot(
            case=snapshot.case,
            ledger=snapshot.fact_ledger,
            strategy=snapshot.strategy,
            offers=snapshot.offers,
            action_intents=snapshot.action_intents,
            approvals=(approval,),
            evidence=(
                *snapshot.evidence,
                execution.evidence,
                confirmation_evidence,
            ),
            completion=completion,
            events=snapshot.visible_events,
            snapshot_revision=snapshot.revision + 1,
            phase=final_phase,
            manifest=snapshot.capability_manifest,
            pending_execution=False,
        )
        final_state = CaseRuntimeState(
            snapshot=final_snapshot,
            events=state.events,
            provider=state.provider,
            execution_count=max(state.execution_count, 1),
            execution_source_pins=state.execution_source_pins,
            execution_intent=intent,
            execution_approval=approval,
            execution_proposal=proposal,
        )
        self.repository.replace(
            case_id,
            expected_revision=snapshot.revision,
            state=final_state,
        )
        return RuntimeResult(
            snapshot=final_snapshot,
            route=CaseCoordinator(snapshot=final_snapshot)
            .advance(RouteRequest(snapshot=final_snapshot, created_at=evaluated_at))
            .route,
            approval=approval,
            evidence=(execution.evidence, confirmation_evidence),
            execution_count=final_state.execution_count,
        )

    def _record_rejection(
        self,
        state: CaseRuntimeState,
        approval: ApprovalRequest,
        decided_at: datetime,
    ) -> RuntimeResult:
        decided = approval.model_copy(
            update={
                "revision": approval.revision + 1,
                "decision": ApprovalDecision.REJECTED,
                "decided_at": decided_at,
            }
        )
        event = _event(
            state.snapshot.case.case_id,
            cursor=state.snapshot.event_cursor + 1,
            occurred_at=decided_at,
            event_type="approval_decision",
            content="The Consumer rejected the exact proposed offer.",
            seed=f"approval:{approval.approval_id}:rejected",
        )
        snapshot = _snapshot(
            case=state.snapshot.case,
            ledger=state.snapshot.fact_ledger,
            strategy=state.snapshot.strategy,
            offers=state.snapshot.offers,
            action_intents=state.snapshot.action_intents,
            approvals=(decided,),
            evidence=state.snapshot.evidence,
            completion=None,
            events=(*state.snapshot.visible_events, event),
            snapshot_revision=state.snapshot.revision + 1,
            phase=CasePhase.NEGOTIATING,
            manifest=state.snapshot.capability_manifest,
        )
        updated = CaseRuntimeState(
            snapshot=snapshot,
            events=(*state.events, event),
            provider=state.provider,
            execution_count=state.execution_count,
        )
        self.repository.replace(
            state.snapshot.case.case_id,
            expected_revision=state.snapshot.revision,
            state=updated,
        )
        return RuntimeResult(snapshot=snapshot, route="fast_now")

    def _repeat_approved(
        self,
        state: CaseRuntimeState,
        approval: ApprovalRequest,
    ) -> RuntimeResult:
        if state.snapshot.completion_decision is not None:
            executor = self._executors.get(state.snapshot.case.case_id)
            if executor is not None and state.execution_source_pins is not None:
                if approval.decided_at is None:
                    raise CaseConflictError(
                        "approved continuation has no decision time"
                    )
                offer = _offer_for_approval(state.snapshot, approval)
                intent = _intent_for_approval(state.snapshot, approval)
                reused = executor.execute(
                    CapabilityExecutionRequest(
                        snapshot=state.snapshot,
                        source_pins=state.execution_source_pins,
                        proposal=_capability_proposal(
                            offer,
                            created_at=approval.decided_at,
                        ),
                        action_intent=intent,
                        approval=approval,
                        executed_at=approval.decided_at,
                    )
                )
                if reused.status is not CapabilityExecutionStatus.REUSED:
                    raise CaseConflictError(
                        "approved continuation lost idempotency state"
                    )
            return RuntimeResult(
                snapshot=state.snapshot,
                route="terminal",
                approval=approval,
                evidence=tuple(
                    evidence
                    for evidence in state.snapshot.evidence
                    if evidence.source_type
                    in {EvidenceType.SIMULATOR_TRANSITION, EvidenceType.CONFIRMATION}
                ),
                execution_count=state.execution_count,
            )
        raise CaseConflictError("approved continuation has no terminal completion")

    def _clock_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return a timezone-aware UTC datetime")
        return now

    def _event_time(self, snapshot: CaseContextSnapshot) -> datetime:
        now = self._clock_now()
        latest = snapshot.visible_events[-1].occurred_at
        if now <= latest:
            raise CaseConflictError("clock time must advance event time")
        return now

    def _approval_time(self, snapshot: CaseContextSnapshot) -> datetime:
        return self._event_time(snapshot)

    def _lane(self, case_id: UUID) -> RLock:
        with self._lanes_lock:
            return self._lanes.setdefault(case_id, RLock())

    def _require(self, case_id: UUID) -> CaseRuntimeState:
        state = self.repository.get(case_id)
        if state is None:
            raise CaseNotFoundError("case not found")
        return state


def offer_compliance_violations_for_case(
    case: Case,
    offer: ProviderOffer,
    *,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    bill = case.bill_snapshot
    target = case.goal.target_monthly_total
    if bill is None:
        return ("missing_bill_snapshot",)
    context = OfferComplianceContext(
        evaluated_at=evaluated_at,
        current_monthly_minor=bill.monthly_total.amount_minor,
        currency=bill.monthly_total.currency,
        target_monthly_minor=target.amount_minor if target is not None else None,
        target_currency=target.currency if target is not None else None,
        required_features=case.goal.required_features,
        forbidden_changes=case.goal.forbidden_changes,
    )
    terms = OfferComplianceTerms(
        monthly_price_minor=offer.monthly_price.amount_minor,
        total_cost_12_months_minor=offer.total_cost.amount_minor,
        currency=offer.monthly_price.currency,
        fees_minor=sum(item.amount.amount_minor for item in offer.fees),
        features=offer.features,
        applied_changes=(),
        expires_at=offer.expires_at,
    )
    return offer_compliance_violations(context, terms)


def _build_approval(
    case: Case,
    strategy: StrategyPacket | None,
    offer: ProviderOffer,
    *,
    requested_at: datetime,
) -> tuple[ActionIntent, ApprovalRequest]:
    if strategy is None:
        raise RuntimeError("a strategy is required before an approval")
    terms = offer_material_terms(offer)
    intent = ActionIntent(
        contract_type="action_intent",
        schema_version="1.0",
        revision=1,
        intent_id=_stable_uuid(f"intent:{case.case_id}:{offer.offer_id}"),
        case_id=case.case_id,
        case_revision=case.revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        constraint_set_revision=case.constraint_set_revision,
        action_type=ActionType.ACCEPT_OFFER,
        offer_ref=OfferReference(
            offer_id=offer.offer_id,
            offer_revision=offer.revision,
        ),
        material_terms=terms,
        material_terms_hash=material_terms_hash(terms),
        approval_required=True,
        idempotency_key=f"phase-04a:{case.case_id}:accept-offer",
        created_at=requested_at,
        expires_at=offer.expires_at,
    )
    approval = ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=1,
        approval_id=_stable_uuid(f"approval:{intent.intent_id}"),
        case_id=case.case_id,
        case_revision=case.revision,
        action_intent_id=intent.intent_id,
        action_intent_revision=intent.revision,
        action_type=intent.action_type,
        strategy_id=intent.strategy_id,
        strategy_revision=intent.strategy_revision,
        constraint_set_revision=intent.constraint_set_revision,
        offer_ref=intent.offer_ref,
        material_terms_hash=intent.material_terms_hash,
        requested_at=requested_at,
        expires_at=offer.expires_at,
    )
    return intent, approval


def _intent_for_approval(
    snapshot: CaseContextSnapshot,
    approval: ApprovalRequest,
) -> ActionIntent:
    return next(
        intent
        for intent in snapshot.action_intents
        if intent.intent_id == approval.action_intent_id
    )


def _offer_for_approval(
    snapshot: CaseContextSnapshot,
    approval: ApprovalRequest,
) -> ProviderOffer:
    if approval.offer_ref is None:
        raise RuntimeError("approval has no offer reference")
    return next(
        offer
        for offer in snapshot.offers
        if offer.offer_id == approval.offer_ref.offer_id
        and offer.revision == approval.offer_ref.offer_revision
    )


def _capability_proposal(
    offer: ProviderOffer,
    *,
    created_at: datetime,
) -> CapabilityProposal:
    return CapabilityProposal(
        proposal_id=_stable_uuid(f"proposal:{offer.offer_id}"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_fictional_offer",
            version="1.0",
        ),
        arguments=(CapabilityArgument(name="offer_id", value=str(offer.offer_id)),),
        created_at=created_at,
        expires_at=offer.expires_at,
    )


def _snapshot(
    *,
    case: Case,
    ledger: FactLedger,
    strategy: StrategyPacket | None,
    offers: tuple[ProviderOffer, ...],
    action_intents: tuple[ActionIntent, ...],
    approvals: tuple[ApprovalRequest, ...],
    evidence: tuple[Evidence, ...],
    completion: CompletionDecision | None,
    events: tuple[VisibleCaseEvent, ...],
    snapshot_revision: int,
    phase: CasePhase,
    manifest: CapabilityManifest | None = None,
    pending_execution: bool = False,
) -> CaseContextSnapshot:
    effective_case = case.model_copy(update={"phase": phase})
    effective_manifest = manifest or _manifest(case.created_at)
    basis = _basis(
        effective_case,
        ledger,
        offers,
        approvals,
        effective_manifest,
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=effective_case.case_id,
        case_revision=effective_case.revision,
        constraint_set_revision=effective_case.constraint_set_revision,
        fact_ledger_revision=ledger.revision,
        strategy_id=strategy.strategy_id if strategy is not None else None,
        strategy_revision=strategy.revision if strategy is not None else 0,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=events[-1].event_cursor if events else 0,
        provider_config_ref=RUNTIME_PROVIDER_CONFIG,
        capability_manifest_version=effective_manifest.manifest_version,
    )
    return CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=snapshot_revision,
        case=effective_case,
        fact_ledger=ledger,
        strategy=strategy,
        offers=offers,
        action_intents=action_intents,
        approval_requests=approvals,
        evidence=evidence,
        completion_decision=completion,
        visible_events=events,
        event_cursor=pins.event_cursor,
        planning_basis=basis,
        pins=pins,
        provider_config_ref=RUNTIME_PROVIDER_CONFIG,
        capability_manifest=effective_manifest,
        pending_execution=pending_execution,
    )


def _case_at(case: Case, created_at: datetime) -> Case:
    goal = case.goal.model_copy(
        update={
            "created_at": created_at,
            "updated_at": created_at,
            "deadline": created_at + timedelta(days=9),
        }
    )
    constraints = tuple(
        constraint.model_copy(update={"valid_from": created_at})
        for constraint in case.constraints
    )
    bill = (
        case.bill_snapshot.model_copy(update={"captured_at": created_at})
        if case.bill_snapshot is not None
        else None
    )
    return case.model_copy(
        update={
            "created_at": created_at,
            "updated_at": created_at,
            "goal": goal,
            "constraints": constraints,
            "bill_snapshot": bill,
        }
    )


def _ledger(case_id: UUID, created_at: datetime) -> FactLedger:
    return FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=_stable_uuid(f"ledger:{case_id}"),
        case_id=case_id,
        created_at=created_at,
        updated_at=created_at,
        entries=(),
    )


def _manifest(issued_at: datetime) -> CapabilityManifest:
    return CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version=RUNTIME_MANIFEST_VERSION,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(days=1),
        capabilities=(
            CapabilityDefinition(
                capability_id="simulator.accept_fictional_offer",
                version="1.0",
                description="Accept one current fictional Provider offer.",
                allowed_action_types=(ActionType.ACCEPT_OFFER,),
                expires_at=issued_at + timedelta(days=1),
            ),
        ),
    )


def _basis(
    case: Case,
    ledger: FactLedger,
    offers: tuple[ProviderOffer, ...],
    approvals: tuple[ApprovalRequest, ...],
    manifest: CapabilityManifest,
) -> PlanningBasis:
    components = {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(
            tuple(sorted(case.constraints, key=lambda item: str(item.constraint_id)))
        ),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(
            tuple(
                sorted(
                    (
                        item
                        for item in ledger.entries
                        if item.status is FactStatus.VERIFIED
                    ),
                    key=lambda item: str(item.fact_id),
                )
            )
        ),
        "material_offers_fingerprint": canonical_fingerprint(
            tuple(sorted(offers, key=lambda item: str(item.offer_id)))
        ),
        "approval_state_fingerprint": canonical_fingerprint(
            tuple(sorted(approvals, key=lambda item: str(item.approval_id)))
        ),
        "provider_config_fingerprint": canonical_fingerprint(RUNTIME_PROVIDER_CONFIG),
        "capability_manifest_fingerprint": canonical_fingerprint(manifest),
    }
    return PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )


def _event(
    case_id: UUID,
    *,
    cursor: int,
    occurred_at: datetime,
    event_type: str,
    content: str,
    seed: str,
) -> VisibleCaseEvent:
    return VisibleCaseEvent(
        contract_type="visible_case_event",
        schema_version="1.0",
        revision=1,
        event_id=_stable_uuid(f"{case_id}:event:{seed}"),
        case_id=case_id,
        event_cursor=cursor,
        occurred_at=occurred_at,
        actor=EventActor.CONSUMER
        if event_type.startswith("consumer") or event_type.startswith("approval")
        else EventActor.PROVIDER,
        event_type=event_type,
        content=content,
    )


def _stable_uuid(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _check_expected_revision(
    snapshot: CaseContextSnapshot,
    expected_revision: int | None,
) -> None:
    if expected_revision is not None and expected_revision != snapshot.revision:
        raise CaseConflictError("case snapshot revision is stale")


__all__ = [
    "CaseConflictError",
    "CaseNotFoundError",
    "ModelRuntimeError",
    "RuntimeResult",
    "ThinAgentRuntime",
    "offer_compliance_violations_for_case",
]
