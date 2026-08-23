"""Deterministic Phase 01B Provider environment and policy verifier."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .scenarios import (
    BenchmarkScenario,
    ProviderTurn,
    PublicOffer,
    ScenarioAction,
)


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

        false_completion = decision.completion_candidate
        expected = self._scenario.expected_action
        if action.value != expected.value:
            reason_codes: tuple[str, ...] = ("unexpected_action",)
            if false_completion:
                reason_codes += ("completion_candidate_on_non_completion",)
            return ScenarioVerification(
                valid_outcome=False,
                completed=False,
                false_completion=false_completion,
                reason_codes=reason_codes,
            )

        reason_codes = self._scenario.private_reason_codes
        if action is EnvironmentAction.ESCALATE and not turn.transfer_available:
            return ScenarioVerification(
                valid_outcome=False,
                completed=False,
                false_completion=false_completion,
                reason_codes=("transfer_unavailable",),
            )
        return ScenarioVerification(
            valid_outcome=not false_completion,
            completed=False,
            false_completion=false_completion,
            reason_codes=reason_codes,
        )

    def _verify_acceptance(
        self, decision: EnvironmentDecision, turn: ProviderTurn
    ) -> ScenarioVerification:
        reasons: list[str] = []
        offer = turn.offers[0] if turn.offers else None
        if self._scenario.expected_action is not ScenarioAction.ACCEPT_OFFER:
            reasons.append("acceptance_not_expected")
        if not turn.approval_current:
            reasons.append("approval_not_current")
        if offer is None:
            reasons.append("offer_missing")
        elif decision.offer_id != offer.offer_id:
            reasons.append("offer_reference_mismatch")
        if offer is not None:
            reasons.extend(_offer_constraint_violations(offer))
        if offer is not None and offer.expires_at <= turn.observed_at:
            reasons.append("offer_expired")
        if not turn.confirmation_evidence_available:
            reasons.append("confirmation_evidence_missing")
        elif turn.confirmation_evidence_ref is None:
            reasons.append("confirmation_evidence_ref_missing")

        if reasons:
            if "acceptance_not_expected" in reasons:
                reasons.append("false_completion")
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


def _offer_constraint_violations(offer: PublicOffer) -> list[str]:
    reasons: list[str] = []
    if offer.monthly_price_minor > 7_500:
        reasons.append("monthly_target_exceeded")
    if offer.total_cost_12_months_minor > 7_500 * 12:
        reasons.append("total_cost_target_exceeded")
    if "mobile_hotspot" not in offer.features:
        reasons.append("required_feature_missing")
    if "device_financing_change" in offer.applied_changes:
        reasons.append("forbidden_term_present")
    if "account_cancellation" in offer.applied_changes:
        reasons.append("unsupported_action")
    return reasons


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "EnvironmentAction",
    "EnvironmentDecision",
    "EnvironmentState",
    "IllegalEnvironmentTransitionError",
    "ProviderEnvironment",
    "ScenarioVerification",
]
