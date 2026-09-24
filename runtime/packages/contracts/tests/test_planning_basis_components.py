"""An independent reference for ``planning_basis_components`` (R-14).

The runtime and the snapshot validator share ``planning_basis_components``, so
the validator no longer re-derives the formula on its own. This test pins the
formula with hand-ordered expectations: every input arrives out of id order
and the fact ledger mixes statuses, so a missing filter or sort changes a
component. It never calls ``planning_basis_components`` to build an expected
value, and it never relies on the snapshot validator for one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from proxyloop_contracts import (
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityDefinition,
    CapabilityManifest,
    Case,
    CaseContextSnapshot,
    FactLedger,
    FactRecord,
    FactStatus,
    ModelInputPins,
    Money,
    OfferReference,
    PlanningBasis,
    ProviderOffer,
    approval_state_fingerprint,
    canonical_fingerprint,
    material_offers_fingerprint,
    planning_basis_components,
    planning_basis_fingerprint,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROVIDER_CONFIG = "carrier-b:custom-config-7"

LOW_CONSTRAINT_ID = "44444444-4444-4444-8444-444444444444"  # from case.valid.json
HIGH_CONSTRAINT_ID = "c4c4c4c4-c4c4-4c4c-8c4c-c4c4c4c4c4c4"
LOW_FACT_ID = UUID("a0a0a0a0-a0a0-4a0a-8a0a-a0a0a0a0a0a0")
HIGH_FACT_ID = UUID("f0f0f0f0-f0f0-4f0f-8f0f-f0f0f0f0f0f0")
LOW_OFFER_ID = UUID("2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b")
HIGH_OFFER_ID = UUID("eaeaeaea-eaea-4aea-8aea-eaeaeaeaeaea")
LOW_APPROVAL_ID = UUID("3c3c3c3c-3c3c-4c3c-8c3c-3c3c3c3c3c3c")
HIGH_APPROVAL_ID = UUID("dbdbdbdb-dbdb-4bdb-8bdb-dbdbdbdbdbdb")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _case() -> Case:
    payload = json.loads(
        (ROOT / "tests" / "fixtures" / "case.valid.json").read_text(encoding="utf-8")
    )
    payload["phase"] = "negotiating"
    (existing,) = payload["constraints"]
    assert existing["constraint_id"] == LOW_CONSTRAINT_ID
    later = {
        **existing,
        "constraint_id": HIGH_CONSTRAINT_ID,
        "statement": "Keep the mobile hotspot feature.",
    }
    payload["constraints"] = [later, existing]  # reverse id order
    return Case.model_validate_json(json.dumps(payload))


def _fact(fact_id: UUID, status: FactStatus, key: str) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        key=key,
        value=key,
        status=status,
        source_message_id="msg-1" if status is FactStatus.CANDIDATE else None,
        evidence_ids=(EVIDENCE_ID,) if status is FactStatus.VERIFIED else (),
        confidence=0.9,
        recorded_at=T0,
    )


VERIFIED_HIGH = _fact(HIGH_FACT_ID, FactStatus.VERIFIED, "current_plan")
CANDIDATE = _fact(
    UUID("b1b1b1b1-b1b1-4b1b-8b1b-b1b1b1b1b1b1"), FactStatus.CANDIDATE, "rumour"
)
VERIFIED_LOW = _fact(LOW_FACT_ID, FactStatus.VERIFIED, "monthly_total")
REJECTED = _fact(
    UUID("05050505-0505-4505-8505-050505050505"), FactStatus.REJECTED, "stale_quote"
)


def _ledger() -> FactLedger:
    return FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=3,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=CASE_ID,
        created_at=T0,
        updated_at=T0,
        # Mixed statuses; the VERIFIED facts arrive in reverse fact_id order.
        entries=(VERIFIED_HIGH, CANDIDATE, VERIFIED_LOW, REJECTED),
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


def _offer(offer_id: UUID, monthly_minor: int) -> ProviderOffer:
    return ProviderOffer(
        contract_type="provider_offer",
        schema_version="1.0",
        revision=1,
        offer_id=offer_id,
        case_id=CASE_ID,
        provider_id="simulated_carrier",
        created_at=T0,
        expires_at=T0 + timedelta(days=1),
        monthly_price=Money(amount_minor=monthly_minor, currency="USD"),
        total_cost=Money(amount_minor=monthly_minor * 12, currency="USD"),
        fees=(),
        features=("mobile_hotspot",),
        term_months=12,
        evidence_ids=(EVIDENCE_ID,),
    )


def _approval(approval_id: UUID, decision: ApprovalDecision) -> ApprovalRequest:
    decided = decision in {ApprovalDecision.APPROVED, ApprovalDecision.REJECTED}
    return ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=2 if decided else 1,
        approval_id=approval_id,
        case_id=CASE_ID,
        case_revision=1,
        action_intent_id=UUID("88888888-8888-4888-8888-888888888888"),
        action_intent_revision=1,
        action_type=ActionType.ACCEPT_OFFER,
        strategy_id=UUID("99999999-9999-4999-8999-999999999999"),
        strategy_revision=1,
        constraint_set_revision=1,
        offer_ref=OfferReference(offer_id=HIGH_OFFER_ID, offer_revision=1),
        material_terms_hash="0" * 64,
        requested_at=T0,
        expires_at=T0 + timedelta(hours=1),
        decision=decision,
        decided_at=T0 + timedelta(minutes=10) if decided else None,
    )


HIGH_OFFER = _offer(HIGH_OFFER_ID, 7400)
LOW_OFFER = _offer(LOW_OFFER_ID, 6900)
HIGH_APPROVAL = _approval(HIGH_APPROVAL_ID, ApprovalDecision.APPROVED)
LOW_APPROVAL = _approval(LOW_APPROVAL_ID, ApprovalDecision.PENDING)
OFFERS = (HIGH_OFFER, LOW_OFFER)  # reverse offer_id order
APPROVALS = (HIGH_APPROVAL, LOW_APPROVAL)  # reverse approval_id order
# Every fact, sorted by fact_id but not filtered to VERIFIED.
UNFILTERED_IN_ID_ORDER = (REJECTED, VERIFIED_LOW, CANDIDATE, VERIFIED_HIGH)


def _reference(
    version: str,
    *,
    verified_facts: tuple[FactRecord, ...] = (VERIFIED_LOW, VERIFIED_HIGH),
    constraints_in_id_order: bool = True,
    ten_in_id_order: bool = True,
) -> dict[str, str]:
    """The expected components, with every order written out by hand."""

    case = _case()
    low_constraint, high_constraint = (
        next(c for c in case.constraints if str(c.constraint_id) == LOW_CONSTRAINT_ID),
        next(c for c in case.constraints if str(c.constraint_id) == HIGH_CONSTRAINT_ID),
    )
    constraints = (
        (low_constraint, high_constraint)
        if constraints_in_id_order
        else case.constraints
    )
    if version == "1.1":
        offers_fp = material_offers_fingerprint(OFFERS)
        approvals_fp = approval_state_fingerprint(APPROVALS)
    else:
        offers_fp = canonical_fingerprint(
            (LOW_OFFER, HIGH_OFFER) if ten_in_id_order else OFFERS
        )
        approvals_fp = canonical_fingerprint(
            (LOW_APPROVAL, HIGH_APPROVAL) if ten_in_id_order else APPROVALS
        )
    return {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(constraints),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(verified_facts),
        "material_offers_fingerprint": offers_fp,
        "approval_state_fingerprint": approvals_fp,
        "provider_config_fingerprint": canonical_fingerprint(PROVIDER_CONFIG),
        "capability_manifest_fingerprint": canonical_fingerprint(_manifest()),
    }


def _snapshot_fields(version: str, components: dict[str, str]) -> dict[str, Any]:
    case = _case()
    ledger = _ledger()
    manifest = _manifest()
    basis = PlanningBasis(
        contract_type="planning_basis",
        schema_version=version,  # type: ignore[arg-type]
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=ledger.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=0,
        provider_config_ref=PROVIDER_CONFIG,
        capability_manifest_version=manifest.manifest_version,
    )
    return {
        "contract_type": "case_context_snapshot",
        "schema_version": version,
        "revision": 1,
        "case": case,
        "fact_ledger": ledger,
        "offers": OFFERS,
        "approval_requests": APPROVALS,
        "event_cursor": 0,
        "planning_basis": basis,
        "pins": pins,
        "provider_config_ref": PROVIDER_CONFIG,
        "capability_manifest": manifest,
    }


def test_the_fixture_inputs_are_out_of_order_and_mixed() -> None:
    case = _case()
    assert [str(c.constraint_id) for c in case.constraints] == [
        HIGH_CONSTRAINT_ID,
        LOW_CONSTRAINT_ID,
    ]
    assert {entry.status for entry in _ledger().entries} == set(FactStatus)
    assert str(HIGH_FACT_ID) > str(LOW_FACT_ID)
    assert list(UNFILTERED_IN_ID_ORDER) == sorted(
        _ledger().entries, key=lambda item: str(item.fact_id)
    )
    assert str(HIGH_OFFER_ID) > str(LOW_OFFER_ID)
    assert str(HIGH_APPROVAL_ID) > str(LOW_APPROVAL_ID)


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_planning_basis_components_match_the_hand_ordered_reference(
    version: str,
) -> None:
    actual = planning_basis_components(
        schema_version=version,  # type: ignore[arg-type]
        case=_case(),
        fact_ledger=_ledger(),
        offers=OFFERS,
        approval_requests=APPROVALS,
        provider_config_ref=PROVIDER_CONFIG,
        capability_manifest=_manifest(),
    )

    assert actual == _reference(version)
    # The version switch is material for these inputs.
    assert _reference("1.0") != _reference("1.1")


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_snapshot_accepts_the_reference_basis(version: str) -> None:
    snapshot = CaseContextSnapshot.model_validate(
        _snapshot_fields(version, _reference(version))
    )

    assert snapshot.planning_basis.verified_facts_fingerprint == (
        canonical_fingerprint((VERIFIED_LOW, VERIFIED_HIGH))
    )


@pytest.mark.parametrize(
    ("version", "defect"),
    [
        ("1.0", {"verified_facts": UNFILTERED_IN_ID_ORDER}),
        ("1.1", {"verified_facts": UNFILTERED_IN_ID_ORDER}),
        ("1.0", {"verified_facts": (VERIFIED_HIGH, VERIFIED_LOW)}),
        ("1.1", {"verified_facts": (VERIFIED_HIGH, VERIFIED_LOW)}),
        ("1.0", {"constraints_in_id_order": False}),
        ("1.1", {"constraints_in_id_order": False}),
        ("1.0", {"ten_in_id_order": False}),
    ],
    ids=[
        "1.0-unfiltered-facts",
        "1.1-unfiltered-facts",
        "1.0-unsorted-facts",
        "1.1-unsorted-facts",
        "1.0-unsorted-constraints",
        "1.1-unsorted-constraints",
        "1.0-unsorted-offers-and-approvals",
    ],
)
def test_snapshot_rejects_a_basis_built_without_the_filter_or_sort(
    version: str, defect: dict[str, Any]
) -> None:
    components = _reference(version, **defect)
    assert components != _reference(version)

    with pytest.raises(ValidationError, match="planning basis components must match"):
        CaseContextSnapshot.model_validate(_snapshot_fields(version, components))
