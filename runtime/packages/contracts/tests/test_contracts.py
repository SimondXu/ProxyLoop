from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from proxyloop_contracts import (
    CANONICAL_MODELS,
    ActionType,
    ApprovalRequest,
    CapabilityDefinition,
    CapabilityManifest,
    CapabilityReference,
    Case,
    CaseContextSnapshot,
    CompletionDecision,
    Evidence,
    FactLedger,
    FastTurnDecision,
    ModelInputPins,
    Money,
    PlanningBasis,
    RoutingDecision,
    RoutingOutcome,
    SlowReasonerView,
    SlowWorkRequest,
    canonical_fingerprint,
    planning_basis_fingerprint,
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
        "FastModelView",
        "ModelInputPins",
        "ModelTrace",
        "PlanningBasis",
        "ProviderOffer",
        "CapabilityManifest",
        "CaseContextSnapshot",
        "RoutingDecision",
        "SlowReasonerView",
        "SlowWorkRequest",
        "SlowWorkResult",
        "StrategyPacket",
        "VisibleCaseEvent",
    }


def _phase_03a1_fixture() -> tuple[
    Case,
    FactLedger,
    PlanningBasis,
    ModelInputPins,
    CapabilityManifest,
]:
    case = Case.model_validate_json(read_fixture("case.valid.json"))
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=case.case_id,
        created_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
        updated_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
        entries=(),
    )
    manifest = CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="sim-v1",
        issued_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
        expires_at=datetime.fromisoformat("2026-08-23T12:00:00+00:00"),
        capabilities=(
            CapabilityDefinition(
                capability_id="simulator.send_message",
                version="1",
                description="Send a bounded simulator message.",
                allowed_action_types=(ActionType.SEND_MESSAGE,),
            ),
        ),
    )
    components = {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(case.constraints),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(()),
        "material_offers_fingerprint": canonical_fingerprint(()),
        "approval_state_fingerprint": canonical_fingerprint(()),
        "provider_config_fingerprint": canonical_fingerprint("simulator.default"),
        "capability_manifest_fingerprint": canonical_fingerprint(manifest),
    }
    basis = PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=ledger.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=0,
        provider_config_ref="simulator.default",
        capability_manifest_version="sim-v1",
    )
    return case, ledger, basis, pins, manifest


def test_phase_03a1_snapshot_pins_and_manifest_are_strict() -> None:
    case, ledger, basis, pins, manifest = _phase_03a1_fixture()
    snapshot = CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=1,
        case=case,
        fact_ledger=ledger,
        event_cursor=0,
        planning_basis=basis,
        pins=pins,
        provider_config_ref="simulator.default",
        capability_manifest=manifest,
    )
    assert snapshot.pins == pins
    with pytest.raises(ValidationError, match="both be empty or versioned"):
        ModelInputPins(
            contract_type="model_input_pins",
            schema_version="1.0",
            revision=1,
            case_id=case.case_id,
            case_revision=1,
            constraint_set_revision=1,
            fact_ledger_revision=1,
            strategy_id=case.case_id,
            strategy_revision=0,
            planning_basis_fingerprint=basis.planning_basis_fingerprint,
            event_cursor=0,
            provider_config_ref="simulator.default",
            capability_manifest_version="sim-v1",
        )

    with pytest.raises(ValidationError, match="bind every material component"):
        PlanningBasis(
            **{
                **basis.model_dump(),
                "goal_fingerprint": "f" * 64,
            }
        )


def test_phase_03a1_slow_request_echoes_pins_and_routing_is_closed() -> None:
    case, _ledger, basis, pins, manifest = _phase_03a1_fixture()
    view = SlowReasonerView(
        contract_type="slow_reasoner_view",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        pins=pins,
        planning_basis=basis,
        goal=case.goal,
        constraints=case.constraints,
        delegated_authority=case.delegated_authority,
        verified_facts=(),
        capability_manifest=manifest,
        provider_config_ref="simulator.default",
        reason_code="case_initialized",
    )
    request = SlowWorkRequest(
        contract_type="slow_work_request",
        schema_version="1.0",
        revision=1,
        request_id=UUID("88888888-8888-4888-8888-888888888888"),
        case_id=case.case_id,
        pins=pins,
        planning_basis=basis,
        view=view,
        reason_code="case_initialized",
        created_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
    )
    assert request.view.pins == request.pins
    decision = RoutingDecision(
        contract_type="routing_decision",
        schema_version="1.0",
        revision=1,
        outcome=RoutingOutcome.SLOW_REFRESH,
        reason_codes=("case_initialized",),
        pins=pins,
        created_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
    )
    assert decision.outcome is RoutingOutcome.SLOW_REFRESH


def test_phase_03a1_non_simulator_capability_and_bad_expiry_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CapabilityDefinition(
            capability_id="gmail.send",
            version="1",
            description="Must not be exposed in this phase.",
            namespace="provider",  # type: ignore[arg-type]
            allowed_action_types=(ActionType.SEND_MESSAGE,),
        )
    with pytest.raises(ValidationError, match="simulator namespace"):
        CapabilityReference(
            namespace="simulator",
            capability_id="gmail.send",
            version="1",
        )
    with pytest.raises(ValidationError, match="expires_at must be after"):
        CapabilityManifest(
            contract_type="capability_manifest",
            schema_version="1.0",
            revision=1,
            namespace="simulator",
            manifest_version="sim-v1",
            issued_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
            expires_at=datetime.fromisoformat("2026-08-22T12:00:00+00:00"),
            capabilities=(),
        )
