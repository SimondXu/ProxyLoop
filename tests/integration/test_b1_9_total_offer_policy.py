"""The runtime's offer-policy check never raises on a contract-valid offer (B1-9)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_contracts import (
    Case,
    CasePhase,
    Evidence,
    LineItem,
    LineItemCategory,
    Money,
    ProviderOffer,
)
from proxyloop_provider_simulator.provider import FictionalMobileProvider
from test_phase_06b1_channel_runtime import BASE_TIME
from test_slow_refresh_strategy_expiry import _Clock


class _CreditingProvider(FictionalMobileProvider):
    """Issues the fixture offer with a contract-valid negative credit line."""

    def issue_offer(
        self, case: Case, *, issued_at: datetime
    ) -> tuple[ProviderOffer, Evidence]:
        offer, evidence = super().issue_offer(case, issued_at=issued_at)
        credit = LineItem(
            name="Loyalty credit",
            category=LineItemCategory.CREDIT,
            amount=Money(amount_minor=-1_000, currency=offer.monthly_price.currency),
        )
        # Net fees of -1000 make the 12-month total arithmetic consistent, so
        # only the out-of-domain fee sum can keep this offer from approval.
        total = offer.total_cost.model_copy(
            update={"amount_minor": offer.total_cost.amount_minor - 1_000}
        )
        credited = ProviderOffer.model_validate_json(
            offer.model_copy(
                update={"fees": (credit,), "total_cost": total}
            ).model_dump_json()
        )
        return credited, evidence


def test_a_negative_fee_offer_does_not_raise_and_requests_no_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "FictionalMobileProvider", _CreditingProvider)
    repository = InMemoryCaseRepository()
    runtime = ThinAgentRuntime(repository, clock=_Clock(BASE_TIME))
    created = runtime.create_case(occurred_at=BASE_TIME)
    (offer,) = created.snapshot.offers
    assert sum(item.amount.amount_minor for item in offer.fees) == -1_000

    result = runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Is the offer ready?",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )

    assert result.approval is None
    assert result.snapshot.approval_requests == ()
    assert result.snapshot.action_intents == ()
    assert result.snapshot.case.phase is not CasePhase.AWAITING_APPROVAL
    assert runtime_module.offer_compliance_violations_for_case(
        result.snapshot.case,
        offer,
        evaluated_at=BASE_TIME + timedelta(minutes=1),
    ) == ("offer_terms_invalid",)
