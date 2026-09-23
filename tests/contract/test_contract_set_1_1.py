"""Contract set 1.1: per-type versions, 1.0 byte stability, snapshot rules.

Design: ``harness/context/schema-1.1-design.md``. Only StrategyPacket,
PlanningBasis, CaseContextSnapshot and ModelTrace accept "1.0" | "1.1";
ExecutionClaim and CompletionReceipt are "1.1" only; every other type stays
"1.0". A 1.0 document must validate and dump exactly as before.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from proxyloop_contracts import (
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityDefinition,
    CapabilityManifest,
    Case,
    CaseContextSnapshot,
    CasePhase,
    CompletionDecision,
    CompletionOutcome,
    CompletionReceipt,
    Evidence,
    EvidenceType,
    ExecutionClaim,
    FactLedger,
    ModelInputPins,
    ModelTrace,
    Money,
    OfferReference,
    PlanningBasis,
    ProviderOffer,
    StrategyPacket,
    approval_state_fingerprint,
    canonical_fingerprint,
    material_offers_fingerprint,
    material_terms_hash,
    offer_material_terms,
    planning_basis_fingerprint,
    strategy_basis_binding,
    validate_contract_json,
)
from proxyloop_telecom_domain import AppliedOfferConfirmation, confirmation_hash
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA = ROOT / "contracts" / "jsonschema" / "proxyloop-contracts.schema.json"
EPISODES = ROOT / "data" / "manifests" / "phase-03a1-episodes.json"

T0 = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
OFFER_ID = UUID("cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd")
EVIDENCE_ID = UUID("efefefef-efef-4fef-8fef-efefefefefef")
NEW_KEYS = {
    "strategy_packet": {"planning_basis_fingerprint"},
    "model_trace": {"role", "reason_codes", "request_id", "input_pins"},
    "case_context_snapshot": {"completion_receipt"},
}


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def _harness_traces() -> list[dict[str, Any]]:
    episodes = json.loads(EPISODES.read_text(encoding="utf-8"))["episodes"]
    return [trace for episode in episodes for trace in episode["adapter_traces"]]


# --- 1.0 byte stability ------------------------------------------------------


def test_committed_1_0_harness_traces_round_trip_byte_identically() -> None:
    traces = _harness_traces()
    assert len(traces) == 40
    for trace in traces:
        document = ModelTrace.model_validate_json(json.dumps(trace))
        assert document.schema_version == "1.0"
        assert _canonical(document.model_dump(mode="json")) == _canonical(trace)


@pytest.mark.parametrize(
    "name",
    (
        "strategy_packet.v1_0.valid.json",
        "strategy_packet.v1_1.valid.json",
        "model_trace.v1_1.valid.json",
        "execution_claim.valid.json",
        "completion_receipt.valid.json",
    ),
)
def test_committed_fixtures_round_trip_byte_identically(name: str) -> None:
    text = _text(name)
    document = validate_contract_json(text)
    assert _canonical(document.model_dump(mode="json")) == _canonical(json.loads(text))


def test_a_1_0_dump_contains_none_of_the_1_1_keys() -> None:
    documents = [
        StrategyPacket.model_validate_json(_text("strategy_packet.v1_0.valid.json")),
        ModelTrace.model_validate_json(json.dumps(_harness_traces()[0])),
        _snapshot("1.0"),
    ]
    for document in documents:
        new_keys = NEW_KEYS[document.contract_type]
        assert document.schema_version == "1.0"
        assert not new_keys & set(document.model_dump())
        assert not new_keys & set(document.model_dump(mode="json"))
        assert not new_keys & set(json.loads(document.model_dump_json()))


def test_a_1_0_snapshot_dump_keeps_its_nested_documents_at_1_0() -> None:
    dumped = json.loads(_snapshot("1.0").model_dump_json())
    assert "completion_receipt" not in dumped
    assert dumped["planning_basis"]["schema_version"] == "1.0"


# --- per-type version gates -------------------------------------------------


def test_strategy_binding_is_required_at_1_1_and_forbidden_at_1_0() -> None:
    payload = json.loads(_text("strategy_packet.v1_1.valid.json"))
    strategy = StrategyPacket.model_validate_json(json.dumps(payload))
    assert strategy.planning_basis_fingerprint == payload["planning_basis_fingerprint"]

    del payload["planning_basis_fingerprint"]
    with pytest.raises(ValidationError, match=r"required at schema_version 1\.1"):
        StrategyPacket.model_validate_json(json.dumps(payload))
    payload["planning_basis_fingerprint"] = None
    with pytest.raises(ValidationError, match=r"required at schema_version 1\.1"):
        StrategyPacket.model_validate_json(json.dumps(payload))


def test_model_trace_1_1_requires_role_and_reason_codes_only() -> None:
    payload = json.loads(_text("model_trace.v1_1.valid.json"))
    del payload["request_id"]
    payload["reason_codes"] = []
    trace = ModelTrace.model_validate_json(json.dumps(payload))
    assert trace.role == "fast"
    assert trace.reason_codes == ()
    assert trace.request_id is None
    assert trace.input_pins is None
    assert json.loads(trace.model_dump_json())["reason_codes"] == []
    assert _schema_validator().is_valid(payload)

    for key in ("role", "reason_codes"):
        missing = {k: v for k, v in payload.items() if k != key}
        with pytest.raises(ValidationError, match=r"required at schema_version 1\.1"):
            ModelTrace.model_validate_json(json.dumps(missing))
        assert not _schema_validator().is_valid(missing)

    payload["input_pins"] = json.loads(_pins(_basis("1.1")).model_dump_json())
    assert ModelTrace.model_validate_json(json.dumps(payload)).input_pins is not None
    assert _schema_validator().is_valid(payload)


def test_types_outside_the_bump_stay_at_1_0() -> None:
    payload = json.loads(_text("case.valid.json"))
    payload["goal"]["schema_version"] = "1.1"
    with pytest.raises(ValidationError):
        validate_contract_json(json.dumps(payload))
    assert not _schema_validator().is_valid(payload)


def test_execution_claim_command_identity_travels_together() -> None:
    payload = json.loads(_text("execution_claim.valid.json"))
    assert isinstance(validate_contract_json(json.dumps(payload)), ExecutionClaim)

    only_fingerprint = {k: v for k, v in payload.items() if k != "command_id"}
    with pytest.raises(ValidationError, match="travel together"):
        validate_contract_json(json.dumps(only_fingerprint))
    assert not _schema_validator().is_valid(only_fingerprint)

    null_id = {**payload, "command_id": None}
    with pytest.raises(ValidationError, match="travel together"):
        validate_contract_json(json.dumps(null_id))
    assert not _schema_validator().is_valid(null_id)

    direct_mode = {**payload, "command_id": None, "command_fingerprint": None}
    claim = validate_contract_json(json.dumps(direct_mode))
    assert isinstance(claim, ExecutionClaim)
    assert claim.command_id is None
    assert _schema_validator().is_valid(direct_mode)


def test_completion_receipt_recomputes_the_confirmation_hash() -> None:
    receipt = CompletionReceipt.model_validate_json(
        _text("completion_receipt.valid.json")
    )
    confirmation = AppliedOfferConfirmation(
        case_id=receipt.case_id,
        provider_id=receipt.provider_id,
        confirmation_id=receipt.confirmation_id,
        offer_ref=receipt.offer_ref,
        action_intent_id=receipt.action_intent_id,
        approval_id=receipt.approval_id,
        confirmed_at=receipt.confirmed_at,
        previous_monthly_price=receipt.previous_monthly_price,
        new_monthly_price=receipt.new_monthly_price,
        total_cost_12_months=receipt.total_cost_12_months,
        plan_id=receipt.plan_id,
        plan_name=receipt.plan_name,
        features=receipt.features,
        removed_add_ons=receipt.removed_add_ons,
        applied_changes=receipt.applied_changes,
        term_months=receipt.term_months,
        effective_date=receipt.effective_date,
    )
    # The Evidence content_hash the Provider stamps on its CONFIRMATION.
    assert receipt.confirmation_content_hash == confirmation_hash(confirmation)

    payload = json.loads(_text("completion_receipt.valid.json"))
    payload["new_monthly_price"]["amount_minor"] = 7300
    with pytest.raises(ValidationError, match="confirmation_content_hash"):
        CompletionReceipt.model_validate_json(json.dumps(payload))


# --- the snapshot at 1.1 ----------------------------------------------------


def _case(phase: CasePhase = CasePhase.NEGOTIATING) -> Case:
    payload = json.loads(_text("case.valid.json"))
    payload["phase"] = phase.value
    return Case.model_validate_json(json.dumps(payload))


def _ledger() -> FactLedger:
    return FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=CASE_ID,
        created_at=T0,
        updated_at=T0,
        entries=(),
    )


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="sim-v1",
        issued_at=T0,
        expires_at=T0 + timedelta(days=1),
        capabilities=(
            CapabilityDefinition(
                capability_id="simulator.send_message",
                version="1",
                description="Send a bounded simulator message.",
                allowed_action_types=(ActionType.SEND_MESSAGE,),
            ),
        ),
    )


def _offer(
    *, revision: int = 1, monthly_minor: int = 7400, evidence_suffix: str = "1"
) -> ProviderOffer:
    return ProviderOffer(
        contract_type="provider_offer",
        schema_version="1.0",
        revision=revision,
        offer_id=OFFER_ID,
        case_id=CASE_ID,
        provider_id="simulated_carrier",
        created_at=T0,
        expires_at=T0 + timedelta(days=1),
        monthly_price=Money(amount_minor=monthly_minor, currency="USD"),
        total_cost=Money(amount_minor=88800, currency="USD"),
        fees=(),
        features=("mobile_hotspot",),
        term_months=12,
        evidence_ids=(UUID(f"{evidence_suffix * 8}-1111-4111-8111-111111111111"),),
    )


def _approval(decision: ApprovalDecision, approval_id: str) -> ApprovalRequest:
    decided = decision in {ApprovalDecision.APPROVED, ApprovalDecision.REJECTED}
    return ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=2 if decided else 1,
        approval_id=UUID(approval_id),
        case_id=CASE_ID,
        case_revision=1,
        action_intent_id=UUID("88888888-8888-4888-8888-888888888888"),
        action_intent_revision=1,
        action_type=ActionType.ACCEPT_OFFER,
        strategy_id=UUID("99999999-9999-4999-8999-999999999999"),
        strategy_revision=1,
        constraint_set_revision=1,
        offer_ref=OfferReference(offer_id=OFFER_ID, offer_revision=1),
        material_terms_hash="0" * 64,
        requested_at=T0,
        expires_at=T0 + timedelta(hours=1),
        decision=decision,
        decided_at=T0 + timedelta(minutes=10) if decided else None,
    )


APPROVED_ID = "77777777-7777-4777-8777-777777777777"
PENDING_ID = "7a7a7a7a-7a7a-4a7a-8a7a-7a7a7a7a7a7a"


def _receipt() -> CompletionReceipt:
    return CompletionReceipt.model_validate_json(_text("completion_receipt.valid.json"))


def _confirmation_evidence(content_hash: str | None = None) -> Evidence:
    return Evidence(
        contract_type="evidence",
        schema_version="1.0",
        evidence_id=EVIDENCE_ID,
        case_id=CASE_ID,
        source_type=EvidenceType.CONFIRMATION,
        source_ref="conf-0001",
        content_hash=content_hash or _receipt().confirmation_content_hash,
        observed_at=T0 + timedelta(minutes=10),
        captured_at=T0 + timedelta(minutes=10),
    )


def _components(
    formula: str,
    *,
    offers: tuple[ProviderOffer, ...] = (),
    approvals: tuple[ApprovalRequest, ...] = (),
) -> dict[str, str]:
    case = _case()
    if formula == "1.1":
        offers_fp = material_offers_fingerprint(offers)
        approvals_fp = approval_state_fingerprint(approvals)
    else:
        offers_fp = canonical_fingerprint(
            tuple(sorted(offers, key=lambda item: str(item.offer_id)))
        )
        approvals_fp = canonical_fingerprint(
            tuple(sorted(approvals, key=lambda item: str(item.approval_id)))
        )
    return {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(case.constraints),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(()),
        "material_offers_fingerprint": offers_fp,
        "approval_state_fingerprint": approvals_fp,
        "provider_config_fingerprint": canonical_fingerprint("simulator.default"),
        "capability_manifest_fingerprint": canonical_fingerprint(_manifest()),
    }


def _basis(
    version: str,
    *,
    formula: str | None = None,
    offers: tuple[ProviderOffer, ...] = (),
    approvals: tuple[ApprovalRequest, ...] = (),
) -> PlanningBasis:
    components = _components(formula or version, offers=offers, approvals=approvals)
    return PlanningBasis.model_validate(
        {
            "contract_type": "planning_basis",
            "schema_version": version,
            "revision": 1,
            **components,
            "planning_basis_fingerprint": planning_basis_fingerprint(**components),
        }
    )


def _pins(basis: PlanningBasis) -> ModelInputPins:
    return ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        case_revision=1,
        constraint_set_revision=1,
        fact_ledger_revision=1,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=0,
        provider_config_ref="simulator.default",
        capability_manifest_version="sim-v1",
    )


def _snapshot_fields(
    version: str,
    *,
    phase: CasePhase = CasePhase.NEGOTIATING,
    basis: PlanningBasis | None = None,
    offers: tuple[ProviderOffer, ...] = (),
    approvals: tuple[ApprovalRequest, ...] = (),
    evidence: tuple[Evidence, ...] = (),
    receipt: CompletionReceipt | None = None,
    completion_decision: CompletionDecision | None = None,
) -> dict[str, Any]:
    basis = basis or _basis(version, offers=offers, approvals=approvals)
    fields: dict[str, Any] = {
        "contract_type": "case_context_snapshot",
        "schema_version": version,
        "revision": 1,
        "case": _case(phase),
        "fact_ledger": _ledger(),
        "offers": offers,
        "approval_requests": approvals,
        "evidence": evidence,
        "event_cursor": 0,
        "planning_basis": basis,
        "pins": _pins(basis),
        "provider_config_ref": "simulator.default",
        "capability_manifest": _manifest(),
    }
    if receipt is not None:
        fields["completion_receipt"] = receipt
    if completion_decision is not None:
        fields["completion_decision"] = completion_decision
    return fields


def _snapshot(version: str, **kwargs: Any) -> CaseContextSnapshot:
    return CaseContextSnapshot.model_validate(_snapshot_fields(version, **kwargs))


def _completion_decision(
    outcome: CompletionOutcome = CompletionOutcome.COMPLETE,
    evidence_ids: tuple[UUID, ...] = (EVIDENCE_ID,),
) -> CompletionDecision:
    return CompletionDecision(
        contract_type="completion_decision",
        schema_version="1.0",
        revision=1,
        completion_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        case_id=CASE_ID,
        case_revision=1,
        decision=outcome,
        verifier_name="proxyloop_completion_policy",
        verifier_version="1.0.0",
        evaluated_at=T0 + timedelta(minutes=11),
        evidence_ids=evidence_ids,
        missing_evidence=(),
        reason_codes=("confirmation_verified",),
    )


def _complete_1_1(**overrides: Any) -> dict[str, Any]:
    """A COMPLETE 1.1 snapshot whose receipt is bound to the snapshot state."""

    kwargs: dict[str, Any] = {
        "phase": CasePhase.COMPLETE,
        "offers": (_offer(),),
        "approvals": (_approval(ApprovalDecision.APPROVED, APPROVED_ID),),
        "evidence": (_confirmation_evidence(),),
        "receipt": _receipt(),
        "completion_decision": _completion_decision(),
    }
    kwargs.update(overrides)
    return _snapshot_fields("1.1", **kwargs)


def _encode(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _wire(fields: dict[str, Any]) -> dict[str, Any]:
    """The JSON document the snapshot fields serialise to."""

    return {key: _encode(value) for key, value in fields.items()}


def test_the_planning_basis_version_must_equal_the_snapshot_version() -> None:
    assert _snapshot("1.1").planning_basis.schema_version == "1.1"
    for snapshot_version, basis_version in (("1.1", "1.0"), ("1.0", "1.1")):
        fields = _snapshot_fields(snapshot_version, basis=_basis(basis_version))
        with pytest.raises(ValidationError, match="planning basis schema_version"):
            CaseContextSnapshot.model_validate(fields)
        assert not _schema_validator().is_valid(_wire(fields))


def test_a_1_1_snapshot_accepts_nested_1_0_documents() -> None:
    strategy = StrategyPacket.model_validate_json(
        _text("strategy_packet.v1_0.valid.json")
    )
    basis = _basis("1.1")
    pins = _pins(basis).model_copy(
        update={"strategy_id": strategy.strategy_id, "strategy_revision": 1}
    )
    fields = {
        **_snapshot_fields("1.1", basis=basis),
        "strategy": strategy,
        "pins": pins,
    }
    snapshot = CaseContextSnapshot.model_validate(fields)
    assert snapshot.strategy is not None
    assert snapshot.strategy.schema_version == "1.0"
    assert _schema_validator().is_valid(_wire(fields))


def test_1_1_approval_component_counts_decided_approvals_only() -> None:
    approved = _approval(ApprovalDecision.APPROVED, APPROVED_ID)
    rejected = _approval(ApprovalDecision.REJECTED, APPROVED_ID)
    pending = _approval(ApprovalDecision.PENDING, PENDING_ID)
    expired = _approval(ApprovalDecision.EXPIRED, PENDING_ID)

    assert approval_state_fingerprint((approved,)) == canonical_fingerprint(
        [[APPROVED_ID, "approved"]]
    )
    assert approval_state_fingerprint((approved, pending)) == (
        approval_state_fingerprint((approved,))
    )
    assert approval_state_fingerprint((expired, approved)) == (
        approval_state_fingerprint((approved,))
    )
    assert approval_state_fingerprint((pending,)) == approval_state_fingerprint(())
    assert approval_state_fingerprint((rejected,)) != approval_state_fingerprint(
        (approved,)
    )
    # The 1.0 formula still moves on every approval document.
    assert _components("1.0", approvals=(approved, pending)) != _components(
        "1.0", approvals=(approved,)
    )


def test_1_1_offer_component_binds_identity_revision_and_material_terms() -> None:
    offer = _offer()
    expected = canonical_fingerprint(
        [[str(OFFER_ID), 1, material_terms_hash(offer_material_terms(offer))]]
    )
    assert material_offers_fingerprint((offer,)) == expected
    # Evidence ids are not material terms; the 1.0 formula moved on them.
    assert material_offers_fingerprint((_offer(evidence_suffix="2"),)) == expected
    assert _components("1.0", offers=(_offer(evidence_suffix="2"),)) != _components(
        "1.0", offers=(offer,)
    )
    assert material_offers_fingerprint((_offer(revision=2),)) != expected
    assert material_offers_fingerprint((_offer(monthly_minor=7300),)) != expected


def test_the_snapshot_formula_follows_the_snapshot_version() -> None:
    offers = (_offer(),)
    approvals = (
        _approval(ApprovalDecision.APPROVED, APPROVED_ID),
        _approval(ApprovalDecision.PENDING, PENDING_ID),
    )
    _snapshot("1.1", offers=offers, approvals=approvals)
    _snapshot("1.0", offers=offers, approvals=approvals)

    wrong_for_1_1 = _basis("1.1", formula="1.0", offers=offers, approvals=approvals)
    with pytest.raises(ValidationError, match="planning basis components"):
        _snapshot("1.1", offers=offers, approvals=approvals, basis=wrong_for_1_1)
    wrong_for_1_0 = _basis("1.0", formula="1.1", offers=offers, approvals=approvals)
    with pytest.raises(ValidationError, match="planning basis components"):
        _snapshot("1.0", offers=offers, approvals=approvals, basis=wrong_for_1_0)


def test_a_1_1_snapshot_is_complete_exactly_when_it_carries_a_receipt() -> None:
    fields = _complete_1_1()
    snapshot = CaseContextSnapshot.model_validate(fields)
    assert snapshot.completion_receipt == _receipt()
    assert _schema_validator().is_valid(_wire(fields))

    no_receipt = _complete_1_1(receipt=None)
    with pytest.raises(ValidationError, match="complete exactly when"):
        CaseContextSnapshot.model_validate(no_receipt)
    assert not _schema_validator().is_valid(_wire(no_receipt))

    not_complete = _complete_1_1(phase=CasePhase.CANDIDATE_COMPLETE)
    with pytest.raises(ValidationError, match="complete exactly when"):
        CaseContextSnapshot.model_validate(not_complete)
    assert not _schema_validator().is_valid(_wire(not_complete))

    # A 1.0 snapshot keeps the 1.0 meaning: COMPLETE without a receipt.
    _snapshot("1.0", phase=CasePhase.COMPLETE)


def test_the_receipt_hash_must_equal_its_confirmation_evidence_hash() -> None:
    other_hash = "a" * 64
    mismatched = _complete_1_1(evidence=(_confirmation_evidence(other_hash),))
    with pytest.raises(ValidationError, match="CONFIRMATION evidence"):
        CaseContextSnapshot.model_validate(mismatched)

    missing = _complete_1_1(evidence=())
    with pytest.raises(ValidationError, match="CONFIRMATION evidence"):
        CaseContextSnapshot.model_validate(missing)

    wrong_type = _complete_1_1(
        evidence=(
            _confirmation_evidence().model_copy(
                update={"source_type": EvidenceType.PROVIDER_MESSAGE}
            ),
        )
    )
    with pytest.raises(ValidationError, match="CONFIRMATION evidence"):
        CaseContextSnapshot.model_validate(wrong_type)


def _rejects(fields: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        CaseContextSnapshot.model_validate(fields)


def test_the_receipt_must_name_an_approved_approval_revision() -> None:
    approved = _approval(ApprovalDecision.APPROVED, APPROVED_ID)
    match = "APPROVED accept_offer approval revision"
    _rejects(_complete_1_1(approvals=()), match)
    # Reviewer repro: a REJECTED approval with the receipt's id and revision.
    rejected = _approval(ApprovalDecision.REJECTED, APPROVED_ID)
    assert rejected.revision == _receipt().approval_revision
    _rejects(_complete_1_1(approvals=(rejected,)), match)
    _rejects(
        _complete_1_1(approvals=(approved.model_copy(update={"revision": 3}),)),
        match,
    )


def test_the_receipt_approval_must_accept_an_offer() -> None:
    send_message = _approval(ApprovalDecision.APPROVED, APPROVED_ID).model_copy(
        update={"action_type": ActionType.SEND_MESSAGE}
    )
    assert send_message.offer_ref is not None
    _rejects(
        _complete_1_1(approvals=(send_message,)),
        "APPROVED accept_offer approval revision",
    )


def test_a_1_1_snapshot_rejects_duplicate_approval_ids() -> None:
    approved = _approval(ApprovalDecision.APPROVED, APPROVED_ID)
    rejected = _approval(ApprovalDecision.REJECTED, APPROVED_ID)
    match = "duplicate approval ids"
    # Reviewer repros: APPROVED + REJECTED with one id, and rev 2 APPROVED
    # followed by rev 3 REJECTED.
    _rejects(_complete_1_1(approvals=(approved, rejected)), match)
    _rejects(
        _complete_1_1(
            approvals=(approved, rejected.model_copy(update={"revision": 3}))
        ),
        match,
    )
    _rejects(_snapshot_fields("1.1", approvals=(approved, rejected)), match)
    # A 1.0 snapshot keeps its 1.0 rules.
    _snapshot("1.0", approvals=(approved, rejected))


def test_the_receipt_intent_and_offer_must_match_the_approval_and_snapshot() -> None:
    approved = _approval(ApprovalDecision.APPROVED, APPROVED_ID)
    other_intent = approved.model_copy(
        update={"action_intent_id": UUID("8a8a8a8a-8a8a-4a8a-8a8a-8a8a8a8a8a8a")}
    )
    _rejects(_complete_1_1(approvals=(other_intent,)), "must match its approval")
    other_offer = approved.model_copy(
        update={"offer_ref": OfferReference(offer_id=OFFER_ID, offer_revision=2)}
    )
    _rejects(_complete_1_1(approvals=(other_offer,)), "must match its approval")
    _rejects(_complete_1_1(offers=()), "offer must be in the snapshot")
    _rejects(
        _complete_1_1(offers=(_offer(revision=2),)), "offer must be in the snapshot"
    )


def test_the_receipt_evidence_source_ref_must_be_its_confirmation_id() -> None:
    evidence = _confirmation_evidence().model_copy(update={"source_ref": "conf-9999"})
    _rejects(_complete_1_1(evidence=(evidence,)), "CONFIRMATION evidence")


def test_the_receipt_requires_a_complete_decision_citing_its_evidence() -> None:
    match = "COMPLETE completion decision"
    without = _complete_1_1(completion_decision=None)
    _rejects(without, match)
    assert not _schema_validator().is_valid(_wire(without))

    candidate = _complete_1_1(
        completion_decision=_completion_decision(CompletionOutcome.CANDIDATE_COMPLETE)
    )
    _rejects(candidate, match)
    assert not _schema_validator().is_valid(_wire(candidate))

    other_evidence = UUID("abababab-abab-4bab-8bab-abababababab")
    _rejects(
        _complete_1_1(
            completion_decision=_completion_decision(evidence_ids=(other_evidence,))
        ),
        match,
    )


def test_a_1_0_snapshot_rejects_a_receipt_key_even_when_null() -> None:
    fields = _snapshot_fields(
        "1.0",
        phase=CasePhase.COMPLETE,
        evidence=(_confirmation_evidence(),),
        receipt=_receipt(),
    )
    with pytest.raises(ValidationError, match=r"not part of schema_version 1\.0"):
        CaseContextSnapshot.model_validate(fields)
    assert not _schema_validator().is_valid(_wire(fields))

    wire = _wire(_snapshot_fields("1.0"))
    assert _schema_validator().is_valid(wire)
    wire["completion_receipt"] = None
    with pytest.raises(ValidationError, match=r"not part of schema_version 1\.0"):
        validate_contract_json(json.dumps(wire))
    assert not _schema_validator().is_valid(wire)


def test_a_1_1_trace_binds_its_pins_and_has_unique_reason_codes() -> None:
    payload = json.loads(_text("model_trace.v1_1.valid.json"))
    pins = json.loads(_pins(_basis("1.1")).model_dump_json())
    pins["case_id"] = "12121212-1212-4212-8212-121212121212"
    with pytest.raises(ValidationError, match="input_pins must reference"):
        ModelTrace.model_validate_json(json.dumps({**payload, "input_pins": pins}))

    duplicated = {**payload, "reason_codes": ["provider_message", "provider_message"]}
    with pytest.raises(ValidationError, match="duplicate reason codes"):
        ModelTrace.model_validate_json(json.dumps(duplicated))


def test_a_null_1_1_key_nested_in_a_1_0_document_is_rejected() -> None:
    strategy = StrategyPacket.model_validate_json(
        _text("strategy_packet.v1_0.valid.json")
    )
    basis = _basis("1.0")
    pins = _pins(basis).model_copy(
        update={"strategy_id": strategy.strategy_id, "strategy_revision": 1}
    )
    fields = {**_snapshot_fields("1.0", basis=basis), "strategy": strategy}
    wire = _wire({**fields, "pins": pins})
    validate_contract_json(json.dumps(wire))
    assert _schema_validator().is_valid(wire)

    wire["strategy"]["planning_basis_fingerprint"] = None
    with pytest.raises(ValidationError, match=r"not part of schema_version 1\.0"):
        validate_contract_json(json.dumps(wire))
    assert not _schema_validator().is_valid(wire)


def test_python_none_is_absent_at_1_0_so_field_copies_keep_working() -> None:
    # Only a JSON document can carry a null key; strict mode validates wire
    # documents as JSON. ``Model(**other.__dict__)`` passes every field.
    snapshot = _snapshot("1.0")
    copied = CaseContextSnapshot(**snapshot.__dict__)
    assert copied == snapshot
    assert "completion_receipt" not in copied.model_dump(mode="json")

    trace = ModelTrace.model_validate_json(json.dumps(_harness_traces()[0]))
    assert ModelTrace(**trace.__dict__) == trace

    with pytest.raises(ValidationError, match=r"not part of schema_version 1\.0"):
        ModelTrace(**{**trace.__dict__, "role": "fast"})


def test_strategy_basis_binding_follows_the_basis_version() -> None:
    assert strategy_basis_binding(_basis("1.0")) == {"schema_version": "1.0"}
    basis = _basis("1.1")
    binding = strategy_basis_binding(basis)
    assert binding == {
        "schema_version": "1.1",
        "planning_basis_fingerprint": basis.planning_basis_fingerprint,
    }
    payload = json.loads(_text("strategy_packet.v1_0.valid.json"))
    payload.update(binding)
    strategy = StrategyPacket.model_validate_json(json.dumps(payload))
    assert strategy.planning_basis_fingerprint == basis.planning_basis_fingerprint
