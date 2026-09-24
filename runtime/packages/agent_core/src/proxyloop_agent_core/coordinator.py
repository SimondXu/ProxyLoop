"""Deep deterministic Case coordinator for Phase 03A1 evaluation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Literal, TypeVar
from uuid import UUID

from proxyloop_contracts import (
    CaseContextSnapshot,
    DialogueAct,
    FactStatus,
    FastModelView,
    FastTurnDecision,
    ModelInputPins,
    ModelResult,
    ModelTrace,
    RoutingDecision,
    RoutingOutcome,
    SlowReasonerView,
    SlowWorkRequest,
    SlowWorkResult,
    canonical_fingerprint,
)

from .disclosure_gate import FastGate
from .fast_observation import ObservationRefusal, fast_public_observation
from .interfaces import (
    BOUNDED_FAST_STATUS_TEXT,
    FastAdapter,
    FastAdapterFailure,
    FastAdapterResult,
    IdentifiedAdapter,
    ModelCallUsage,
    ModelIdentity,
    ObservingFastAdapter,
    SlowAdapter,
    UsageReportingFastAdapter,
    UsageReportingSlowAdapter,
)
from .router import DeterministicRouter, RouteRequest

_T = TypeVar("_T")
_EXTERNAL_REF_MAX = 256  # the ModelTrace identity fields are ExternalRef


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
    # One 1.1 ModelTrace per adapter call on a 1.1 snapshot, in call order.
    traces: tuple[ModelTrace, ...] = ()
    # The Fast output was validated, then withheld by the disclosure gate.
    fast_disclosure_rejected: bool = False
    # The Fast call raised a captured ``FastAdapterFailure`` (no decision).
    fast_failed: bool = False


@dataclass(frozen=True, slots=True)
class _CallWindow:
    started_at: datetime
    # None without a clock (or with an unusable end reading).
    completed_at: datetime | None
    elapsed_ms: int | None


@dataclass(frozen=True, slots=True)
class SnapshotCommit:
    accepted: bool
    reason_codes: tuple[str, ...]
    snapshot: CaseContextSnapshot


class CaseCoordinator:
    """Advance one immutable snapshot through one deterministic route.

    ``clock`` and ``monotonic`` time the model calls traced on a 1.1 snapshot.
    The coordinator never reads a wall clock. Latency is the adapter-reported
    value, else the ``monotonic`` measurement. Without ``clock`` a trace starts
    at the route request's ``created_at`` and ends ``latency`` later (0 when
    nothing measured); with a clock but no measurement the latency is the
    clock window's width. A non-UTC clock is refused before the model call.

    ``fast_gate`` (the product Runtime only) runs on a Fast output that passed
    ``validate_fast_result``. A non-empty verdict rejects the Fast audit with
    the gate's codes, withholds the decision, and sets
    ``fast_disclosure_rejected``. Without a gate the behaviour is unchanged.

    ``capture_fast_failures`` (the product Runtime only) turns a
    ``FastAdapterFailure`` raised by the Fast call into a ``FAILED`` Fast trace
    and ``fast_failed``; there is no retry and no other adapter. Any other
    exception propagates, and without the flag so does the failure.

    An ``ObservingFastAdapter`` is called with ``fast_public_observation`` of
    the snapshot the view is projected from; a refusal is a
    ``fast_input_unrenderable`` failure raised before the adapter is called.
    """

    def __init__(
        self,
        router: DeterministicRouter | None = None,
        snapshot: CaseContextSnapshot | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        fast_gate: FastGate | None = None,
        capture_fast_failures: bool = False,
    ) -> None:
        self._router = router or DeterministicRouter()
        self._lock = RLock()
        self._current_snapshot = snapshot
        self._clock = clock
        self._monotonic = monotonic
        self._fast_gate = fast_gate
        self._capture_fast_failures = capture_fast_failures

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
        # Only a 1.1 snapshot is traced; the 1.0 (ML/evaluation) path is as before.
        traced = request.snapshot.schema_version == "1.1"
        traces: list[ModelTrace] = []
        slow_result: SlowWorkResult | None = None
        fast_decision: FastTurnDecision | None = None
        fast_disclosure_rejected = False
        fast_failed = False

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
            if traced:
                (slow_output, slow_usage), window = self._timed(
                    lambda: _reason(slow, slow_request), request.created_at
                )
            else:
                slow_output = slow.reason(slow_request)
            audit = self.validate_slow_result(
                slow_output,
                request.snapshot,
                expected_request=slow_request,
                evaluated_at=request.created_at,
            )
            audits.append(audit)
            if traced:
                traces.append(
                    _model_trace(
                        role="slow",
                        adapter=slow,
                        snapshot=request.snapshot,
                        audit=audit,
                        window=window,
                        usage=slow_usage,
                        request_id=slow_request.request_id,
                        input_schema_version=slow_request.schema_version,
                        output_schema_version=slow_output.schema_version,
                        output_id=slow_output.result_id,
                        result=_audit_result(audit),
                    )
                )
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
                    traces=tuple(traces),
                )
            fast_view = self.project_fast_view(request.snapshot)
            snapshot = request.snapshot
            if traced:
                called, window = self._timed(
                    lambda: self._captured(lambda: _decide(fast, fast_view, snapshot)),
                    request.created_at,
                )
            else:
                called = self._captured(
                    lambda: (_decide_untraced(fast, fast_view, snapshot), None)
                )
            if isinstance(called, FastAdapterFailure):
                fast_failed = True
                audit = ResultAudit(
                    source="fast",
                    accepted=False,
                    reason_codes=called.reason_codes,
                    input_pins=snapshot.pins,
                    current_pins=snapshot.pins,
                )
                audits.append(audit)
                if traced:
                    # Reported tokens count; the latency is the call window.
                    reported = called.usage or ModelCallUsage()
                    traces.append(
                        _model_trace(
                            role="fast",
                            adapter=fast,
                            snapshot=snapshot,
                            audit=audit,
                            window=window,
                            usage=replace(reported, latency_ms=None),
                            request_id=None,
                            input_schema_version=fast_view.schema_version,
                            output_schema_version="none",
                            output_id=None,
                            result=ModelResult.FAILED,
                        )
                    )
            else:
                fast_output, fast_usage = called
                audit = self.validate_fast_result(
                    fast_output,
                    snapshot,
                    bounded=route.outcome is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH,
                )
                if audit.accepted and self._fast_gate is not None:
                    gate_codes = self._fast_gate(fast_output.decision, snapshot)
                    if gate_codes:
                        fast_disclosure_rejected = True
                        audit = replace(audit, accepted=False, reason_codes=gate_codes)
                audits.append(audit)
                if traced:
                    traces.append(
                        _model_trace(
                            role="fast",
                            adapter=fast,
                            snapshot=snapshot,
                            audit=audit,
                            window=window,
                            usage=fast_usage,
                            request_id=None,
                            input_schema_version=fast_view.schema_version,
                            output_schema_version=fast_output.decision.schema_version,
                            output_id=fast_output.decision.decision_id,
                            result=_audit_result(audit),
                        )
                    )
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
            traces=tuple(traces),
            fast_disclosure_rejected=fast_disclosure_rejected,
            fast_failed=fast_failed,
        )

    def _captured(self, call: Callable[[], _T]) -> _T | FastAdapterFailure:
        """The call's value, or its ``FastAdapterFailure`` when captured."""

        try:
            return call()
        except FastAdapterFailure as failure:
            if not self._capture_fast_failures:
                raise
            return failure

    def _timed(self, call: Callable[[], _T], at: datetime) -> tuple[_T, _CallWindow]:
        # A broken injected source is refused before the model call, clearly.
        started_at = at
        if self._clock is not None:
            clock_start = _utc_reading(self._clock())
            if clock_start is None:
                raise ValueError("clock must return a timezone-aware UTC datetime")
            started_at = clock_start
        start: float | None = None
        if self._monotonic is not None:
            start = _monotonic_reading(self._monotonic())
            if start is None:
                raise ValueError("monotonic must return a finite number")
        value = call()
        # After the call, observability never fails the business result: an
        # unusable reading falls back to the window derived in _model_trace.
        elapsed_ms: int | None = None
        if self._monotonic is not None and start is not None:
            end = _monotonic_reading(self._monotonic())
            if end is not None and end >= start:
                elapsed_ms = round((end - start) * 1000)
        completed_at: datetime | None = None
        if self._clock is not None:
            clock_end = _utc_reading(self._clock())
            if clock_end is not None and clock_end >= started_at:
                completed_at = clock_end
        return value, _CallWindow(started_at, completed_at, elapsed_ms)

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
            if (
                current.schema_version == "1.1"
                and strategy.planning_basis_fingerprint
                != current.planning_basis.planning_basis_fingerprint
            ):
                reasons.append("slow_strategy_basis_mismatch")
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


def _reason(
    slow: SlowAdapter, request: SlowWorkRequest
) -> tuple[SlowWorkResult, ModelCallUsage | None]:
    if isinstance(slow, UsageReportingSlowAdapter):
        return slow.reason_with_usage(request)
    return slow.reason(request), None


def _decide(
    fast: FastAdapter, view: FastModelView, snapshot: CaseContextSnapshot
) -> tuple[FastAdapterResult, ModelCallUsage | None]:
    if isinstance(fast, ObservingFastAdapter):
        return _decide_observed(fast, view, snapshot)
    if isinstance(fast, UsageReportingFastAdapter):
        return fast.decide_with_usage(view)
    return fast.decide(view), None


def _decide_untraced(
    fast: FastAdapter, view: FastModelView, snapshot: CaseContextSnapshot
) -> FastAdapterResult:
    # The untraced (1.0, ML) path calls ``decide`` exactly as before.
    if isinstance(fast, ObservingFastAdapter):
        return _decide_observed(fast, view, snapshot)[0]
    return fast.decide(view)


def _decide_observed(
    fast: ObservingFastAdapter, view: FastModelView, snapshot: CaseContextSnapshot
) -> tuple[FastAdapterResult, ModelCallUsage]:
    observation = fast_public_observation(snapshot)
    if isinstance(observation, ObservationRefusal):
        raise FastAdapterFailure(
            "fast_input_unrenderable", detail_code=observation.reason_codes[0]
        )
    return fast.decide_observed(view, observation)


def _audit_result(audit: ResultAudit) -> ModelResult:
    return ModelResult.SUCCEEDED if audit.accepted else ModelResult.REJECTED


def _model_trace(
    *,
    role: Literal["fast", "slow"],
    adapter: object,
    snapshot: CaseContextSnapshot,
    audit: ResultAudit,
    window: _CallWindow,
    usage: ModelCallUsage | None,
    request_id: UUID | None,
    input_schema_version: str,
    output_schema_version: str,
    output_id: UUID | None,
    result: ModelResult,
) -> ModelTrace:
    """Record one adapter call; an unidentified adapter is named by its class.

    Whatever the adapter reports is normalised rather than trusted: this runs
    after the model call, so it must not turn a trace problem into a failure.
    """

    identity = _identity(adapter)
    reported = _normalised_usage(usage)
    measured = (
        reported.latency_ms if reported.latency_ms is not None else window.elapsed_ms
    )
    if window.completed_at is None:
        # No clock: the window is derived from the latency, never contradicts it.
        latency_ms = measured if measured is not None else 0
        completed_at = window.started_at + timedelta(milliseconds=latency_ms)
    else:
        completed_at = window.completed_at
        latency_ms = (
            measured
            if measured is not None
            else round((completed_at - window.started_at).total_seconds() * 1000)
        )
    trace = ModelTrace(
        contract_type="model_trace",
        schema_version="1.1",
        revision=1,
        trace_id=_stable_uuid4("model-trace"),
        case_id=snapshot.case.case_id,
        started_at=window.started_at,
        completed_at=completed_at,
        provider=identity.provider,
        model=identity.model,
        model_version=identity.model_version,
        adapter_version=identity.adapter_version,
        prompt_version=identity.prompt_version,
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        latency_ms=latency_ms,
        input_tokens=reported.input_tokens,
        output_tokens=reported.output_tokens,
        result=result,
        output_ref=str(output_id) if output_id is not None else None,
        safety_flags=(),
        role=role,
        # A reason repeated per offending proposal is recorded once.
        reason_codes=tuple(dict.fromkeys(audit.reason_codes)),
        request_id=request_id,
        input_pins=snapshot.pins,
    )
    # The id is derived from every other field: one call, one stable id.
    content = trace.model_dump(mode="json", exclude={"trace_id"})
    trace_id = _stable_uuid4(f"model-trace:{canonical_fingerprint(content)}")
    return trace.model_copy(update={"trace_id": trace_id})


def _identity(adapter: object) -> ModelIdentity:
    reported = (
        adapter.model_identity if isinstance(adapter, IdentifiedAdapter) else None
    )

    def field(name: str, fallback: str) -> str:
        value = getattr(reported, name, None)
        if isinstance(value, str) and 0 < len(value.strip()) <= _EXTERNAL_REF_MAX:
            return value
        return fallback

    return ModelIdentity(
        provider=field("provider", "unidentified"),
        model=field("model", type(adapter).__name__[:_EXTERNAL_REF_MAX]),
        model_version=field("model_version", "unversioned"),
        adapter_version=field("adapter_version", "unversioned"),
        prompt_version=field("prompt_version", "unversioned"),
    )


def _normalised_usage(usage: object) -> ModelCallUsage:
    """A reported count that is not a non-negative int (or bool) becomes 0."""

    def count(name: str) -> int | None:
        value = getattr(usage, name, None)
        return value if type(value) is int and value >= 0 else None

    return ModelCallUsage(
        input_tokens=count("input_tokens") or 0,
        output_tokens=count("output_tokens") or 0,
        latency_ms=count("latency_ms"),
    )


def _utc_reading(value: object) -> datetime | None:
    if (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    ):
        return value
    return None


def _monotonic_reading(value: object) -> float | None:
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return float(value)
    return None


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
