"""A 1.1 runtime strategy is bound to its planning basis (P1 A-1, A-10, A-6)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from proxyloop_agent_core import (
    CaseCoordinator,
    DeterministicRouter,
    RouteRequest,
    ScriptedSlowAdapter,
)
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.postgres_repository import PostgresCaseRepository
from proxyloop_contracts import (
    ApprovalDecision,
    CaseContextSnapshot,
    CasePhase,
    CompletionOutcome,
    EvidenceType,
    PlanningBasis,
    RoutingDecision,
    RoutingOutcome,
    SlowWorkRequest,
    StrategyPacket,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_openai_adapter import (
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)
from test_phase_06b1_channel_runtime import BASE_TIME, _ChannelRepository
from test_slow_refresh_strategy_expiry import _channel_command, _Clock, _CountingSlow

T0 = BASE_TIME
_BASIS_COMPONENTS = (
    "goal_fingerprint",
    "constraints_fingerprint",
    "delegated_authority_fingerprint",
    "verified_facts_fingerprint",
    "material_offers_fingerprint",
    "approval_state_fingerprint",
    "provider_config_fingerprint",
    "capability_manifest_fingerprint",
)


def _created(
    slow: ScriptedSlowAdapter | None = None,
    repository: InMemoryCaseRepository | None = None,
) -> tuple[ThinAgentRuntime, InMemoryCaseRepository, _Clock]:
    repository = repository if repository is not None else InMemoryCaseRepository()
    clock = _Clock(T0)
    runtime = ThinAgentRuntime(repository, clock=clock, slow=slow)
    runtime.create_case(occurred_at=T0)
    return runtime, repository, clock


def _route(snapshot: CaseContextSnapshot, at: datetime) -> RoutingDecision:
    return DeterministicRouter().route(RouteRequest(snapshot=snapshot, created_at=at))


def _resnapshot(
    snapshot: CaseContextSnapshot, **changes: object
) -> CaseContextSnapshot:
    fields: dict[str, object] = {
        "case": snapshot.case,
        "ledger": snapshot.fact_ledger,
        "strategy": snapshot.strategy,
        "offers": snapshot.offers,
        "action_intents": snapshot.action_intents,
        "approvals": snapshot.approval_requests,
        "evidence": snapshot.evidence,
        "completion": snapshot.completion_decision,
        "events": snapshot.visible_events,
        "snapshot_revision": snapshot.revision + 1,
        "phase": snapshot.case.phase,
        "manifest": snapshot.capability_manifest,
    }
    fields.update(changes)
    return runtime_module._snapshot(**fields)  # type: ignore[arg-type]


def _state(repository: InMemoryCaseRepository) -> CaseRuntimeState:
    state = repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


def _as_stored_1_0(state: CaseRuntimeState) -> CaseRuntimeState:
    """Rewrite a runtime state as the pre-1.1 runtime wrote it."""

    snapshot = state.snapshot
    strategy = snapshot.strategy
    legacy_strategy = (
        None
        if strategy is None
        else StrategyPacket(
            **{
                **strategy.__dict__,
                "schema_version": "1.0",
                "planning_basis_fingerprint": None,
            }
        )
    )
    components = {
        name: getattr(snapshot.planning_basis, name) for name in _BASIS_COMPONENTS
    }
    components["material_offers_fingerprint"] = canonical_fingerprint(
        tuple(sorted(snapshot.offers, key=lambda item: str(item.offer_id)))
    )
    components["approval_state_fingerprint"] = canonical_fingerprint(
        tuple(
            sorted(snapshot.approval_requests, key=lambda item: str(item.approval_id))
        )
    )
    basis = PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )
    pins = snapshot.pins.model_copy(
        update={"planning_basis_fingerprint": basis.planning_basis_fingerprint}
    )
    legacy = CaseContextSnapshot(
        **{
            **snapshot.__dict__,
            "schema_version": "1.0",
            "strategy": legacy_strategy,
            "planning_basis": basis,
            "pins": pins,
            "completion_receipt": None,
        }
    )
    return replace(
        state,
        snapshot=legacy,
        execution_source_pins=pins if state.execution_source_pins is not None else None,
    )


def _through_postgres_envelope(state: CaseRuntimeState) -> CaseRuntimeState:
    """Encode and decode one state exactly as the PostgreSQL repository does."""

    payload = json.loads(json.dumps(PostgresCaseRepository._encode_state(state)))
    return PostgresCaseRepository._decode_state(
        state.snapshot.case.case_id, state.snapshot.revision, payload
    )


def _transition_route(repository: InMemoryCaseRepository, command_id: UUID) -> str:
    return next(
        item.route
        for item in _state(repository).transitions
        if item.command_id == command_id
    )


def _assert_bound(snapshot: CaseContextSnapshot) -> None:
    assert snapshot.schema_version == "1.1"
    assert snapshot.planning_basis.schema_version == "1.1"
    assert snapshot.strategy is not None
    assert snapshot.strategy.schema_version == "1.1"
    assert (
        snapshot.strategy.planning_basis_fingerprint
        == snapshot.pins.planning_basis_fingerprint
    )


def _assert_bound_receipt(snapshot: CaseContextSnapshot) -> None:
    assert snapshot.schema_version == "1.1"
    assert snapshot.case.phase is CasePhase.COMPLETE
    receipt = snapshot.completion_receipt
    assert receipt is not None
    (approval,) = snapshot.approval_requests
    assert approval.decision is ApprovalDecision.APPROVED
    assert (receipt.approval_id, receipt.approval_revision) == (
        approval.approval_id,
        approval.revision,
    )
    assert receipt.action_intent_id == approval.action_intent_id
    assert receipt.offer_ref == approval.offer_ref
    (confirmation,) = (
        item
        for item in snapshot.evidence
        if item.source_type is EvidenceType.CONFIRMATION
    )
    assert receipt.confirmation_evidence_id == confirmation.evidence_id
    assert receipt.confirmation_id == confirmation.source_ref
    assert receipt.confirmation_content_hash == confirmation.content_hash
    decision = snapshot.completion_decision
    assert decision is not None
    assert decision.decision is CompletionOutcome.COMPLETE
    assert confirmation.evidence_id in decision.evidence_ids
    # The strict JSON wire form validates with every 1.1 receipt rule.
    assert CaseContextSnapshot.model_validate_json(snapshot.model_dump_json()) == (
        snapshot
    )


def test_the_runtime_produces_1_1_snapshots_with_a_bound_strategy() -> None:
    runtime, _, _ = _created()
    snapshot = runtime.current_result(SCRIPTED_CASE_ID).snapshot

    _assert_bound(snapshot)
    decision = _route(snapshot, T0 + timedelta(minutes=1))
    assert decision.outcome is RoutingOutcome.FAST_NOW


def test_a1_offer_revision_change_under_a_valid_strategy_routes_slow_refresh() -> None:
    runtime, _, _ = _created()
    snapshot = runtime.current_result(SCRIPTED_CASE_ID).snapshot
    at = T0 + timedelta(minutes=1)
    assert snapshot.strategy is not None
    assert snapshot.strategy.expires_at > at
    (offer,) = snapshot.offers
    changed = _resnapshot(
        snapshot, offers=(offer.model_copy(update={"revision": offer.revision + 1}),)
    )

    decision = _route(changed, at)

    assert decision.outcome is RoutingOutcome.SLOW_REFRESH
    assert decision.reason_codes == ("strategy_basis_incompatible",)
    refreshed = CaseCoordinator(snapshot=changed).advance(
        RouteRequest(snapshot=changed, created_at=at), slow=ScriptedSlowAdapter()
    )
    assert refreshed.slow_result is not None
    strategy = refreshed.slow_result.strategy_proposal
    assert strategy is not None
    assert strategy.planning_basis_fingerprint == (
        changed.pins.planning_basis_fingerprint
    )


def test_the_coordinator_rejects_a_strategy_bound_to_another_basis() -> None:
    runtime, _, _ = _created()
    snapshot = runtime.current_result(SCRIPTED_CASE_ID).snapshot
    at = T0 + timedelta(minutes=1)
    (offer,) = snapshot.offers
    changed = _resnapshot(
        snapshot, offers=(offer.model_copy(update={"revision": offer.revision + 1}),)
    )
    request = CaseCoordinator.build_slow_request(
        changed, reason_code="strategy_basis_incompatible", created_at=at
    )
    result = ScriptedSlowAdapter().reason(request)
    assert result.strategy_proposal is not None
    stale = StrategyPacket(
        **{
            **result.strategy_proposal.__dict__,
            "planning_basis_fingerprint": snapshot.pins.planning_basis_fingerprint,
        }
    )
    stale_result = result.model_copy(update={"strategy_proposal": stale})

    audit = CaseCoordinator.validate_slow_result(
        stale_result, changed, expected_request=request, evaluated_at=at
    )

    assert audit.accepted is False
    assert audit.reason_codes == ("slow_strategy_basis_mismatch",)


def test_an_expired_approval_is_not_material_and_makes_no_slow_call() -> None:
    slow = _CountingSlow()
    repository = _ChannelRepository()
    runtime, _, _ = _created(slow, repository)
    # Refresh after the first strategy lifetime so a strategy is current when
    # the approval (bound to the offer's one-hour window) expires.
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=35),
    )
    approval = pending.approval
    assert approval is not None
    assert slow.reason_codes == ["case_initialization", "strategy_expired"]

    command_id = uuid4()
    expired = runtime.expire_approval(
        SCRIPTED_CASE_ID,
        approval.approval_id,
        expected_revision=pending.snapshot.revision,
        expires_at=approval.expires_at,
        command_id=command_id,
    )

    snapshot = expired.snapshot
    assert isinstance(expired.route, RoutingDecision)
    assert expired.route.outcome is RoutingOutcome.FAST_NOW
    assert expired.route == _route(snapshot, approval.expires_at)
    assert _transition_route(repository, command_id) == "fast_now"
    _assert_bound(snapshot)
    after = approval.expires_at + timedelta(minutes=1)
    assert _route(snapshot, after).outcome is RoutingOutcome.FAST_NOW
    applied = runtime.apply_command(_channel_command(repository, after))
    assert applied.route == "fast_now"
    assert slow.reason_codes == ["case_initialization", "strategy_expired"]


def test_an_approval_expiring_after_its_strategy_records_the_router_route() -> None:
    slow = _CountingSlow()
    runtime, repository, _ = _created(slow)
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )
    approval = pending.approval
    strategy = pending.snapshot.strategy
    assert approval is not None
    assert strategy is not None
    assert strategy.expires_at <= approval.expires_at
    command_id = uuid4()

    expired = runtime.expire_approval(
        SCRIPTED_CASE_ID,
        approval.approval_id,
        expected_revision=pending.snapshot.revision,
        expires_at=approval.expires_at,
        command_id=command_id,
    )

    # The expiry records the Router's decision (the strategy has expired),
    # not a hard-coded fast_now, and calls no adapter.
    assert isinstance(expired.route, RoutingDecision)
    assert expired.route.outcome is RoutingOutcome.SLOW_REFRESH
    assert expired.route.reason_codes == ("strategy_expired",)
    assert expired.route == _route(expired.snapshot, approval.expires_at)
    assert _transition_route(repository, command_id) == "slow_refresh"
    assert slow.reason_codes == ["case_initialization"]


def test_a_bounded_acknowledgement_requires_a_compatible_strategy() -> None:
    runtime, _, _ = _created()
    snapshot = runtime.current_result(SCRIPTED_CASE_ID).snapshot
    at = T0 + timedelta(minutes=1)
    router = DeterministicRouter()

    compatible = router.route(
        RouteRequest(
            snapshot=snapshot,
            created_at=at,
            mandatory_slow_reason_codes=("new_material_evidence",),
            bounded_acknowledgement_allowed=True,
        )
    )
    assert compatible.outcome is RoutingOutcome.FAST_NOW_AND_SLOW_REFRESH

    (offer,) = snapshot.offers
    changed = _resnapshot(
        snapshot, offers=(offer.model_copy(update={"revision": offer.revision + 1}),)
    )
    incompatible = router.route(
        RouteRequest(
            snapshot=changed, created_at=at, bounded_acknowledgement_allowed=True
        )
    )
    assert incompatible.outcome is RoutingOutcome.SLOW_REFRESH
    assert incompatible.reason_codes == ("strategy_basis_incompatible",)


def test_a_rejected_approval_routes_slow_refresh_and_refreshes_once() -> None:
    slow = _CountingSlow()
    repository = _ChannelRepository()
    runtime, _, _ = _created(slow, repository)
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )
    assert pending.approval is not None
    command_id = uuid4()
    decided_at = T0 + timedelta(minutes=6)

    rejected = runtime.approve(
        SCRIPTED_CASE_ID,
        pending.approval.approval_id,
        decision="rejected",
        occurred_at=decided_at,
        command_id=command_id,
    )

    # The recorded route is the Router's decision, not a hard-coded fast_now.
    assert isinstance(rejected.route, RoutingDecision)
    assert rejected.route.outcome is RoutingOutcome.SLOW_REFRESH
    assert rejected.route.reason_codes == ("strategy_basis_incompatible",)
    assert rejected.route == _route(rejected.snapshot, decided_at)
    assert _transition_route(repository, command_id) == "slow_refresh"
    assert slow.reason_codes == ["case_initialization"]

    at = T0 + timedelta(minutes=7)
    applied = runtime.apply_command(_channel_command(repository, at))

    assert slow.reason_codes == ["case_initialization", "strategy_basis_incompatible"]
    stored = _state(repository).snapshot
    _assert_bound(stored)
    assert stored.strategy is not None
    assert stored.strategy.created_at == at
    assert applied.delivery_id is not None
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    assert (outbox.source_strategy_id, outbox.source_strategy_revision) == (
        stored.strategy.strategy_id,
        stored.strategy.revision,
    )


def test_a_full_approved_flow_ends_in_a_bound_1_1_completion_receipt() -> None:
    runtime, repository, _ = _created()
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )
    assert pending.approval is not None
    _assert_bound(pending.snapshot)

    result = runtime.approve(
        SCRIPTED_CASE_ID,
        pending.approval.approval_id,
        occurred_at=T0 + timedelta(minutes=6),
    )

    assert result.execution_count == 1
    _assert_bound_receipt(result.snapshot)
    assert isinstance(result.route, RoutingDecision)
    assert result.route.outcome is RoutingOutcome.TERMINAL
    state = _state(repository)
    assert _through_postgres_envelope(state).snapshot == state.snapshot


def test_a_stored_1_0_case_refreshes_its_strategy_on_the_next_event() -> None:
    slow = _CountingSlow()
    runtime, repository, _ = _created(slow)
    created = _state(repository)
    legacy = _through_postgres_envelope(_as_stored_1_0(created))
    assert legacy.snapshot.schema_version == "1.0"
    assert legacy.snapshot.strategy is not None
    assert legacy.snapshot.strategy.schema_version == "1.0"
    repository.replace(
        SCRIPTED_CASE_ID, expected_revision=created.snapshot.revision, state=legacy
    )

    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )

    assert slow.reason_codes == ["case_initialization", "strategy_basis_incompatible"]
    _assert_bound(pending.snapshot)
    approval = pending.approval
    assert approval is not None
    assert pending.snapshot.strategy is not None
    assert (approval.strategy_id, approval.strategy_revision) == (
        pending.snapshot.strategy.strategy_id,
        pending.snapshot.strategy.revision,
    )

    result = runtime.approve(
        SCRIPTED_CASE_ID, approval.approval_id, occurred_at=T0 + timedelta(minutes=6)
    )

    _assert_bound_receipt(result.snapshot)
    assert slow.reason_codes == ["case_initialization", "strategy_basis_incompatible"]
    state = _state(repository)
    assert _through_postgres_envelope(state).snapshot == state.snapshot


def test_the_coordinator_rejects_a_1_0_strategy_on_a_1_1_snapshot() -> None:
    # The frozen ``ml/slow_output.py`` compiler still stamps 1.0 strategies.
    runtime, _, _ = _created()
    snapshot = runtime.current_result(SCRIPTED_CASE_ID).snapshot
    at = T0 + timedelta(minutes=1)
    request = CaseCoordinator.build_slow_request(
        snapshot, reason_code="case_initialization", created_at=at
    )
    result = ScriptedSlowAdapter().reason(request)
    assert result.strategy_proposal is not None
    legacy = StrategyPacket(
        **{
            **result.strategy_proposal.__dict__,
            "schema_version": "1.0",
            "planning_basis_fingerprint": None,
        }
    )
    legacy_result = result.model_copy(update={"strategy_proposal": legacy})

    audit = CaseCoordinator.validate_slow_result(
        legacy_result, snapshot, expected_request=request, evaluated_at=at
    )

    assert audit.accepted is False
    assert audit.reason_codes == ("slow_strategy_basis_mismatch",)


def test_the_router_does_not_flag_a_1_0_snapshot_with_a_1_0_strategy() -> None:
    _, repository, _ = _created()
    legacy = _as_stored_1_0(_state(repository)).snapshot
    assert legacy.schema_version == "1.0"
    assert legacy.strategy is not None
    assert legacy.strategy.planning_basis_fingerprint is None

    decision = _route(legacy, T0 + timedelta(minutes=1))

    assert decision.outcome is RoutingOutcome.FAST_NOW
    assert decision.reason_codes == ("current_strategy_dialogue",)


def test_a_stored_1_0_case_refreshes_exactly_once_through_channel_ingest() -> None:
    slow = _CountingSlow()
    repository = _ChannelRepository()
    runtime, _, _ = _created(slow, repository)
    created = _state(repository)
    legacy = _through_postgres_envelope(_as_stored_1_0(created))
    repository.replace(
        SCRIPTED_CASE_ID, expected_revision=created.snapshot.revision, state=legacy
    )

    first = runtime.apply_command(
        _channel_command(repository, T0 + timedelta(minutes=5))
    )

    assert first.route == "fast_now"
    assert slow.reason_codes == ["case_initialization", "strategy_basis_incompatible"]
    refreshed = _state(repository).snapshot
    _assert_bound(refreshed)
    assert first.delivery_id is not None
    outbox = repository.get_outbox_record(first.delivery_id)
    assert outbox is not None
    assert refreshed.strategy is not None
    assert (outbox.source_strategy_id, outbox.source_strategy_revision) == (
        refreshed.strategy.strategy_id,
        refreshed.strategy.revision,
    )

    runtime.apply_command(_channel_command(repository, T0 + timedelta(minutes=6)))

    assert slow.reason_codes == ["case_initialization", "strategy_basis_incompatible"]
    assert _state(repository).snapshot.strategy == refreshed.strategy


def test_a_stored_1_0_case_awaiting_approval_completes_at_1_1() -> None:
    runtime, repository, _ = _created()
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )
    assert pending.approval is not None
    waiting = _state(repository)
    legacy = _through_postgres_envelope(_as_stored_1_0(waiting))
    repository.replace(
        SCRIPTED_CASE_ID, expected_revision=waiting.snapshot.revision, state=legacy
    )

    result = runtime.approve(
        SCRIPTED_CASE_ID,
        pending.approval.approval_id,
        occurred_at=T0 + timedelta(minutes=6),
    )

    _assert_bound_receipt(result.snapshot)
    state = _state(repository)
    assert _through_postgres_envelope(state).snapshot == state.snapshot


class _ClaimCrashRepository(InMemoryCaseRepository):
    """Persist the execution claim, then fail as if the process died."""

    def replace(
        self,
        case_id: UUID,
        *,
        expected_revision: int,
        state: CaseRuntimeState,
    ) -> CaseRuntimeState:
        updated = super().replace(
            case_id, expected_revision=expected_revision, state=state
        )
        if state.snapshot.pending_execution:
            raise RuntimeError("simulated crash after the claim write")
        return updated


def test_a_stored_1_0_pending_claim_completes_in_its_claim_version() -> None:
    runtime, repository, _ = _created(repository=_ClaimCrashRepository())
    pending = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=T0 + timedelta(minutes=5),
    )
    assert pending.approval is not None
    with pytest.raises(RuntimeError, match="simulated crash"):
        runtime.approve(
            SCRIPTED_CASE_ID,
            pending.approval.approval_id,
            occurred_at=T0 + timedelta(minutes=6),
        )
    claimed = _state(repository)
    assert claimed.snapshot.pending_execution
    legacy = _through_postgres_envelope(_as_stored_1_0(claimed))
    resumed_repository = InMemoryCaseRepository()
    resumed_repository.create(legacy)
    resumed = ThinAgentRuntime(
        resumed_repository, clock=_Clock(T0 + timedelta(minutes=7))
    )

    result = resumed.approve(SCRIPTED_CASE_ID, pending.approval.approval_id)

    # The claim's source pins bind the 1.0 basis, so the claim completes at 1.0
    # and the stored execution pins still equal the terminal snapshot's pins.
    snapshot = result.snapshot
    assert snapshot.schema_version == "1.0"
    assert snapshot.case.phase is CasePhase.COMPLETE
    assert snapshot.completion_receipt is None
    state = _state(resumed_repository)
    assert state.execution_source_pins == snapshot.pins
    assert _through_postgres_envelope(state).snapshot == snapshot


def _strategy_output() -> SlowModelOutput:
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Reduce the recurring bill safely.",
            current_subgoal="Handle the latest fictional Provider turn safely.",
            ranked_preference_positions=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=(),
            fallback_outcomes=(),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional Provider confirmation is required.",
                ),
            ),
            escalation_conditions=(),
            replan_conditions=(),
        )
    )


def _scripted(request: SlowWorkRequest) -> StrategyPacket | None:
    return ScriptedSlowAdapter().reason(request).strategy_proposal


def _compiled(request: SlowWorkRequest) -> StrategyPacket | None:
    return compile_slow_output(request, _strategy_output()).strategy_proposal


@pytest.mark.parametrize("produce", [_scripted, _compiled])
def test_strategy_producers_stamp_the_version_of_their_planning_basis(
    produce: Callable[[SlowWorkRequest], StrategyPacket | None],
) -> None:
    _, repository, _ = _created()
    current = _state(repository).snapshot
    at = T0 + timedelta(minutes=1)
    for snapshot, version in (
        (current, "1.1"),
        (_as_stored_1_0(_state(repository)).snapshot, "1.0"),
    ):
        request = CaseCoordinator.build_slow_request(
            snapshot, reason_code="case_initialization", created_at=at
        )
        strategy = produce(request)
        assert strategy is not None
        assert strategy.schema_version == version
        if version == "1.1":
            assert strategy.planning_basis_fingerprint == (
                request.planning_basis.planning_basis_fingerprint
            )
        else:
            assert "planning_basis_fingerprint" not in json.loads(
                strategy.model_dump_json()
            )
