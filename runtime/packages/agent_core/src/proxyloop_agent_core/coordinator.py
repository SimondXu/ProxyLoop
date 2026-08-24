"""Deep deterministic Case coordinator for Phase 03A1 evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID

from proxyloop_contracts import (
    CaseContextSnapshot,
    DialogueAct,
    FactStatus,
    FastModelView,
    FastTurnDecision,
    ModelInputPins,
    RoutingDecision,
    RoutingOutcome,
    SlowReasonerView,
    SlowWorkRequest,
    SlowWorkResult,
)

from .interfaces import (
    BOUNDED_FAST_STATUS_TEXT,
    FastAdapter,
    FastAdapterResult,
    SlowAdapter,
)
from .router import DeterministicRouter, RouteRequest


class CoordinatorStatus(StrEnum):
    ROUTED = "routed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAST_UNAVAILABLE = "fast_unavailable"
    SLOW_UNAVAILABLE = "slow_unavailable"


@dataclass(frozen=True, slots=True)
class ResultAudit:
    source: str
    accepted: bool
    reason_codes: tuple[str, ...]
    input_pins: ModelInputPins
    current_pins: ModelInputPins


@dataclass(frozen=True, slots=True)
class CoordinatorOutcome:
    route: RoutingDecision
    status: CoordinatorStatus
    fast_decision: FastTurnDecision | None = None
    slow_result: SlowWorkResult | None = None
    audits: tuple[ResultAudit, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotCommit:
    accepted: bool
    reason_codes: tuple[str, ...]
    snapshot: CaseContextSnapshot


class CaseCoordinator:
    """Advance one immutable snapshot through one deterministic route."""

    def __init__(
        self,
        router: DeterministicRouter | None = None,
        snapshot: CaseContextSnapshot | None = None,
    ) -> None:
        self._router = router or DeterministicRouter()
        self._lock = RLock()
        self._current_snapshot = snapshot

    @property
    def current_snapshot(self) -> CaseContextSnapshot | None:
        with self._lock:
            return self._current_snapshot

    def compare_and_swap(
        self,
        expected_pins: ModelInputPins,
        next_snapshot: CaseContextSnapshot,
    ) -> SnapshotCommit:
        """Commit one immutable next snapshot through the serialized write lane."""

        with self._lock:
            current = self._current_snapshot
            if current is None:
                return SnapshotCommit(
                    accepted=False,
                    reason_codes=("coordinator_snapshot_not_initialized",),
                    snapshot=next_snapshot,
                )
            reasons: list[str] = []
            if expected_pins != current.pins:
                reasons.append("snapshot_compare_and_swap_conflict")
            if next_snapshot.case.case_id != current.case.case_id:
                reasons.append("snapshot_case_mismatch")
            if next_snapshot.revision <= current.revision:
                reasons.append("snapshot_revision_not_advanced")
            if next_snapshot.event_cursor < current.event_cursor:
                reasons.append("snapshot_event_cursor_regressed")
            if reasons:
                return SnapshotCommit(
                    accepted=False,
                    reason_codes=tuple(reasons),
                    snapshot=current,
                )
            self._current_snapshot = next_snapshot
            return SnapshotCommit(
                accepted=True,
                reason_codes=("snapshot_committed",),
                snapshot=next_snapshot,
            )

    def advance(
        self,
        request: RouteRequest,
        *,
        fast: FastAdapter | None = None,
        slow: SlowAdapter | None = None,
    ) -> CoordinatorOutcome:
        with self._lock:
            current = self._current_snapshot
        if current is not None and request.snapshot.pins != current.pins:
            latest_request = replace(
                request,
                snapshot=current,
                triggering_event=None,
            )
            return CoordinatorOutcome(
                route=self._router.route(latest_request),
                status=CoordinatorStatus.REJECTED,
                audits=(
                    ResultAudit(
                        source="coordinator",
                        accepted=False,
                        reason_codes=("stale_route_request_rerouted_to_latest",),
                        input_pins=request.snapshot.pins,
                        current_pins=current.pins,
                    ),
                ),
            )
        route = self._router.route(request)
        if route.outcome in {
            RoutingOutcome.TERMINAL,
            RoutingOutcome.VERIFY_ONLY,
            RoutingOutcome.WAIT_FOR_APPROVAL,
        }:
            return CoordinatorOutcome(route=route, status=CoordinatorStatus.ROUTED)

        audits: list[ResultAudit] = []
        slow_result: SlowWorkResult | None = None
        fast_decision: FastTurnDecision | None = None

        if route.outcome in {
            RoutingOutcome.SLOW_REFRESH,
            RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        }:
            if slow is None:
                return CoordinatorOutcome(
                    route=route,
                    status=CoordinatorStatus.SLOW_UNAVAILABLE,
                )
            slow_request = self.build_slow_request(
                request.snapshot,
                reason_code=route.reason_codes[0],
                created_at=request.created_at,
            )
            slow_output = slow.reason(slow_request)
            audit = self.validate_slow_result(
                slow_output,
                request.snapshot,
                expected_request=slow_request,
                evaluated_at=request.created_at,
            )
            audits.append(audit)
            if audit.accepted:
                slow_result = slow_output

        if route.outcome in {
            RoutingOutcome.FAST_NOW,
            RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
        }:
            if fast is None:
                return CoordinatorOutcome(
                    route=route,
                    status=CoordinatorStatus.FAST_UNAVAILABLE,
                    slow_result=slow_result,
                    audits=tuple(audits),
                )
            fast_output = fast.decide(self.project_fast_view(request.snapshot))
            audit = self.validate_fast_result(
                fast_output,
                request.snapshot,
                bounded=route.outcome is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
            )
            audits.append(audit)
            if audit.accepted:
                fast_decision = fast_output.decision

        accepted = bool(fast_decision is not None or slow_result is not None)
        return CoordinatorOutcome(
            route=route,
            status=(
                CoordinatorStatus.ACCEPTED if accepted else CoordinatorStatus.REJECTED
            ),
            fast_decision=fast_decision,
            slow_result=slow_result,
            audits=tuple(audits),
        )

    @staticmethod
    def project_fast_view(snapshot: CaseContextSnapshot) -> FastModelView:
        verified_facts = tuple(
            fact
            for fact in snapshot.fact_ledger.entries
            if fact.status is FactStatus.VERIFIED
        )
        latest_provider = next(
            (
                event
                for event in reversed(snapshot.visible_events)
                if event.actor.value == "provider"
            ),
            None,
        )
        allowed_disclosures = (
            tuple(
                disclosure
                for disclosure in snapshot.strategy.allowed_disclosures
                if disclosure in snapshot.case.delegated_authority.allowed_disclosures
            )
            if snapshot.strategy is not None
            else ()
        )
        return FastModelView(
            contract_type="fast_model_view",
            schema_version="1.0",
            revision=1,
            case_id=snapshot.case.case_id,
            pins=snapshot.pins,
            planning_basis=snapshot.planning_basis,
            goal=snapshot.case.goal,
            constraints=snapshot.case.constraints,
            verified_facts=verified_facts,
            strategy=snapshot.strategy,
            recent_events=snapshot.visible_events[-8:],
            latest_provider_event=latest_provider,
            pending_slow_work=snapshot.pending_slow_work,
            allowed_dialogue_acts=tuple(DialogueAct),
            allowed_disclosures=allowed_disclosures,
        )

    @staticmethod
    def project_slow_view(
        snapshot: CaseContextSnapshot, *, reason_code: str
    ) -> SlowReasonerView:
        verified_facts = tuple(
            fact
            for fact in snapshot.fact_ledger.entries
            if fact.status is FactStatus.VERIFIED
        )
        return SlowReasonerView(
            contract_type="slow_reasoner_view",
            schema_version="1.0",
            revision=1,
            case_id=snapshot.case.case_id,
            pins=snapshot.pins,
            planning_basis=snapshot.planning_basis,
            goal=snapshot.case.goal,
            constraints=snapshot.case.constraints,
            delegated_authority=snapshot.case.delegated_authority,
            verified_facts=verified_facts,
            offers=snapshot.offers,
            approval_requests=snapshot.approval_requests,
            strategy=snapshot.strategy,
            recent_events=snapshot.visible_events,
            capability_manifest=snapshot.capability_manifest,
            provider_config_ref=snapshot.provider_config_ref,
            reason_code=reason_code,
        )

    @classmethod
    def build_slow_request(
        cls,
        snapshot: CaseContextSnapshot,
        *,
        reason_code: str,
        created_at: datetime,
    ) -> SlowWorkRequest:
        view = cls.project_slow_view(snapshot, reason_code=reason_code)
        request_id = _stable_uuid4(
            f"{snapshot.case.case_id}:{snapshot.event_cursor}:{reason_code}"
        )
        return SlowWorkRequest(
            contract_type="slow_work_request",
            schema_version="1.0",
            revision=1,
            request_id=request_id,
            case_id=snapshot.case.case_id,
            pins=snapshot.pins,
            planning_basis=snapshot.planning_basis,
            view=view,
            reason_code=reason_code,
            created_at=created_at,
        )

    @staticmethod
    def validate_fast_result(
        result: FastAdapterResult,
        current: CaseContextSnapshot,
        *,
        bounded: bool = False,
    ) -> ResultAudit:
        reasons: list[str] = []
        decision = result.decision
        if result.pins != current.pins:
            reasons.append("stale_fast_result")
        if decision.case_id != current.case.case_id:
            reasons.append("fast_case_mismatch")
        if decision.case_revision != current.case.revision:
            reasons.append("fast_case_revision_mismatch")
        if current.strategy is None or (
            decision.strategy_id != current.strategy.strategy_id
            or decision.strategy_revision != current.strategy.revision
        ):
            reasons.append("fast_strategy_mismatch")
        if decision.action_intent is not None:
            reasons.append("fast_action_intent_forbidden")
        visible_message_ids = {str(event.event_id) for event in current.visible_events}
        if any(
            update.source_message_id not in visible_message_ids
            for update in decision.fact_updates
        ):
            reasons.append("fact_provenance_not_visible")
        if current.visible_events and (
            decision.created_at < current.visible_events[-1].occurred_at
        ):
            reasons.append("fast_result_predates_latest_event")
        if bounded and (
            decision.dialogue_act is not DialogueAct.CLARIFY
            or decision.fact_updates
            or decision.completion_claim.status != "not_done"
            or decision.action_intent is not None
            or decision.response_text != BOUNDED_FAST_STATUS_TEXT
        ):
            reasons.append("bounded_fast_output_violation")
        return ResultAudit(
            source="fast",
            accepted=not reasons,
            reason_codes=tuple(reasons) or ("fast_result_current",),
            input_pins=result.pins,
            current_pins=current.pins,
        )

    @staticmethod
    def validate_slow_result(
        result: SlowWorkResult,
        current: CaseContextSnapshot,
        *,
        expected_request: SlowWorkRequest | None = None,
        evaluated_at: datetime | None = None,
    ) -> ResultAudit:
        reasons: list[str] = []
        if result.pins != current.pins:
            reasons.append("stale_slow_result")
        if (
            result.planning_basis.planning_basis_fingerprint
            != current.planning_basis.planning_basis_fingerprint
        ):
            reasons.append("planning_basis_fingerprint_mismatch")
        if result.case_id != current.case.case_id:
            reasons.append("slow_case_mismatch")
        if expected_request is not None:
            if result.request_id != expected_request.request_id:
                reasons.append("slow_request_mismatch")
            if result.created_at < expected_request.created_at:
                reasons.append("slow_result_predates_request")
        strategy = result.strategy_proposal
        evaluation_time = evaluated_at or result.created_at
        if strategy is not None:
            if strategy.case_id != current.case.case_id:
                reasons.append("slow_strategy_case_mismatch")
            if strategy.case_revision != current.case.revision:
                reasons.append("slow_strategy_case_revision_mismatch")
            if strategy.fact_ledger_revision != current.fact_ledger.revision:
                reasons.append("slow_strategy_fact_ledger_revision_mismatch")
            if expected_request is not None and (
                strategy.created_at < expected_request.created_at
            ):
                reasons.append("slow_strategy_predates_request")
            if strategy.expires_at <= evaluation_time:
                reasons.append("slow_strategy_expired")
        for action in result.action_proposals:
            if action.created_at < result.created_at:
                reasons.append("slow_action_predates_result")
            if action.expires_at is not None and action.expires_at <= evaluation_time:
                reasons.append("slow_action_expired")
        return ResultAudit(
            source="slow",
            accepted=not reasons,
            reason_codes=tuple(reasons) or ("slow_result_current",),
            input_pins=result.pins,
            current_pins=current.pins,
        )


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = [
    "CaseCoordinator",
    "CoordinatorOutcome",
    "CoordinatorStatus",
    "ResultAudit",
    "SnapshotCommit",
]
