"""Deterministic Phase 01B Provider environment and policy verifier."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from proxyloop_telecom_domain import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
    unsupported_applied_changes,
)

from .scenarios import (
    CASE_CURRENCY,
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
    ScenarioParameters,
)

# Label of the verifier semantics implemented by ``_verify_decision``.  Offline
# rescores of hosted evidence bind to it so a later verifier change is visible
# in the derived artifact's ``evaluator_version``.
PROVIDER_VERIFIER_VERSION = "phase-01b-verifier-v2-state"


class EnvironmentState(StrEnum):
    READY = "ready"
    RESPONDED = "responded"
    TERMINAL = "terminal"


class EnvironmentAction(StrEnum):
    """The bounded action vocabulary accepted by the environment."""

    ACCEPT_OFFER = "accept_offer"
    REQUEST_CLARIFICATION = "request_clarification"
    REQUEST_REPLAN = "request_replan"
    ESCALATE = "escalate"
    REFUSE_DISCLOSURE = "refuse_disclosure"
    DECLINE_OFFER = "decline_offer"
    DECLINE = "decline"


@dataclass(frozen=True, slots=True)
class EnvironmentDecision:
    """Decision fields required to verify a proposed environment action.

    ``offer_id`` is a public reference.  Confirmation Evidence belongs to the
    Provider environment and is never accepted from a model-facing caller.
    """

    action: EnvironmentAction | str
    offer_id: str | None = None
    completion_candidate: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioVerification:
    """Deterministic result of checking one environment decision."""

    valid_outcome: bool
    completed: bool
    false_completion: bool
    reason_codes: tuple[str, ...]
    evidence_ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "valid_outcome": self.valid_outcome,
            "completed": self.completed,
            "false_completion": self.false_completion,
            "reason_codes": list(self.reason_codes),
            "evidence_ref": self.evidence_ref,
        }


class IllegalEnvironmentTransitionError(ValueError):
    """Raised when an action is attempted outside the response state."""


class ProviderEnvironment:
    """One deterministic scenario execution with private expected semantics."""

    def __init__(self, scenario: BenchmarkScenario) -> None:
        self._scenario = scenario
        self._state = EnvironmentState.READY
        self._state_history: list[EnvironmentState] = [self._state]
        self._turn: ProviderTurn | None = None

    @property
    def scenario_id(self) -> str:
        return self._scenario.scenario_id

    @property
    def state(self) -> EnvironmentState:
        return self._state

    @property
    def state_history(self) -> tuple[EnvironmentState, ...]:
        return tuple(self._state_history)

    def observe(self) -> ProviderTurn:
        """Emit the public Provider turn, deterministically and idempotently."""

        if self._turn is None:
            self._turn = self._scenario.provider_turn
            self._transition(EnvironmentState.RESPONDED)
        return self._turn

    def verify(self, decision: EnvironmentDecision) -> ScenarioVerification:
        """Verify a decision without changing state.

        Verification is available only after the Provider has emitted its
        public turn.  ``apply`` is the state-changing wrapper used by a runner.
        """

        if self._state is not EnvironmentState.RESPONDED or self._turn is None:
            raise IllegalEnvironmentTransitionError(
                "a Provider turn must be observed before verification"
            )
        return self._verify_decision(decision, self._turn)

    def apply(self, decision: EnvironmentDecision) -> ScenarioVerification:
        """Verify and terminally consume one decision."""

        result = self.verify(decision)
        self._transition(EnvironmentState.TERMINAL)
        return result

    def _transition(self, target: EnvironmentState) -> None:
        allowed = {
            EnvironmentState.READY: {EnvironmentState.RESPONDED},
            EnvironmentState.RESPONDED: {EnvironmentState.TERMINAL},
            EnvironmentState.TERMINAL: set(),
        }
        if target not in allowed[self._state]:
            raise IllegalEnvironmentTransitionError(
                f"cannot transition from {self._state.value} to {target.value}"
            )
        self._state = target
        self._state_history.append(target)

    def _verify_decision(
        self, decision: EnvironmentDecision, turn: ProviderTurn
    ) -> ScenarioVerification:
        action = _normalise_action(decision.action)
        if action is None:
            return ScenarioVerification(
                valid_outcome=False,
                completed=False,
                false_completion=decision.completion_candidate,
                reason_codes=("invalid_action",),
            )

        if action is EnvironmentAction.ACCEPT_OFFER:
            return self._verify_acceptance(decision, turn)

        # Every non-completion action is verified against the public turn
        # state, never against the scenario's reference label.  The label only
        # selects the rationale codes when the action happens to be the
        # reference one, which keeps the scripted-oracle artifacts stable.
        false_completion = decision.completion_candidate
        if action is EnvironmentAction.ESCALATE:
            state_valid = turn.transfer_available
            failure_code = "transfer_unavailable"
        elif action is EnvironmentAction.REQUEST_CLARIFICATION:
            state_valid = turn.clarification_required
            failure_code = "clarification_not_required"
        elif action is EnvironmentAction.REFUSE_DISCLOSURE:
            state_valid = turn.disclosure_restricted
            failure_code = "disclosure_not_restricted"
        elif action in (
            EnvironmentAction.DECLINE_OFFER,
            EnvironmentAction.REQUEST_REPLAN,
        ):
            state_valid = not self._acceptance_state_valid(turn)
            failure_code = "acceptance_available"
        else:
            # A new EnvironmentAction member must get an explicit predicate;
            # it never inherits the acceptance rule silently.
            return ScenarioVerification(
                valid_outcome=False,
                completed=False,
                false_completion=false_completion,
                reason_codes=("invalid_action",),
            )

        if not state_valid:
            reason_codes: tuple[str, ...] = (failure_code,)
        elif action.value == self._scenario.expected_action.value:
            reason_codes = self._scenario.private_reason_codes
        else:
            reason_codes = ("state_verified_noncompletion",)
        if false_completion:
            reason_codes += ("completion_candidate_on_non_completion",)
        return ScenarioVerification(
            valid_outcome=state_valid and not false_completion,
            completed=False,
            false_completion=false_completion,
            reason_codes=reason_codes,
        )

    def _acceptance_state_valid(self, turn: ProviderTurn) -> bool:
        """Whether the turn's offer could be accepted under the state rules."""

        offer = turn.offers[0] if turn.offers else None
        return (
            offer is not None
            and turn.approval_current
            and not _offer_constraint_violations(
                offer,
                params=self._scenario.parameters,
                observed_at=turn.observed_at,
            )
            and turn.confirmation_evidence_available
            and turn.confirmation_evidence_ref is not None
        )

    def _verify_acceptance(
        self, decision: EnvironmentDecision, turn: ProviderTurn
    ) -> ScenarioVerification:
        reasons: list[str] = []
        offer = turn.offers[0] if turn.offers else None
        if not turn.approval_current:
            reasons.append("approval_not_current")
        if offer is None:
            reasons.append("offer_missing")
        elif decision.offer_id != offer.offer_id:
            reasons.append("offer_reference_mismatch")
        if offer is not None:
            reasons.extend(
                _offer_constraint_violations(
                    offer,
                    params=self._scenario.parameters,
                    observed_at=turn.observed_at,
                )
            )
        if not turn.confirmation_evidence_available:
            reasons.append("confirmation_evidence_missing")
        elif turn.confirmation_evidence_ref is None:
            reasons.append("confirmation_evidence_ref_missing")

        if reasons:
            return ScenarioVerification(
                valid_outcome=False,
                completed=False,
                false_completion=True,
                reason_codes=_dedupe(reasons),
            )
        return ScenarioVerification(
            valid_outcome=True,
            completed=True,
            false_completion=False,
            reason_codes=("verified_confirmation_evidence",),
            evidence_ref=turn.confirmation_evidence_ref,
        )


def _normalise_action(action: EnvironmentAction | str) -> EnvironmentAction | None:
    if action == EnvironmentAction.DECLINE.value:
        return EnvironmentAction.DECLINE_OFFER
    try:
        return EnvironmentAction(action)
    except ValueError:
        return None


def _offer_constraint_violations(
    offer: PublicOffer, *, params: ScenarioParameters, observed_at: datetime
) -> list[str]:
    context = OfferComplianceContext(
        evaluated_at=observed_at,
        current_monthly_minor=params.current_monthly_minor,
        currency=CASE_CURRENCY,
        target_monthly_minor=params.target_monthly_minor,
        target_currency=CASE_CURRENCY,
        required_features=params.required_features,
        forbidden_changes=params.forbidden_changes,
    )
    terms = OfferComplianceTerms(
        monthly_price_minor=offer.monthly_price_minor,
        total_cost_12_months_minor=offer.total_cost_12_months_minor,
        currency=offer.currency,
        fees_minor=offer.fees_minor,
        features=offer.features,
        applied_changes=offer.applied_changes,
        expires_at=offer.expires_at,
    )
    legacy_reason_codes = {
        "recurring_price_not_reduced": "monthly_target_exceeded",
        "target_monthly_total_not_met": "monthly_target_exceeded",
        "total_cost_exceeds_current": "total_cost_target_exceeded",
        "forbidden_change_present": "forbidden_term_present",
    }
    reasons = [
        legacy_reason_codes.get(reason, reason)
        for reason in offer_compliance_violations(context, terms)
    ]
    if unsupported_applied_changes(offer.applied_changes):
        reasons.append("unsupported_action")
    return reasons


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "PROVIDER_VERIFIER_VERSION",
    "EnvironmentAction",
    "EnvironmentDecision",
    "EnvironmentState",
    "IllegalEnvironmentTransitionError",
    "ProviderEnvironment",
    "ScenarioVerification",
]
