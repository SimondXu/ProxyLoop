"""M2 product-path parity: divergence classes, the delivery replay, and the
committed report's validation (no model)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import pytest
from proxyloop_agent_core import CaseCoordinator
from test_local_fast_gateway import _heldout_positions

from scripts import run_phase03c_product_parity as m2

GATE_PASSING_TEXT = "Could you say which part of the offer worries you most?"


@lru_cache(maxsize=1)
def _plan() -> tuple[dict[str, Any], ...]:
    return tuple(m2.plan_rows())


def _committed() -> dict[str, Any]:
    report: dict[str, Any] = json.loads(m2.REPORT.read_text(encoding="utf-8"))
    return report


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ([], "none"),
        (["offers[].applied_changes"], "applied_changes_dropped"),
        (
            ["transfer_available", "requested_disclosures"],
            "provider_flags_defaulted+requested_disclosures_dropped",
        ),
        (["offers[].offer_id"], "other:offers[].offer_id"),
    ],
)
def test_divergence_classes(fields: list[str], expected: str) -> None:
    assert m2._divergence_class(fields) == expected


def _output(**update: object) -> str:
    output: dict[str, object] = {
        "dialogue_act": "clarify",
        "fact_updates": [],
        "reasoner_request": {"needed": False, "reason_code": "none"},
        "completion_claim": {"status": "not_done", "evidence_message_ids": []},
        "response_text": GATE_PASSING_TEXT,
        "action_intent": None,
    }
    output.update(update)
    return json.dumps(output)


@pytest.mark.parametrize(
    ("raw", "status", "stage", "delivered"),
    [
        (_output(), "succeeded", "delivered", True),
        (_output(dialogue_act="confirm"), "succeeded", "gate_rejected", False),
        (
            _output(response_text="Your new total is 38880 a year."),
            "succeeded",
            "gate_rejected",
            False,
        ),
        (None, "invalid_output", "gateway_invalid_output", False),
        (None, "unrenderable", "gateway_unrenderable", False),
    ],
)
def test_delivery_replays_the_runtime_rules(
    raw: str | None, status: str, stage: str, delivered: bool
) -> None:
    scenario, position = _heldout_positions()[0]
    snapshot = m2.product_snapshot(scenario, position)
    view = CaseCoordinator.project_fast_view(snapshot)
    result = m2._delivery(raw, status, view, snapshot)
    assert (result["stage"], result["delivered"]) == (stage, delivered)
    if stage == "gate_rejected":
        assert all(code.startswith("fast_gate_") for code in result["codes"])


def test_the_plan_matches_the_committed_report() -> None:
    plan = list(_plan())
    assert _committed()["plan"] == plan
    refused = [row for row in plan if row["refusal_codes"]]
    assert {row["family_id"] for row in refused} == {"refusal-transfer"}
    assert len([row for row in plan if m2._needs_generation(row)]) == 200


def _drop_one(observed: dict[str, dict[str, Any]]) -> None:
    observed["distilled"]["rows"] = observed["distilled"]["rows"][1:]


def _duplicate(observed: dict[str, dict[str, Any]]) -> None:
    rows = observed["untuned"]["rows"]
    observed["untuned"]["rows"] = rows[:-1] + rows[:1]


def _edit_identity(observed: dict[str, dict[str, Any]]) -> None:
    observed["distilled"]["identity"]["decoding_fingerprint"] = "0" * 64


@pytest.mark.parametrize("tamper", [_drop_one, _duplicate, _edit_identity])
def test_validation_refuses_a_rewritten_row_set_or_identity(
    tamper: Callable[[dict[str, dict[str, Any]]], None],
) -> None:
    observed = m2._observed_from_report(_committed())
    m2.validate_observed(copy.deepcopy(observed), list(_plan()))
    tamper(observed)
    with pytest.raises(SystemExit):
        m2.validate_observed(observed, list(_plan()))
