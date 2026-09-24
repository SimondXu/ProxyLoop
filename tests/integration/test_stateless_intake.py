"""PR-12: stateless ``POST /intake/proposals`` with a deterministic parser.

The parser turns free text into a typed, inert proposal of the four
``CreateCaseRequest`` fields plus closed-code clarifications. It creates no
Case, calls no model, and never logs, echoes, or persists the text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import pytest
from proxyloop_api import (
    InMemoryOperationRecorder,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_api.app import CreateCaseRequest
from proxyloop_api.intake import (
    INTAKE_PARSER_VERSION,
    INTAKE_TEXT_MAX_LENGTH,
    MAX_AMOUNT_MINOR,
    NORMALIZED_TEXT_MAX_LENGTH,
    propose_intake,
)
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
        ("I'm paying $1,092.50 and would like $80.25", 109250, 8025),
        ("Currently $92, $75 or less", 9200, 7500),
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
            # "No change" names no feature and follows "Keep hotspot": it
            # casts doubt on the hotspot too (I-1 orphan rule).
            "I pay $92, target $75. Keep hotspot. "
            "No change, but please modify device financing.",
            {
                "mobile_hotspot_required": "ambiguous",
                "device_financing_change_forbidden": "ambiguous",
            },
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


_GRID = (
    7000,
    7199,
    7200,
    7201,
    7500,
    9199,
    9200,
    9201,
    12000,
    MAX_AMOUNT_MINOR - 1,
    MAX_AMOUNT_MINOR,
    MAX_AMOUNT_MINOR + 1,
)


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


# Review I-1: a negation, a question, or a later doubt never becomes true.
@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("hotspot isn't required", "mobile_hotspot_required"),
        ("I won't need hotspot", "mobile_hotspot_required"),
        ("hotspot doesn't need to stay", "mobile_hotspot_required"),
        ("financing isn't staying the same", "device_financing_change_forbidden"),
        ("I can't keep financing the same", "device_financing_change_forbidden"),
        ("Can I keep my hotspot?", "mobile_hotspot_required"),
        ("Keep the hotspot? Nope", "mobile_hotspot_required"),
        (
            "I need a hotspot for work but honestly I'd drop it",
            "mobile_hotspot_required",
        ),
        (
            "keep financing unchanged but I want to end it",
            "device_financing_change_forbidden",
        ),
        ("keep hotspot unless it costs more", "mobile_hotspot_required"),
        ("hotspot is optional", "mobile_hotspot_required"),
        ("I'd rather not keep hotspot", "mobile_hotspot_required"),
        ("Is my hotspot kept", "mobile_hotspot_required"),
        (
            "keep my device payments, I'll pay off the phone next month",
            "device_financing_change_forbidden",
        ),
    ],
)
def test_negations_questions_and_later_doubts_are_ambiguous(
    text: str, field: str
) -> None:
    body = _body(text)

    assert body["proposal"][field] is None
    assert _clarifications(text)[field] == "ambiguous"


# Review I-2: an amount with no sure role marks both amounts ambiguous.
@pytest.mark.parametrize(
    "text",
    [
        "I want to save $80 on my $200 bill.",
        "Cut $75 off my $180 bill",
        "Lower my $92 bill by $12",
        "Reduce it by $75 from $160",
        "My bill is $92 and I want to spend at least $80 less",
        "I pay $150 and would accept anything under $100 but ideally $80",
        "bill $92, target between $75 and $80",
        "I pay $92 and want $70 to $80",
        "my bill went up to $92",
        "My bill went up to $92 and I want $80",
        "Went up from $80 to $92",
        "The plan went from $80 to $92",
        "It jumped from $85 to $110 and I want $90",
        "I was paying $80 until they raised it to $92, I want $80 back",
        "My bill rose to $110. I want $90",
        "Is it possible to go from $120 to $75?",
        "Could I pay $80 instead of $92?",
        "Write me a poem about my $5 coffee",
    ],
)
def test_change_range_history_and_question_amounts_are_ambiguous(
    text: str,
) -> None:
    body = _body(text)

    assert body["proposal"]["current_monthly_total"] is None
    assert body["proposal"]["target_monthly_total"] is None
    assert _clarifications(text)["current_monthly_total"] == "ambiguous"
    assert _clarifications(text)["target_monthly_total"] == "ambiguous"


@pytest.mark.parametrize(
    ("text", "field", "reason"),
    [
        # Review M-3: digits are ASCII only.
        (
            "my bill is $\u0669\u0662, I want $80",
            "current_monthly_total",
            "invalid_amount",
        ),
        ("I pay \u0669\u0662 dollars", "current_monthly_total", "missing"),
        (
            "My bill is $1,000,000.00, I want $80",
            "current_monthly_total",
            "invalid_amount",
        ),
    ],
)
def test_non_ascii_digits_and_amounts_over_the_cap_are_not_read(
    text: str, field: str, reason: str
) -> None:
    assert _body(text)["proposal"][field] is None
    assert _clarifications(text)[field] == reason


def test_the_cap_itself_is_read() -> None:
    body = _body("My bill is $999,999.99, I want $80")

    assert body["proposal"]["current_monthly_total"] == _usd(MAX_AMOUNT_MINOR)


OFF_TOPIC_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "apps/web/app/components/intake-offtopic-proposals.json"
)


# The Web's card-opening table uses these real parser outputs (review M-1,
# third amendment). Only this text reads values; the others read none.
ON_TOPIC_FIXTURE_TEXTS = {"My bill is $92 and I'd like $75"}


def test_off_topic_inputs_read_no_value_and_match_the_web_fixture() -> None:
    """The Web's card-opening test uses these real parser outputs."""

    fixture = json.loads(OFF_TOPIC_FIXTURE.read_text())

    assert list(fixture) == [
        "Help me plan a vacation for $2,000",
        "What does device financing mean?",
        "Can I keep my hotspot?",
        "Convert 10 euros to dollars",
        "Write me a poem about my $5 coffee",
        "My bill is $92 and I'd like $75",
        "My bill went up to $92 and I want $80",
        "My plan went up to $92",
        "Which phone should I take on a euro trip?",
    ]
    for text, expected in fixture.items():
        body = _body(text)
        assert body == expected
        if text not in ON_TOPIC_FIXTURE_TEXTS:
            assert all(value is None for value in body["proposal"].values())


# Re-review UX rules: common target cues, lowering requests (also as a
# question), and "Actually … both" / "Actually no." doubt on every feature.
@pytest.mark.parametrize(
    ("text", "current", "target"),
    [
        ("My bill is $92 and I'd like $75", 9200, 7500),
        ("I pay $92 and would be happy with $75", 9200, 7500),
        ("My phone bill is $92/month, I'd like it to be $75", 9200, 7500),
        ("My last bill was $92, I'm hoping for $75", 9200, 7500),
        ("My bill is $92, I want it to be $75", 9200, 7500),
        ("My bill is $92. Get it down to $75.", 9200, 7500),
        ("Can you lower my phone bill from $92 to $75?", 9200, 7500),
        ("How can I lower my $92 phone bill to $75?", 9200, 7500),
        ("Could you get my mobile bill down to $75? I pay $92.", 9200, 7500),
        ("Please reduce my bill from $92 to $75", 9200, 7500),
        ("Cut my bill from $92 to $75", 9200, 7500),
    ],
)
def test_common_target_cues_and_lowering_requests_are_read(
    text: str, current: int, target: int
) -> None:
    body = _body(text)

    assert body["proposal"]["current_monthly_total"] == _usd(current)
    assert body["proposal"]["target_monthly_total"] == _usd(target)


@pytest.mark.parametrize(
    "text",
    [
        "Is it possible to go from $120 to $75?",
        "I pay $92 now. Is $75 possible?",
        "Can you lower my bill? It went from $80 to $92.",
    ],
)
def test_a_question_without_a_clean_lowering_request_stays_ambiguous(
    text: str,
) -> None:
    clarifications = _clarifications(text)

    assert clarifications["current_monthly_total"] == "ambiguous"
    assert clarifications["target_monthly_total"] == "ambiguous"


@pytest.mark.parametrize(
    "text",
    [
        "I pay $92, target $75, keep hotspot, keep financing unchanged. "
        "Actually, forget it, I want to change both.",
        "Keep hotspot and financing unchanged. Actually no.",
        "Keep my hotspot. Leave financing alone. Actually, change everything.",
    ],
)
def test_an_actually_both_doubt_reaches_every_named_feature(text: str) -> None:
    clarifications = _clarifications(text)

    assert clarifications["mobile_hotspot_required"] == "ambiguous"
    assert clarifications["device_financing_change_forbidden"] == "ambiguous"


# Fourth amendment I-1: bare "get" is not a lowering request; a comparative
# ("lower than $X") in a question is not one either.
@pytest.mark.parametrize(
    "text",
    [
        "Should I get the $92 plan? I want to pay under $80.",
        "Why did my bill get to $92?",
        "Is $80 realistic to get?",
        "Should I get the $92 plan?",
        "Can I get it lower than $92?",
        "Is it lower than $92?",
    ],
)
def test_a_question_that_does_not_ask_to_lower_reads_no_amount(text: str) -> None:
    body = _body(text)

    assert body["proposal"]["current_monthly_total"] is None
    assert body["proposal"]["target_monthly_total"] is None
    assert _clarifications(text)["current_monthly_total"] == "ambiguous"
    assert _clarifications(text)["target_monthly_total"] == "ambiguous"


def test_get_with_a_lowering_word_is_still_a_lowering_request() -> None:
    text = "Could you get my mobile bill down to $75?"

    assert _body(text)["proposal"]["target_monthly_total"] == _usd(7500)
    assert _clarifications(text)["current_monthly_total"] == "missing"


# Fourth amendment M-2: a current cue nearer the amount than the target cue
# that rule-2 order would pick makes the amount ambiguous. The last four were
# read as values before the amendment; they are ambiguous now.
@pytest.mark.parametrize(
    "text",
    [
        "Hoping you can explain why my bill is $92",
        "I'm happy at $92, I'd rather keep it",
        "I'd like to lower my phone bill that is currently $92",
        "I pay $92. My budget is $75.",
        "My bill is $92 but I only want to pay $75",
        "I'm paying $92 and would like to pay $80",
        "My target is $75 and my bill is $92",
    ],
)
def test_an_amount_with_both_role_cues_is_ambiguous(text: str) -> None:
    body = _body(text)

    assert body["proposal"]["current_monthly_total"] is None
    assert body["proposal"]["target_monthly_total"] is None
    assert _clarifications(text)["current_monthly_total"] == "ambiguous"
    assert _clarifications(text)["target_monthly_total"] == "ambiguous"


# Fourth amendment M-3: a retraction after named features doubts all of them.
@pytest.mark.parametrize(
    "retraction", ["Wait, no.", "No.", "Never mind.", "Scratch that."]
)
def test_a_retraction_doubts_every_named_feature(retraction: str) -> None:
    text = f"Keep my hotspot. Keep financing unchanged. {retraction}"

    clarifications = _clarifications(text)

    assert clarifications["mobile_hotspot_required"] == "ambiguous"
    assert clarifications["device_financing_change_forbidden"] == "ambiguous"


# Fourth amendment M-1: text whose NFKC form is longer than 4000 characters is
# not read: every field is `missing`, with no value.
def test_text_that_expands_past_the_normalized_cap_is_not_read() -> None:
    text = "My bill is $92, I want $75, keep my hotspot. " + "\ufdfa" * 250

    body = _body(text)

    assert len(unicodedata.normalize("NFKC", text)) > NORMALIZED_TEXT_MAX_LENGTH
    assert all(value is None for value in body["proposal"].values())
    assert set(_clarifications(text).values()) == {"missing"}
    assert len(body["clarifications"]) == 4


def test_text_at_the_normalized_cap_is_still_read() -> None:
    head = "My bill is $92, I want $75. " + "\ufdfa" * 200
    padding = NORMALIZED_TEXT_MAX_LENGTH - len(unicodedata.normalize("NFKC", head))
    at_cap = head + " " * padding

    assert len(unicodedata.normalize("NFKC", at_cap)) == NORMALIZED_TEXT_MAX_LENGTH
    assert _body(at_cap)["proposal"]["current_monthly_total"] == _usd(9200)
    assert _body(at_cap + " ")["proposal"]["current_monthly_total"] is None


# Review I-A / M-5: bounded work on adversarial 2000-character input. Locally
# each case takes well under 1 ms (see the log); the bound is generous for CI.
_WORST_CASES = {
    "from 1, 1300 spaces, many $5": ("from 1" + " " * 1300 + "$5 " * 231),
    "1, 1000 spaces, many $5": ("1" + " " * 1000 + "$5 " * 333),
    "1, 1000 tabs, many $5": ("1" + "\t" * 1000 + "$5 " * 333),
    "fullwidth dollar and circled 20": "\uff04\u2473" * 1000,
    "$1- repeated": "$1-" * 667,
    "from 1, spaces, 8 x $5": ("from 1" + " " * 1970 + "$5 " * 8),
    "from 1, tabs, 8 x $5": ("from 1" + "\t" * 1970 + "$5 " * 8),
    "(from 1, 240 spaces, $5) x 8": ("from 1" + " " * 240 + "$5") * 8,
    "1 usd, spaces, 8 x $5": ("1 usd" + " " * 1970 + "$5 " * 8),
    # Fourth amendment M-1: NFKC expansion (U+FDFA is 18 characters after
    # NFKC) and a long run of orphan negations.
    "U+FDFA pad, 8 x $5": "\ufdfa" * 1975 + "$5 " * 8,
    "keep hotspot, 350 x No-sign, U+FDFA pad": (
        "keep hotspot, " + "\u2116, " * 350 + "\ufdfa" * 2000
    )[:INTAKE_TEXT_MAX_LENGTH],
    "keep hotspot, 500 x no,": "keep hotspot, " + "no, " * 500,
    "near the cap: U+FDFA x 100, keep hotspot, 470 x no,": (
        "\ufdfa" * 100 + "keep hotspot, " + "no, " * 470
    ),
}


@pytest.mark.parametrize("name", sorted(_WORST_CASES))
def test_adversarial_input_is_parsed_in_bounded_time(name: str) -> None:
    text = _WORST_CASES[name][-INTAKE_TEXT_MAX_LENGTH:]
    started = time.perf_counter()
    propose_intake(text)
    elapsed = time.perf_counter() - started
    print(f"{name}: {len(text)} chars, {elapsed * 1000:.2f} ms")

    assert elapsed < 0.25


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
