"""The principal's mandate (ARCHITECTURE §9.3): its hash, what it covers, and the
hard constraints no approval can lift. Its bounds live in private state only."""

from __future__ import annotations

from decimal import Decimal

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.state import Blackboard, Mandate
from proxyloop.guard.policy import (
    UNSUPPORTED_APPLIED_CHANGE,
    unsupported_applied_changes,
)
from proxyloop.guard.terms import Terms

_BOUNDS = (  # the epoch too: a re-proposal after a decision is a new subject
    "mandate_id",
    "epoch",
    "max_monthly_price_minor",
    "max_term_months",
    "max_one_time_fees_minor",
    "required_features",
    "forbidden_changes",
    "expires_ms",
)


def mandate_hash(m: Mandate) -> str:
    bounds = m.model_dump(mode="json", include=set(_BOUNDS))
    for key in ("required_features", "forbidden_changes"):
        bounds[key] = sorted(bounds[key])
    return sha256_text(canonical_json(bounds))


def proposal(
    bb: Blackboard, mandate_id: str, **bounds: object
) -> tuple[str, dict[str, object]]:
    """``mandate.proposed``: bound to its hash and the current epoch. Only a
    ``mandate.decided`` from the UI or the sim approver grants it."""
    fields = {"mandate_id": mandate_id, "mandate_hash": "", "status": "proposed"}
    m = Mandate.model_validate(fields | {"epoch": bb.epoch} | bounds)
    m = m.model_copy(update={"mandate_hash": mandate_hash(m)})
    return "mandate.proposed", m.model_dump(mode="json")


def hard_violations(terms: Terms, m: Mandate | None) -> tuple[str, ...]:
    """Constraints an approval cannot lift (v0 ``offer_policy`` codes)."""
    out: list[str] = []
    if m is not None and not set(m.required_features) <= set(terms.features):
        out.append("required_feature_missing")
    if m is not None and set(m.forbidden_changes) & set(terms.applied_changes):
        out.append("forbidden_change_present")
    if unsupported_applied_changes(terms.applied_changes):
        out.append(UNSUPPORTED_APPLIED_CHANGE)
    return tuple(out)


def mandate_gap(bb: Blackboard, terms: Terms) -> str | None:
    """Why the mandate does not cover ``terms`` now; ``None`` if it does."""
    m = bb.private.mandate
    if m is None or m.status != "granted":
        return "not_authorized"
    if m.epoch != bb.epoch:
        return "mandate_stale_epoch"
    if m.expires_ms is not None and m.expires_ms <= bb.t_ms:
        return "mandate_expired"
    fees = sum(f.amount_minor for f in terms.fees)
    over = (
        (m.max_monthly_price_minor, terms.monthly_price_minor),
        (m.max_term_months, terms.term_months),
        (m.max_one_time_fees_minor, fees),
    )
    if any(bound is not None and value > bound for bound, value in over):
        return "outside_mandate"
    return None


def bound_numbers(m: Mandate) -> set[Decimal]:
    """The mandate's numbers as a person says them: dollars and months."""
    minor = (m.max_monthly_price_minor, m.max_one_time_fees_minor)
    out = {Decimal(v) / 100 for v in minor if v is not None}
    return out | ({Decimal(m.max_term_months)} if m.max_term_months else set())
