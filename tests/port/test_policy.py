from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from proxyloop.guard.policy import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_violations,
    unsupported_applied_changes,
)

V0 = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "v0" / "offer_policy.json"
    ).read_text("utf-8")
)


def _violations(case: dict[str, Any]) -> tuple[str, ...]:
    context = case["context"]
    offer = case["offer"]
    return offer_violations(
        OfferComplianceContext(
            evaluated_at=datetime.fromisoformat(context["evaluated_at"]),
            current_monthly_minor=context["current_monthly_minor"],
            currency=context["currency"],
            target_monthly_minor=context["target_monthly_minor"],
            target_currency=context["target_currency"],
            required_features=tuple(context["required_features"]),
            forbidden_changes=tuple(context["forbidden_changes"]),
        ),
        OfferComplianceTerms(
            monthly_price_minor=offer["monthly_price_minor"],
            total_cost_12_months_minor=offer["total_cost_12_months_minor"],
            currency=offer["currency"],
            fees_minor=offer["fees_minor"],
            features=tuple(offer["features"]),
            applied_changes=tuple(offer["applied_changes"]),
            expires_at=datetime.fromisoformat(offer["expires_at"]),
        ),
    )


@pytest.mark.parametrize("case", V0["cases"], ids=[c["name"] for c in V0["cases"]])
def test_offer_violations_match_v0(case: dict[str, Any]) -> None:
    if "error" in case:
        with pytest.raises(ValueError, match=re.escape(case["error"])):
            _violations(case)
        return
    assert _violations(case) == tuple(case["offer_violations"])
    assert unsupported_applied_changes(tuple(case["offer"]["applied_changes"])) == (
        tuple(case["unsupported_applied_changes"])
    )


def test_fixture_reaches_every_v0_reason_code() -> None:
    seen = {code for case in V0["cases"] for code in case.get("offer_violations", [])}
    assert seen == {
        "currency_mismatch",
        "offer_expired",
        "recurring_price_not_reduced",
        "target_monthly_total_not_met",
        "total_cost_target_exceeded",
        "total_cost_exceeds_current",
        "fee_total_mismatch",
        "required_feature_missing",
        "forbidden_change_present",
        "unsupported_applied_change",
    }


@pytest.mark.parametrize("row", V0["unsupported_applied_changes"])
def test_unsupported_applied_changes_match_v0(row: dict[str, Any]) -> None:
    assert unsupported_applied_changes(tuple(row["changes"])) == tuple(
        row["unsupported"]
    )
