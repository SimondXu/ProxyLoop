from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from proxyloop_agent_core import (
    BOUNDED_FAST_STATUS_TEXT,
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    CoordinatorStatus,
    DeterministicRouter,
    FastAdapterResult,
    PreparedSimulatorExecution,
    RouteRequest,
    ScriptedFastAdapter,
    ScriptedSlowAdapter,
    accepted_fast_reasoner_trigger,
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
    DialogueAct,
    EventActor,
    Evidence,
    EvidenceType,
    FactLedger,
    FactRecord,
    FactStatus,
    FastTurnDecision,
    ModelInputPins,
    PlanningBasis,
    ProviderOffer,
    RoutingOutcome,
    SlowWorkRequest,
    SlowWorkResult,
    StrategyPacket,
    VisibleCaseEvent,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement, ReasonerRequest
from proxyloop_provider_simulator.episode import Phase01AEpisode

NOW = datetime(2026, 8, 23, 12, 20, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
STRATEGY_ID = UUID("99999999-9999-4999-8999-999999999999")


def _basis(
    *,
    case: Case,
    ledger: FactLedger,
    offers: tuple[ProviderOffer, ...],
    approvals: tuple[ApprovalRequest, ...],
    provider_config_ref: str,
    manifest: CapabilityManifest,
) -> PlanningBasis:
    components = {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(case.constraints),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(
            tuple(item for item in ledger.entries if item.status is FactStatus.VERIFIED)
        ),
        "material_offers_fingerprint": canonical_fingerprint(offers),
        "approval_state_fingerprint": canonical_fingerprint(approvals),
        "provider_config_fingerprint": canonical_fingerprint(provider_config_ref),
        "capability_manifest_fingerprint": canonical_fingerprint(manifest),
    }
    aggregate = planning_basis_fingerprint(
        **components,
    )
    return PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=aggregate,
    )


def _strategy() -> StrategyPacket:
    return StrategyPacket(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=1,
        strategy_id=STRATEGY_ID,
        case_id=CASE_ID,
        case_revision=1,
        fact_ledger_revision=1,
        created_at=NOW - timedelta(minutes=20),
        expires_at=NOW + timedelta(hours=1),
        primary_objective="Reduce the recurring bill safely.",
        current_subgoal="Evaluate the current fictional Provider offer.",
        hard_constraint_ids=(UUID("44444444-4444-4444-8444-444444444444"),),
        ranked_preference_ids=(),
        allowed_disclosures=("current_monthly_total",),
        approval_required_disclosures=(),
        concession_ladder=("Preserve mobile hotspot.",),
        fallback_outcomes=("Ask the consumer for direction.",),
        required_completion_evidence=(
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A fictional Provider confirmation is required.",
            ),
        ),
        escalation_conditions=("A material offer changes.",),
        replan_conditions=("The offer expires.",),
    )


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="phase-03a1-v1",
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        capabilities=(
            CapabilityDefinition(
                capability_id="simulator.accept_fictional_offer",
                version="1.0",
                description="Accept a current fictional Provider offer.",
                namespace="simulator",
                allowed_action_types=(ActionType.ACCEPT_OFFER,),
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
    )


def _snapshot(
    *,
    strategy: StrategyPacket | None = None,
    approval_current: bool = False,
) -> tuple[CaseContextSnapshot, Phase01AEpisode]:
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    approval = None
    if approval_current:
        episode.request_approval()
        approval = episode.approval_request
    active_strategy = strategy if strategy is not None else _strategy()
    manifest = _manifest()
    approvals = (approval,) if approval is not None else ()
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=episode.case.case_id,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
        entries=(),
    )
    basis = _basis(
        case=episode.case,
        ledger=ledger,
        offers=(offer,),
        approvals=approvals,
        provider_config_ref="cooperative-v1",
        manifest=manifest,
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=episode.case.case_id,
        case_revision=episode.case.revision,
        constraint_set_revision=episode.case.constraint_set_revision,
        fact_ledger_revision=1,
        strategy_id=active_strategy.strategy_id,
        strategy_revision=active_strategy.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=1,
        provider_config_ref="cooperative-v1",
        capability_manifest_version=manifest.manifest_version,
    )
    snapshot = CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=1,
        case=episode.case,
        fact_ledger=ledger,
        strategy=active_strategy,
        offers=(offer,),
        approval_requests=approvals,
        visible_events=(
            VisibleCaseEvent(
                contract_type="visible_case_event",
                schema_version="1.0",
                revision=1,
                event_id=UUID("88888888-8888-4888-8888-888888888888"),
                case_id=episode.case.case_id,
                event_cursor=1,
                occurred_at=NOW,
                actor=EventActor.PROVIDER,
                event_type="provider_message",
                content="A fictional offer is available.",
            ),
        ),
        event_cursor=1,
        planning_basis=basis,
        pins=pins,
        provider_config_ref="cooperative-v1",
        capability_manifest=manifest,
    )
    return snapshot, episode


def _without_strategy(snapshot: CaseContextSnapshot) -> CaseContextSnapshot:
    pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    return snapshot.model_copy(update={"strategy": None, "pins": pins})


def _with_approval(
    snapshot: CaseContextSnapshot,
    approval: ApprovalRequest,
) -> CaseContextSnapshot:
    basis = _basis(
        case=snapshot.case,
        ledger=snapshot.fact_ledger,
        offers=snapshot.offers,
        approvals=(approval,),
        provider_config_ref=snapshot.provider_config_ref,
        manifest=snapshot.capability_manifest,
    )
    pins = snapshot.pins.model_copy(
        update={"planning_basis_fingerprint": basis.planning_basis_fingerprint}
    )
    return CaseContextSnapshot(
        **{
            **snapshot.__dict__,
            "approval_requests": (approval,),
            "planning_basis": basis,
            "pins": pins,
        }
    )


def test_router_evaluates_the_frozen_precedence_and_mandatory_slow() -> None:
    snapshot, _ = _snapshot(approval_current=True)
    router = DeterministicRouter()

    waiting = router.route(RouteRequest(snapshot=snapshot, created_at=NOW))
    assert waiting.outcome is RoutingOutcome.WAIT_FOR_APPROVAL

    verify_snapshot = snapshot.model_copy(update={"pending_execution": True})
    verify = router.route(RouteRequest(snapshot=verify_snapshot, created_at=NOW))
    assert verify.outcome is RoutingOutcome.VERIFY_ONLY

    initial = _without_strategy(
        snapshot.model_copy(
            update={"approval_requests": (), "pending_execution": False}
        )
    )
    slow = router.route(
        RouteRequest(
            snapshot=initial,
            created_at=NOW,
            bounded_acknowledgement_allowed=True,
        )
    )
    assert slow.outcome is RoutingOutcome.SLOW_REFRESH

    combined = router.route(
        RouteRequest(
            snapshot=snapshot.model_copy(update={"approval_requests": ()}),
            created_at=NOW,
            mandatory_slow_reason_codes=("material_offer_changed",),
            bounded_acknowledgement_allowed=True,
        )
    )
    assert combined.outcome is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH

    terminal_case = snapshot.case.model_copy(update={"phase": CasePhase.CLOSED})
    terminal_snapshot = snapshot.model_copy(
        update={"case": terminal_case, "pending_execution": True}
    )
    terminal = router.route(RouteRequest(snapshot=terminal_snapshot, created_at=NOW))
    assert terminal.outcome is RoutingOutcome.TERMINAL


def test_fast_reasoner_request_is_advisory_to_closed_router_policy() -> None:
    assert accepted_fast_reasoner_trigger(
        ReasonerRequest(needed=True, reason_code="conflicting_facts")
    ) == ("fast_reasoner_request:conflicting_facts",)
    assert (
        accepted_fast_reasoner_trigger(
            ReasonerRequest(needed=True, reason_code="force_slow")
        )
        == ()
    )
    assert (
        accepted_fast_reasoner_trigger(
            ReasonerRequest(needed=False, reason_code="conflicting_facts")
        )
        == ()
    )


@dataclass
class _Fast:
    pins: ModelInputPins
    action_intent: ActionIntent | None = None
    response_text: str = "Could you confirm the next step?"

    def decide(self, view: object) -> FastAdapterResult:
        return FastAdapterResult(
            pins=self.pins,
            decision=FastTurnDecision(
                contract_type="fast_turn_decision",
                schema_version="1.0",
                decision_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                case_id=CASE_ID,
                case_revision=1,
                strategy_id=STRATEGY_ID,
                strategy_revision=1,
                created_at=NOW,
                dialogue_act=DialogueAct.CLARIFY,
                fact_updates=(),
                reasoner_request={"needed": False, "reason_code": "none"},
                completion_claim={
                    "status": "not_done",
                    "evidence_message_ids": (),
                },
                response_text=self.response_text,
                action_intent=self.action_intent,
            ),
        )


@dataclass
class _Slow:
    pins: ModelInputPins

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        return SlowWorkResult(
            contract_type="slow_work_result",
            schema_version="1.0",
            revision=1,
            result_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            request_id=request.request_id,
            case_id=request.case_id,
            pins=self.pins,
            planning_basis=request.planning_basis,
            created_at=NOW,
        )


def test_coordinator_rejects_stale_fast_and_forbidden_action_intent() -> None:
    snapshot, episode = _snapshot()
    coordinator = CaseCoordinator()
    route = RouteRequest(snapshot=snapshot, created_at=NOW)
    stale_pins = snapshot.pins.model_copy(update={"event_cursor": 0})

    stale = coordinator.advance(route, fast=_Fast(stale_pins))
    assert stale.status is CoordinatorStatus.REJECTED
    assert stale.audits[0].reason_codes == ("stale_fast_result",)

    episode.request_approval()
    forbidden = coordinator.advance(
        route,
        fast=_Fast(snapshot.pins, action_intent=episode.action_intent),
    )
    assert forbidden.status is CoordinatorStatus.REJECTED
    assert "fast_action_intent_forbidden" in forbidden.audits[0].reason_codes

    accepted = coordinator.advance(route, fast=_Fast(snapshot.pins))
    assert accepted.status is CoordinatorStatus.ACCEPTED
    assert accepted.fast_decision is not None


def test_harmless_dialogue_advances_cursor_without_invalidating_strategy() -> None:
    snapshot, _episode = _snapshot()
    old_fast_result = ScriptedFastAdapter().decide(
        CaseCoordinator.project_fast_view(snapshot)
    )
    later_event = VisibleCaseEvent(
        contract_type="visible_case_event",
        schema_version="1.0",
        revision=1,
        event_id=UUID("99999999-9999-4999-8999-999999999998"),
        case_id=snapshot.case.case_id,
        event_cursor=2,
        occurred_at=NOW + timedelta(seconds=1),
        actor=EventActor.CONSUMER,
        event_type="consumer_acknowledgement",
        content="Please continue.",
    )
    later_pins = snapshot.pins.model_copy(update={"event_cursor": 2})
    later = CaseContextSnapshot(
        **{
            **snapshot.__dict__,
            "revision": 2,
            "visible_events": (*snapshot.visible_events, later_event),
            "event_cursor": 2,
            "pins": later_pins,
        }
    )

    route = DeterministicRouter().route(RouteRequest(snapshot=later, created_at=NOW))
    audit = CaseCoordinator.validate_fast_result(old_fast_result, later)

    assert later.planning_basis == snapshot.planning_basis
    assert later.strategy == snapshot.strategy
    assert route.outcome is RoutingOutcome.FAST_NOW
    assert "stale_fast_result" in audit.reason_codes


def test_each_material_snapshot_change_invalidates_the_planning_basis() -> None:
    snapshot, _ = _snapshot(approval_current=True)
    verified_fact = FactRecord(
        fact_id=UUID("12121212-1212-4212-8212-121212121212"),
        key="verified_monthly_total",
        value=9200,
        status=FactStatus.VERIFIED,
        evidence_ids=(UUID("13131313-1313-4313-8313-131313131313"),),
        confidence=1.0,
        recorded_at=NOW,
    )
    changed_goal = snapshot.case.model_copy(
        update={
            "goal": snapshot.case.goal.model_copy(
                update={"desired_outcome": "A materially different outcome."}
            )
        }
    )
    changed_constraints = snapshot.case.model_copy(
        update={
            "constraints": (
                snapshot.case.constraints[0].model_copy(
                    update={"statement": "A materially different constraint."}
                ),
            )
        }
    )
    changed_authority = snapshot.case.model_copy(
        update={
            "delegated_authority": snapshot.case.delegated_authority.model_copy(
                update={"allowed_disclosures": ()}
            )
        }
    )
    changed_ledger = snapshot.fact_ledger.model_copy(
        update={"entries": (verified_fact,)}
    )
    changed_offer = snapshot.offers[0].model_copy(
        update={
            "monthly_price": snapshot.offers[0].monthly_price.model_copy(
                update={"amount_minor": 1}
            )
        }
    )
    changed_approval = snapshot.approval_requests[0].model_copy(
        update={
            "decision": ApprovalDecision.APPROVED,
            "decided_at": NOW,
        }
    )
    changed_manifest = snapshot.capability_manifest.model_copy(
        update={
            "capabilities": (
                snapshot.capability_manifest.capabilities[0].model_copy(
                    update={"description": "A materially changed capability."}
                ),
            )
        }
    )
    mutations: tuple[dict[str, object], ...] = (
        {"case": changed_goal},
        {"case": changed_constraints},
        {"case": changed_authority},
        {"fact_ledger": changed_ledger},
        {"offers": (changed_offer,)},
        {"approval_requests": (changed_approval,)},
        {
            "provider_config_ref": "different-provider-config",
            "pins": snapshot.pins.model_copy(
                update={"provider_config_ref": "different-provider-config"}
            ),
        },
        {"capability_manifest": changed_manifest},
    )
    for mutation in mutations:
        with pytest.raises(
            ValueError,
            match="planning basis components must match material snapshot state",
        ):
            CaseContextSnapshot(**{**snapshot.__dict__, **mutation})


def test_missing_slow_is_typed_and_slow_results_use_compare_and_swap() -> None:
    snapshot, _ = _snapshot()
    initial = _without_strategy(snapshot)
    coordinator = CaseCoordinator()
    route = RouteRequest(snapshot=initial, created_at=NOW)

    unavailable = coordinator.advance(route)
    assert unavailable.status is CoordinatorStatus.SLOW_UNAVAILABLE

    stale_pins = initial.pins.model_copy(update={"event_cursor": 2})
    stale = coordinator.advance(route, slow=_Slow(stale_pins))
    assert stale.status is CoordinatorStatus.REJECTED
    assert stale.audits[0].reason_codes == ("stale_slow_result",)

    accepted = coordinator.advance(route, slow=_Slow(initial.pins))
    assert accepted.status is CoordinatorStatus.ACCEPTED

    scripted_slow = coordinator.advance(route, slow=ScriptedSlowAdapter())
    assert scripted_slow.status is CoordinatorStatus.ACCEPTED
    assert scripted_slow.slow_result is not None
    scripted_strategy = scripted_slow.slow_result.strategy_proposal
    assert scripted_strategy is not None
    planned_pins = snapshot.pins.model_copy(
        update={
            "strategy_id": scripted_strategy.strategy_id,
            "strategy_revision": scripted_strategy.revision,
        }
    )
    planned = snapshot.model_copy(
        update={"strategy": scripted_strategy, "pins": planned_pins}
    )
    scripted_fast = coordinator.advance(
        RouteRequest(snapshot=planned, created_at=NOW),
        fast=ScriptedFastAdapter(),
    )
    assert scripted_fast.status is CoordinatorStatus.ACCEPTED


@dataclass
class _Capability:
    invocations: int = 0

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        del proposal
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            case_id=CASE_ID,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash="e" * 64,
            observed_at=NOW,
            captured_at=NOW,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=self._commit)

    def _commit(self) -> None:
        self.invocations += 1


@dataclass
class _SlowCommitCapability(_Capability):
    def _commit(self) -> None:
        time.sleep(0.02)
        self.invocations += 1


def test_capability_executor_rechecks_authority_and_reuses_evidence() -> None:
    snapshot, episode = _snapshot()
    episode.request_approval()
    episode.approve()
    snapshot = _with_approval(snapshot, episode.approval_request)
    assert episode.action_intent is not None
    proposal = CapabilityProposal(
        proposal_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_fictional_offer",
            version="1.0",
        ),
        arguments=(
            CapabilityArgument(
                name="offer_id",
                value=str(episode.action_intent.offer_ref.offer_id),
            ),
        ),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
    )
    adapter = _Capability()
    executor = CapabilityExecutor(adapter)
    request = CapabilityExecutionRequest(
        snapshot=snapshot,
        source_pins=snapshot.pins,
        proposal=proposal,
        action_intent=episode.action_intent,
        approval=episode.approval_request,
        executed_at=NOW,
    )

    first = executor.execute(request)
    repeated = executor.execute(request)

    assert first.status is CapabilityExecutionStatus.EXECUTED
    assert repeated.status is CapabilityExecutionStatus.REUSED
    assert repeated.evidence is first.evidence
    assert adapter.invocations == 1

    changed_offer = snapshot.offers[0].model_copy(update={"revision": 2})
    rejected = CapabilityExecutor(_Capability()).execute(
        CapabilityExecutionRequest(
            snapshot=snapshot.model_copy(update={"offers": (changed_offer,)}),
            source_pins=snapshot.pins,
            proposal=proposal,
            action_intent=episode.action_intent,
            approval=episode.approval_request,
            executed_at=NOW,
        )
    )
    assert rejected.status is CapabilityExecutionStatus.REJECTED
    assert "current_offer_mismatch" in rejected.reason_codes


def test_capability_executor_serializes_concurrent_duplicate_execution() -> None:
    snapshot, episode = _snapshot()
    episode.request_approval()
    episode.approve()
    snapshot = _with_approval(snapshot, episode.approval_request)
    assert episode.action_intent is not None
    assert episode.action_intent.offer_ref is not None
    proposal = CapabilityProposal(
        proposal_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_fictional_offer",
            version="1.0",
        ),
        arguments=(
            CapabilityArgument(
                name="offer_id",
                value=str(episode.action_intent.offer_ref.offer_id),
            ),
        ),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
    )
    request = CapabilityExecutionRequest(
        snapshot=snapshot,
        source_pins=snapshot.pins,
        proposal=proposal,
        action_intent=episode.action_intent,
        approval=episode.approval_request,
        executed_at=NOW,
    )
    adapter = _SlowCommitCapability()
    executor = CapabilityExecutor(adapter)
    start = Barrier(3)

    def execute_together() -> CapabilityExecutionStatus:
        start.wait()
        return executor.execute(request).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute_together) for _ in range(2)]
        start.wait()
        statuses = {future.result() for future in futures}

    assert statuses == {
        CapabilityExecutionStatus.EXECUTED,
        CapabilityExecutionStatus.REUSED,
    }
    assert adapter.invocations == 1


@dataclass
class _InvalidEvidenceCapability:
    source_ref: str
    commits: int = 0

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        del proposal, idempotency_key
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeef"),
            case_id=CASE_ID,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=self.source_ref,
            content_hash="f" * 64,
            observed_at=NOW,
            captured_at=NOW,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=self._commit)

    def _commit(self) -> None:
        self.commits += 1


def test_capability_executor_rejects_unbound_evidence_before_commit() -> None:
    snapshot, episode = _snapshot()
    episode.request_approval()
    episode.approve()
    snapshot = _with_approval(snapshot, episode.approval_request)
    assert episode.action_intent is not None
    proposal = CapabilityProposal(
        proposal_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_fictional_offer",
            version="1.0",
        ),
        arguments=(
            CapabilityArgument(
                name="offer_id",
                value=str(episode.action_intent.offer_ref.offer_id),
            ),
        ),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
    )
    adapter = _InvalidEvidenceCapability("different-execution")
    outcome = CapabilityExecutor(adapter).execute(
        CapabilityExecutionRequest(
            snapshot=snapshot,
            source_pins=snapshot.pins,
            proposal=proposal,
            action_intent=episode.action_intent,
            approval=episode.approval_request,
            executed_at=NOW,
        )
    )
    assert outcome.status is CapabilityExecutionStatus.REJECTED
    assert outcome.reason_codes == ("evidence_execution_binding_mismatch",)
    assert adapter.commits == 0


def test_coordinator_serializes_snapshot_compare_and_swap() -> None:
    snapshot, _ = _snapshot()
    next_pins = snapshot.pins.model_copy(update={"event_cursor": 2})
    next_snapshot = snapshot.model_copy(
        update={"revision": 2, "event_cursor": 2, "pins": next_pins}
    )
    competing = next_snapshot.model_copy(update={"revision": 3})
    coordinator = CaseCoordinator(snapshot=snapshot)

    first = coordinator.compare_and_swap(snapshot.pins, next_snapshot)
    second = coordinator.compare_and_swap(snapshot.pins, competing)

    assert first.accepted is True
    assert second.accepted is False
    assert second.reason_codes == ("snapshot_compare_and_swap_conflict",)
    assert coordinator.current_snapshot is next_snapshot

    stale_route = coordinator.advance(RouteRequest(snapshot=snapshot, created_at=NOW))
    assert stale_route.status is CoordinatorStatus.REJECTED
    assert stale_route.audits[0].reason_codes == (
        "stale_route_request_rerouted_to_latest",
    )
    assert stale_route.route.pins == next_snapshot.pins


def test_slow_result_must_match_request_and_current_strategy_revisions() -> None:
    snapshot, _ = _snapshot()
    initial = _without_strategy(snapshot)
    request = CaseCoordinator.build_slow_request(
        initial,
        reason_code="case_initialization",
        created_at=NOW,
    )
    result = ScriptedSlowAdapter().reason(request)
    wrong_request = result.model_copy(
        update={"request_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")}
    )
    wrong_request_audit = CaseCoordinator.validate_slow_result(
        wrong_request,
        initial,
        expected_request=request,
        evaluated_at=NOW,
    )
    assert "slow_request_mismatch" in wrong_request_audit.reason_codes

    assert result.strategy_proposal is not None
    stale_strategy = result.strategy_proposal.model_copy(
        update={
            "case_revision": initial.case.revision + 1,
            "fact_ledger_revision": initial.fact_ledger.revision + 1,
            "expires_at": NOW,
        }
    )
    stale_result = result.model_copy(update={"strategy_proposal": stale_strategy})
    stale_audit = CaseCoordinator.validate_slow_result(
        stale_result,
        initial,
        expected_request=request,
        evaluated_at=NOW,
    )
    assert "slow_strategy_case_revision_mismatch" in stale_audit.reason_codes
    assert "slow_strategy_fact_ledger_revision_mismatch" in stale_audit.reason_codes
    assert "slow_strategy_expired" in stale_audit.reason_codes


def test_bounded_fast_requires_the_exact_non_material_template() -> None:
    snapshot, _ = _snapshot()
    chinese_material = _Fast(
        snapshot.pins,
        response_text="月费和合同条款已经更新 请确认",
    ).decide(object())
    rejected = CaseCoordinator.validate_fast_result(
        chinese_material,
        snapshot,
        bounded=True,
    )
    accepted = CaseCoordinator.validate_fast_result(
        _Fast(snapshot.pins, response_text=BOUNDED_FAST_STATUS_TEXT).decide(object()),
        snapshot,
        bounded=True,
    )
    assert "bounded_fast_output_violation" in rejected.reason_codes
    assert accepted.accepted is True


def test_approval_trigger_must_be_the_latest_verified_visible_event() -> None:
    snapshot, _ = _snapshot(approval_current=True)
    approval_event = VisibleCaseEvent(
        contract_type="visible_case_event",
        schema_version="1.0",
        revision=1,
        event_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab"),
        case_id=snapshot.case.case_id,
        event_cursor=2,
        occurred_at=NOW + timedelta(seconds=1),
        actor=EventActor.CONSUMER,
        event_type="approval_decision",
        content="approved",
    )
    latest = snapshot.model_copy(
        update={
            "revision": 2,
            "visible_events": (*snapshot.visible_events, approval_event),
            "event_cursor": 2,
            "pins": snapshot.pins.model_copy(update={"event_cursor": 2}),
        }
    )
    with pytest.raises(ValueError, match="latest visible snapshot event"):
        RouteRequest(
            snapshot=latest,
            created_at=NOW + timedelta(seconds=1),
            triggering_event=snapshot.visible_events[0],
        )
    decision = DeterministicRouter().route(
        RouteRequest(
            snapshot=latest,
            created_at=NOW + timedelta(seconds=1),
            triggering_event=approval_event,
        )
    )
    assert decision.outcome is RoutingOutcome.FAST_NOW
