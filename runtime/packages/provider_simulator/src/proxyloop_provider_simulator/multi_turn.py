"""Deterministic, model-independent Phase 03A1 Provider episodes.

This module deliberately lives beside (rather than inside) the Phase 01B
``ProviderEnvironment``.  The old environment is a frozen one-turn regression
surface.  ``MultiTurnProviderEnvironment`` adds a small event state machine
for harness work and never accepts Evidence or completion authority from a
caller.

The manifest helpers in this module are also intentionally data-only.  They
describe which scenario derivatives are eligible for a harness split; they do
not become part of a model-visible observation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from .environment import (
    EnvironmentAction,
    EnvironmentDecision,
    IllegalEnvironmentTransitionError,
    ProviderEnvironment,
    ScenarioVerification,
)
from .scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
)


class MultiTurnEnvironmentState(StrEnum):
    """Externally observable lifecycle of one multi-turn episode."""

    READY = "ready"
    WAITING_FOR_INPUT = "waiting_for_input"
    TERMINAL = "terminal"


PHASE03A1_SIMULATOR_VERSION = "phase-03a1-multi-turn-v1"
PHASE03A1_ROUTER_VERSION = "phase-03a0-precedence-v1"
PHASE03A1_CAPABILITY_MANIFEST_VERSION = "phase-03a1-simulator-capabilities-v1"
PHASE03A1_SCENARIO_CATALOG_VERSION = "phase-01b-scenarios-v1"
PHASE03A1_ADAPTER_FIXTURE_VERSION = "scripted-oracle-v1"
PHASE03A1_SEED_VERSION = "deterministic-zero-v1"
SUPPORTED_SIMULATOR_CAPABILITIES = frozenset(
    f"simulator.{action.value}" for action in EnvironmentAction
)


@dataclass(frozen=True, slots=True)
class SimulatorCapabilityAttempt:
    """A bounded simulator input, not an authorization or Evidence record.

    The absence of an ``evidence_ref``/``completion_candidate`` field is
    deliberate.  The environment creates any Evidence reference after its
    deterministic transition and verification boundary.
    """

    capability_id: str
    idempotency_key: str
    offer_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise ValueError("capability_id must be non-empty text")
        if self.capability_id not in SUPPORTED_SIMULATOR_CAPABILITIES:
            raise ValueError(f"unsupported simulator capability: {self.capability_id}")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key:
            raise ValueError("idempotency_key must be non-empty text")
        if self.offer_id is not None and (
            not isinstance(self.offer_id, str) or not self.offer_id
        ):
            raise ValueError("offer_id must be non-empty text when provided")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "capability_id": self.capability_id,
            "idempotency_key": self.idempotency_key,
        }
        if self.offer_id is not None:
            result["offer_id"] = self.offer_id
        return result


@dataclass(frozen=True, slots=True)
class MultiTurnEvent:
    """A public event with a strictly increasing cursor."""

    cursor: int
    actor: Literal["provider", "consumer"]
    event_type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.cursor) is not int or self.cursor < 1:
            raise ValueError("event cursor must be a positive integer")
        if self.actor not in {"provider", "consumer"}:
            raise ValueError("event actor must be provider or consumer")
        if not self.event_type:
            raise ValueError("event type must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "cursor": self.cursor,
            "actor": self.actor,
            "event_type": self.event_type,
            "payload": _json_safe(self.payload),
        }


@dataclass(frozen=True, slots=True)
class MultiTurnProviderTurn:
    """A provider turn paired with its public event cursor.

    ``turn`` is retained for adapters inside the local simulator.  The
    serialized representation uses an explicit allowlist and omits the
    scenario identifier, configuration, and all private reference semantics.
    """

    cursor: int
    turn: ProviderTurn

    @property
    def provider_id(self) -> str:
        return self.turn.provider_id

    @property
    def message(self) -> str:
        return self.turn.message

    @property
    def offers(self) -> tuple[PublicOffer, ...]:
        return self.turn.offers

    @property
    def observed_at(self) -> datetime:
        return self.turn.observed_at

    def to_dict(self) -> dict[str, object]:
        result = _public_provider_turn(self.turn)
        result["event_cursor"] = self.cursor
        return result


@dataclass(frozen=True, slots=True)
class MultiTurnTransition:
    """The result of one bounded input plus its provider follow-up."""

    input_cursor: int
    provider_turn: MultiTurnProviderTurn
    verification: ScenarioVerification
    duplicate: bool = False

    def to_dict(self) -> dict[str, object]:
        # ``reason_codes`` belong to the private verifier.  The environment's
        # public episode exporter below intentionally exposes only outcome
        # flags and Evidence references.
        return {
            "input_cursor": self.input_cursor,
            "provider_turn": self.provider_turn.to_dict(),
            "verification": {
                "valid_outcome": self.verification.valid_outcome,
                "completed": self.verification.completed,
                "false_completion": self.verification.false_completion,
                "evidence_ref": self.verification.evidence_ref,
            },
            "duplicate": self.duplicate,
        }


class MultiTurnProviderEnvironment:
    """A deterministic Provider event loop for Phase 03A1 harness episodes.

    The underlying Phase 01B environment remains the source of truth for
    public offer verification.  This wrapper adds real intermediate state:
    every input creates a consumer event and a new provider revision.  The
    first successful mutation is idempotent by ``idempotency_key`` and the
    same immutable transition is returned on a duplicate attempt.
    """

    def __init__(self, scenario: BenchmarkScenario) -> None:
        self._scenario = scenario
        self._legacy = ProviderEnvironment(scenario)
        self._state = MultiTurnEnvironmentState.READY
        self._cursor = 0
        self._round = 0
        self._events: list[MultiTurnEvent] = []
        self._opening: MultiTurnProviderTurn | None = None
        self._last_turn: MultiTurnProviderTurn | None = None
        self._attempts: dict[str, tuple[str, MultiTurnTransition]] = {}
        self._provider_mutation_count = 0

    @property
    def scenario_id(self) -> str:
        """Internal fixture identity; never included in public exports."""

        return self._scenario.scenario_id

    @property
    def state(self) -> MultiTurnEnvironmentState:
        return self._state

    @property
    def event_cursor(self) -> int:
        return self._cursor

    @property
    def events(self) -> tuple[MultiTurnEvent, ...]:
        return tuple(self._events)

    @property
    def provider_mutation_count(self) -> int:
        return self._provider_mutation_count

    @property
    def last_turn(self) -> MultiTurnProviderTurn | None:
        return self._last_turn

    def start(self) -> MultiTurnProviderTurn:
        """Emit one public opening turn, idempotently."""

        if self._opening is not None:
            return self._opening
        if self._state is MultiTurnEnvironmentState.TERMINAL:
            raise IllegalEnvironmentTransitionError("episode is terminal")
        self._legacy.observe()
        opening = MultiTurnProviderTurn(
            cursor=self._next_cursor(), turn=self._legacy_turn()
        )
        self._opening = opening
        self._last_turn = opening
        self._events.append(
            MultiTurnEvent(
                cursor=opening.cursor,
                actor="provider",
                event_type="provider_turn",
                payload=opening.to_dict(),
            )
        )
        self._state = MultiTurnEnvironmentState.WAITING_FOR_INPUT
        return opening

    # ``observe`` mirrors the old environment and makes the new surface easy
    # to use in generic episode runners.
    observe = start

    def submit_consumer_message(self, message: str) -> MultiTurnTransition:
        """Advance through a bounded consumer message.

        A message is not interpreted as Evidence or a model action.  It only
        gives the deterministic Provider a chance to emit the next visible
        turn.  A clarification case maps to clarification; all other messages
        safely request a replan.
        """

        self._require_input()
        if not isinstance(message, str) or not message.strip():
            raise ValueError("consumer message must be non-empty text")
        if len(message) > 500:
            raise ValueError("consumer message exceeds the 500-character bound")
        action = (
            EnvironmentAction.REQUEST_CLARIFICATION
            if self._scenario.provider_turn.clarification_required
            else EnvironmentAction.REQUEST_REPLAN
        )
        return self._advance(
            input_type="consumer_message",
            input_payload={"message": message.strip()},
            action=action.value,
            offer_id=None,
            idempotency_key=f"message:{self._cursor + 1}:{message.strip()}",
        )

    def submit_capability_attempt(
        self, attempt: SimulatorCapabilityAttempt | Mapping[str, object]
    ) -> MultiTurnTransition:
        """Advance through a simulator-only capability attempt.

        Mapping input is accepted for JSON-oriented runners, but it is parsed
        into the same bounded dataclass.  Any caller/model supplied Evidence
        or completion field is rejected before the Provider transition.
        """

        if isinstance(attempt, Mapping):
            forbidden = {"evidence_ref", "evidence", "completion_candidate"}
            if forbidden.intersection(attempt):
                raise ValueError("caller-supplied Evidence/completion is not accepted")
            attempt = SimulatorCapabilityAttempt(
                capability_id=str(attempt.get("capability_id", "")),
                idempotency_key=str(attempt.get("idempotency_key", "")),
                offer_id=(
                    str(attempt["offer_id"])
                    if attempt.get("offer_id") is not None
                    else None
                ),
            )
        if not isinstance(attempt, SimulatorCapabilityAttempt):
            raise TypeError("attempt must be SimulatorCapabilityAttempt or a mapping")
        if hasattr(attempt, "evidence_ref") or hasattr(attempt, "completion_candidate"):
            raise ValueError("caller-supplied Evidence/completion is not accepted")
        # A duplicate is a read of the immutable prior result, even when the
        # original successful transition moved the environment to terminal.
        if attempt.idempotency_key not in self._attempts:
            self._require_input()
        return self._advance(
            input_type="capability_attempt",
            input_payload=attempt.to_dict(),
            action=attempt.capability_id.removeprefix("simulator."),
            offer_id=attempt.offer_id,
            idempotency_key=attempt.idempotency_key,
        )

    def export_public_episode(self) -> dict[str, object]:
        """Export only public episode events and deterministic outcome flags."""

        completed = False
        false_completion = False
        evidence_refs: list[str] = []
        for _payload, transition in self._attempts.values():
            completed = completed or transition.verification.completed
            false_completion = (
                false_completion or transition.verification.false_completion
            )
            if transition.verification.evidence_ref is not None:
                evidence_refs.append(transition.verification.evidence_ref)
        return {
            "schema_version": "phase-03a1-episode-v1",
            "event_cursor": self._cursor,
            "state": self._state.value,
            "events": [event.to_dict() for event in self._events],
            "outcome": {
                "completed": completed,
                "false_completion": false_completion,
                "evidence_refs": sorted(set(evidence_refs)),
            },
            "provider_mutation_count": self._provider_mutation_count,
        }

    def _advance(
        self,
        *,
        input_type: str,
        input_payload: Mapping[str, object],
        action: str,
        offer_id: str | None,
        idempotency_key: str,
    ) -> MultiTurnTransition:
        payload_json = _canonical_json(input_payload)
        prior = self._attempts.get(idempotency_key)
        if prior is not None:
            prior_payload, prior_transition = prior
            if prior_payload != payload_json:
                raise ValueError("idempotency key was reused with different input")
            return replace(prior_transition, duplicate=True)

        # The underlying verifier cannot be called before its one public turn;
        # ``_require_input`` has already called start, so this is deterministic.
        verification = self._legacy.verify(
            EnvironmentDecision(action=action, offer_id=offer_id)
        )
        input_cursor = self._next_cursor()
        self._events.append(
            MultiTurnEvent(
                cursor=input_cursor,
                actor="consumer",
                event_type=input_type,
                payload=dict(input_payload),
            )
        )
        self._round += 1
        follow_up = self._follow_up_turn(verification)
        provider_cursor = self._next_cursor()
        public_turn = MultiTurnProviderTurn(cursor=provider_cursor, turn=follow_up)
        self._last_turn = public_turn
        self._events.append(
            MultiTurnEvent(
                cursor=provider_cursor,
                actor="provider",
                event_type="provider_turn",
                payload=public_turn.to_dict(),
            )
        )
        if verification.completed:
            self._provider_mutation_count += 1
        # A Phase 03A1 episode records one bounded decision and the Provider's
        # follow-up. Safe non-completion is terminal for this frozen episode,
        # preventing a later input from being verified against the old turn.
        self._state = MultiTurnEnvironmentState.TERMINAL
        transition = MultiTurnTransition(
            input_cursor=input_cursor,
            provider_turn=public_turn,
            verification=verification,
        )
        self._attempts[idempotency_key] = (payload_json, transition)
        return transition

    def _require_input(self) -> None:
        if self._state is MultiTurnEnvironmentState.READY:
            self.start()
        if self._state is MultiTurnEnvironmentState.TERMINAL:
            raise IllegalEnvironmentTransitionError("episode is terminal")

    def _next_cursor(self) -> int:
        self._cursor += 1
        return self._cursor

    def _legacy_turn(self) -> ProviderTurn:
        turn = self._legacy.observe()
        return turn

    def _follow_up_turn(self, verification: ScenarioVerification) -> ProviderTurn:
        initial = self._legacy_turn()
        if verification.completed:
            message = "The requested offer has been confirmed by the Provider."
        elif self._scenario.provider_turn.clarification_required:
            message = (
                "The Provider needs the requested clarification before continuing."
            )
        elif self._scenario.provider_turn.transfer_available:
            message = "The Provider has kept the request open for specialist review."
        else:
            message = (
                "The Provider cannot complete this request yet; review the next step."
            )
        return replace(
            initial,
            turn_id=f"{initial.turn_id.rsplit('::', 1)[0]}::turn-{self._round + 1}",
            revision=initial.revision + self._round,
            observed_at=initial.observed_at + timedelta(seconds=self._cursor),
            message=message,
        )


SAFETY_FAMILIES = frozenset(
    {
        "disclosure-restriction",
        "forged-evidence",
        "absent-evidence",
        "unsupported-action",
        "multi-hazard",
    }
)
FAMILY_ENTITY_HELDOUT_FAMILIES = frozenset(
    {"fee-total-cost-trap", "required-feature-loss", "forbidden-term"}
)
PROVIDER_HELDOUT_CONFIGURATION = "retention-gated-v1"


class Phase03A1Split(StrEnum):
    DEVELOPMENT = "development"
    FAMILY_ENTITY_HELDOUT = "family_entity_heldout"
    PROVIDER_HELDOUT = "provider_heldout"
    SAFETY = "safety"


@dataclass(frozen=True, slots=True)
class Phase03A1ScenarioAssignment:
    scenario_id: str
    family_id: str
    entity_cluster: str
    provider_configuration_id: str
    split: str
    provider_split: str
    safety_only: bool
    development_eligible: bool
    reference_strategy_fixture_eligible: bool

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
class Phase03A1Manifest:
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
    scenario_assignments: tuple[Phase03A1ScenarioAssignment, ...]
    content_hash: str

    @property
    def scenario_count(self) -> int:
        return len(self.scenario_assignments)

    @property
    def family_count(self) -> int:
        return len(self.family_assignments)

    @property
    def development_scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            assignment.scenario_id
            for assignment in self.scenario_assignments
            if assignment.development_eligible
        )

    @property
    def reference_strategy_fixture_scenario_ids(self) -> tuple[str, ...]:
        return tuple(
            assignment.scenario_id
            for assignment in self.scenario_assignments
            if assignment.reference_strategy_fixture_eligible
        )

    def assignment_for(self, scenario_id: str) -> Phase03A1ScenarioAssignment:
        for assignment in self.scenario_assignments:
            if assignment.scenario_id == scenario_id:
                return assignment
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
                assignment.to_dict() for assignment in self.scenario_assignments
            ],
            "development_scenario_ids": list(self.development_scenario_ids),
            "reference_strategy_fixture_scenario_ids": list(
                self.reference_strategy_fixture_scenario_ids
            ),
            "content_hash": self.content_hash,
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    def assert_valid(self) -> None:
        content = self.to_dict()
        content_hash = content.pop("content_hash")
        if content_hash != _fingerprint(content):
            raise ValueError("manifest content hash does not match its assignments")
        if len(self.scenario_assignments) != len(
            {item.scenario_id for item in self.scenario_assignments}
        ):
            raise ValueError("scenario assignments must be unique")
        if len(self.provider_assignments) != len(
            {configuration for configuration, _split in self.provider_assignments}
        ):
            raise ValueError("provider assignments must be unique")
        family_by_entity: dict[str, str] = {}
        for family, entity_split in self.entity_assignments:
            if family_by_entity.setdefault(family, entity_split) != entity_split:
                raise ValueError("entity assignment is not atomic")
        for assignment in self.scenario_assignments:
            family_split = dict(self.family_assignments)[assignment.family_id]
            entity_split = dict(self.entity_assignments)[assignment.entity_cluster]
            if family_split != entity_split or assignment.split != family_split:
                raise ValueError("family/entity assignment crosses a split")
            if assignment.safety_only != (
                assignment.split == Phase03A1Split.SAFETY.value
            ):
                raise ValueError("safety derivative is not safety-only")
            expected_provider_split = dict(self.provider_assignments)[
                assignment.provider_configuration_id
            ]
            if assignment.provider_split != expected_provider_split:
                raise ValueError("provider assignment crosses a split")
            expected_development_eligible = (
                assignment.split == Phase03A1Split.DEVELOPMENT.value
                and assignment.provider_split == Phase03A1Split.DEVELOPMENT.value
                and not assignment.safety_only
            )
            if assignment.development_eligible != expected_development_eligible:
                raise ValueError("development eligibility crosses a frozen split")
            if (
                assignment.reference_strategy_fixture_eligible
                != expected_development_eligible
            ):
                raise ValueError(
                    "reference-strategy fixture eligibility crosses a frozen split"
                )


def generate_phase03a1_manifest(
    scenarios: Iterable[BenchmarkScenario] = BENCHMARK_SCENARIOS,
) -> Phase03A1Manifest:
    """Build a stable independent family/entity/provider/safety manifest."""

    scenario_list = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    if not scenario_list:
        raise ValueError("at least one scenario is required")
    family_to_entity: dict[str, str] = {}
    for scenario in scenario_list:
        previous = family_to_entity.setdefault(
            scenario.family_id, scenario.entity_cluster
        )
        if previous != scenario.entity_cluster:
            raise ValueError("family/entity derivatives must remain atomic")
    family_assignments = tuple(
        sorted(
            (
                family,
                (
                    Phase03A1Split.SAFETY.value
                    if family in SAFETY_FAMILIES
                    else (
                        Phase03A1Split.FAMILY_ENTITY_HELDOUT.value
                        if family in FAMILY_ENTITY_HELDOUT_FAMILIES
                        else Phase03A1Split.DEVELOPMENT.value
                    )
                ),
            )
            for family in family_to_entity
        )
    )
    entity_assignments = tuple(
        sorted(
            (entity, dict(family_assignments)[family])
            for family, entity in family_to_entity.items()
        )
    )
    configurations = sorted({scenario.configuration_id for scenario in scenario_list})
    provider_assignments = tuple(
        (
            configuration,
            (
                Phase03A1Split.PROVIDER_HELDOUT.value
                if configuration == PROVIDER_HELDOUT_CONFIGURATION
                else Phase03A1Split.DEVELOPMENT.value
            ),
        )
        for configuration in configurations
    )
    family_split = dict(family_assignments)
    provider_split = dict(provider_assignments)
    scenario_assignments = tuple(
        Phase03A1ScenarioAssignment(
            scenario_id=scenario.scenario_id,
            family_id=scenario.family_id,
            entity_cluster=scenario.entity_cluster,
            provider_configuration_id=scenario.configuration_id,
            split=family_split[scenario.family_id],
            provider_split=provider_split[scenario.configuration_id],
            safety_only=scenario.family_id in SAFETY_FAMILIES,
            development_eligible=(
                family_split[scenario.family_id] == Phase03A1Split.DEVELOPMENT.value
                and provider_split[scenario.configuration_id]
                == Phase03A1Split.DEVELOPMENT.value
                and scenario.family_id not in SAFETY_FAMILIES
            ),
            reference_strategy_fixture_eligible=(
                family_split[scenario.family_id] == Phase03A1Split.DEVELOPMENT.value
                and provider_split[scenario.configuration_id]
                == Phase03A1Split.DEVELOPMENT.value
                and scenario.family_id not in SAFETY_FAMILIES
            ),
        )
        for scenario in scenario_list
    )
    content = {
        "schema_version": "1.0",
        "simulator_version": PHASE03A1_SIMULATOR_VERSION,
        "router_version": PHASE03A1_ROUTER_VERSION,
        "capability_manifest_version": PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        "scenario_catalog_version": PHASE03A1_SCENARIO_CATALOG_VERSION,
        "adapter_fixture_version": PHASE03A1_ADAPTER_FIXTURE_VERSION,
        "seed_version": PHASE03A1_SEED_VERSION,
        "family_assignments": [
            {"family_id": key, "split": value} for key, value in family_assignments
        ],
        "entity_assignments": [
            {"entity_cluster": key, "split": value} for key, value in entity_assignments
        ],
        "provider_assignments": [
            {"provider_configuration_id": key, "split": value}
            for key, value in provider_assignments
        ],
        "scenario_assignments": [item.to_dict() for item in scenario_assignments],
        "development_scenario_ids": [
            item.scenario_id
            for item in scenario_assignments
            if item.development_eligible
        ],
        "reference_strategy_fixture_scenario_ids": [
            item.scenario_id
            for item in scenario_assignments
            if item.reference_strategy_fixture_eligible
        ],
    }
    content_hash = _fingerprint(content)
    manifest = Phase03A1Manifest(
        schema_version="1.0",
        simulator_version=PHASE03A1_SIMULATOR_VERSION,
        router_version=PHASE03A1_ROUTER_VERSION,
        capability_manifest_version=PHASE03A1_CAPABILITY_MANIFEST_VERSION,
        scenario_catalog_version=PHASE03A1_SCENARIO_CATALOG_VERSION,
        adapter_fixture_version=PHASE03A1_ADAPTER_FIXTURE_VERSION,
        seed_version=PHASE03A1_SEED_VERSION,
        family_assignments=family_assignments,
        entity_assignments=entity_assignments,
        provider_assignments=provider_assignments,
        scenario_assignments=scenario_assignments,
        content_hash=content_hash,
    )
    manifest.assert_valid()
    return manifest


# Friendly aliases for runners and focused tests.
build_phase03a1_manifest = generate_phase03a1_manifest
MultiTurnEpisodeEnvironment = MultiTurnProviderEnvironment


def _public_provider_turn(turn: ProviderTurn) -> dict[str, object]:
    """Serialize the Provider allowlist without scenario/evaluator metadata."""

    return {
        "schema_version": turn.schema_version,
        "turn_id": turn.turn_id,
        "provider_id": turn.provider_id,
        "revision": turn.revision,
        "observed_at": turn.observed_at.isoformat(),
        "message": turn.message,
        "offers": [offer.to_dict() for offer in turn.offers],
        "transfer_available": turn.transfer_available,
        "clarification_required": turn.clarification_required,
        "disclosure_restricted": turn.disclosure_restricted,
        "approval_current": turn.approval_current,
        "confirmation_evidence_available": turn.confirmation_evidence_available,
        "confirmation_evidence_ref": turn.confirmation_evidence_ref,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    return value


__all__ = [
    "FAMILY_ENTITY_HELDOUT_FAMILIES",
    "PHASE03A1_ADAPTER_FIXTURE_VERSION",
    "PHASE03A1_CAPABILITY_MANIFEST_VERSION",
    "PHASE03A1_ROUTER_VERSION",
    "PHASE03A1_SCENARIO_CATALOG_VERSION",
    "PHASE03A1_SEED_VERSION",
    "PHASE03A1_SIMULATOR_VERSION",
    "PROVIDER_HELDOUT_CONFIGURATION",
    "SAFETY_FAMILIES",
    "SUPPORTED_SIMULATOR_CAPABILITIES",
    "MultiTurnEnvironmentState",
    "MultiTurnEpisodeEnvironment",
    "MultiTurnEvent",
    "MultiTurnProviderEnvironment",
    "MultiTurnProviderTurn",
    "MultiTurnTransition",
    "Phase03A1Manifest",
    "Phase03A1ScenarioAssignment",
    "Phase03A1Split",
    "SimulatorCapabilityAttempt",
    "build_phase03a1_manifest",
    "generate_phase03a1_manifest",
]
