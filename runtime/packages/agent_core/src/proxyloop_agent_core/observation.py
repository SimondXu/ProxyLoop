from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from proxyloop_contracts import Case, ProviderOffer

_SUPPORTED_APPLIED_CHANGES = frozenset(
    {
        "plan_change",
        "revised_plan_change",
        "predefined_promotion_credit",
    }
)
_REMOVE_ADD_ON_PREFIX = "remove_add_on:"


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validate_utc(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _validate_text(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _validate_currency(value: str, *, name: str = "currency") -> None:
    if len(value) != 3 or not value.isascii() or value != value.upper():
        raise ValueError(f"{name} must be an uppercase ISO currency code")


def _validate_tokens(values: tuple[str, ...], *, name: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be a tuple")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    for value in values:
        _validate_text(value, name=name)


@dataclass(frozen=True)
class SafeOffer:
    """The provider-offer fields permitted in an agent-visible observation."""

    offer_id: str
    provider_id: str
    monthly_price_minor: int
    total_cost_12_months_minor: int
    currency: str
    features: tuple[str, ...]
    fees_minor: int
    term_months: int
    applied_changes: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self) -> None:
        _validate_text(self.offer_id, name="offer_id")
        _validate_text(self.provider_id, name="provider_id")
        _validate_currency(self.currency)
        for value, name in (
            (self.monthly_price_minor, "monthly_price_minor"),
            (self.total_cost_12_months_minor, "total_cost_12_months_minor"),
            (self.fees_minor, "fees_minor"),
            (self.term_months, "term_months"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        _validate_tokens(self.features, name="features")
        _validate_tokens(self.applied_changes, name="applied_changes")
        _validate_utc(self.expires_at, name="expires_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "offer_id": self.offer_id,
            "provider_id": self.provider_id,
            "monthly_price_minor": self.monthly_price_minor,
            "total_cost_12_months_minor": self.total_cost_12_months_minor,
            "currency": self.currency,
            "features": list(self.features),
            "fees_minor": self.fees_minor,
            "term_months": self.term_months,
            "applied_changes": list(self.applied_changes),
            "expires_at": _utc_text(self.expires_at),
        }


@dataclass(frozen=True)
class SafeObservation:
    """An explicit, serialized allowlist for consumer decision components."""

    schema_version: str
    case_id: str
    case_revision: int
    constraint_set_revision: int
    current_monthly_total_minor: int
    target_monthly_total_minor: int | None
    currency: str
    required_features: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    allowed_disclosures: tuple[str, ...]
    provider_id: str
    provider_message: str
    offers: tuple[SafeOffer, ...]
    requested_disclosures: tuple[str, ...]
    needs_clarification: bool
    transfer_available: bool
    approval_current: bool
    observed_at: datetime
    confirmation_evidence_available: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("unsupported safe observation schema version")
        _validate_text(self.case_id, name="case_id")
        _validate_text(self.provider_id, name="provider_id")
        _validate_text(self.provider_message, name="provider_message")
        _validate_currency(self.currency)
        for value, name in (
            (self.case_revision, "case_revision"),
            (self.constraint_set_revision, "constraint_set_revision"),
            (self.current_monthly_total_minor, "current_monthly_total_minor"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.case_revision < 1 or self.constraint_set_revision < 1:
            raise ValueError("revisions must be positive")
        if self.target_monthly_total_minor is not None and (
            type(self.target_monthly_total_minor) is not int
            or self.target_monthly_total_minor < 0
        ):
            raise ValueError("target_monthly_total_minor must be non-negative")
        _validate_tokens(self.required_features, name="required_features")
        _validate_tokens(self.forbidden_changes, name="forbidden_changes")
        _validate_tokens(self.allowed_disclosures, name="allowed_disclosures")
        _validate_tokens(self.requested_disclosures, name="requested_disclosures")
        for value, name in (
            (self.needs_clarification, "needs_clarification"),
            (self.transfer_available, "transfer_available"),
            (self.approval_current, "approval_current"),
            (
                self.confirmation_evidence_available,
                "confirmation_evidence_available",
            ),
        ):
            if type(value) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if not isinstance(self.offers, tuple):
            raise ValueError("offers must be a tuple")
        if len(self.offers) != len({offer.offer_id for offer in self.offers}):
            raise ValueError("offers cannot contain duplicate offer ids")
        for offer in self.offers:
            if offer.provider_id != self.provider_id:
                raise ValueError("offer provider must match observation provider")
        _validate_utc(self.observed_at, name="observed_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "case_revision": self.case_revision,
            "constraint_set_revision": self.constraint_set_revision,
            "current_monthly_total_minor": self.current_monthly_total_minor,
            "target_monthly_total_minor": self.target_monthly_total_minor,
            "currency": self.currency,
            "required_features": list(self.required_features),
            "forbidden_changes": list(self.forbidden_changes),
            "allowed_disclosures": list(self.allowed_disclosures),
            "provider_id": self.provider_id,
            "provider_message": self.provider_message,
            "offers": [offer.to_dict() for offer in self.offers],
            "requested_disclosures": list(self.requested_disclosures),
            "needs_clarification": self.needs_clarification,
            "transfer_available": self.transfer_available,
            "approval_current": self.approval_current,
            "observed_at": _utc_text(self.observed_at),
            "confirmation_evidence_available": self.confirmation_evidence_available,
        }

    def to_json(self) -> str:
        return (
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        )


class SafeObservationAdapter:
    """Build SafeObservation from canonical Case and explicit public fields."""

    @staticmethod
    def build(
        case: Case,
        *,
        provider_id: str,
        provider_message: str,
        offers: Iterable[ProviderOffer | SafeOffer],
        requested_disclosures: tuple[str, ...] = (),
        needs_clarification: bool = False,
        transfer_available: bool = False,
        approval_current: bool = True,
        observed_at: datetime,
        confirmation_evidence_available: bool = True,
    ) -> SafeObservation:
        if case.bill_snapshot is None:
            raise ValueError("SafeObservation requires a current bill snapshot")
        _validate_text(provider_id, name="provider_id")
        _validate_text(provider_message, name="provider_message")
        _validate_utc(observed_at, name="observed_at")

        safe_offers = tuple(
            SafeObservationAdapter._adapt_offer(
                offer, provider_id=provider_id, case_id=str(case.case_id)
            )
            for offer in offers
        )
        return SafeObservation(
            schema_version="1.0",
            case_id=str(case.case_id),
            case_revision=case.revision,
            constraint_set_revision=case.constraint_set_revision,
            current_monthly_total_minor=case.bill_snapshot.monthly_total.amount_minor,
            target_monthly_total_minor=(
                case.goal.target_monthly_total.amount_minor
                if case.goal.target_monthly_total is not None
                else None
            ),
            currency=case.bill_snapshot.monthly_total.currency,
            required_features=tuple(
                str(value) for value in case.goal.required_features
            ),
            forbidden_changes=tuple(
                str(value) for value in case.goal.forbidden_changes
            ),
            allowed_disclosures=tuple(
                str(value) for value in case.delegated_authority.allowed_disclosures
            ),
            provider_id=provider_id,
            provider_message=provider_message,
            offers=safe_offers,
            requested_disclosures=tuple(requested_disclosures),
            needs_clarification=needs_clarification,
            transfer_available=transfer_available,
            approval_current=approval_current,
            observed_at=observed_at,
            confirmation_evidence_available=confirmation_evidence_available,
        )

    @staticmethod
    def _adapt_offer(
        offer: ProviderOffer | SafeOffer, *, provider_id: str, case_id: str
    ) -> SafeOffer:
        if isinstance(offer, SafeOffer):
            if offer.provider_id != provider_id:
                raise ValueError("offer provider does not match provider_id")
            return offer
        if not isinstance(offer, ProviderOffer):
            raise TypeError("offers must contain ProviderOffer or SafeOffer values")
        if str(offer.case_id) != case_id or offer.provider_id != provider_id:
            raise ValueError(
                "provider offer does not belong to this public observation"
            )
        return SafeOffer(
            offer_id=str(offer.offer_id),
            provider_id=str(offer.provider_id),
            monthly_price_minor=offer.monthly_price.amount_minor,
            total_cost_12_months_minor=offer.total_cost.amount_minor,
            currency=offer.monthly_price.currency,
            features=tuple(str(value) for value in offer.features),
            fees_minor=sum(item.amount.amount_minor for item in offer.fees),
            term_months=offer.term_months,
            applied_changes=(),
            expires_at=offer.expires_at,
        )


class OracleAction(StrEnum):
    ACCEPT_OFFER = "accept_offer"
    REQUEST_CLARIFICATION = "request_clarification"
    ESCALATE = "escalate"
    REQUEST_REPLAN = "request_replan"
    REFUSE_DISCLOSURE = "refuse_disclosure"
    DECLINE = "decline"


@dataclass(frozen=True)
class OracleDecision:
    action: OracleAction
    offer_id: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action is OracleAction.ACCEPT_OFFER and self.offer_id is None:
            raise ValueError("accept_offer requires offer_id")
        if self.action is not OracleAction.ACCEPT_OFFER and self.offer_id is not None:
            raise ValueError("only accept_offer may reference an offer")


class ScriptedOracleConsumer:
    """Reference policy that accepts only a SafeObservation input."""

    def decide(self, observation: SafeObservation) -> OracleDecision:
        if not isinstance(observation, SafeObservation):
            raise TypeError("ScriptedOracleConsumer requires SafeObservation")
        if observation.needs_clarification:
            return OracleDecision(
                OracleAction.REQUEST_CLARIFICATION,
                None,
                ("needs_clarification",),
            )
        if not set(observation.requested_disclosures) <= set(
            observation.allowed_disclosures
        ):
            return OracleDecision(
                OracleAction.REFUSE_DISCLOSURE,
                None,
                ("disclosure_not_allowed",),
            )
        if not observation.approval_current:
            return OracleDecision(
                OracleAction.REQUEST_REPLAN,
                None,
                ("approval_not_current",),
            )
        if observation.transfer_available:
            return OracleDecision(OracleAction.ESCALATE, None, ("transfer_available",))
        if not observation.confirmation_evidence_available:
            return OracleDecision(
                OracleAction.REQUEST_REPLAN,
                None,
                ("confirmation_evidence_unavailable",),
            )

        valid_offers = tuple(
            offer
            for offer in observation.offers
            if self._is_valid_offer(offer, observation)
        )
        if not valid_offers:
            return OracleDecision(OracleAction.DECLINE, None, ("no_valid_offer",))
        selected = min(
            valid_offers,
            key=lambda offer: (
                offer.total_cost_12_months_minor,
                offer.monthly_price_minor,
                offer.offer_id,
            ),
        )
        return OracleDecision(
            OracleAction.ACCEPT_OFFER,
            selected.offer_id,
            ("valid_offer",),
        )

    @staticmethod
    def _is_valid_offer(offer: SafeOffer, observation: SafeObservation) -> bool:
        if offer.expires_at <= observation.observed_at:
            return False
        if offer.currency != observation.currency:
            return False
        if offer.total_cost_12_months_minor >= (
            observation.current_monthly_total_minor * 12
        ):
            return False
        if (
            observation.target_monthly_total_minor is not None
            and offer.monthly_price_minor > observation.target_monthly_total_minor
        ):
            return False
        if not set(observation.required_features) <= set(offer.features):
            return False
        if set(observation.forbidden_changes) & set(offer.applied_changes):
            return False
        return not any(
            change not in _SUPPORTED_APPLIED_CHANGES
            and not (
                change.startswith(_REMOVE_ADD_ON_PREFIX)
                and len(change) > len(_REMOVE_ADD_ON_PREFIX)
            )
            for change in offer.applied_changes
        )
