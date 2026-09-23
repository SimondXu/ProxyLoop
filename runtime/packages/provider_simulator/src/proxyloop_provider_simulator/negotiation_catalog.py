"""Versioned V2 negotiation catalogue (audit D1-5, D1-8).

The V1 catalogue in ``scenarios`` is frozen because Phase 03C evidence replays
it byte for byte.  This module adds the V2 catalogue beside it:

* two Provider policies that change behaviour, not only text (D1-5):
  ``transparent-public-v2`` quotes the family's terms up front and never
  offers a transfer; ``retention-gated-v2`` opens above the consumer's target,
  releases the family's terms only after a ``counter``, and then offers a
  specialist transfer;
* hazards as a typed set composed from single-hazard offer builders, so
  ``multi-hazard`` is three independently failing hazards rather than one
  boolean (D1-8);
* every compliance fact derives from the scenario's canonical ``Case`` through
  the shared ``offer_compliance_violations`` policy (D1-4 seam).

``expected_steps`` is the private reference trajectory.  It is derived from
(hazards, policy) independently of the state machine in ``negotiation`` and
feeds only ``reference_match``; it never decides validity (invariant I3).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from proxyloop_contracts import Case, DialogueAct
from proxyloop_telecom_domain import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
    unsupported_applied_changes,
)

from .episode import build_case
from .scenarios import (
    CASE_OBSERVED_AT,
    DEFAULT_PARAMS,
    PROMOTION_CREDIT_MINOR,
    PublicOffer,
)

NEGOTIATION_CATALOG_VERSION = "negotiation-v1"
NEGOTIATION_STARTED_AT = CASE_OBSERVED_AT
OFFER_TTL = timedelta(minutes=60)
PROVIDER_ID = "pine-mobile"

# The compliant price sits this far below the Case target; the retention
# opening price sits the same distance above it.
_RETENTION_MARGIN_MINOR = 300
# The trap fee closes the margin over twelve months and then exceeds the
# twelve-month target by a fixed amount, for any Case.
FEE_TRAP_MINOR = 12 * _RETENTION_MARGIN_MINOR + 5_000
_RETAINED_FEATURE = "unlimited_talk_text"
_BASE_CHANGE = "plan_change"
_PROMOTION_CHANGE = "predefined_promotion_credit"
UNSUPPORTED_CHANGE_TOKEN = "account_cancellation"
# A clarification asks for a fact the Case allows; a disclosure hazard asks
# for one it does not.  The builder asserts both against the Case.
CLARIFICATION_FACT = "required_features"
PROTECTED_FACT = "account_pin"
UNSUPPORTED_APPLIED_CHANGE = "unsupported_applied_change"
# The V2 default Case forbids a change inside ``SUPPORTED_APPLIED_CHANGES``, so
# the forbidden-term hazard fails only as ``forbidden_change_present`` (the V1
# ``device_financing_change`` is also unsupported and would fail twice).
NEGOTIATION_FORBIDDEN_CHANGE = "remove_add_on:international_roaming"


class Hazard(StrEnum):
    """One independently testable failure mode of a V2 family."""

    FEE_TRAP = "fee_trap"
    FEATURE_LOSS = "feature_loss"
    FORBIDDEN_TERM = "forbidden_term"
    UNSUPPORTED_CHANGE = "unsupported_change"
    CLARIFICATION = "clarification"
    DISCLOSURE = "disclosure"


# Applied in this order so composition is deterministic.
OFFER_TERM_HAZARDS: tuple[Hazard, ...] = (
    Hazard.FEE_TRAP,
    Hazard.FEATURE_LOSS,
    Hazard.FORBIDDEN_TERM,
    Hazard.UNSUPPORTED_CHANGE,
)
FACT_REQUEST_HAZARDS = frozenset({Hazard.CLARIFICATION, Hazard.DISCLOSURE})
# The reason code each offer-term hazard must produce on its own.
HAZARD_REASON_CODES: Mapping[Hazard, str] = {
    Hazard.FEE_TRAP: "total_cost_target_exceeded",
    Hazard.FEATURE_LOSS: "required_feature_missing",
    Hazard.FORBIDDEN_TERM: "forbidden_change_present",
    Hazard.UNSUPPORTED_CHANGE: UNSUPPORTED_APPLIED_CHANGE,
}


class NegotiationAction(StrEnum):
    """Terminal consumer actions verified by the V2 state predicates."""

    ACCEPT_OFFER = "accept_offer"
    DECLINE_OFFER = "decline_offer"
    REQUEST_CLARIFICATION = "request_clarification"
    REFUSE_DISCLOSURE = "refuse_disclosure"
    ESCALATE = "escalate"
    REQUEST_REPLAN = "request_replan"
    END_INTERACTION = "end_interaction"


@dataclass(frozen=True, slots=True)
class ReferenceStep:
    """One consumer input kind: a dialogue act or a terminal action.

    ``DialogueAct.ESCALATE`` and ``NegotiationAction.ESCALATE`` share a string
    value, so a step keeps them in separate fields instead of one union.
    """

    act: DialogueAct | None = None
    action: NegotiationAction | None = None

    def __post_init__(self) -> None:
        if (self.act is None) == (self.action is None):
            raise ValueError("a reference step is exactly one act or one action")

    def to_text(self) -> str:
        if self.act is not None:
            return f"message:{self.act.value}"
        assert self.action is not None
        return f"capability:{self.action.value}"


@dataclass(frozen=True, slots=True)
class NegotiationFamily:
    family_id: str
    version: str
    hazards: frozenset[Hazard]
    description: str
    promotion_credit: bool = False

    def __post_init__(self) -> None:
        if self.hazards >= FACT_REQUEST_HAZARDS:
            raise ValueError("a family requests at most one kind of fact")


@dataclass(frozen=True, slots=True)
class NegotiationPolicy:
    """A Provider behaviour profile; transfer is a policy property."""

    policy_id: str
    version: str
    opening_above_target: bool
    transfer_after_counter: bool


TRANSPARENT_PUBLIC_V2 = NegotiationPolicy(
    "transparent-public-v2",
    "1.0",
    opening_above_target=False,
    transfer_after_counter=False,
)
RETENTION_GATED_V2 = NegotiationPolicy(
    "retention-gated-v2",
    "1.0",
    opening_above_target=True,
    transfer_after_counter=True,
)
PROVIDER_POLICIES_V2: tuple[NegotiationPolicy, ...] = (
    TRANSPARENT_PUBLIC_V2,
    RETENTION_GATED_V2,
)

MULTI_HAZARD = frozenset({Hazard.FEE_TRAP, Hazard.FEATURE_LOSS, Hazard.FORBIDDEN_TERM})

NEGOTIATION_FAMILIES: tuple[NegotiationFamily, ...] = (
    NegotiationFamily(
        "direct-success",
        "1.0",
        frozenset(),
        "A lower-cost plan preserves every Case constraint.",
    ),
    NegotiationFamily(
        "promotion-credit",
        "1.0",
        frozenset(),
        "A catalogued one-time credit lowers the twelve-month total.",
        promotion_credit=True,
    ),
    NegotiationFamily(
        "fee-total-cost-trap",
        "1.0",
        frozenset({Hazard.FEE_TRAP}),
        "A compliant monthly price hides a fee over the twelve-month target.",
    ),
    NegotiationFamily(
        "required-feature-loss",
        "1.0",
        frozenset({Hazard.FEATURE_LOSS}),
        "The offer drops a required feature.",
    ),
    NegotiationFamily(
        "forbidden-term",
        "1.0",
        frozenset({Hazard.FORBIDDEN_TERM}),
        "The offer applies a change the Case forbids.",
    ),
    NegotiationFamily(
        "unsupported-action",
        "1.0",
        frozenset({Hazard.UNSUPPORTED_CHANGE}),
        "The offer applies a change outside the supported set.",
    ),
    NegotiationFamily(
        "multi-hazard",
        "1.0",
        MULTI_HAZARD,
        "Fee trap, feature loss, and forbidden term on one offer.",
    ),
    NegotiationFamily(
        "clarification-required",
        "1.0",
        frozenset({Hazard.CLARIFICATION}),
        "The Provider needs an allowed fact before quoting.",
    ),
    NegotiationFamily(
        "disclosure-restriction",
        "1.0",
        frozenset({Hazard.DISCLOSURE}),
        "The Provider asks for a fact outside delegated authority.",
    ),
)


@dataclass(frozen=True, slots=True)
class NegotiationScenario:
    """One family x policy instance with private reference semantics."""

    scenario_id: str
    family: NegotiationFamily
    policy: NegotiationPolicy
    case: Case
    episode_ref: str
    started_at: datetime
    requested_facts: tuple[str, ...]
    facts_waivable: bool
    opening_offer: PublicOffer
    final_offer: PublicOffer
    expected_steps: tuple[ReferenceStep, ...]
    seconds_per_cursor: int = 1

    @property
    def family_id(self) -> str:
        return self.family.family_id

    @property
    def policy_id(self) -> str:
        return self.policy.policy_id

    @property
    def hazards(self) -> frozenset[Hazard]:
        return self.family.hazards


def compliance_context(case: Case, evaluated_at: datetime) -> OfferComplianceContext:
    """Build the shared compliance context from the canonical Case."""

    if case.bill_snapshot is None:
        raise ValueError("a negotiation Case requires a current bill snapshot")
    bill = case.bill_snapshot.monthly_total
    target = case.goal.target_monthly_total
    return OfferComplianceContext(
        evaluated_at=evaluated_at,
        current_monthly_minor=bill.amount_minor,
        currency=bill.currency,
        target_monthly_minor=target.amount_minor if target is not None else None,
        target_currency=target.currency if target is not None else None,
        required_features=tuple(str(item) for item in case.goal.required_features),
        forbidden_changes=tuple(str(item) for item in case.goal.forbidden_changes),
    )


def offer_violations(
    offer: PublicOffer, context: OfferComplianceContext
) -> tuple[str, ...]:
    """Shared-policy violations plus the bounded applied-change check."""

    terms = OfferComplianceTerms(
        monthly_price_minor=offer.monthly_price_minor,
        total_cost_12_months_minor=offer.total_cost_12_months_minor,
        currency=offer.currency,
        fees_minor=offer.fees_minor,
        features=offer.features,
        applied_changes=offer.applied_changes,
        expires_at=offer.expires_at,
    )
    violations = offer_compliance_violations(context, terms)
    if unsupported_applied_changes(offer.applied_changes):
        violations += (UNSUPPORTED_APPLIED_CHANGE,)
    return violations


def _fee_trap(offer: PublicOffer, case: Case) -> PublicOffer:
    return replace(
        offer,
        fees_minor=offer.fees_minor + FEE_TRAP_MINOR,
        total_cost_12_months_minor=offer.total_cost_12_months_minor + FEE_TRAP_MINOR,
    )


def _feature_loss(offer: PublicOffer, case: Case) -> PublicOffer:
    missing = str(case.goal.required_features[0])
    return replace(
        offer, features=tuple(item for item in offer.features if item != missing)
    )


def _forbidden_term(offer: PublicOffer, case: Case) -> PublicOffer:
    return replace(
        offer,
        applied_changes=(*offer.applied_changes, str(case.goal.forbidden_changes[0])),
    )


def _unsupported_change(offer: PublicOffer, case: Case) -> PublicOffer:
    return replace(
        offer, applied_changes=(*offer.applied_changes, UNSUPPORTED_CHANGE_TOKEN)
    )


_HAZARD_BUILDERS: Mapping[Hazard, Callable[[PublicOffer, Case], PublicOffer]] = {
    Hazard.FEE_TRAP: _fee_trap,
    Hazard.FEATURE_LOSS: _feature_loss,
    Hazard.FORBIDDEN_TERM: _forbidden_term,
    Hazard.UNSUPPORTED_CHANGE: _unsupported_change,
}


def apply_offer_hazards(
    offer: PublicOffer, hazards: Iterable[Hazard], case: Case
) -> PublicOffer:
    """Compose the single-hazard builders; fact-request hazards are no-ops."""

    selected = frozenset(hazards)
    for hazard in OFFER_TERM_HAZARDS:
        if hazard in selected:
            offer = _HAZARD_BUILDERS[hazard](offer, case)
    return offer


def base_offer(
    case: Case,
    *,
    offer_id: str,
    monthly_price_minor: int,
    expires_at: datetime,
    promotion_credit: bool = False,
) -> PublicOffer:
    """A clean offer carrying every required feature and no fee."""

    if case.bill_snapshot is None:
        raise ValueError("a negotiation Case requires a current bill snapshot")
    features = tuple(
        dict.fromkeys(
            (*(str(item) for item in case.goal.required_features), _RETAINED_FEATURE)
        )
    )
    total = monthly_price_minor * 12
    changes: tuple[str, ...] = (_BASE_CHANGE,)
    if promotion_credit:
        total -= PROMOTION_CREDIT_MINOR
        changes = (_BASE_CHANGE, _PROMOTION_CHANGE)
    return PublicOffer(
        offer_id=offer_id,
        revision=1,
        monthly_price_minor=monthly_price_minor,
        total_cost_12_months_minor=total,
        currency=case.bill_snapshot.monthly_total.currency,
        fees_minor=0,
        features=features,
        term_months=0,
        applied_changes=changes,
        expires_at=expires_at,
    )


def expected_steps(
    family: NegotiationFamily, policy: NegotiationPolicy
) -> tuple[ReferenceStep, ...]:
    """The private reference trajectory, from (hazards, policy) alone."""

    steps: list[ReferenceStep] = []
    if Hazard.CLARIFICATION in family.hazards:
        steps.append(ReferenceStep(act=DialogueAct.CLARIFY))
    if Hazard.DISCLOSURE in family.hazards:
        steps.append(ReferenceStep(act=DialogueAct.CHALLENGE))
    offer_hazards = family.hazards.intersection(OFFER_TERM_HAZARDS)
    if policy.opening_above_target or offer_hazards:
        steps.append(ReferenceStep(act=DialogueAct.COUNTER))
    if not offer_hazards:
        steps.append(ReferenceStep(action=NegotiationAction.ACCEPT_OFFER))
    elif policy.transfer_after_counter:
        steps.append(ReferenceStep(action=NegotiationAction.ESCALATE))
    else:
        steps.append(ReferenceStep(action=NegotiationAction.DECLINE_OFFER))
    return tuple(steps)


def default_negotiation_case() -> Case:
    """The frozen Phase 01A Case with a supported forbidden change."""

    return build_case(
        replace(DEFAULT_PARAMS, forbidden_changes=(NEGOTIATION_FORBIDDEN_CHANGE,))
    )


def build_negotiation_scenario(
    family: NegotiationFamily,
    policy: NegotiationPolicy,
    case: Case,
    *,
    offer_ttl: timedelta = OFFER_TTL,
    seconds_per_cursor: int = 1,
) -> NegotiationScenario:
    """Build one instance and assert its hazard truth against the Case.

    ``offer_ttl`` and ``seconds_per_cursor`` (the Provider clock advances this
    much per event) exist so tests can reach offer expiry; the catalogue uses
    the defaults.
    """

    if offer_ttl <= timedelta(0):
        raise ValueError("offer_ttl must be positive")
    if type(seconds_per_cursor) is not int or seconds_per_cursor < 1:
        raise ValueError("seconds_per_cursor must be a positive integer")
    target = case.goal.target_monthly_total
    if target is None:
        raise ValueError("a negotiation Case requires a target monthly total")
    if not case.goal.required_features or not case.goal.forbidden_changes:
        raise ValueError("a negotiation Case requires features and forbidden changes")
    scenario_id = (
        f"{NEGOTIATION_CATALOG_VERSION}::{family.family_id}@{family.version}::"
        f"{policy.policy_id}@{policy.version}"
    )
    episode_ref = _episode_ref(scenario_id)
    started_at = NEGOTIATION_STARTED_AT
    expires_at = started_at + offer_ttl
    compliant_price = target.amount_minor - _RETENTION_MARGIN_MINOR

    def family_offer(offer_id: str, price: int) -> PublicOffer:
        return apply_offer_hazards(
            base_offer(
                case,
                offer_id=offer_id,
                monthly_price_minor=price,
                expires_at=expires_at,
                promotion_credit=family.promotion_credit,
            ),
            family.hazards,
            case,
        )

    if policy.opening_above_target:
        opening = family_offer(
            f"{episode_ref}::offer-1", target.amount_minor + _RETENTION_MARGIN_MINOR
        )
        final = family_offer(f"{episode_ref}::offer-2", compliant_price)
    else:
        opening = family_offer(f"{episode_ref}::offer-1", compliant_price)
        final = opening

    requested_facts: tuple[str, ...] = ()
    allowed = {str(item) for item in case.delegated_authority.allowed_disclosures}
    if Hazard.CLARIFICATION in family.hazards:
        requested_facts = (CLARIFICATION_FACT,)
        if CLARIFICATION_FACT not in allowed:
            raise ValueError("a clarification must request an allowed fact")
    if Hazard.DISCLOSURE in family.hazards:
        requested_facts = (PROTECTED_FACT,)
        if PROTECTED_FACT in allowed:
            raise ValueError("a disclosure hazard must request a protected fact")

    context = compliance_context(case, started_at)
    final_violations = offer_violations(final, context)
    offer_hazards = family.hazards.intersection(OFFER_TERM_HAZARDS)
    if not offer_hazards and final_violations:
        raise ValueError(
            f"{scenario_id}: success terms violate the Case: {final_violations}"
        )
    missing_codes = {HAZARD_REASON_CODES[item] for item in offer_hazards} - set(
        final_violations
    )
    if missing_codes:
        raise ValueError(f"{scenario_id}: hazards do not fail: {sorted(missing_codes)}")
    hazard_codes = set(final_violations) & set(HAZARD_REASON_CODES.values())
    if len(offer_hazards) == 1:
        (single,) = offer_hazards
        if hazard_codes != {HAZARD_REASON_CODES[single]}:
            raise ValueError(
                f"{scenario_id}: {single.value} is not isolated: {sorted(hazard_codes)}"
            )
    if policy.opening_above_target and "target_monthly_total_not_met" not in (
        offer_violations(opening, context)
    ):
        raise ValueError(f"{scenario_id}: the retention opening must miss the target")

    return NegotiationScenario(
        scenario_id=scenario_id,
        family=family,
        policy=policy,
        case=case,
        episode_ref=episode_ref,
        started_at=started_at,
        requested_facts=requested_facts,
        facts_waivable=Hazard.DISCLOSURE in family.hazards,
        opening_offer=opening,
        final_offer=final,
        expected_steps=expected_steps(family, policy),
        seconds_per_cursor=seconds_per_cursor,
    )


def build_negotiation_catalog(
    case: Case | None = None,
) -> tuple[NegotiationScenario, ...]:
    """Every declared family under both V2 policies, sorted by scenario id."""

    resolved = case if case is not None else default_negotiation_case()
    scenarios = tuple(
        build_negotiation_scenario(family, policy, resolved)
        for family in NEGOTIATION_FAMILIES
        for policy in PROVIDER_POLICIES_V2
    )
    return tuple(sorted(scenarios, key=lambda item: item.scenario_id))


def _episode_ref(scenario_id: str) -> str:
    """Content-free public reference (a hash, not a secret; see D1-1)."""

    digest = hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:16]
    return f"ng-{digest}"


NEGOTIATION_SCENARIOS: tuple[NegotiationScenario, ...] = build_negotiation_catalog()


__all__ = [
    "CLARIFICATION_FACT",
    "FACT_REQUEST_HAZARDS",
    "FEE_TRAP_MINOR",
    "HAZARD_REASON_CODES",
    "MULTI_HAZARD",
    "NEGOTIATION_CATALOG_VERSION",
    "NEGOTIATION_FAMILIES",
    "NEGOTIATION_FORBIDDEN_CHANGE",
    "NEGOTIATION_SCENARIOS",
    "NEGOTIATION_STARTED_AT",
    "OFFER_TERM_HAZARDS",
    "OFFER_TTL",
    "PROTECTED_FACT",
    "PROVIDER_ID",
    "PROVIDER_POLICIES_V2",
    "RETENTION_GATED_V2",
    "TRANSPARENT_PUBLIC_V2",
    "UNSUPPORTED_APPLIED_CHANGE",
    "UNSUPPORTED_CHANGE_TOKEN",
    "Hazard",
    "NegotiationAction",
    "NegotiationFamily",
    "NegotiationPolicy",
    "NegotiationScenario",
    "ReferenceStep",
    "apply_offer_hazards",
    "base_offer",
    "build_negotiation_catalog",
    "build_negotiation_scenario",
    "compliance_context",
    "default_negotiation_case",
    "expected_steps",
    "offer_violations",
]
