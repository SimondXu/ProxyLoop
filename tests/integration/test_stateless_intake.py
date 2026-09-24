"""PR-12: stateless ``POST /intake/proposals`` with a deterministic parser.

The parser turns free text into a typed, inert proposal of the four
``CreateCaseRequest`` fields plus closed-code clarifications. It creates no
Case, calls no model, and never logs, echoes, or persists the text.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

import httpx
import pytest
from proxyloop_api import (
    InMemoryOperationRecorder,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_api.app import CreateCaseRequest
from proxyloop_api.intake import INTAKE_PARSER_VERSION, propose_intake
from proxyloop_case_runtime import SCRIPTED_CASE_ID
from pydantic import ValidationError
from test_phase_05a_temporal_api import FailingTemporalCaseClient

MARKER = "zebra-marker-4471"
FULL_TEXT = (
    "Lower my mobile bill. I currently pay $92, I want it under $75. "
    "Keep my hotspot, and never change my device financing."
)


def _usd(amount_minor: int) -> dict[str, Any]:
    return {"amount_minor": amount_minor, "currency": "USD"}


def _body(text: str) -> dict[str, Any]:
    return propose_intake(text).model_dump(mode="json")


def _clarifications(text: str) -> dict[str, str]:
    return {item["field"]: item["reason"] for item in _body(text)["clarifications"]}


def test_a_full_sentence_proposes_all_four_typed_facts() -> None:
    body = _body(FULL_TEXT)

    assert body == {
        "parser": INTAKE_PARSER_VERSION,
        "proposal": {
            "current_monthly_total": _usd(9200),
            "target_monthly_total": _usd(7500),
            "mobile_hotspot_required": True,
            "device_financing_change_forbidden": True,
        },
        "clarifications": [],
    }


@pytest.mark.parametrize(
    ("text", "current", "target"),
    [
        ("Lower my bill from $92 to $75", 9200, 7500),
        ("Get my $92 bill down to $75", 9200, 7500),
        ("My bill is 92 dollars, target 75 USD", 9200, 7500),
        ("I'm paying $1,092.50 and would like to pay $80.25", 109250, 8025),
        ("Currently $92, $75 or less", 9200, 7500),
        ("I pay $92. My budget is $75.", 9200, 7500),
        ("My bill is $92 but I only want to pay $75", 9200, 7500),
    ],
)
def test_amounts_are_assigned_by_their_cues(
    text: str, current: int, target: int
) -> None:
    proposal = _body(text)["proposal"]

    assert proposal["current_monthly_total"] == _usd(current)
    assert proposal["target_monthly_total"] == _usd(target)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Lower my mobile bill",
            {
                "current_monthly_total": "missing",
                "target_monthly_total": "missing",
                "mobile_hotspot_required": "missing",
                "device_financing_change_forbidden": "missing",
            },
        ),
        (
            "I pay $92. Target $75 or maybe $78. Keep hotspot. Financing unchanged.",
            {"target_monthly_total": "ambiguous"},
        ),
        (
            "$92 and $75. Keep hotspot. Financing unchanged.",
            {
                "current_monthly_total": "ambiguous",
                "target_monthly_total": "ambiguous",
            },
        ),
        (
            "I pay $92, target $70-75. Keep hotspot. Financing unchanged.",
            {"target_monthly_total": "invalid_amount"},
        ),
        (
            "I pay -$92, target $75. Keep hotspot. Financing unchanged.",
            {"current_monthly_total": "invalid_amount"},
        ),
        (
            "I pay $92k, target $75. Keep hotspot. Financing unchanged.",
            {"current_monthly_total": "invalid_amount"},
        ),
        (
            "I pay $92, target $12.345. Keep hotspot. Financing unchanged.",
            {"target_monthly_total": "invalid_amount"},
        ),
        (
            "I pay €92, target $75. Keep hotspot. Financing unchanged.",
            {
                "current_monthly_total": "unsupported_currency",
                "target_monthly_total": "unsupported_currency",
            },
        ),
        (
            "I pay A$92, target $75. Keep hotspot. Financing unchanged.",
            {
                "current_monthly_total": "unsupported_currency",
                "target_monthly_total": "unsupported_currency",
            },
        ),
        (
            "I pay $92, target $75. Remove my hotspot. Financing unchanged.",
            {"mobile_hotspot_required": "ambiguous"},
        ),
        (
            "I pay $92, target $75. I don't need hotspot. Financing unchanged.",
            {"mobile_hotspot_required": "ambiguous"},
        ),
        (
            "I pay $92, target $75. What about hotspot? Financing unchanged.",
            {"mobile_hotspot_required": "ambiguous"},
        ),
        (
            "I pay $92, target $75. Keep hotspot. "
            "No change, but please modify device financing.",
            {"device_financing_change_forbidden": "ambiguous"},
        ),
        (
            "I pay $92, target $75. Keep hotspot. I want to change my financing.",
            {"device_financing_change_forbidden": "ambiguous"},
        ),
    ],
)
def test_unreadable_facts_become_clarifications_without_values(
    text: str, expected: dict[str, str]
) -> None:
    body = _body(text)

    assert _clarifications(text) == expected
    for field in expected:
        assert body["proposal"][field] is None


@pytest.mark.parametrize(
    ("text", "field", "reason", "value"),
    [
        (
            "I pay $72. Keep hotspot. Financing unchanged.",
            "current_monthly_total",
            "below_fixed_offer",
            _usd(7200),
        ),
        (
            "I pay $92, target $70. Keep hotspot. Financing unchanged.",
            "target_monthly_total",
            "below_fixed_offer",
            _usd(7000),
        ),
        (
            "I pay $80, target $85. Keep hotspot. Financing unchanged.",
            "target_monthly_total",
            "target_not_below_current",
            _usd(8500),
        ),
    ],
)
def test_value_rules_keep_the_value_and_name_the_rule(
    text: str, field: str, reason: str, value: dict[str, Any]
) -> None:
    body = _body(text)
    clarifications = _clarifications(text)

    assert clarifications.pop(field) == reason
    assert set(clarifications.values()) <= {"missing"}
    assert body["proposal"][field] == value


@pytest.mark.parametrize(
    "text",
    [
        "Keep my mobile hotspot and don't change device financing. $92 now, $75 target",
        "hotspot is required; leave the phone financing alone; from $92 to $75",
        "I need tethering. Device payments stay the same. From $92 to $75.",
    ],
)
def test_keep_and_never_change_phrases_set_the_typed_booleans(text: str) -> None:
    body = _body(text)

    assert body["clarifications"] == []
    assert body["proposal"]["mobile_hotspot_required"] is True
    assert body["proposal"]["device_financing_change_forbidden"] is True


_GRID = (7000, 7199, 7200, 7201, 7500, 9199, 9200, 9201, 12000)


@pytest.mark.parametrize("current", _GRID)
@pytest.mark.parametrize("target", _GRID)
def test_amount_rules_match_the_create_case_validator(
    current: int, target: int
) -> None:
    text = (
        f"I pay ${current // 100}.{current % 100:02d}, "
        f"target ${target // 100}.{target % 100:02d}"
    )
    amount_fields = {"current_monthly_total", "target_monthly_total"}
    parser_accepts = not amount_fields & set(_clarifications(text))
    try:
        CreateCaseRequest.model_validate(
            {
                "current_monthly_total": _usd(current),
                "target_monthly_total": _usd(target),
                "mobile_hotspot_required": True,
                "device_financing_change_forbidden": True,
            }
        )
        validator_accepts = True
    except ValidationError:
        validator_accepts = False

    assert parser_accepts is validator_accepts


def test_the_parser_is_deterministic() -> None:
    first = propose_intake(FULL_TEXT).model_dump_json()
    second = propose_intake(FULL_TEXT).model_dump_json()

    assert first == second


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def test_route_returns_the_typed_proposal_and_creates_no_case() -> None:
    runtime = ThinAgentRuntime()

    async def call() -> httpx.Response:
        async with _client(create_app(runtime)) as client:
            return await client.post("/intake/proposals", json={"text": FULL_TEXT})

    response = asyncio.run(call())

    assert response.status_code == 200
    assert response.json() == _body(FULL_TEXT)
    assert runtime.repository.get(SCRIPTED_CASE_ID) is None


def test_route_never_dispatches_in_temporal_mode() -> None:
    runtime = ThinAgentRuntime()
    temporal = FailingTemporalCaseClient(runtime, "temporal_unavailable")

    async def call() -> httpx.Response:
        async with _client(create_app(runtime, temporal_client=temporal)) as client:
            return await client.post("/intake/proposals", json={"text": FULL_TEXT})

    response = asyncio.run(call())

    assert response.status_code == 200
    assert response.json()["proposal"]["target_monthly_total"] == _usd(7500)
    assert runtime.repository.get(SCRIPTED_CASE_ID) is None


@pytest.mark.parametrize(
    "request_body",
    [
        {"text": ""},
        {"text": "x" * 2001},
        {"text": 42},
        {"text": "hello", "case_id": "x"},
        {},
    ],
)
def test_invalid_requests_get_the_content_free_422(
    request_body: dict[str, Any],
) -> None:
    async def call() -> httpx.Response:
        async with _client(create_app(ThinAgentRuntime())) as client:
            return await client.post("/intake/proposals", json=request_body)

    response = asyncio.run(call())

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "request_invalid", "message": "request rejected"}
    }


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (f"{FULL_TEXT} {MARKER}", 200),
        (f"{MARKER} " + "y" * 2000, 422),
    ],
)
def test_free_text_is_never_echoed_logged_or_recorded(
    text: str, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = InMemoryOperationRecorder()

    async def call() -> httpx.Response:
        async with _client(create_app(ThinAgentRuntime(), recorder=recorder)) as client:
            return await client.post("/intake/proposals", json={"text": text})

    with caplog.at_level(logging.DEBUG):
        response = asyncio.run(call())

    assert response.status_code == status
    assert MARKER not in response.text
    for record in caplog.records:
        assert MARKER not in record.getMessage()
    assert recorder.records
    assert [operation.operation for operation in recorder.records] == [
        "intake_proposal"
    ]
    for operation in recorder.records:
        assert MARKER not in json.dumps(asdict(operation))
