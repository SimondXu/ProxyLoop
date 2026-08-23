from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from proxyloop_contracts import (
    CANONICAL_MODELS,
    ApprovalRequest,
    Case,
    CompletionDecision,
    Evidence,
    FastTurnDecision,
    Money,
    validate_contract_json,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "tests" / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_valid_case_round_trips_through_canonical_interface() -> None:
    document = validate_contract_json(read_fixture("case.valid.json"))

    assert isinstance(document, Case)
    assert document.schema_version == "1.0"
    assert document.bill_snapshot is not None
    assert document.bill_snapshot.monthly_total == Money(
        amount_minor=9200,
        currency="USD",
    )
    assert '"contract_type":"case"' in document.model_dump_json()


def test_unknown_fields_are_rejected_deterministically() -> None:
    with pytest.raises(ValidationError) as error:
        validate_contract_json(read_fixture("case.unknown-field.invalid.json"))

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_wire_discriminant_and_schema_version_are_required() -> None:
    payload = json.loads(read_fixture("case.valid.json"))
    del payload["contract_type"]
    with pytest.raises(ValidationError, match="Unable to extract tag"):
        validate_contract_json(json.dumps(payload))

    payload = json.loads(read_fixture("case.valid.json"))
    del payload["schema_version"]
    with pytest.raises(ValidationError):
        validate_contract_json(json.dumps(payload))


def test_approval_offer_reference_requires_exact_revision() -> None:
    with pytest.raises(ValidationError) as error:
        ApprovalRequest.model_validate_json(
            read_fixture("approval.mismatched-reference.invalid.json")
        )

    assert any(item["type"] == "missing" for item in error.value.errors())


def test_approval_decision_must_precede_expiry() -> None:
    payload = json.loads(read_fixture("approval.mismatched-reference.invalid.json"))
    payload["offer_ref"]["offer_revision"] = 2
    payload["decision"] = "approved"
    payload["decided_at"] = "2026-08-22T12:31:00Z"

    with pytest.raises(ValidationError, match="must precede expiry"):
        ApprovalRequest.model_validate_json(json.dumps(payload))


def test_unsupported_completion_is_rejected() -> None:
    with pytest.raises(ValidationError, match="complete requires external evidence"):
        CompletionDecision.model_validate_json(
            read_fixture("completion.unsupported.invalid.json")
        )


def test_model_output_cannot_be_evidence_or_final_completion() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {
                "contract_type": "evidence",
                "schema_version": "1.0",
                "evidence_id": "66666666-6666-4666-8666-666666666666",
                "case_id": "11111111-1111-4111-8111-111111111111",
                "source_type": "model_output",
                "source_ref": "trace_123",
                "content_hash": "0" * 64,
                "observed_at": datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
                "captured_at": datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
            }
        )

    with pytest.raises(ValidationError):
        FastTurnDecision.model_validate(
            {
                "contract_type": "fast_turn_decision",
                "schema_version": "1.0",
                "decision_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "case_id": "11111111-1111-4111-8111-111111111111",
                "case_revision": 1,
                "strategy_id": "99999999-9999-4999-8999-999999999999",
                "strategy_revision": 1,
                "created_at": datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
                "dialogue_act": "close",
                "fact_updates": [],
                "reasoner_request": {"needed": False, "reason_code": "none"},
                "completion_claim": {
                    "status": "complete",
                    "evidence_message_ids": [],
                },
                "response_text": "Done.",
            }
        )


def test_money_is_exact_and_contracts_are_frozen() -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"amount_minor": 12.5, "currency": "USD"})

    money = Money(amount_minor=-500, currency="USD")
    with pytest.raises(ValidationError, match="frozen"):
        money.amount_minor = 0  # type: ignore[misc]


def test_non_utc_timestamp_is_rejected() -> None:
    payload = read_fixture("case.valid.json").replace(
        "2026-08-22T12:00:00Z",
        "2026-08-22T13:00:00+01:00",
        1,
    )

    with pytest.raises(ValidationError, match="UTC"):
        Case.model_validate_json(payload)


def test_canonical_model_registry_has_exact_phase_surface() -> None:
    assert {model.__name__ for model in CANONICAL_MODELS} == {
        "ActionIntent",
        "ApprovalRequest",
        "BillSnapshot",
        "Case",
        "CompletionDecision",
        "Constraint",
        "ConsumerGoal",
        "Evidence",
        "FactLedger",
        "FastTurnDecision",
        "ModelTrace",
        "ProviderOffer",
        "StrategyPacket",
    }
