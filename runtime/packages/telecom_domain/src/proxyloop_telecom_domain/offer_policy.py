"""Pure, shared offer-compliance policy for the telecom vertical."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

_KNOWN_CREDITS_MINOR = {
    "predefined_promotion_credit": 5_000,
}


@dataclass(frozen=True, slots=True)
class OfferComplianceContext:
    """Public current-state inputs used to evaluate one Provider offer."""

    evaluated_at: datetime
    current_monthly_minor: int
    currency: str
    target_monthly_minor: int | None
    target_currency: str | None
    required_features: tuple[str, ...]
    forbidden_changes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_utc(self.evaluated_at, name="evaluated_at")
        _require_non_negative_int(
            self.current_monthly_minor, name="current_monthly_minor"
        )
        if self.target_monthly_minor is not None:
            _require_non_negative_int(
                self.target_monthly_minor, name="target_monthly_minor"
            )
        _require_currency(self.currency, name="currency")
        if self.target_currency is not None:
            _require_currency(self.target_currency, name="target_currency")
        _require_tokens(self.required_features, name="required_features")
        _require_tokens(self.forbidden_changes, name="forbidden_changes")


@dataclass(frozen=True, slots=True)
class OfferComplianceTerms:
    """Allowlisted Provider terms evaluated against one compliance context."""

    monthly_price_minor: int
    total_cost_12_months_minor: int
    currency: str
    fees_minor: int
    features: tuple[str, ...]
    applied_changes: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.monthly_price_minor, "monthly_price_minor"),
            (self.total_cost_12_months_minor, "total_cost_12_months_minor"),
            (self.fees_minor, "fees_minor"),
        ):
            _require_non_negative_int(value, name=name)
        _require_currency(self.currency, name="currency")
        _require_tokens(self.features, name="features")
        _require_tokens(self.applied_changes, name="applied_changes")
        _require_utc(self.expires_at, name="expires_at")


def offer_compliance_violations(
    context: OfferComplianceContext,
    terms: OfferComplianceTerms,
) -> tuple[str, ...]:
    """Return deterministic reason codes for terms that violate the context."""

    violations: list[str] = []

    if context.currency != terms.currency or (
        context.target_currency is not None
        and context.target_currency != context.currency
    ):
        violations.append("currency_mismatch")
    if terms.expires_at <= context.evaluated_at:
        violations.append("offer_expired")
    if terms.monthly_price_minor >= context.current_monthly_minor:
        violations.append("recurring_price_not_reduced")

    if context.target_monthly_minor is not None:
        if terms.monthly_price_minor > context.target_monthly_minor:
            violations.append("target_monthly_total_not_met")
        if terms.total_cost_12_months_minor > context.target_monthly_minor * 12:
            violations.append("total_cost_target_exceeded")
    elif terms.total_cost_12_months_minor >= context.current_monthly_minor * 12:
        violations.append("total_cost_exceeds_current")

    # The fictional fixture exposes credits as bounded public change tokens,
    # not as a separate contract field. Only the explicitly catalogued
    # promotion credit may reduce the total; unknown credit-like tokens do not
    # bypass fee consistency.
    known_credit_minor = sum(
        _KNOWN_CREDITS_MINOR.get(change, 0) for change in terms.applied_changes
    )
    expected_total = (
        terms.monthly_price_minor * 12 + terms.fees_minor - known_credit_minor
    )
    if terms.total_cost_12_months_minor != expected_total:
        violations.append("fee_total_mismatch")
    if not set(context.required_features) <= set(terms.features):
        violations.append("required_feature_missing")
    if set(context.forbidden_changes) & set(terms.applied_changes):
        violations.append("forbidden_change_present")

    return tuple(violations)


def _require_utc(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _require_non_negative_int(value: int, *, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_currency(value: str, *, name: str) -> None:
    if len(value) != 3 or not value.isascii() or value != value.upper():
        raise ValueError(f"{name} must be an uppercase ISO currency code")


def _require_tokens(values: tuple[str, ...], *, name: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be a tuple")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain non-empty text")


__all__ = [
    "OfferComplianceContext",
    "OfferComplianceTerms",
    "offer_compliance_violations",
]
