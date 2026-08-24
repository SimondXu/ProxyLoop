from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from proxyloop_contracts import (
    ActionType,
    CapabilityDefinition,
    CapabilityManifest,
    ConstraintClassification,
    DelegatedAuthority,
    EvidenceType,
    ModelInputPins,
    Money,
    PlanningBasis,
    SlowReasonerView,
    SlowWorkRequest,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import Constraint, EvidenceRequirement, ProviderOffer
from proxyloop_evaluation.slow_output import (
    AcceptOfferCapabilityModelOutput,
    NonOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("88888888-8888-4888-8888-888888888888")
STRATEGY_ID = UUID("99999999-9999-4999-8999-999999999999")
HARD_ID = UUID("22222222-2222-4222-8222-222222222222")
SOFT_ONE_ID = UUID("33333333-3333-4333-8333-333333333333")
SOFT_TWO_ID = UUID("44444444-4444-4444-8444-444444444444")
OFFER_ID = UUID("55555555-5555-4555-8555-555555555555")


def _strategy_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "primary_objective": "Reduce the recurring bill safely.",
        "current_subgoal": "Evaluate the current provider response.",
        "ranked_preference_positions": (),
        "allowed_disclosures": (),
        "approval_required_disclosures": (),
        "concession_ladder": ("Preserve every hard constraint.",),
        "fallback_outcomes": ("Keep the current arrangement unchanged.",),
        "required_completion_evidence": (
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A fictional Provider confirmation is required.",
            ),
        ),
        "escalation_conditions": (),
        "replan_conditions": (),
    }
    payload.update(updates)
    return payload


def _strategy(**updates: object) -> StrategyModelOutput:
    return StrategyModelOutput.model_validate(_strategy_payload(**updates))


def _offer() -> ProviderOffer:
    return ProviderOffer.model_construct(
        contract_type="provider_offer",
        schema_version="1.0",
        revision=1,
        offer_id=OFFER_ID,
        case_id=CASE_ID,
        provider_id="simulator.provider",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        monthly_price=Money(amount_minor=7_200, currency="USD"),
        total_cost=Money(amount_minor=86_400, currency="USD"),
        fees=(),
        features=(),
        term_months=12,
        evidence_ids=(UUID("66666666-6666-4666-8666-666666666666"),),
    )


def _request(
    *,
    constraints: tuple[Constraint, ...] = (),
    offers: tuple[ProviderOffer, ...] = (),
    capability_names: tuple[str, ...] = (
        "accept_offer",
        "request_clarification",
        "escalate",
        "request_replan",
        "refuse_disclosure",
        "decline",
    ),
) -> SlowWorkRequest:
    action_types = {
        "accept_offer": ActionType.ACCEPT_OFFER,
        "request_clarification": ActionType.REQUEST_CLARIFICATION,
        "escalate": ActionType.SEND_MESSAGE,
        "request_replan": ActionType.SEND_MESSAGE,
        "refuse_disclosure": ActionType.SEND_MESSAGE,
        "decline": ActionType.END_INTERACTION,
    }
    manifest = CapabilityManifest.model_construct(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="sim-v1",
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        capabilities=tuple(
            CapabilityDefinition.model_construct(
                capability_id=f"simulator.{name}",
                version="v1",
                description=name,
                allowed_action_types=(action_types[name],),
            )
            for name in capability_names
        ),
    )
    basis_components = {
        "goal_fingerprint": "1" * 64,
        "constraints_fingerprint": "2" * 64,
        "delegated_authority_fingerprint": "3" * 64,
        "verified_facts_fingerprint": "4" * 64,
        "material_offers_fingerprint": "5" * 64,
        "approval_state_fingerprint": "6" * 64,
        "provider_config_fingerprint": "7" * 64,
        "capability_manifest_fingerprint": "8" * 64,
    }
    basis = PlanningBasis.model_construct(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **basis_components,  # type: ignore[arg-type]
        planning_basis_fingerprint=planning_basis_fingerprint(**basis_components),
    )
    pins = ModelInputPins.model_construct(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        case_revision=1,
        constraint_set_revision=1,
        fact_ledger_revision=1,
        strategy_id=STRATEGY_ID,
        strategy_revision=1,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=1,
        provider_config_ref="simulator.default",
        capability_manifest_version=manifest.manifest_version,
    )
    view = SlowReasonerView.model_construct(
        contract_type="slow_reasoner_view",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        pins=pins,
        planning_basis=basis,
        goal=None,
        constraints=constraints,
        delegated_authority=DelegatedAuthority.model_construct(
            allowed_actions=(),
            approval_required_actions=(ActionType.ACCEPT_OFFER,),
            allowed_disclosures=(),
        ),
        verified_facts=(),
        offers=offers,
        approval_requests=(),
        strategy=None,
        recent_events=(),
        capability_manifest=manifest,
        provider_config_ref="simulator.default",
    )
    return SlowWorkRequest.model_construct(
        contract_type="slow_work_request",
        schema_version="1.0",
        revision=1,
        request_id=REQUEST_ID,
        case_id=CASE_ID,
        pins=pins,
        planning_basis=basis,
        view=view,
        reason_code="case_initialized",
        created_at=NOW,
    )


def _constraint(
    constraint_id: UUID, classification: ConstraintClassification
) -> Constraint:
    return Constraint.model_construct(
        contract_type="constraint",
        schema_version="1.0",
        revision=1,
        constraint_id=constraint_id,
        case_id=CASE_ID,
        classification=classification,
        statement=str(constraint_id),
        source="fixture",
        valid_from=NOW,
        priority=1 if classification is ConstraintClassification.SOFT else None,
    )


def test_infrastructure_uuid_fields_are_not_model_output() -> None:
    with pytest.raises(ValidationError):
        StrategyModelOutput.model_validate(
            _strategy_payload(hard_constraint_ids=(HARD_ID,))
        )


def test_slow_output_cannot_represent_two_capability_proposals() -> None:
    with pytest.raises(ValidationError):
        SlowModelOutput.model_validate(
            {
                "strategy": _strategy_payload(),
                "capability_proposals": (),
                "next_capability": None,
            }
        )


def test_non_accept_capability_cannot_carry_an_offer_position() -> None:
    with pytest.raises(ValidationError):
        SlowModelOutput.model_validate(
            {
                "strategy": _strategy_payload(),
                "next_capability": {
                    "capability": "decline",
                    "offer_position": 0,
                },
            }
        )


def test_negative_preference_position_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        _strategy(ranked_preference_positions=(-1,))


def test_duplicate_and_out_of_range_preference_positions_are_rejected() -> None:
    constraints = (
        _constraint(HARD_ID, ConstraintClassification.HARD),
        _constraint(SOFT_ONE_ID, ConstraintClassification.SOFT),
        _constraint(SOFT_TWO_ID, ConstraintClassification.SOFT),
    )
    request = _request(constraints=constraints)

    with pytest.raises(ValueError, match="duplicate preference position"):
        compile_slow_output(
            request,
            SlowModelOutput(
                strategy=_strategy(ranked_preference_positions=(0, 0)),
                next_capability=None,
            ),
        )

    with pytest.raises(ValueError, match="preference position is out of range"):
        compile_slow_output(
            request,
            SlowModelOutput(
                strategy=_strategy(ranked_preference_positions=(2,)),
                next_capability=None,
            ),
        )


def test_offer_position_must_be_in_range() -> None:
    request = _request(offers=(_offer(),))
    with pytest.raises(ValueError, match="offer position is out of range"):
        compile_slow_output(
            request,
            SlowModelOutput(
                strategy=_strategy(),
                next_capability=AcceptOfferCapabilityModelOutput(
                    capability="accept_offer", offer_position=1
                ),
            ),
        )


def test_compiler_binds_hard_and_soft_constraints_deterministically() -> None:
    constraints = (
        _constraint(HARD_ID, ConstraintClassification.HARD),
        _constraint(SOFT_ONE_ID, ConstraintClassification.SOFT),
        _constraint(SOFT_TWO_ID, ConstraintClassification.SOFT),
    )
    request = _request(constraints=constraints)
    result = compile_slow_output(
        request,
        SlowModelOutput(
            strategy=_strategy(ranked_preference_positions=(1, 0)),
            next_capability=None,
        ),
    )

    assert result.strategy_proposal is not None
    assert result.strategy_proposal.hard_constraint_ids == (HARD_ID,)
    assert result.strategy_proposal.ranked_preference_ids == (
        SOFT_TWO_ID,
        SOFT_ONE_ID,
    )


def test_compiler_maps_accept_and_non_accept_to_one_canonical_capability() -> None:
    request = _request(offers=(_offer(),))
    accept = compile_slow_output(
        request,
        SlowModelOutput(
            strategy=_strategy(),
            next_capability=AcceptOfferCapabilityModelOutput(
                capability="accept_offer", offer_position=0
            ),
        ),
    )
    assert len(accept.capability_proposals) == 1
    assert len(accept.action_proposals) == 1
    assert accept.capability_proposals[0].capability.capability_id == (
        "simulator.accept_offer"
    )
    assert accept.action_proposals[0].offer_ref is not None
    assert accept.action_proposals[0].offer_ref.offer_id == OFFER_ID

    non_accept = compile_slow_output(
        request,
        SlowModelOutput(
            strategy=_strategy(),
            next_capability=NonOfferCapabilityModelOutput(capability="decline"),
        ),
    )
    assert len(non_accept.capability_proposals) == 1
    assert len(non_accept.action_proposals) == 1
    assert non_accept.capability_proposals[0].capability.capability_id == (
        "simulator.decline"
    )
    assert non_accept.capability_proposals[0].arguments == ()
    assert non_accept.action_proposals[0].offer_ref is None
