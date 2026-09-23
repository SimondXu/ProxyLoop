"""The runtime capability manifest lives until the Case deadline (A-11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from proxyloop_agent_core import (
    CapabilityExecutionOutcome,
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    PreparedSimulatorExecution,
)
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime.runtime import (
    _build_approval,
    _capability_proposal,
    _snapshot,
)
from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityManifest,
    CapabilityProposal,
    CaseContextSnapshot,
    CasePhase,
    Evidence,
    EvidenceType,
    OfferReference,
    ProviderOffer,
)
from proxyloop_contracts.material_terms import (
    material_terms_hash,
    offer_material_terms,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _AcceptCapability:
    def __init__(self, case_id: UUID, *, at: datetime) -> None:
        self._case_id = case_id
        self._at = at

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        del proposal
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            case_id=self._case_id,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash="e" * 64,
            observed_at=self._at,
            captured_at=self._at,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=lambda: None)


def _created() -> tuple[ThinAgentRuntime, _Clock, CaseContextSnapshot]:
    clock = _Clock(T0)
    runtime = ThinAgentRuntime(InMemoryCaseRepository(), clock=clock)
    snapshot = runtime.create_case(occurred_at=T0).snapshot
    return runtime, clock, snapshot


def _offer_until(snapshot: CaseContextSnapshot, expires_at: datetime) -> ProviderOffer:
    return ProviderOffer.model_validate(
        {**snapshot.offers[0].model_dump(), "expires_at": expires_at}
    )


def _one_day_manifest(manifest: CapabilityManifest) -> CapabilityManifest:
    """The manifest ``main`` minted before A-11: ``issued_at + 1 day``."""
    expires_at = manifest.issued_at + timedelta(days=1)
    return CapabilityManifest.model_validate(
        {
            **manifest.model_dump(),
            "expires_at": expires_at,
            "capabilities": tuple(
                {**item.model_dump(), "expires_at": expires_at}
                for item in manifest.capabilities
            ),
        }
    )


def _approved(
    snapshot: CaseContextSnapshot,
    offer: ProviderOffer,
    *,
    decided_at: datetime,
) -> tuple[ActionIntent, ApprovalRequest]:
    case = snapshot.case
    strategy = snapshot.strategy
    assert strategy is not None
    terms = offer_material_terms(offer)
    intent = ActionIntent(
        contract_type="action_intent",
        schema_version="1.0",
        revision=1,
        intent_id=UUID("11111111-1111-4111-8111-111111111111"),
        case_id=case.case_id,
        case_revision=case.revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        constraint_set_revision=case.constraint_set_revision,
        action_type=ActionType.ACCEPT_OFFER,
        offer_ref=OfferReference(
            offer_id=offer.offer_id, offer_revision=offer.revision
        ),
        material_terms=terms,
        material_terms_hash=material_terms_hash(terms),
        approval_required=True,
        idempotency_key=f"a-11:{case.case_id}:accept-offer",
        created_at=offer.created_at,
        expires_at=offer.expires_at,
    )
    approval = ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=2,
        approval_id=UUID("22222222-2222-4222-8222-222222222222"),
        case_id=intent.case_id,
        case_revision=intent.case_revision,
        action_intent_id=intent.intent_id,
        action_intent_revision=intent.revision,
        action_type=intent.action_type,
        strategy_id=intent.strategy_id,
        strategy_revision=intent.strategy_revision,
        constraint_set_revision=intent.constraint_set_revision,
        offer_ref=intent.offer_ref,
        material_terms_hash=intent.material_terms_hash,
        requested_at=intent.created_at,
        expires_at=offer.expires_at,
        decision=ApprovalDecision.APPROVED,
        decided_at=decided_at,
    )
    return intent, approval


def _execute(
    created: CaseContextSnapshot,
    offer: ProviderOffer,
    manifest: CapabilityManifest,
    *,
    executed_at: datetime,
) -> CapabilityExecutionOutcome:
    intent, approval = _approved(created, offer, decided_at=T0 + timedelta(hours=1))
    snapshot = _snapshot(
        case=created.case,
        ledger=created.fact_ledger,
        strategy=created.strategy,
        offers=(offer,),
        action_intents=(intent,),
        approvals=(approval,),
        evidence=created.evidence,
        completion=None,
        events=created.visible_events,
        snapshot_revision=created.revision + 1,
        phase=CasePhase.AWAITING_APPROVAL,
        manifest=manifest,
    )
    executor = CapabilityExecutor(
        _AcceptCapability(created.case.case_id, at=executed_at),
        terms_derivation=offer_material_terms,
    )
    return executor.execute(
        CapabilityExecutionRequest(
            snapshot=snapshot,
            source_pins=snapshot.pins,
            proposal=_capability_proposal(offer, created_at=T0 + timedelta(hours=1)),
            action_intent=intent,
            approval=approval,
            executed_at=executed_at,
        )
    )


def test_a_48_hour_approval_executes_after_the_first_day() -> None:
    _, _, created = _created()
    offer = _offer_until(created, T0 + timedelta(hours=48))
    executed_at = T0 + timedelta(hours=25)

    outcome = _execute(
        created, offer, created.capability_manifest, executed_at=executed_at
    )

    assert outcome.status is CapabilityExecutionStatus.EXECUTED, outcome.reason_codes


def test_the_one_day_manifest_rejects_the_same_48_hour_approval() -> None:
    # Counter-control: only the manifest lifetime differs from the test above.
    _, _, created = _created()
    offer = _offer_until(created, T0 + timedelta(hours=48))

    outcome = _execute(
        created,
        offer,
        _one_day_manifest(created.capability_manifest),
        executed_at=T0 + timedelta(hours=25),
    )

    assert outcome.status is CapabilityExecutionStatus.REJECTED
    assert set(outcome.reason_codes) == {
        "capability_manifest_expired",
        "capability_expired",
    }


def test_execution_before_the_deadline_is_allowed() -> None:
    _, _, created = _created()
    deadline = created.case.goal.deadline
    assert deadline is not None
    offer = _offer_until(created, deadline)

    outcome = _execute(
        created,
        offer,
        created.capability_manifest,
        executed_at=deadline - timedelta(minutes=1),
    )

    assert outcome.status is CapabilityExecutionStatus.EXECUTED, outcome.reason_codes


@pytest.mark.parametrize("after", [timedelta(0), timedelta(hours=1)])
def test_execution_at_or_after_the_deadline_is_rejected(after: timedelta) -> None:
    _, _, created = _created()
    deadline = created.case.goal.deadline
    assert deadline is not None
    offer = _offer_until(created, deadline)

    outcome = _execute(
        created,
        offer,
        created.capability_manifest,
        executed_at=deadline + after,
    )

    assert outcome.status is CapabilityExecutionStatus.REJECTED
    assert "capability_manifest_expired" in outcome.reason_codes


def test_a_new_case_mints_one_manifest_that_expires_at_the_deadline() -> None:
    runtime, clock, created = _created()
    manifest = created.capability_manifest

    assert created.case.goal.deadline == T0 + timedelta(days=9)
    assert manifest.issued_at == created.case.created_at == T0
    assert manifest.expires_at == created.case.goal.deadline
    assert all(
        item.expires_at == created.case.goal.deadline for item in manifest.capabilities
    )

    clock.now = T0 + timedelta(minutes=1)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Is the offer ready?")

    assert waiting.snapshot.capability_manifest == manifest
    (approval,) = waiting.snapshot.approval_requests
    assert approval.expires_at <= manifest.expires_at


def test_the_runtime_refuses_an_approval_outliving_the_manifest() -> None:
    _, _, created = _created()
    manifest = created.capability_manifest
    requested_at = T0 + timedelta(minutes=1)

    _, approval = _build_approval(
        created.case,
        created.strategy,
        _offer_until(created, manifest.expires_at),
        requested_at=requested_at,
        manifest=manifest,
    )
    assert approval.expires_at == manifest.expires_at

    with pytest.raises(RuntimeError, match="capability manifest"):
        _build_approval(
            created.case,
            created.strategy,
            _offer_until(created, manifest.expires_at + timedelta(seconds=1)),
            requested_at=requested_at,
            manifest=manifest,
        )
