"""Leakage-safe Phase 03A1-E r2 catalog and model fixtures.

The r2 bundle is a deterministic public-surface derivative of the frozen
Phase 01B behavior families.  It deliberately keeps evaluator references in
the fixture wrapper and never serializes them into a model-facing snapshot.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from proxyloop_agent_core import SafeObservation, SafeObservationAdapter, SafeOffer
from proxyloop_contracts import (
    ActionType,
    CapabilityDefinition,
    CapabilityManifest,
    CaseContextSnapshot,
    ConstraintClassification,
    EventActor,
    EvidenceType,
    FactLedger,
    FactStatus,
    ModelInputPins,
    PlanningBasis,
    ProviderOffer,
    StrategyPacket,
    VisibleCaseEvent,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnProviderTurn,
    Phase03A1Manifest,
    Phase03A1Split,
    generate_phase03a1_manifest,
)
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
)

FRESH_PHASE03A1_CATALOG_VERSION: Final = "phase-03a1-r2-catalog-v1"
FRESH_PHASE03A1_SEED_VERSION: Final = "phase-03a1-r2-seed-deterministic-v1"
FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION: Final = (
    "phase-03a1-r2-fixture-derivation-v1"
)
FRESH_PHASE03A1_SIMULATOR_VERSION: Final = "phase-03a1-multi-turn-v1"
FRESH_PHASE03A1_ROUTER_VERSION: Final = "phase-03a0-precedence-v1"
FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION: Final = (
    "phase-03a1-r2-simulator-capabilities-v1"
)
FRESH_PHASE03A1_ADAPTER_FIXTURE_VERSION: Final = "phase-03a1-r2-scripted-v1"
FRESH_PHASE03A1_OBSERVED_AT: Final = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
FRESH_PHASE03A1_EXPIRY_DELTA: Final = timedelta(hours=2)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _r2_id(old_id: str) -> str:
    return f"phase-03a1-r2::{old_id}"


def _r2_scenario_id(scenario: BenchmarkScenario) -> str:
    return f"{_r2_id(scenario.family_id)}@2.0::{_r2_id(scenario.configuration_id)}@2.0"


def _fresh_offer(old: PublicOffer, *, scenario_id: str) -> PublicOffer:
    return replace(
        old,
        offer_id=f"{scenario_id}::offer-r2",
        expires_at=FRESH_PHASE03A1_OBSERVED_AT + FRESH_PHASE03A1_EXPIRY_DELTA,
    )


def _fresh_turn(old: ProviderTurn, *, scenario_id: str) -> ProviderTurn:
    offers = tuple(_fresh_offer(item, scenario_id=scenario_id) for item in old.offers)
    old_evidence = old.confirmation_evidence_ref
    evidence_ref = (
        f"{scenario_id}::confirmation-r2" if old_evidence is not None else None
    )
    return replace(
        old,
        turn_id=f"{scenario_id}::turn-r2-1",
        scenario_id=scenario_id,
        observed_at=FRESH_PHASE03A1_OBSERVED_AT,
        message=f"Fresh Provider update: {old.message}",
        offers=offers,
        confirmation_evidence_ref=evidence_ref,
    )


def _fresh_scenario(old: BenchmarkScenario) -> BenchmarkScenario:
    scenario_id = _r2_scenario_id(old)
    expected_offer_id = (
        f"{scenario_id}::offer-r2" if old.expected_offer_id is not None else None
    )
    expected_evidence_ref = (
        f"{scenario_id}::confirmation-r2"
        if old.expected_evidence_ref is not None
        else None
    )
    return replace(
        old,
        scenario_id=scenario_id,
        family_version="2.0",
        configuration_version="2.0",
        observed_at=FRESH_PHASE03A1_OBSERVED_AT,
        provider_turn=_fresh_turn(old.provider_turn, scenario_id=scenario_id),
        expected_offer_id=expected_offer_id,
        expected_evidence_ref=expected_evidence_ref,
    )


def build_fresh_phase03a1_scenarios(
    scenarios: Iterable[BenchmarkScenario] = BENCHMARK_SCENARIOS,
) -> tuple[BenchmarkScenario, ...]:
    """Derive exactly one fresh identity for each known family/config pair."""

    source = tuple(scenarios)
    if len(source) != 32:
        raise ValueError("Phase 03A1-E requires exactly 32 source scenarios")
    fresh = tuple(
        sorted(
            (_fresh_scenario(item) for item in source),
            key=lambda item: item.scenario_id,
        )
    )
    if len({item.scenario_id for item in fresh}) != len(fresh):
        raise ValueError("fresh scenario IDs must be unique")
    return fresh


@dataclass(frozen=True, slots=True)
class FreshScenarioAssignment:
    """One fresh scenario's family/entity/provider split assignment."""

    scenario_id: str
    family_id: str
    entity_cluster: str
    provider_configuration_id: str
    split: str
    provider_split: str
    safety_only: bool
    development_eligible: bool
    reference_strategy_fixture_eligible: bool

    @property
    def family_split(self) -> str:
        return self.split

    @property
    def entity_split(self) -> str:
        return self.split

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "family_id": self.family_id,
            "entity_cluster": self.entity_cluster,
            "provider_configuration_id": self.provider_configuration_id,
            "split": self.split,
            "provider_split": self.provider_split,
            "safety_only": self.safety_only,
            "development_eligible": self.development_eligible,
            "reference_strategy_fixture_eligible": (
                self.reference_strategy_fixture_eligible
            ),
        }


@dataclass(frozen=True, slots=True)
class FreshPhase03A1Manifest:
    """Versioned r2 split manifest with content-bound fingerprint."""

    schema_version: str
    simulator_version: str
    router_version: str
    capability_manifest_version: str
    scenario_catalog_version: str
    adapter_fixture_version: str
    seed_version: str
    family_assignments: tuple[tuple[str, str], ...]
    entity_assignments: tuple[tuple[str, str], ...]
    provider_assignments: tuple[tuple[str, str], ...]
    scenario_assignments: tuple[FreshScenarioAssignment, ...]
    content_hash: str

    @property
    def scenario_count(self) -> int:
        return len(self.scenario_assignments)

    @property
    def split_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for assignment in self.scenario_assignments:
            counts[assignment.split] = counts.get(assignment.split, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def provider_split_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for assignment in self.scenario_assignments:
            counts[assignment.provider_split] = (
                counts.get(assignment.provider_split, 0) + 1
            )
        return dict(sorted(counts.items()))

    @property
    def development_scenario_ids(self) -> tuple[str, ...]:
        return self.ids_for_split(Phase03A1Split.DEVELOPMENT.value)

    @property
    def family_entity_heldout_scenario_ids(self) -> tuple[str, ...]:
        return self.ids_for_split(Phase03A1Split.FAMILY_ENTITY_HELDOUT.value)

    @property
    def safety_scenario_ids(self) -> tuple[str, ...]:
        return self.ids_for_split(Phase03A1Split.SAFETY.value)

    @property
    def provider_heldout_scenario_ids(self) -> tuple[str, ...]:
        return self.ids_for_provider_split("provider_heldout")

    def ids_for_split(self, split: str) -> tuple[str, ...]:
        return tuple(
            item.scenario_id
            for item in self.scenario_assignments
            if item.split == split
        )

    def ids_for_provider_split(self, split: str) -> tuple[str, ...]:
        return tuple(
            item.scenario_id
            for item in self.scenario_assignments
            if item.provider_split == split
        )

    def assignment_for(self, scenario_id: str) -> FreshScenarioAssignment:
        for item in self.scenario_assignments:
            if item.scenario_id == scenario_id:
                return item
        raise KeyError(scenario_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "simulator_version": self.simulator_version,
            "router_version": self.router_version,
            "capability_manifest_version": self.capability_manifest_version,
            "scenario_catalog_version": self.scenario_catalog_version,
            "adapter_fixture_version": self.adapter_fixture_version,
            "seed_version": self.seed_version,
            "family_assignments": [
                {"family_id": key, "split": value}
                for key, value in self.family_assignments
            ],
            "entity_assignments": [
                {"entity_cluster": key, "split": value}
                for key, value in self.entity_assignments
            ],
            "provider_assignments": [
                {"provider_configuration_id": key, "split": value}
                for key, value in self.provider_assignments
            ],
            "scenario_assignments": [
                item.to_dict() for item in self.scenario_assignments
            ],
            "split_counts": self.split_counts,
            "provider_split_counts": self.provider_split_counts,
            "content_hash": self.content_hash,
        }

    def assert_valid(self) -> None:
        content = self.to_dict()
        content.pop("content_hash")
        if self.content_hash != _fingerprint(content):
            raise ValueError("fresh manifest fingerprint drift")
        if self.scenario_count != 32:
            raise ValueError("fresh manifest must contain 32 scenarios")
        if len({item.scenario_id for item in self.scenario_assignments}) != 32:
            raise ValueError("fresh manifest scenario IDs must be unique")
        family_split = dict(self.family_assignments)
        entity_split = dict(self.entity_assignments)
        provider_split = dict(self.provider_assignments)
        for item in self.scenario_assignments:
            if family_split[item.family_id] != entity_split[item.entity_cluster]:
                raise ValueError("family/entity assignment crosses a split")
            if item.split != family_split[item.family_id]:
                raise ValueError("scenario family assignment does not match")
            if item.provider_split != provider_split[item.provider_configuration_id]:
                raise ValueError("provider assignment crosses a split")


def build_fresh_phase03a1_manifest(
    scenarios: Iterable[BenchmarkScenario] | None = None,
) -> FreshPhase03A1Manifest:
    scenario_list = tuple(
        sorted(
            scenarios if scenarios is not None else build_fresh_phase03a1_scenarios(),
            key=lambda item: item.scenario_id,
        )
    )
    # The existing deterministic assignment algorithm is the frozen split
    # policy.  Only the scenario identities and metadata are fresh here.
    legacy: Phase03A1Manifest = generate_phase03a1_manifest(scenario_list)
    assignments = tuple(
        FreshScenarioAssignment(
            scenario_id=item.scenario_id,
            family_id=item.family_id,
            entity_cluster=item.entity_cluster,
            provider_configuration_id=item.provider_configuration_id,
            split=item.split,
            provider_split=item.provider_split,
            safety_only=item.safety_only,
            development_eligible=item.development_eligible,
            reference_strategy_fixture_eligible=item.reference_strategy_fixture_eligible,
        )
        for item in legacy.scenario_assignments
    )
    content = {
        "schema_version": "1.0",
        "simulator_version": FRESH_PHASE03A1_SIMULATOR_VERSION,
        "router_version": FRESH_PHASE03A1_ROUTER_VERSION,
        "capability_manifest_version": FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        "scenario_catalog_version": FRESH_PHASE03A1_CATALOG_VERSION,
        "adapter_fixture_version": FRESH_PHASE03A1_ADAPTER_FIXTURE_VERSION,
        "seed_version": FRESH_PHASE03A1_SEED_VERSION,
        "family_assignments": [
            {"family_id": key, "split": value}
            for key, value in legacy.family_assignments
        ],
        "entity_assignments": [
            {"entity_cluster": key, "split": value}
            for key, value in legacy.entity_assignments
        ],
        "provider_assignments": [
            {"provider_configuration_id": key, "split": value}
            for key, value in legacy.provider_assignments
        ],
        "scenario_assignments": [item.to_dict() for item in assignments],
        "split_counts": {
            key: sum(1 for item in assignments if item.split == key)
            for key in sorted({item.split for item in assignments})
        },
        "provider_split_counts": {
            key: sum(1 for item in assignments if item.provider_split == key)
            for key in sorted({item.provider_split for item in assignments})
        },
    }
    manifest = FreshPhase03A1Manifest(
        schema_version="1.0",
        simulator_version=FRESH_PHASE03A1_SIMULATOR_VERSION,
        router_version=FRESH_PHASE03A1_ROUTER_VERSION,
        capability_manifest_version=FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        scenario_catalog_version=FRESH_PHASE03A1_CATALOG_VERSION,
        adapter_fixture_version=FRESH_PHASE03A1_ADAPTER_FIXTURE_VERSION,
        seed_version=FRESH_PHASE03A1_SEED_VERSION,
        family_assignments=legacy.family_assignments,
        entity_assignments=legacy.entity_assignments,
        provider_assignments=legacy.provider_assignments,
        scenario_assignments=assignments,
        content_hash=_fingerprint(content),
    )
    manifest.assert_valid()
    return manifest


@dataclass(frozen=True, slots=True)
class FreshBundleMetadata:
    """Derivation versions and fingerprint for one immutable r2 bundle."""

    catalog_version: str
    seed_version: str
    fixture_derivation_version: str
    simulator_version: str
    router_version: str
    capability_manifest_version: str
    bundle_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "catalog_version": self.catalog_version,
            "seed_version": self.seed_version,
            "fixture_derivation_version": self.fixture_derivation_version,
            "simulator_version": self.simulator_version,
            "router_version": self.router_version,
            "capability_manifest_version": self.capability_manifest_version,
            "bundle_fingerprint": self.bundle_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class FreshPhase03A1ModelFixture:
    """Model-visible snapshot plus evaluator-only reference labels."""

    scenario: BenchmarkScenario
    episode_id: str
    split: str
    provider_split: str
    safety_only: bool
    snapshot: CaseContextSnapshot
    reference_capability_id: str
    reference_offer_id: str | None

    def prompt_visible_dump(self) -> dict[str, object]:
        """Return the only fields adapters may serialize to model prompts."""

        return self.snapshot.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class FreshPhase03A1Bundle:
    metadata: FreshBundleMetadata
    scenarios: tuple[BenchmarkScenario, ...]
    manifest: FreshPhase03A1Manifest
    fixtures: tuple[FreshPhase03A1ModelFixture, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_dict(),
            "scenarios": [_scenario_dict(item) for item in self.scenarios],
            "manifest": self.manifest.to_dict(),
            "fixture_episode_ids": [item.episode_id for item in self.fixtures],
        }


def _scenario_dict(scenario: BenchmarkScenario) -> dict[str, object]:
    return {
        "scenario_id": scenario.scenario_id,
        "family_id": scenario.family_id,
        "hazard": scenario.hazard,
        "family_version": scenario.family_version,
        "entity_cluster": scenario.entity_cluster,
        "configuration_id": scenario.configuration_id,
        "configuration_version": scenario.configuration_version,
        "observed_at": scenario.observed_at.isoformat(),
        "provider_turn": scenario.provider_turn.to_dict(),
    }


def _canonical_provider_offer(
    public_offer: PublicOffer,
    *,
    case_id: UUID,
    provider_id: str,
    observed_at: datetime,
) -> ProviderOffer:
    from proxyloop_contracts import LineItem, LineItemCategory, Money

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


def _capability_manifest() -> CapabilityManifest:
    now = FRESH_PHASE03A1_OBSERVED_AT
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
        manifest_version=FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=4),
        capabilities=tuple(
            CapabilityDefinition(
                capability_id=f"simulator.{name}",
                version="1.0",
                description=f"Execute the bounded {name} simulator input.",
                namespace="simulator",
                allowed_action_types=(action_type,),
                expires_at=now + timedelta(hours=3),
            )
            for name, action_type in action_types.items()
        ),
    )


def _strategy(case: object) -> StrategyPacket:
    from proxyloop_contracts import Case

    if not isinstance(case, Case):
        raise TypeError("case must be canonical Case")
    return StrategyPacket(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=1,
        strategy_id=_stable_uuid4("phase-03a1-r2-strategy"),
        case_id=case.case_id,
        case_revision=case.revision,
        fact_ledger_revision=1,
        created_at=FRESH_PHASE03A1_OBSERVED_AT - timedelta(minutes=20),
        expires_at=FRESH_PHASE03A1_OBSERVED_AT + timedelta(hours=1),
        primary_objective="Reduce the recurring bill safely.",
        current_subgoal="Evaluate the current fictional Provider offer.",
        hard_constraint_ids=tuple(
            item.constraint_id
            for item in case.constraints
            if item.classification is ConstraintClassification.HARD
        ),
        ranked_preference_ids=(),
        allowed_disclosures=tuple(sorted(case.delegated_authority.allowed_disclosures)),
        approval_required_disclosures=(),
        concession_ladder=("Preserve every hard Consumer constraint.",),
        fallback_outcomes=("Return control to the Consumer safely.",),
        required_completion_evidence=(
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A fictional Provider confirmation is required.",
            ),
        ),
        escalation_conditions=("A material offer or authority input changes.",),
        replan_conditions=("The planning basis is no longer current.",),
    )


def _planning_basis(
    *,
    case: object,
    ledger: FactLedger,
    offers: tuple[ProviderOffer, ...],
    provider_config_ref: str,
    manifest: CapabilityManifest,
) -> PlanningBasis:
    from proxyloop_contracts import Case

    if not isinstance(case, Case):
        raise TypeError("case must be canonical Case")
    components = {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(
            tuple(sorted(case.constraints, key=lambda item: str(item.constraint_id)))
        ),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(
            tuple(item for item in ledger.entries if item.status is FactStatus.VERIFIED)
        ),
        "material_offers_fingerprint": canonical_fingerprint(
            tuple(sorted(offers, key=lambda item: str(item.offer_id)))
        ),
        "approval_state_fingerprint": canonical_fingerprint(()),
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


def _build_snapshot(scenario: BenchmarkScenario) -> CaseContextSnapshot:
    episode = Phase01AEpisode.success()
    case = episode.case
    opening = scenario.provider_turn
    manifest = _capability_manifest()
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
            item,
            case_id=case.case_id,
            provider_id=opening.provider_id,
            observed_at=opening.observed_at,
        )
        for item in opening.offers
    )
    strategy = _strategy(case)
    provider_config_ref = f"{scenario.configuration_id}@2.0"
    basis = _planning_basis(
        case=case,
        ledger=ledger,
        offers=offers,
        provider_config_ref=provider_config_ref,
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
        provider_config_ref=provider_config_ref,
        capability_manifest_version=manifest.manifest_version,
    )
    event = VisibleCaseEvent(
        contract_type="visible_case_event",
        schema_version="1.0",
        revision=1,
        event_id=_stable_uuid4(f"event:{scenario.scenario_id}:r2:1"),
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
        action_intents=(),
        approval_requests=(),
        visible_events=(event,),
        event_cursor=1,
        planning_basis=basis,
        pins=pins,
        provider_config_ref=provider_config_ref,
        capability_manifest=manifest,
    )
    return CaseContextSnapshot.model_validate(snapshot.model_dump(mode="python"))


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


def build_fresh_safe_observation(
    scenario: BenchmarkScenario, turn: ProviderTurn | MultiTurnProviderTurn
) -> SafeObservation:
    provider_turn = turn.turn if isinstance(turn, MultiTurnProviderTurn) else turn
    case = Phase01AEpisode.success().case
    return SafeObservationAdapter.build(
        case,
        provider_id=provider_turn.provider_id,
        provider_message=provider_turn.message,
        offers=_safe_offers(provider_turn),
        requested_disclosures=("account_pin",)
        if provider_turn.disclosure_restricted
        else (),
        needs_clarification=provider_turn.clarification_required,
        transfer_available=provider_turn.transfer_available,
        approval_current=provider_turn.approval_current,
        confirmation_evidence_available=provider_turn.confirmation_evidence_available,
        observed_at=provider_turn.observed_at,
    )


def build_fresh_phase03a1_model_fixtures(
    scenarios: Iterable[BenchmarkScenario] | None = None,
    manifest: FreshPhase03A1Manifest | None = None,
) -> tuple[FreshPhase03A1ModelFixture, ...]:
    scenario_list = tuple(
        sorted(
            scenarios if scenarios is not None else build_fresh_phase03a1_scenarios(),
            key=lambda item: item.scenario_id,
        )
    )
    split_manifest = manifest or build_fresh_phase03a1_manifest(scenario_list)
    fixtures: list[FreshPhase03A1ModelFixture] = []
    for scenario in scenario_list:
        observation = build_fresh_safe_observation(scenario, scenario.provider_turn)
        from proxyloop_agent_core import ScriptedOracleConsumer

        decision = ScriptedOracleConsumer().decide(observation)
        assignment = split_manifest.assignment_for(scenario.scenario_id)
        snapshot = _build_snapshot(scenario)
        fixtures.append(
            FreshPhase03A1ModelFixture(
                scenario=scenario,
                episode_id=f"episode-r2-{scenario.scenario_id}",
                split=assignment.split,
                provider_split=assignment.provider_split,
                safety_only=assignment.safety_only,
                snapshot=snapshot,
                reference_capability_id=f"simulator.{decision.action.value}",
                reference_offer_id=decision.offer_id,
            )
        )
    return tuple(fixtures)


def build_fresh_phase03a1_bundle(
    *, scenarios: Iterable[BenchmarkScenario] | None = None
) -> FreshPhase03A1Bundle:
    scenario_list = tuple(
        sorted(
            scenarios if scenarios is not None else build_fresh_phase03a1_scenarios(),
            key=lambda item: item.scenario_id,
        )
    )
    manifest = build_fresh_phase03a1_manifest(scenario_list)
    fixtures = build_fresh_phase03a1_model_fixtures(scenario_list, manifest)
    content = {
        "catalog_version": FRESH_PHASE03A1_CATALOG_VERSION,
        "seed_version": FRESH_PHASE03A1_SEED_VERSION,
        "fixture_derivation_version": FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION,
        "simulator_version": FRESH_PHASE03A1_SIMULATOR_VERSION,
        "router_version": FRESH_PHASE03A1_ROUTER_VERSION,
        "capability_manifest_version": FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        "scenarios": [_scenario_dict(item) for item in scenario_list],
        "manifest": manifest.to_dict() | {"content_hash": manifest.content_hash},
        "fixture_snapshot_fingerprints": [
            canonical_fingerprint(item.snapshot) for item in fixtures
        ],
        "fixture_references": [
            {
                "episode_id": item.episode_id,
                "reference_capability_id": item.reference_capability_id,
                "reference_offer_id": item.reference_offer_id,
            }
            for item in fixtures
        ],
    }
    metadata = FreshBundleMetadata(
        catalog_version=FRESH_PHASE03A1_CATALOG_VERSION,
        seed_version=FRESH_PHASE03A1_SEED_VERSION,
        fixture_derivation_version=FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION,
        simulator_version=FRESH_PHASE03A1_SIMULATOR_VERSION,
        router_version=FRESH_PHASE03A1_ROUTER_VERSION,
        capability_manifest_version=FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        bundle_fingerprint=_fingerprint(content),
    )
    return FreshPhase03A1Bundle(metadata, scenario_list, manifest, fixtures)


__all__ = [
    "FRESH_PHASE03A1_ADAPTER_FIXTURE_VERSION",
    "FRESH_PHASE03A1_CAPABILITY_MANIFEST_VERSION",
    "FRESH_PHASE03A1_CATALOG_VERSION",
    "FRESH_PHASE03A1_FIXTURE_DERIVATION_VERSION",
    "FRESH_PHASE03A1_OBSERVED_AT",
    "FRESH_PHASE03A1_ROUTER_VERSION",
    "FRESH_PHASE03A1_SEED_VERSION",
    "FRESH_PHASE03A1_SIMULATOR_VERSION",
    "FreshBundleMetadata",
    "FreshPhase03A1Bundle",
    "FreshPhase03A1Manifest",
    "FreshPhase03A1ModelFixture",
    "FreshScenarioAssignment",
    "build_fresh_phase03a1_bundle",
    "build_fresh_phase03a1_manifest",
    "build_fresh_phase03a1_model_fixtures",
    "build_fresh_phase03a1_scenarios",
    "build_fresh_safe_observation",
]
