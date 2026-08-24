#!/usr/bin/env python3
"""Run the deterministic Phase 03A1 multi-turn harness.

The command generates committed deterministic evidence with ``--write`` and
``--check`` verifies exact artifact drift, manifest isolation, public-event
leakage, runtime authority probes, and the scripted-oracle ceiling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from proxyloop_agent_core import (
    CapabilityExecutionOutcome,
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    DeterministicRouter,
    FastAdapterResult,
    PreparedSimulatorExecution,
    RouteRequest,
    SafeObservation,
    SafeObservationAdapter,
    SafeOffer,
    ScriptedFastAdapter,
    ScriptedOracleConsumer,
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
    FactStatus,
    FastTurnDecision,
    LineItem,
    LineItemCategory,
    MaterialTerm,
    ModelInputPins,
    ModelResult,
    ModelTrace,
    Money,
    OfferReference,
    PlanningBasis,
    ProviderOffer,
    SlowWorkResult,
    StrategyPacket,
    VisibleCaseEvent,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnProviderEnvironment,
    MultiTurnTransition,
    Phase03A1Manifest,
    SimulatorCapabilityAttempt,
    generate_phase03a1_manifest,
)
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
)

FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "family_id",
        "entity_cluster",
        "configuration_id",
        "provider_configuration_id",
        "provider_configuration_version",
        "private_policy",
        "reference_action",
        "expected_action",
        "expected_outcome",
        "reward",
        "verifier_criteria",
        "account_state",
        "database_state",
        "gold_label",
        "evaluator_criteria",
        "private_reason_codes",
        "oracle_action",
        "oracle_offer_id",
        "oracle_reason_codes",
    }
)
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "manifests" / "phase-03a1-manifest.json"
EPISODES_PATH = ROOT / "data" / "manifests" / "phase-03a1-episodes.json"
CEILING_PATH = ROOT / "data" / "manifests" / "phase-03a1-ceiling-report.json"
PROBE_NOW = datetime(2026, 8, 23, 12, 20, tzinfo=UTC)
PROBE_CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROBE_STRATEGY_ID = UUID("99999999-9999-4999-8999-999999999999")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _scripted_model_trace(
    *,
    adapter: str,
    case_id: UUID,
    output_fingerprint: str,
) -> dict[str, object]:
    return ModelTrace(
        contract_type="model_trace",
        schema_version="1.0",
        revision=1,
        trace_id=_stable_uuid4(f"trace:{adapter}:{output_fingerprint}"),
        case_id=case_id,
        started_at=PROBE_NOW,
        completed_at=PROBE_NOW,
        provider="proxyloop_harness",
        model=adapter,
        model_version="phase-03a1-scripted-v1",
        adapter_version="phase-03a1-v1",
        prompt_version="no-prompt-scripted-v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        latency_ms=0,
        input_tokens=0,
        output_tokens=0,
        result=ModelResult.SUCCEEDED,
        output_ref=output_fingerprint,
        safety_flags=(),
    ).model_dump(mode="json")


def _leaked_keys(value: object) -> tuple[str, ...]:
    leaked: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                leaked.add(key)
            leaked.update(_leaked_keys(child))
    elif isinstance(value, list):
        for child in value:
            leaked.update(_leaked_keys(child))
    return tuple(sorted(leaked))


def _safe_offers(turn: ProviderTurn) -> tuple[SafeOffer, ...]:
    return tuple(
        SafeOffer(
            offer_id=offer.offer_id,
            provider_id=turn.provider_id,
            monthly_price_minor=offer.monthly_price_minor,
            total_cost_12_months_minor=offer.total_cost_12_months_minor,
            currency=offer.currency,
            features=offer.features,
            fees_minor=offer.fees_minor,
            term_months=offer.term_months,
            applied_changes=offer.applied_changes,
            expires_at=offer.expires_at,
        )
        for offer in turn.offers
    )


def _safe_observation(case: Any, turn: ProviderTurn) -> SafeObservation:
    return SafeObservationAdapter.build(
        case,
        provider_id=turn.provider_id,
        provider_message=turn.message,
        offers=_safe_offers(turn),
        requested_disclosures=("account_pin",) if turn.disclosure_restricted else (),
        needs_clarification=turn.clarification_required,
        transfer_available=turn.transfer_available,
        approval_current=turn.approval_current,
        confirmation_evidence_available=turn.confirmation_evidence_available,
        observed_at=turn.observed_at,
    )


def _planning_basis(
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
    return PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )


def _probe_strategy() -> StrategyPacket:
    return StrategyPacket(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=1,
        strategy_id=PROBE_STRATEGY_ID,
        case_id=PROBE_CASE_ID,
        case_revision=1,
        fact_ledger_revision=1,
        created_at=PROBE_NOW - timedelta(minutes=20),
        expires_at=PROBE_NOW + timedelta(hours=1),
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


def _probe_capability_manifest() -> CapabilityManifest:
    action_types = {
        "accept_offer": ActionType.ACCEPT_OFFER,
        "request_clarification": ActionType.REQUEST_CLARIFICATION,
        "escalate": ActionType.SEND_MESSAGE,
        "request_replan": ActionType.SEND_MESSAGE,
        "refuse_disclosure": ActionType.SEND_MESSAGE,
        "decline": ActionType.SEND_MESSAGE,
    }
    return CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="phase-03a1-simulator-capabilities-v1",
        issued_at=PROBE_NOW - timedelta(hours=1),
        expires_at=PROBE_NOW + timedelta(hours=2),
        capabilities=tuple(
            CapabilityDefinition(
                capability_id=f"simulator.{capability_name}",
                version="1.0",
                description=f"Execute the bounded {capability_name} simulator input.",
                namespace="simulator",
                allowed_action_types=(action_type,),
                expires_at=PROBE_NOW + timedelta(hours=1),
            )
            for capability_name, action_type in action_types.items()
        ),
    )


def _probe_snapshot() -> tuple[
    CaseContextSnapshot,
    Phase01AEpisode,
    ApprovalRequest,
    ApprovalRequest,
]:
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    pending_approval = episode.request_approval()
    approved = episode.approve()
    strategy = _probe_strategy()
    manifest = _probe_capability_manifest()
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=episode.case.case_id,
        created_at=PROBE_NOW - timedelta(hours=1),
        updated_at=PROBE_NOW,
        entries=(),
    )
    basis = _planning_basis(
        case=episode.case,
        ledger=ledger,
        offers=(offer,),
        approvals=(approved,),
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
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
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
        strategy=strategy,
        offers=(offer,),
        approval_requests=(approved,),
        visible_events=(
            VisibleCaseEvent(
                contract_type="visible_case_event",
                schema_version="1.0",
                revision=1,
                event_id=UUID("88888888-8888-4888-8888-888888888888"),
                case_id=episode.case.case_id,
                event_cursor=1,
                occurred_at=PROBE_NOW,
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
    return snapshot, episode, pending_approval, approved


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _canonical_provider_offer(
    public_offer: PublicOffer,
    *,
    case_id: UUID,
    provider_id: str,
    observed_at: datetime,
) -> ProviderOffer:
    fees = (
        (
            LineItem(
                name="Fictional Provider fees",
                category=LineItemCategory.FEE,
                amount=Money(
                    amount_minor=public_offer.fees_minor,
                    currency=public_offer.currency,
                ),
            ),
        )
        if public_offer.fees_minor
        else ()
    )
    return ProviderOffer(
        contract_type="provider_offer",
        schema_version="1.0",
        revision=public_offer.revision,
        offer_id=_stable_uuid4(f"offer:{public_offer.offer_id}"),
        case_id=case_id,
        provider_id=provider_id,
        created_at=observed_at - timedelta(minutes=1),
        expires_at=public_offer.expires_at,
        monthly_price=Money(
            amount_minor=public_offer.monthly_price_minor,
            currency=public_offer.currency,
        ),
        total_cost=Money(
            amount_minor=public_offer.total_cost_12_months_minor,
            currency=public_offer.currency,
        ),
        fees=fees,
        features=public_offer.features,
        term_months=public_offer.term_months,
        evidence_ids=(_stable_uuid4(f"offer-evidence:{public_offer.offer_id}"),),
    )


def _material_terms(offer: ProviderOffer) -> tuple[MaterialTerm, ...]:
    return (
        MaterialTerm(name="monthly_price", value=str(offer.monthly_price.amount_minor)),
        MaterialTerm(name="total_cost", value=str(offer.total_cost.amount_minor)),
        MaterialTerm(name="term_months", value=str(offer.term_months)),
    )


def _material_terms_hash(terms: tuple[MaterialTerm, ...]) -> str:
    return _fingerprint(
        sorted(
            (term.model_dump(mode="json") for term in terms),
            key=lambda item: (str(item["name"]), str(item["value"])),
        )
    )


def _episode_execution_context(
    *,
    case: Case,
    scenario: BenchmarkScenario,
    opening: ProviderTurn,
    attempt: SimulatorCapabilityAttempt,
) -> tuple[
    CaseContextSnapshot,
    CapabilityProposal,
    ActionIntent,
    ApprovalRequest | None,
]:
    manifest = _probe_capability_manifest()
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=_stable_uuid4(f"ledger:{scenario.scenario_id}"),
        case_id=case.case_id,
        created_at=case.created_at,
        updated_at=opening.observed_at,
        entries=(),
    )
    offers = tuple(
        _canonical_provider_offer(
            offer,
            case_id=case.case_id,
            provider_id=opening.provider_id,
            observed_at=opening.observed_at,
        )
        for offer in opening.offers
    )
    selected_offer = None
    if attempt.offer_id is not None:
        selected_offer = next(
            offer
            for public_offer, offer in zip(opening.offers, offers, strict=True)
            if public_offer.offer_id == attempt.offer_id
        )
    action_type = (
        ActionType.ACCEPT_OFFER
        if attempt.capability_id == "simulator.accept_offer"
        else (
            ActionType.REQUEST_CLARIFICATION
            if attempt.capability_id == "simulator.request_clarification"
            else ActionType.SEND_MESSAGE
        )
    )
    terms = _material_terms(selected_offer) if selected_offer is not None else ()
    strategy = _probe_strategy()
    intent = ActionIntent(
        contract_type="action_intent",
        schema_version="1.0",
        revision=1,
        intent_id=_stable_uuid4(f"intent:{scenario.scenario_id}"),
        case_id=case.case_id,
        case_revision=case.revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        constraint_set_revision=case.constraint_set_revision,
        action_type=action_type,
        offer_ref=(
            OfferReference(
                offer_id=selected_offer.offer_id,
                offer_revision=selected_offer.revision,
            )
            if selected_offer is not None
            else None
        ),
        material_terms=terms,
        material_terms_hash=_material_terms_hash(terms),
        approval_required=action_type is ActionType.ACCEPT_OFFER,
        idempotency_key=attempt.idempotency_key,
        created_at=PROBE_NOW - timedelta(minutes=3),
        expires_at=PROBE_NOW + timedelta(minutes=10),
    )
    approval = None
    if action_type is ActionType.ACCEPT_OFFER:
        approval = ApprovalRequest(
            contract_type="approval_request",
            schema_version="1.0",
            revision=2,
            approval_id=_stable_uuid4(f"approval:{scenario.scenario_id}"),
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
            requested_at=PROBE_NOW - timedelta(minutes=2),
            expires_at=PROBE_NOW + timedelta(minutes=10),
            decision=ApprovalDecision.APPROVED,
            decided_at=PROBE_NOW - timedelta(minutes=1),
        )
    approvals = (approval,) if approval is not None else ()
    basis = _planning_basis(
        case=case,
        ledger=ledger,
        offers=offers,
        approvals=approvals,
        provider_config_ref=scenario.configuration_id,
        manifest=manifest,
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=ledger.revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=1,
        provider_config_ref=scenario.configuration_id,
        capability_manifest_version=manifest.manifest_version,
    )
    event = VisibleCaseEvent(
        contract_type="visible_case_event",
        schema_version="1.0",
        revision=1,
        event_id=_stable_uuid4(f"event:{scenario.scenario_id}:1"),
        case_id=case.case_id,
        event_cursor=1,
        occurred_at=opening.observed_at,
        actor=EventActor.PROVIDER,
        event_type="provider_turn",
        content=opening.message,
    )
    snapshot = CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=1,
        case=case,
        fact_ledger=ledger,
        strategy=strategy,
        offers=offers,
        action_intents=(intent,),
        approval_requests=approvals,
        visible_events=(event,),
        event_cursor=1,
        planning_basis=basis,
        pins=pins,
        provider_config_ref=scenario.configuration_id,
        capability_manifest=manifest,
    )
    arguments = (
        (
            CapabilityArgument(
                name="offer_id",
                value=str(selected_offer.offer_id),
            ),
        )
        if selected_offer is not None
        else ()
    )
    proposal = CapabilityProposal(
        proposal_id=_stable_uuid4(f"proposal:{scenario.scenario_id}"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id=attempt.capability_id,
            version="1.0",
        ),
        arguments=arguments,
        created_at=PROBE_NOW - timedelta(minutes=1),
        expires_at=PROBE_NOW + timedelta(minutes=5),
    )
    return snapshot, proposal, intent, approval


@dataclass
class _EpisodeCapabilityAdapter:
    environment: MultiTurnProviderEnvironment
    attempt: SimulatorCapabilityAttempt
    canonical_offer_id: str | None
    observed_at: datetime
    transition: MultiTurnTransition | None = None
    commits: int = 0

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        if proposal.capability.capability_id != self.attempt.capability_id:
            raise ValueError("proposal capability does not match simulator attempt")
        if idempotency_key != self.attempt.idempotency_key:
            raise ValueError("idempotency key does not match simulator attempt")
        proposal_offer_id = next(
            (
                str(argument.value)
                for argument in proposal.arguments
                if argument.name == "offer_id"
            ),
            None,
        )
        if proposal_offer_id != self.canonical_offer_id:
            raise ValueError("proposal offer binding does not match simulator attempt")
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=_stable_uuid4(f"execution-evidence:{idempotency_key}"),
            case_id=PROBE_CASE_ID,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash=canonical_fingerprint(self.attempt.to_dict()),
            observed_at=self.observed_at,
            captured_at=PROBE_NOW,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=self._commit)

    def _commit(self) -> None:
        self.transition = self.environment.submit_capability_attempt(self.attempt)
        self.commits += 1


@dataclass
class _ProbeCapabilityAdapter:
    evidence_mode: str = "valid"
    invocations: int = 0

    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        del proposal
        if self.evidence_mode == "missing":
            return cast(PreparedSimulatorExecution, None)
        source_type = (
            EvidenceType.PROVIDER_MESSAGE
            if self.evidence_mode == "forged"
            else EvidenceType.SIMULATOR_TRANSITION
        )
        source_ref = (
            "different-execution"
            if self.evidence_mode == "mismatched_binding"
            else idempotency_key
        )
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            case_id=PROBE_CASE_ID,
            source_type=source_type,
            source_ref=source_ref,
            content_hash="e" * 64,
            observed_at=PROBE_NOW,
            captured_at=PROBE_NOW,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=self._commit)

    def _commit(self) -> None:
        self.invocations += 1


def _build_router_probe_report(
    snapshot: CaseContextSnapshot, pending: ApprovalRequest
) -> dict[str, object]:
    router = DeterministicRouter()
    no_strategy_pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    no_strategy = snapshot.model_copy(
        update={
            "strategy": None,
            "pins": no_strategy_pins,
            "approval_requests": (),
        }
    )
    closed_case = snapshot.case.model_copy(update={"phase": CasePhase.CLOSED})
    fixtures: tuple[tuple[str, CaseContextSnapshot, tuple[str, ...], bool], ...] = (
        (
            "terminal",
            snapshot.model_copy(update={"case": closed_case}),
            (),
            False,
        ),
        (
            "verify_only",
            snapshot.model_copy(update={"pending_execution": True}),
            (),
            False,
        ),
        (
            "wait_for_approval",
            snapshot.model_copy(update={"approval_requests": (pending,)}),
            (),
            False,
        ),
        (
            "slow_refresh",
            no_strategy,
            (),
            False,
        ),
        (
            "fast_now_and_slow_refresh",
            snapshot.model_copy(update={"approval_requests": ()}),
            ("material_offer_changed",),
            True,
        ),
        (
            "fast_now",
            snapshot.model_copy(update={"approval_requests": ()}),
            (),
            False,
        ),
    )
    rows: list[dict[str, object]] = []
    for expected, candidate, mandatory_reasons, bounded in fixtures:
        actual = router.route(
            RouteRequest(
                snapshot=candidate,
                created_at=PROBE_NOW,
                mandatory_slow_reason_codes=mandatory_reasons,
                bounded_acknowledgement_allowed=bounded,
            )
        )
        rows.append(
            {
                "expected": expected,
                "actual": actual.outcome.value,
                "reason_codes": list(actual.reason_codes),
                "passed": actual.outcome.value == expected,
            }
        )
    reasoner_rows = (
        accepted_fast_reasoner_trigger(
            ReasonerRequest(needed=True, reason_code="conflicting_facts")
        )
        == ("fast_reasoner_request:conflicting_facts",),
        accepted_fast_reasoner_trigger(
            ReasonerRequest(needed=True, reason_code="force_slow")
        )
        == (),
        accepted_fast_reasoner_trigger(
            ReasonerRequest(needed=False, reason_code="conflicting_facts")
        )
        == (),
    )
    return {
        "probe_count": len(rows),
        "agreement_count": sum(1 for row in rows if row["passed"] is True),
        "reasoner_request_probe_count": len(reasoner_rows),
        "reasoner_request_agreement_count": sum(reasoner_rows),
        "rows": rows,
    }


def _build_authorization_probe_report(
    snapshot: CaseContextSnapshot,
    episode: Phase01AEpisode,
    approved: ApprovalRequest,
) -> dict[str, object]:
    action_intent = episode.action_intent
    if action_intent is None:
        raise RuntimeError("probe episode requires an Action Intent")
    if action_intent.offer_ref is None:
        raise RuntimeError("probe Action Intent requires an exact offer reference")
    proposal = CapabilityProposal(
        proposal_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        capability=CapabilityReference(
            namespace="simulator",
            capability_id="simulator.accept_offer",
            version="1.0",
        ),
        arguments=(
            CapabilityArgument(
                name="offer_id",
                value=str(action_intent.offer_ref.offer_id),
            ),
        ),
        created_at=PROBE_NOW - timedelta(minutes=1),
        expires_at=PROBE_NOW + timedelta(minutes=5),
    )

    def request(
        *,
        candidate_snapshot: CaseContextSnapshot = snapshot,
        source_pins: ModelInputPins = snapshot.pins,
        candidate_proposal: CapabilityProposal = proposal,
        approval: ApprovalRequest | None = approved,
    ) -> CapabilityExecutionRequest:
        return CapabilityExecutionRequest(
            snapshot=candidate_snapshot,
            source_pins=source_pins,
            proposal=candidate_proposal,
            action_intent=action_intent,
            approval=approval,
            executed_at=PROBE_NOW,
        )

    rows: list[dict[str, object]] = []

    def record(name: str, expected: str, outcome: CapabilityExecutionOutcome) -> None:
        rows.append(
            {
                "name": name,
                "expected": expected,
                "actual": outcome.status.value,
                "reason_codes": list(outcome.reason_codes),
                "passed": outcome.status.value == expected,
            }
        )

    valid_adapter = _ProbeCapabilityAdapter()
    valid_executor = CapabilityExecutor(valid_adapter)
    first = valid_executor.execute(request())
    record("authorized_execution", CapabilityExecutionStatus.EXECUTED.value, first)
    duplicate = valid_executor.execute(request())
    record("duplicate_execution", CapabilityExecutionStatus.REUSED.value, duplicate)
    changed_proposal = proposal.model_copy(
        update={"proposal_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")}
    )
    record(
        "idempotency_binding_mismatch",
        CapabilityExecutionStatus.REJECTED.value,
        valid_executor.execute(request(candidate_proposal=changed_proposal)),
    )

    stale_pins = snapshot.pins.model_copy(update={"event_cursor": 2})
    record(
        "stale_proposal",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(
            request(source_pins=stale_pins)
        ),
    )
    unsupported = proposal.model_copy(
        update={
            "capability": CapabilityReference(
                namespace="simulator",
                capability_id="simulator.unsupported",
                version="1.0",
            )
        }
    )
    record(
        "unsupported_capability",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(
            request(candidate_proposal=unsupported)
        ),
    )
    record(
        "missing_approval",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(request(approval=None)),
    )
    mismatched_approval = approved.model_copy(update={"material_terms_hash": "f" * 64})
    record(
        "approval_binding_mismatch",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(
            request(approval=mismatched_approval)
        ),
    )
    expired_approval = approved.model_copy(
        update={"expires_at": PROBE_NOW - timedelta(seconds=1)}
    )
    record(
        "expired_approval",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(
            request(approval=expired_approval)
        ),
    )
    changed_offer = snapshot.offers[0].model_copy(update={"revision": 2})
    record(
        "changed_offer",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(_ProbeCapabilityAdapter()).execute(
            request(
                candidate_snapshot=snapshot.model_copy(
                    update={"offers": (changed_offer,)}
                )
            )
        ),
    )
    missing_adapter = _ProbeCapabilityAdapter("missing")
    record(
        "missing_evidence",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(missing_adapter).execute(request()),
    )
    forged_adapter = _ProbeCapabilityAdapter("forged")
    record(
        "forged_evidence",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(forged_adapter).execute(request()),
    )
    mismatched_binding_adapter = _ProbeCapabilityAdapter("mismatched_binding")
    record(
        "evidence_execution_binding_mismatch",
        CapabilityExecutionStatus.REJECTED.value,
        CapabilityExecutor(mismatched_binding_adapter).execute(request()),
    )
    return {
        "probe_count": len(rows),
        "agreement_count": sum(1 for row in rows if row["passed"] is True),
        "provider_mutation_count": valid_adapter.invocations,
        "rejected_evidence_mutation_count": (
            missing_adapter.invocations
            + forged_adapter.invocations
            + mismatched_binding_adapter.invocations
        ),
        "rows": rows,
    }


def _build_stale_result_probe_report(
    snapshot: CaseContextSnapshot,
    episode: Phase01AEpisode,
) -> dict[str, object]:
    coordinator = CaseCoordinator()
    current_decision = FastTurnDecision(
        contract_type="fast_turn_decision",
        schema_version="1.0",
        decision_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        case_id=PROBE_CASE_ID,
        case_revision=1,
        strategy_id=PROBE_STRATEGY_ID,
        strategy_revision=1,
        created_at=PROBE_NOW,
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="Could you confirm the next step?",
    )
    stale_pins = snapshot.pins.model_copy(update={"event_cursor": 2})
    stale_fast = coordinator.validate_fast_result(
        FastAdapterResult(pins=stale_pins, decision=current_decision),
        snapshot,
    )
    if episode.action_intent is None:
        raise RuntimeError("probe episode requires an Action Intent")
    forbidden_fast = coordinator.validate_fast_result(
        FastAdapterResult(
            pins=snapshot.pins,
            decision=current_decision.model_copy(
                update={"action_intent": episode.action_intent}
            ),
        ),
        snapshot,
    )
    stale_slow = coordinator.validate_slow_result(
        SlowWorkResult(
            contract_type="slow_work_result",
            schema_version="1.0",
            revision=1,
            result_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            request_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            case_id=PROBE_CASE_ID,
            pins=stale_pins,
            planning_basis=snapshot.planning_basis,
            created_at=PROBE_NOW,
        ),
        snapshot,
    )
    rows = (
        {
            "name": "stale_fast",
            "passed": not stale_fast.accepted,
            "reason_codes": list(stale_fast.reason_codes),
        },
        {
            "name": "forbidden_fast_action_intent",
            "passed": not forbidden_fast.accepted,
            "reason_codes": list(forbidden_fast.reason_codes),
        },
        {
            "name": "stale_slow",
            "passed": not stale_slow.accepted,
            "reason_codes": list(stale_slow.reason_codes),
        },
    )
    return {
        "probe_count": len(rows),
        "rejection_count": sum(1 for row in rows if row["passed"] is True),
        "rows": list(rows),
    }


def _build_runtime_probe_report() -> dict[str, object]:
    snapshot, episode, pending, approved = _probe_snapshot()
    router = _build_router_probe_report(snapshot, pending)
    authorization = _build_authorization_probe_report(snapshot, episode, approved)
    stale_results = _build_stale_result_probe_report(snapshot, episode)
    gate_passed = (
        router["agreement_count"] == router["probe_count"]
        and router["reasoner_request_agreement_count"]
        == router["reasoner_request_probe_count"]
        and authorization["agreement_count"] == authorization["probe_count"]
        and authorization["provider_mutation_count"] == 1
        and authorization["rejected_evidence_mutation_count"] == 0
        and stale_results["rejection_count"] == stale_results["probe_count"]
    )
    return {
        "schema_version": "phase-03a1-runtime-probes-v1",
        "router": router,
        "authorization": authorization,
        "stale_results": stale_results,
        "gate_passed": gate_passed,
    }


def _run_episode(
    scenario: BenchmarkScenario,
    *,
    case: Any,
    manifest: Phase03A1Manifest,
) -> dict[str, object]:
    environment = MultiTurnProviderEnvironment(scenario)
    opening = environment.start()
    observation = _safe_observation(case, opening.turn)
    observation_payload = observation.to_dict()
    oracle_decision = ScriptedOracleConsumer().decide(observation)

    attempt = SimulatorCapabilityAttempt(
        capability_id=f"simulator.{oracle_decision.action.value}",
        offer_id=oracle_decision.offer_id,
        idempotency_key=f"oracle:{scenario.scenario_id}",
    )
    snapshot, proposal, action_intent, approval = _episode_execution_context(
        case=case,
        scenario=scenario,
        opening=opening.turn,
        attempt=attempt,
    )
    capability_adapter = _EpisodeCapabilityAdapter(
        environment=environment,
        attempt=attempt,
        canonical_offer_id=(
            str(action_intent.offer_ref.offer_id)
            if action_intent.offer_ref is not None
            else None
        ),
        observed_at=opening.observed_at,
    )
    executor = CapabilityExecutor(capability_adapter)
    execution_request = CapabilityExecutionRequest(
        snapshot=snapshot,
        source_pins=snapshot.pins,
        proposal=proposal,
        action_intent=action_intent,
        approval=approval,
        executed_at=PROBE_NOW,
    )
    first_execution = executor.execute(execution_request)
    duplicate_execution = executor.execute(execution_request)
    transition = capability_adapter.transition
    if (
        first_execution.status is not CapabilityExecutionStatus.EXECUTED
        or duplicate_execution.status is not CapabilityExecutionStatus.REUSED
        or capability_adapter.commits != 1
        or transition is None
    ):
        raise RuntimeError("formal episode did not pass the sole Executor lane")

    public_episode = environment.export_public_episode()
    assignment = manifest.assignment_for(scenario.scenario_id)
    routing_decisions, typed_adapter_traces = _episode_routing_decisions(
        snapshot,
        allow_strategy_refresh=assignment.reference_strategy_fixture_eligible,
    )
    row: dict[str, object] = {
        "episode_id": f"episode-{scenario.scenario_id}",
        "split": assignment.split,
        "provider_split": assignment.provider_split,
        "development_eligible": assignment.development_eligible,
        "reference_strategy_fixture_eligible": (
            assignment.reference_strategy_fixture_eligible
        ),
        "observation_fingerprint": _fingerprint(observation_payload),
        "routing_decisions": routing_decisions,
        "adapter_traces": [
            *typed_adapter_traces,
        ],
        "consumer_policy_trace": {
            "policy": "scripted_oracle_consumer",
            "policy_version": "scripted-oracle-v1",
            "result": "accepted",
            "input_fingerprint": _fingerprint(observation_payload),
            "output_fingerprint": _fingerprint(
                {
                    "action": oracle_decision.action.value,
                    "offer_id": oracle_decision.offer_id,
                }
            ),
        },
        "capability_attempt": attempt.to_dict(),
        "execution": {
            "first_status": first_execution.status.value,
            "duplicate_status": duplicate_execution.status.value,
            "commit_count": capability_adapter.commits,
            "evidence_id": str(first_execution.evidence.evidence_id)
            if first_execution.evidence is not None
            else None,
        },
        "public_episode": public_episode,
        "transition": {
            "valid_outcome": transition.verification.valid_outcome,
            "completed": transition.verification.completed,
            "false_completion": transition.verification.false_completion,
            "evidence_ref": transition.verification.evidence_ref,
        },
    }
    row["leaked_public_keys"] = list(_leaked_keys(row))
    return {**row, "episode_fingerprint": _fingerprint(row)}


def _episode_routing_decisions(
    snapshot: CaseContextSnapshot,
    *,
    allow_strategy_refresh: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    coordinator = CaseCoordinator()
    router = DeterministicRouter()
    if not allow_strategy_refresh:
        fast_route = router.route(RouteRequest(snapshot=snapshot, created_at=PROBE_NOW))
        fast_result = ScriptedFastAdapter().decide(
            coordinator.project_fast_view(snapshot)
        )
        fast_audit = coordinator.validate_fast_result(fast_result, snapshot)
        if not fast_audit.accepted:
            raise RuntimeError(
                "scripted Fast adapter did not produce a current decision"
            )
        return (
            [
                {
                    "outcome": fast_route.outcome.value,
                    "reason_codes": list(fast_route.reason_codes),
                    "pins_fingerprint": _fingerprint(
                        fast_route.pins.model_dump(mode="json")
                    ),
                }
            ],
            [
                _scripted_model_trace(
                    adapter="scripted_fast",
                    case_id=snapshot.case.case_id,
                    output_fingerprint=_fingerprint(
                        fast_result.decision.model_dump(mode="json")
                    ),
                )
            ],
        )
    no_strategy_pins = snapshot.pins.model_copy(
        update={"strategy_id": None, "strategy_revision": 0}
    )
    initial = snapshot.model_copy(
        update={
            "strategy": None,
            "pins": no_strategy_pins,
        }
    )
    slow_route = router.route(RouteRequest(snapshot=initial, created_at=PROBE_NOW))
    slow_request = coordinator.build_slow_request(
        initial,
        reason_code=slow_route.reason_codes[0],
        created_at=PROBE_NOW,
    )
    slow_result = ScriptedSlowAdapter().reason(slow_request)
    slow_audit = coordinator.validate_slow_result(slow_result, initial)
    strategy = slow_result.strategy_proposal
    if strategy is None or not slow_audit.accepted:
        raise RuntimeError("scripted Slow adapter did not produce a current strategy")
    planned_pins = snapshot.pins.model_copy(
        update={
            "strategy_id": strategy.strategy_id,
            "strategy_revision": strategy.revision,
        }
    )
    planned = snapshot.model_copy(
        update={
            "strategy": strategy,
            "pins": planned_pins,
        }
    )
    fast_route = router.route(RouteRequest(snapshot=planned, created_at=PROBE_NOW))
    fast_result = ScriptedFastAdapter().decide(coordinator.project_fast_view(planned))
    fast_audit = coordinator.validate_fast_result(fast_result, planned)
    if not fast_audit.accepted:
        raise RuntimeError("scripted Fast adapter did not produce a current decision")
    decisions = (slow_route, fast_route)
    routing: list[dict[str, object]] = [
        {
            "outcome": decision.outcome.value,
            "reason_codes": list(decision.reason_codes),
            "pins_fingerprint": _fingerprint(decision.pins.model_dump(mode="json")),
        }
        for decision in decisions
    ]
    traces: list[dict[str, object]] = [
        _scripted_model_trace(
            adapter="scripted_slow",
            case_id=snapshot.case.case_id,
            output_fingerprint=_fingerprint(slow_result.model_dump(mode="json")),
        ),
        _scripted_model_trace(
            adapter="scripted_fast",
            case_id=snapshot.case.case_id,
            output_fingerprint=_fingerprint(
                fast_result.decision.model_dump(mode="json")
            ),
        ),
    ]
    return routing, traces


def _counts(rows: Iterable[dict[str, object]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str):
            raise TypeError(f"{key} must be text")
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _build_ceiling(
    rows: list[dict[str, object]], runtime_probes: dict[str, object]
) -> dict[str, object]:
    transitions = [cast(dict[str, object], row["transition"]) for row in rows]
    public_episodes = [cast(dict[str, object], row["public_episode"]) for row in rows]
    valid = sum(1 for transition in transitions if transition["valid_outcome"] is True)
    completed = sum(1 for transition in transitions if transition["completed"] is True)
    false_completion = sum(
        1 for transition in transitions if transition["false_completion"] is True
    )
    leakage = sum(len(cast(list[object], row["leaked_public_keys"])) for row in rows)
    multi_position = sum(
        1
        for episode in public_episodes
        if len(cast(list[object], episode["events"])) >= 3
    )
    valid_noncompletion = sum(
        1
        for transition in transitions
        if transition["valid_outcome"] is True and transition["completed"] is False
    )
    provider_holdout_rows = [
        row for row in rows if row["provider_split"] == "provider_heldout"
    ]
    reference_strategy_input_count = sum(
        1
        for row in rows
        if any(
            trace["model"] == "scripted_slow"
            for trace in cast(list[dict[str, object]], row["adapter_traces"])
        )
    )
    ineligible_reference_strategy_input_count = sum(
        1
        for row in rows
        if row["reference_strategy_fixture_eligible"] is False
        and any(
            trace["model"] == "scripted_slow"
            for trace in cast(list[dict[str, object]], row["adapter_traces"])
        )
    )
    return {
        "schema_version": "phase-03a1-ceiling-v1",
        "scenario_count": len(rows),
        "valid_outcome_count": valid,
        "completed_count": completed,
        "valid_noncompletion_count": valid_noncompletion,
        "false_completion_count": false_completion,
        "leakage_violation_count": leakage,
        "multi_position_episode_count": multi_position,
        "provider_holdout_episode_count": len(provider_holdout_rows),
        "reference_strategy_input_count": reference_strategy_input_count,
        "ineligible_reference_strategy_input_count": (
            ineligible_reference_strategy_input_count
        ),
        "split_counts": _counts(rows, "split"),
        "provider_split_counts": _counts(rows, "provider_split"),
        "runtime_probe_gate_passed": runtime_probes["gate_passed"],
        "gate_passed": (
            len(rows) == 32
            and valid == len(rows)
            and false_completion == 0
            and leakage == 0
            and multi_position == len(rows)
            and len(provider_holdout_rows) > 0
            and reference_strategy_input_count > 0
            and ineligible_reference_strategy_input_count == 0
            and valid_noncompletion > 0
            and runtime_probes["gate_passed"] is True
        ),
    }


def build_phase03a1_harness_report(
    scenarios: Iterable[BenchmarkScenario] = BENCHMARK_SCENARIOS,
) -> dict[str, object]:
    """Build a deterministic in-memory manifest, episode, and ceiling report."""

    scenario_list = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    manifest = generate_phase03a1_manifest(scenario_list)
    case = Phase01AEpisode.success().case
    episodes = [
        _run_episode(scenario, case=case, manifest=manifest)
        for scenario in scenario_list
    ]
    runtime_probes = _build_runtime_probe_report()
    ceiling = _build_ceiling(episodes, runtime_probes)
    report_without_fingerprint: dict[str, object] = {
        "schema_version": "phase-03a1-harness-v1",
        "manifest": manifest.to_dict(),
        "episodes": episodes,
        "ceiling_report": ceiling,
        "runtime_probe_report": runtime_probes,
        "manifest_fingerprint": manifest.content_hash,
        "episode_fingerprint": _fingerprint(episodes),
        "ceiling_fingerprint": _fingerprint(ceiling),
    }
    return {
        **report_without_fingerprint,
        "report_fingerprint": _fingerprint(report_without_fingerprint),
    }


# Alias used by focused tests and future Make integration.
build_harness_report = build_phase03a1_harness_report


def _artifact_payloads() -> tuple[str, str, str]:
    report = build_phase03a1_harness_report()
    episodes_artifact = {
        "schema_version": "phase-03a1-episodes-v1",
        "manifest_fingerprint": report["manifest_fingerprint"],
        "episode_fingerprint": report["episode_fingerprint"],
        "episodes": report["episodes"],
    }
    ceiling = cast(dict[str, object], report["ceiling_report"])
    ceiling_artifact = {
        **ceiling,
        "runtime_probe_report": report["runtime_probe_report"],
        "manifest_fingerprint": report["manifest_fingerprint"],
        "episode_fingerprint": report["episode_fingerprint"],
        "ceiling_fingerprint": report["ceiling_fingerprint"],
        "report_fingerprint": report["report_fingerprint"],
    }
    return (
        _artifact_text(report["manifest"]),
        _artifact_text(episodes_artifact),
        _artifact_text(ceiling_artifact),
    )


def write_artifacts() -> None:
    manifest, episodes, ceiling = _artifact_payloads()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(manifest, encoding="utf-8")
    EPISODES_PATH.write_text(episodes, encoding="utf-8")
    CEILING_PATH.write_text(ceiling, encoding="utf-8")


def check_harness(pattern: str | None = None) -> tuple[bool, tuple[str, ...]]:
    """Check deterministic validity and exact committed artifact drift."""

    first = build_phase03a1_harness_report()
    second = build_phase03a1_harness_report()
    failures: list[str] = []
    if first != second:
        failures.append("non_deterministic_report")
    ceiling = first["ceiling_report"]
    if not isinstance(ceiling, dict) or ceiling.get("gate_passed") is not True:
        failures.append("ceiling_gate_failed")
    if pattern is not None and pattern not in _canonical_json(first):
        failures.append(f"pattern_not_found:{pattern}")
    expected = _artifact_payloads()
    for path, payload, reason in (
        (MANIFEST_PATH, expected[0], "manifest_artifact_drift"),
        (EPISODES_PATH, expected[1], "episodes_artifact_drift"),
        (CEILING_PATH, expected[2], "ceiling_artifact_drift"),
    ):
        if not path.is_file() or path.read_text(encoding="utf-8") != payload:
            failures.append(reason)
    return not failures, tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="write the frozen manifest, episodes, and ceiling artifacts",
    )
    mode.add_argument(
        "--check",
        nargs="?",
        const="",
        metavar="PATTERN",
        help="check deterministic generation; optionally require PATTERN",
    )
    args = parser.parse_args()
    if args.write:
        write_artifacts()
        print("Wrote Phase 03A1 harness manifest, episodes, and ceiling artifacts.")
        return 0
    if args.check is not None:
        passed, failures = check_harness(args.check or None)
        if not passed:
            print("Phase 03A1 harness check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 03A1 harness manifest, episodes, and ceiling gate are valid.")
        return 0
    print(
        json.dumps(
            build_phase03a1_harness_report(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
