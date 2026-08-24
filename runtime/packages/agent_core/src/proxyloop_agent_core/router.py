"""Deterministic Fast/Slow routing with frozen Phase 03A0 precedence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from proxyloop_contracts import (
    ApprovalDecision,
    ApprovalRequest,
    CaseContextSnapshot,
    CasePhase,
    CompletionOutcome,
    EventActor,
    RoutingDecision,
    RoutingOutcome,
    VisibleCaseEvent,
)
from proxyloop_contracts.contracts import ReasonerRequest

# Keep this literal table ordered so architecture drift is reviewable in one place.
ROUTER_PRECEDENCE = (
    "terminal",
    "verify_only",
    "wait_for_approval",
    "slow_refresh",
    "fast_now_and_slow_refresh",
    "fast_now",
)
ALLOWED_FAST_REASONER_REASONS = frozenset(
    {
        "completion_basis_missing",
        "conflicting_facts",
        "high_risk_action",
        "material_offer_changed",
        "new_material_evidence",
        "stalled_dialogue",
    }
)


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Current snapshot plus deterministic event classifications."""

    snapshot: CaseContextSnapshot
    created_at: datetime
    triggering_event: VisibleCaseEvent | None = None
    mandatory_slow_reason_codes: tuple[str, ...] = ()
    bounded_acknowledgement_allowed: bool = False

    def __post_init__(self) -> None:
        if self.triggering_event is not None and (
            not self.snapshot.visible_events
            or self.triggering_event != self.snapshot.visible_events[-1]
        ):
            raise ValueError(
                "triggering event must be the latest visible snapshot event"
            )

    @property
    def trigger_is_approval_decision(self) -> bool:
        event = self.triggering_event
        return (
            event is not None
            and event.actor is EventActor.CONSUMER
            and event.event_type == "approval_decision"
        )


class DeterministicRouter:
    """Select exactly one outcome by the frozen precedence table."""

    def route(self, request: RouteRequest) -> RoutingDecision:
        snapshot = request.snapshot
        outcome, reasons = self._select(request)
        return RoutingDecision(
            contract_type="routing_decision",
            schema_version="1.0",
            revision=1,
            outcome=outcome,
            reason_codes=reasons,
            pins=snapshot.pins,
            created_at=request.created_at,
        )

    def _select(self, request: RouteRequest) -> tuple[RoutingOutcome, tuple[str, ...]]:
        snapshot = request.snapshot
        completion = snapshot.completion_decision

        if snapshot.case.phase is CasePhase.CLOSED or (
            completion is not None and completion.decision is CompletionOutcome.COMPLETE
        ):
            return RoutingOutcome.TERMINAL, ("verified_terminal",)

        if (
            snapshot.pending_execution
            or snapshot.case.phase is CasePhase.COMPLETE
            or (
                completion is not None
                and completion.decision is CompletionOutcome.CANDIDATE_COMPLETE
            )
        ):
            return RoutingOutcome.VERIFY_ONLY, ("verification_pending",)

        pending_approvals = tuple(
            approval
            for approval in snapshot.approval_requests
            if approval.decision is ApprovalDecision.PENDING
        )
        approval_blocking = any(
            _approval_is_current(snapshot, approval, request.created_at)
            for approval in pending_approvals
        )
        if approval_blocking and not request.trigger_is_approval_decision:
            return RoutingOutcome.WAIT_FOR_APPROVAL, ("current_approval_pending",)

        mandatory_reasons = self._mandatory_slow_reasons(request)
        current_strategy_allows_fast = (
            snapshot.strategy is not None
            and snapshot.strategy.expires_at > request.created_at
        )
        if mandatory_reasons and (
            not request.bounded_acknowledgement_allowed
            or not current_strategy_allows_fast
        ):
            return RoutingOutcome.SLOW_REFRESH, mandatory_reasons
        if mandatory_reasons:
            return RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH, mandatory_reasons

        return RoutingOutcome.FAST_NOW, ("current_strategy_dialogue",)

    @staticmethod
    def _mandatory_slow_reasons(request: RouteRequest) -> tuple[str, ...]:
        snapshot = request.snapshot
        reasons = list(request.mandatory_slow_reason_codes)
        if any(
            approval.decision is ApprovalDecision.PENDING
            and not _approval_is_current(snapshot, approval, request.created_at)
            for approval in snapshot.approval_requests
        ):
            reasons.append("stale_approval")
        if snapshot.strategy is None:
            reasons.append("case_initialization")
        elif snapshot.strategy.expires_at <= request.created_at:
            reasons.append("strategy_expired")
        if snapshot.pending_slow_work:
            reasons.append("slow_work_pending")
        return tuple(dict.fromkeys(reasons))


def _approval_is_current(
    snapshot: CaseContextSnapshot,
    approval: ApprovalRequest,
    created_at: datetime,
) -> bool:
    strategy = snapshot.strategy
    offer_ref = approval.offer_ref
    offer_current = offer_ref is None or any(
        offer.offer_id == offer_ref.offer_id
        and offer.revision == offer_ref.offer_revision
        for offer in snapshot.offers
    )
    return (
        approval.case_id == snapshot.case.case_id
        and approval.case_revision == snapshot.case.revision
        and approval.constraint_set_revision == snapshot.case.constraint_set_revision
        and approval.expires_at > created_at
        and strategy is not None
        and approval.strategy_id == strategy.strategy_id
        and approval.strategy_revision == strategy.revision
        and offer_current
    )


def accepted_fast_reasoner_trigger(request: ReasonerRequest) -> tuple[str, ...]:
    """Treat Fast escalation as advisory input to a closed Router policy."""

    if not request.needed or request.reason_code not in ALLOWED_FAST_REASONER_REASONS:
        return ()
    return (f"fast_reasoner_request:{request.reason_code}",)


__all__ = [
    "ALLOWED_FAST_REASONER_REASONS",
    "ROUTER_PRECEDENCE",
    "DeterministicRouter",
    "RouteRequest",
    "accepted_fast_reasoner_trigger",
]
