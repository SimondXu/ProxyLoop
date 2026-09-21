"""Phase 03C Stage 1a per-instance scenario invariants and position harvest.

Parameterised scenarios (``proxyloop_provider_simulator.scenarios``) derive
one instance per ``(family, configuration, seed)``.  This module checks that
every instance keeps the hazard truth of its family and that the scripted
oracle and the environment verifier agree on it, quarantining any instance
that fails.  It also harvests the Fast decision positions of one multi-turn
episode so later stages can render training prompts from real environment
state instead of the opening turn alone.  No model is called anywhere here.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from proxyloop_agent_core import (
    OracleDecision,
    SafeObservation,
    SafeObservationAdapter,
    ScriptedOracleConsumer,
)
from proxyloop_contracts import Case
from proxyloop_provider_simulator.episode import build_case
from proxyloop_provider_simulator.multi_turn import (
    MultiTurnProviderEnvironment,
    MultiTurnProviderTurn,
)
from proxyloop_provider_simulator.scenarios import (
    PROMOTION_CREDIT_MINOR,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
    ScenarioParameters,
    build_parameterised_scenarios,
    change_phrase,
    feature_phrase,
    parameters_from_seed,
)
from proxyloop_telecom_domain import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
)

from proxyloop_evaluation.fresh_fixtures import _safe_offers
from proxyloop_evaluation.phase03b_readiness import proposed_fast_target

INVARIANT_MANIFEST_SCHEMA_VERSION: Final = "phase-03c-scenario-invariants-v1"
INVARIANT_MANIFEST_PATH: Final = Path(
    "data/manifests/phase-03c-scenario-invariants.json"
)
DEFAULT_INVARIANT_SEEDS: Final = range(1, 1001)

# Reason codes emitted by ``check_instance_invariants``.
TWELVE_MONTH_ARITHMETIC: Final = "twelve_month_arithmetic"
FEE_TRAP_TRUTH: Final = "fee_trap_truth"
REQUIRED_FEATURE_LOSS_TRUTH: Final = "required_feature_loss_truth"
FORBIDDEN_TERM_TRUTH: Final = "forbidden_term_truth"
SUCCESS_COMPLIANCE: Final = "success_compliance"
ORACLE_AGREEMENT: Final = "oracle_agreement"
VERIFIER_AGREEMENT: Final = "verifier_agreement"
MESSAGE_OFFER_CONSISTENCY: Final = "message_offer_consistency"

_FEE_TRAP_HAZARDS: Final = frozenset({"fee_total_cost_trap", "multi_hazard"})
_FEATURE_LOSS_HAZARDS: Final = frozenset({"required_feature_loss", "multi_hazard"})
_FORBIDDEN_TERM_HAZARDS: Final = frozenset({"forbidden_term", "multi_hazard"})
_SUCCESS_HAZARDS: Final = frozenset(
    {
        "direct_success",
        "revised_offer",
        "promotion_credit",
        "add_on_removal",
        "plan_change",
    }
)
# Hazards whose public message names a feature the offer carries.
_FEATURE_NAMING_HAZARDS: Final = frozenset({"direct_success", "plan_change"})
# The oracle vocabulary says ``decline``; the scenario vocabulary says
# ``decline_offer``.  ``environment._normalise_action`` accepts both.
_ORACLE_TO_SCENARIO_ACTION: Final = {"decline": "decline_offer"}
_INVARIANT_IDEMPOTENCY_KEY: Final = "invariant:1"


@dataclass(frozen=True, slots=True)
class FastPosition:
    """One Fast decision position harvested from a multi-turn episode."""

    position_index: int
    event_cursor: int
    observation: SafeObservation
    oracle_action: str
    oracle_offer_id: str | None
    provider_turn: MultiTurnProviderTurn


@dataclass(frozen=True, slots=True)
class InvariantReport:
    """Deterministic outcome of the invariant suite over one seed set."""

    seed_first: int
    seed_last: int
    seed_count: int
    total_instances: int
    accepted_count: int
    quarantined: tuple[tuple[str, tuple[str, ...]], ...]
    family_counts: tuple[tuple[str, int], ...]
    reason_counts: tuple[tuple[str, int], ...]
    content_fingerprint: str
    parameters_fingerprint: str

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantined)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": INVARIANT_MANIFEST_SCHEMA_VERSION,
            "seed_range": {
                "first": self.seed_first,
                "last": self.seed_last,
                "count": self.seed_count,
            },
            "total_instances": self.total_instances,
            "accepted_count": self.accepted_count,
            "quarantined_count": self.quarantined_count,
            "family_counts": dict(self.family_counts),
            "reason_counts": dict(self.reason_counts),
            "quarantined": [
                {"scenario_id": scenario_id, "reason_codes": list(reason_codes)}
                for scenario_id, reason_codes in self.quarantined
            ],
            "content_fingerprint": self.content_fingerprint,
            "parameters_fingerprint": self.parameters_fingerprint,
        }


@lru_cache(maxsize=64)
def _cached_case(params: ScenarioParameters) -> Case:
    # One Case serves the 32 family/configuration instances of a seed; the
    # adapter only reads it.
    return build_case(params)


def build_parameterised_observation(
    scenario: BenchmarkScenario, turn: ProviderTurn | MultiTurnProviderTurn
) -> SafeObservation:
    """Build the public observation from the instance's own consumer Case.

    Mirrors ``fresh_fixtures.build_fresh_safe_observation`` except that the
    Case comes from ``build_case(scenario.parameters)``; for ``DEFAULT_PARAMS``
    the two are field-for-field equal.
    """

    provider_turn = turn.turn if isinstance(turn, MultiTurnProviderTurn) else turn
    return SafeObservationAdapter.build(
        _cached_case(scenario.parameters),
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


def _oracle() -> ScriptedOracleConsumer:
    return ScriptedOracleConsumer(offer_policy=offer_compliance_violations)


def _scenario_action(oracle_action: str) -> str:
    return _ORACLE_TO_SCENARIO_ACTION.get(oracle_action, oracle_action)


def _compliance_context(
    params: ScenarioParameters, *, evaluated_at: ProviderTurn
) -> OfferComplianceContext:
    return OfferComplianceContext(
        evaluated_at=evaluated_at.observed_at,
        current_monthly_minor=params.current_monthly_minor,
        currency="USD",
        target_monthly_minor=params.target_monthly_minor,
        target_currency="USD",
        required_features=params.required_features,
        forbidden_changes=params.forbidden_changes,
    )


def _compliance_terms(offer: PublicOffer) -> OfferComplianceTerms:
    return OfferComplianceTerms(
        monthly_price_minor=offer.monthly_price_minor,
        total_cost_12_months_minor=offer.total_cost_12_months_minor,
        currency=offer.currency,
        fees_minor=offer.fees_minor,
        features=offer.features,
        applied_changes=offer.applied_changes,
        expires_at=offer.expires_at,
    )


def _twelve_month_total_holds(offer: PublicOffer) -> bool:
    credit = (
        PROMOTION_CREDIT_MINOR
        if "predefined_promotion_credit" in offer.applied_changes
        else 0
    )
    expected = offer.monthly_price_minor * 12 + offer.fees_minor - credit
    return offer.total_cost_12_months_minor == expected


def _hazard_truth_failures(scenario: BenchmarkScenario) -> list[str]:
    params = scenario.parameters
    hazard = scenario.hazard
    offers = scenario.provider_turn.offers
    failures: list[str] = []
    if hazard in _FEE_TRAP_HAZARDS and not all(
        offer.monthly_price_minor <= params.target_monthly_minor
        and offer.total_cost_12_months_minor > params.target_monthly_minor * 12
        for offer in offers
    ):
        failures.append(FEE_TRAP_TRUTH)
    if hazard in _FEATURE_LOSS_HAZARDS and not all(
        sum(feature not in offer.features for feature in params.required_features) == 1
        for offer in offers
    ):
        failures.append(REQUIRED_FEATURE_LOSS_TRUTH)
    if hazard in _FORBIDDEN_TERM_HAZARDS and not all(
        set(params.forbidden_changes) & set(offer.applied_changes) for offer in offers
    ):
        failures.append(FORBIDDEN_TERM_TRUTH)
    if hazard in _SUCCESS_HAZARDS:
        context = _compliance_context(params, evaluated_at=scenario.provider_turn)
        if not offers or any(
            offer_compliance_violations(context, _compliance_terms(offer))
            for offer in offers
        ):
            failures.append(SUCCESS_COMPLIANCE)
    return failures


def _message_names_offer_content(scenario: BenchmarkScenario) -> bool:
    """The public message must name the feature or change the offer carries.

    Deterministic string containment: for the success hazards that name a
    feature, the message names one of the offer's features; for the loss
    hazard, it names a required feature the offer lacks; for the forbidden
    term hazard, it names one of the offer's applied changes.
    """

    hazard = scenario.hazard
    message = scenario.provider_turn.message
    offers = scenario.provider_turn.offers
    if hazard in _FEATURE_NAMING_HAZARDS:
        return bool(offers) and all(
            any(feature_phrase(feature) in message for feature in offer.features)
            for offer in offers
        )
    if hazard == "required_feature_loss":
        required = scenario.parameters.required_features
        return bool(offers) and all(
            any(
                feature_phrase(feature) in message
                for feature in required
                if feature not in offer.features
            )
            for offer in offers
        )
    if hazard == "forbidden_term":
        return bool(offers) and all(
            any(change_phrase(change) in message for change in offer.applied_changes)
            for offer in offers
        )
    return True


def _verify_oracle_decision(
    scenario: BenchmarkScenario, decision: OracleDecision
) -> bool:
    environment = MultiTurnProviderEnvironment(scenario)
    environment.start()
    transition = environment.submit_capability_attempt(
        {
            "capability_id": f"simulator.{decision.action.value}",
            "idempotency_key": _INVARIANT_IDEMPOTENCY_KEY,
            "offer_id": decision.offer_id,
        }
    )
    verification = transition.verification
    expected_completed = scenario.expected_outcome.value == "completed"
    return (
        verification.valid_outcome is True
        and verification.completed == expected_completed
        and verification.false_completion is False
    )


def check_instance_invariants(scenario: BenchmarkScenario) -> tuple[str, ...]:
    """Return the reason codes an instance violates; empty means accepted."""

    failures: list[str] = []
    offers = scenario.provider_turn.offers
    if not all(_twelve_month_total_holds(offer) for offer in offers):
        failures.append(TWELVE_MONTH_ARITHMETIC)
    failures.extend(_hazard_truth_failures(scenario))
    if not _message_names_offer_content(scenario):
        failures.append(MESSAGE_OFFER_CONSISTENCY)
    observation = build_parameterised_observation(scenario, scenario.provider_turn)
    decision = _oracle().decide(observation)
    if _scenario_action(decision.action.value) != scenario.expected_action.value:
        failures.append(ORACLE_AGREEMENT)
    if not _verify_oracle_decision(scenario, decision):
        failures.append(VERIFIER_AGREEMENT)
    return tuple(failures)


def harvest_positions(scenario: BenchmarkScenario) -> tuple[FastPosition, ...]:
    """Harvest the Fast decision positions of one multi-turn episode.

    Position 1 is the opening turn.  Position 2 is the Provider follow-up
    after the oracle's canonical response text is submitted as a consumer
    message.  The frozen multi-turn environment is terminal after one input,
    so the contract's "2-3 positions" collapses to exactly 2 here.
    """

    oracle = _oracle()
    environment = MultiTurnProviderEnvironment(scenario)
    opening = _position(scenario, 1, environment.start(), oracle)
    response_text = proposed_fast_target(opening.oracle_action)["response_text"]
    if not isinstance(response_text, str):
        raise TypeError("proposed_fast_target response_text must be text")
    transition = environment.submit_consumer_message(response_text)
    follow_up = _position(scenario, 2, transition.provider_turn, oracle)
    return (opening, follow_up)


def _position(
    scenario: BenchmarkScenario,
    index: int,
    turn: MultiTurnProviderTurn,
    oracle: ScriptedOracleConsumer,
) -> FastPosition:
    observation = build_parameterised_observation(scenario, turn)
    decision = oracle.decide(observation)
    return FastPosition(
        position_index=index,
        event_cursor=turn.cursor,
        observation=observation,
        oracle_action=decision.action.value,
        oracle_offer_id=decision.offer_id,
        provider_turn=turn,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def parameters_fingerprint(seeds: Iterable[int]) -> str:
    """SHA-256 of the seeded parameter values, pinning the generator's draws."""

    return _sha256([asdict(parameters_from_seed(seed)) for seed in seeds])


def run_invariant_suite(seeds: Iterable[int]) -> InvariantReport:
    """Run every invariant over all family/configuration instances of ``seeds``."""

    seed_list = tuple(seeds)
    if not seed_list:
        raise ValueError("seeds must be non-empty")
    scenarios = build_parameterised_scenarios(seeds=seed_list)
    accepted_ids: list[str] = []
    quarantined: list[tuple[str, tuple[str, ...]]] = []
    family_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for scenario in scenarios:
        family_counts[scenario.family_id] += 1
        reasons = check_instance_invariants(scenario)
        if reasons:
            quarantined.append((scenario.scenario_id, reasons))
            reason_counts.update(reasons)
        else:
            accepted_ids.append(scenario.scenario_id)
    quarantined.sort()
    fingerprint = _sha256(
        {
            "accepted": sorted(accepted_ids),
            "quarantined": [
                {"scenario_id": scenario_id, "reason_codes": list(reasons)}
                for scenario_id, reasons in quarantined
            ],
        }
    )
    return InvariantReport(
        seed_first=min(seed_list),
        seed_last=max(seed_list),
        seed_count=len(seed_list),
        total_instances=len(scenarios),
        accepted_count=len(accepted_ids),
        quarantined=tuple(quarantined),
        family_counts=tuple(sorted(family_counts.items())),
        reason_counts=tuple(sorted(reason_counts.items())),
        content_fingerprint=fingerprint,
        parameters_fingerprint=parameters_fingerprint(seed_list),
    )


def write_invariant_manifest(path: Path, seeds: Iterable[int]) -> InvariantReport:
    report = run_invariant_suite(seeds)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report


def check_invariant_manifest(path: Path, seeds: Iterable[int]) -> tuple[str, ...]:
    """Recompute the suite and report every field that drifted from ``path``."""

    if not path.is_file():
        return (f"missing_manifest:{path}",)
    committed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(committed, dict):
        return (f"malformed_manifest:{path}",)
    report = run_invariant_suite(seeds)
    expected = report.to_dict()
    problems = [
        f"manifest_drift:{key}"
        for key in sorted(set(committed) | set(expected))
        if committed.get(key) != expected.get(key)
    ]
    # A quarantine row is a finding whether it is recomputed or committed.
    quarantined = {
        (scenario_id, tuple(reasons)) for scenario_id, reasons in report.quarantined
    }
    committed_rows = committed.get("quarantined")
    if isinstance(committed_rows, list):
        quarantined.update(
            (str(row.get("scenario_id")), tuple(row.get("reason_codes", ())))
            for row in committed_rows
            if isinstance(row, dict)
        )
    problems.extend(
        f"quarantined:{scenario_id}:{','.join(reasons)}"
        for scenario_id, reasons in sorted(quarantined)
    )
    return tuple(problems)


__all__ = [
    "DEFAULT_INVARIANT_SEEDS",
    "FEE_TRAP_TRUTH",
    "FORBIDDEN_TERM_TRUTH",
    "INVARIANT_MANIFEST_PATH",
    "INVARIANT_MANIFEST_SCHEMA_VERSION",
    "MESSAGE_OFFER_CONSISTENCY",
    "ORACLE_AGREEMENT",
    "REQUIRED_FEATURE_LOSS_TRUTH",
    "SUCCESS_COMPLIANCE",
    "TWELVE_MONTH_ARITHMETIC",
    "VERIFIER_AGREEMENT",
    "FastPosition",
    "InvariantReport",
    "build_parameterised_observation",
    "check_instance_invariants",
    "check_invariant_manifest",
    "harvest_positions",
    "parameters_fingerprint",
    "run_invariant_suite",
    "write_invariant_manifest",
]
