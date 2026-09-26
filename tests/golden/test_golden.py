"""P1: golden ``render_messages`` snapshots per profile, plus the cp allow-list."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from tests.golden.cases import CASES, GOLDEN, Case

from proxyloop.contract.protocol import OMITTED_ACTIONS, OMITTED_LINES, render_messages
from proxyloop.contract.state import Mandate, PrivateState
from proxyloop.contract.views import FastView


def _golden(case: Case) -> dict[str, Any]:
    return json.loads((GOLDEN / "views" / f"{case.name}.json").read_text("utf-8"))


def _rendered(view: FastView, profile: str) -> list[dict[str, Any]]:
    return [
        m.model_dump(include={"role", "content"})
        for m in render_messages(view, profile)
    ]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_view_and_messages_match_golden(case: Case) -> None:
    golden = _golden(case)
    view = case.view()
    assert golden["profile"] == case.profile
    assert view.model_dump(mode="json") == golden["view"]
    assert _rendered(view, case.profile) == golden["messages"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_stored_view_rerenders_identically(case: Case) -> None:
    """Datasets re-render from the stored FastView JSON (TRAINING §6)."""

    golden = _golden(case)
    view = FastView.model_validate(golden["view"])
    assert _rendered(view, case.profile) == golden["messages"]


def test_golden_set_covers_the_acceptance_cases() -> None:
    by_profile = {c.profile for c in CASES}
    assert len(CASES) >= 12 and by_profile == {"pl_user_v1", "pl_cp_v1"}
    user_text = {c.name: _golden(c)["messages"][1]["content"] for c in CASES}
    assert "PENDING APPROVAL: (none)" in user_text["u01_empty"]
    assert "CASE AGENT GUIDANCE:\n(none)" in user_text["c01_empty"]
    assert "PENDING APPROVAL: $65.00 a month" in user_text["u05_approval_card"]
    assert "(fact:competitor_quote = $55.00 a month" in user_text["c03_guidance"]
    assert "offer:o1.fee:activation = $30.00" in user_text["c03_guidance"]
    for name in ("u06_over_budget", "c06_over_budget", "c07_over_budget_actions"):
        assert OMITTED_LINES in user_text[name]
    assert OMITTED_ACTIONS in user_text["c07_over_budget_actions"]
    assert "- action number 11" in user_text["c07_over_budget_actions"]


def _private_values(private: PrivateState) -> set[str]:
    values = {f.value for f in private.case_facts.values() if f.protected}
    mandate: Mandate | None = private.mandate
    if mandate is not None:
        for minor in (mandate.max_monthly_price_minor, mandate.max_one_time_fees_minor):
            if minor is not None:
                values |= {str(minor), f"{minor // 100}.{minor % 100:02d}"}
        if mandate.max_term_months is not None:
            values.add(str(mandate.max_term_months))
        values |= set(mandate.required_features) | set(mandate.forbidden_changes)
    if private.summary:
        values.add(private.summary)
    return values


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.profile == "pl_cp_v1"], ids=lambda c: c.name
)
def test_no_protected_or_mandate_value_in_cp_goldens(case: Case) -> None:
    text = json.dumps(_golden(case), ensure_ascii=False)
    values = _private_values(case.bb.private)
    leaked = {v for v in values if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", text)}
    assert not leaked
