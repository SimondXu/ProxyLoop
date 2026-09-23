"""The browser receives an explicit allow-listed projection, never the snapshot."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from proxyloop_api import ThinAgentRuntime, create_app

CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}

ENVELOPE_KEYS = {
    "case_id",
    "case",
    "snapshot",
    "revision",
    "event_cursor",
    "route",
    "approval",
    "evidence",
    "completion",
    "execution_count",
}
CASE_KEYS = {"case_id", "revision", "phase", "bill_snapshot", "goal", "constraints"}
BILL_KEYS = {"monthly_total", "usage"}
USAGE_KEYS = {"data_megabytes"}
GOAL_KEYS = {
    "desired_outcome",
    "target_monthly_total",
    "required_features",
    "forbidden_changes",
    "deadline",
}
CONSTRAINT_KEYS = {"classification", "statement"}
MONEY_KEYS = {"amount_minor", "currency"}
SNAPSHOT_KEYS = {
    "revision",
    "event_cursor",
    "phase",
    "pending_execution",
    "case",
    "offers",
    "visible_events",
    "completion",
}
OFFER_KEYS = {
    "offer_id",
    "revision",
    "provider_id",
    "monthly_price",
    "total_cost",
    "fees",
    "term_months",
    "features",
    "expires_at",
}
FEE_KEYS = {"name", "category", "amount"}
VISIBLE_EVENT_KEYS = {"event_cursor", "actor", "event_type", "content", "occurred_at"}
APPROVAL_KEYS = {
    "approval_id",
    "case_revision",
    "action_intent_revision",
    "action_type",
    "decision",
    "requested_at",
    "decided_at",
    "expires_at",
    "material_terms_hash",
    "offer_ref",
}
OFFER_REF_KEYS = {"offer_id", "offer_revision"}
EVIDENCE_KEYS = {"evidence_id", "source_type", "observed_at"}
COMPLETION_KEYS = {"decision", "evidence_ids", "missing_evidence", "reason_codes"}
FAST_KEYS = {"dialogue_act", "response_text", "created_at"}
EXCLUDED_KEYS = {
    "pins",
    "planning_basis",
    "capability_manifest",
    "delegated_authority",
    "fact_ledger",
    "strategy",
    "action_intents",
    "approval_requests",
    "idempotency_key",
    "provider_config_ref",
}


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys |= _all_keys(child)
        return keys
    if isinstance(value, list):
        keys = set()
        for child in value:
            keys |= _all_keys(child)
        return keys
    return set()


def _assert_money(value: Any) -> None:
    assert set(value) == MONEY_KEYS


def _assert_case(value: dict[str, Any]) -> None:
    assert set(value) == CASE_KEYS
    assert set(value["bill_snapshot"]) == BILL_KEYS
    _assert_money(value["bill_snapshot"]["monthly_total"])
    assert set(value["bill_snapshot"]["usage"]) == USAGE_KEYS
    assert isinstance(value["bill_snapshot"]["usage"]["data_megabytes"], int)
    assert set(value["goal"]) == GOAL_KEYS
    _assert_money(value["goal"]["target_monthly_total"])
    assert value["constraints"]
    for constraint in value["constraints"]:
        assert set(constraint) == CONSTRAINT_KEYS


def _assert_projection(payload: dict[str, Any]) -> None:
    fast_keys = {"fast"} if "fast" in payload else set()
    assert set(payload) == ENVELOPE_KEYS | fast_keys
    _assert_case(payload["case"])

    snapshot = payload["snapshot"]
    assert set(snapshot) == SNAPSHOT_KEYS
    _assert_case(snapshot["case"])
    assert snapshot["completion"] == payload["completion"]
    for offer in snapshot["offers"]:
        assert set(offer) == OFFER_KEYS
        _assert_money(offer["monthly_price"])
        _assert_money(offer["total_cost"])
        for fee in offer["fees"]:
            assert set(fee) == FEE_KEYS
            _assert_money(fee["amount"])
    for event in snapshot["visible_events"]:
        assert set(event) == VISIBLE_EVENT_KEYS

    approval = payload["approval"]
    if approval is not None:
        assert set(approval) == APPROVAL_KEYS
        if approval["offer_ref"] is not None:
            assert set(approval["offer_ref"]) == OFFER_REF_KEYS
    for item in payload["evidence"]:
        assert set(item) == EVIDENCE_KEYS
    assert set(payload["completion"]) == COMPLETION_KEYS
    if "fast" in payload:
        assert set(payload["fast"]) == FAST_KEYS

    keys = _all_keys(payload)
    assert not keys & EXCLUDED_KEYS
    assert not [key for key in keys if "fingerprint" in key or "idempotency" in key]


def test_browser_routes_emit_only_the_allow_listed_projection() -> None:
    asyncio.run(_test_browser_routes_emit_only_the_allow_listed_projection())


async def _test_browser_routes_emit_only_the_allow_listed_projection() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(ThinAgentRuntime())),
        base_url="http://testserver",
    ) as client:
        created = await client.post("/cases", json=CREATE_CASE_REQUEST)
        assert created.status_code == 201
        _assert_projection(created.json())
        case_id = created.json()["case_id"]

        turn = await client.post(
            f"/cases/{case_id}/events",
            json={
                "content": "Please review the current offer.",
                "expected_revision": created.json()["revision"],
            },
        )
        assert turn.status_code == 200
        waiting = turn.json()
        _assert_projection(waiting)
        assert "fast" in waiting
        assert waiting["snapshot"]["offers"]
        approval = waiting["approval"]
        assert approval["decision"] == "pending"
        assert approval["offer_ref"] is not None

        read = await client.get(f"/cases/{case_id}")
        assert read.status_code == 200
        _assert_projection(read.json())

        approved = await client.post(
            f"/cases/{case_id}/approvals/{approval['approval_id']}",
            json={
                "decision": "approved",
                "expected_revision": waiting["revision"],
                "expected_case_revision": approval["case_revision"],
                "expected_action_intent_revision": approval["action_intent_revision"],
            },
        )
        assert approved.status_code == 200
        completed = approved.json()
        _assert_projection(completed)
        assert completed["completion"]["decision"] == "complete"
        assert completed["execution_count"] == 1
        assert completed["evidence"]
        assert set(completed["completion"]["evidence_ids"]) <= {
            item["evidence_id"] for item in completed["evidence"]
        }

        final = await client.get(f"/cases/{case_id}")
        assert final.status_code == 200
        _assert_projection(final.json())
