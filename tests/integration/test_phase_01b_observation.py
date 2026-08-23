from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from proxyloop_agent_core import (
    OracleAction,
    SafeObservation,
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_contracts import (
    BillSnapshot,
    Case,
    CasePhase,
    ConsumerGoal,
    DelegatedAuthority,
    LineItem,
    LineItemCategory,
    Money,
    ProviderOffer,
    UsageProfile,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
EVIDENCE_ID = UUID("22222222-2222-4222-8222-222222222222")


def make_case(
    *,
    required_features: tuple[str, ...] = ("mobile_hotspot",),
    forbidden_changes: tuple[str, ...] = (),
    allowed_disclosures: tuple[str, ...] = ("service_address",),
    target_minor: int | None = 7500,
) -> Case:
    return Case(
        contract_type="case",
        schema_version="1.0",
        revision=1,
        case_id=CASE_ID,
        consumer_id=UUID("33333333-3333-4333-8333-333333333333"),
        phase=CasePhase.NEGOTIATING,
        constraint_set_revision=1,
        created_at=NOW,
        updated_at=NOW,
        goal=ConsumerGoal(
            contract_type="consumer_goal",
            schema_version="1.0",
            revision=1,
            goal_id=UUID("44444444-4444-4444-8444-444444444444"),
            case_id=CASE_ID,
            created_at=NOW,
            updated_at=NOW,
            desired_outcome="Reduce the recurring mobile bill",
            target_monthly_total=(
                Money(amount_minor=target_minor, currency="USD")
                if target_minor is not None
                else None
            ),
            required_features=required_features,
            forbidden_changes=forbidden_changes,
        ),
        constraints=(),
        delegated_authority=DelegatedAuthority(
            allowed_actions=(),
            approval_required_actions=(),
            allowed_disclosures=allowed_disclosures,
        ),
        bill_snapshot=BillSnapshot(
            contract_type="bill_snapshot",
            schema_version="1.0",
            revision=1,
            snapshot_id=UUID("55555555-5555-4555-8555-555555555555"),
            case_id=CASE_ID,
            captured_at=NOW,
            monthly_total=Money(amount_minor=9000, currency="USD"),
            line_items=(
                LineItem(
                    name="Mobile service",
                    category=LineItemCategory.SERVICE,
                    amount=Money(amount_minor=9000, currency="USD"),
                ),
            ),
            add_ons=(),
            term_months=0,
            usage=UsageProfile(voice_minutes=0, sms_count=0, data_megabytes=0),
            evidence_ids=(EVIDENCE_ID,),
        ),
    )


def make_offer(
    *,
    offer_id: str = "offer-valid",
    monthly: int = 7200,
    total: int = 86400,
    currency: str = "USD",
    features: tuple[str, ...] = ("mobile_hotspot",),
    applied_changes: tuple[str, ...] = (),
    expires_at: datetime = NOW + timedelta(hours=1),
) -> SafeOffer:
    return SafeOffer(
        offer_id=offer_id,
        provider_id="pine-mobile",
        monthly_price_minor=monthly,
        total_cost_12_months_minor=total,
        currency=currency,
        features=features,
        fees_minor=0,
        term_months=0,
        applied_changes=applied_changes,
        expires_at=expires_at,
    )


def make_observation(
    *,
    case: Case | None = None,
    offers: tuple[SafeOffer, ...] = (make_offer(),),
    requested_disclosures: tuple[str, ...] = (),
    needs_clarification: bool = False,
    transfer_available: bool = False,
    approval_current: bool = True,
    observed_at: datetime = NOW,
    confirmation_evidence_available: bool = True,
) -> SafeObservation:
    return SafeObservationAdapter.build(
        case or make_case(),
        provider_id="pine-mobile",
        provider_message="The current offer is available.",
        offers=offers,
        requested_disclosures=requested_disclosures,
        needs_clarification=needs_clarification,
        transfer_available=transfer_available,
        approval_current=approval_current,
        observed_at=observed_at,
        confirmation_evidence_available=confirmation_evidence_available,
    )


def test_safe_observation_serialization_has_only_the_allowlist() -> None:
    observation = make_observation()

    assert set(observation.to_dict()) == {
        "schema_version",
        "case_id",
        "case_revision",
        "constraint_set_revision",
        "current_monthly_total_minor",
        "target_monthly_total_minor",
        "currency",
        "required_features",
        "forbidden_changes",
        "allowed_disclosures",
        "provider_id",
        "provider_message",
        "offers",
        "requested_disclosures",
        "needs_clarification",
        "transfer_available",
        "approval_current",
        "observed_at",
        "confirmation_evidence_available",
    }
    serialized = json.loads(observation.to_json())
    assert set(serialized["offers"][0]) == {
        "offer_id",
        "provider_id",
        "monthly_price_minor",
        "total_cost_12_months_minor",
        "currency",
        "features",
        "fees_minor",
        "term_months",
        "applied_changes",
        "expires_at",
    }
    forbidden = {
        "family_id",
        "entity_cluster",
        "split",
        "provider_config",
        "private_policy",
        "reference_action",
        "expected_outcome",
        "reward",
        "verifier_criteria",
        "account_state",
        "database_state",
    }
    assert forbidden.isdisjoint(serialized)
    assert forbidden.isdisjoint(serialized["offers"][0])


def test_safe_observation_json_is_deterministic() -> None:
    observation = make_observation()

    assert observation.to_json() == observation.to_json()
    assert (
        observation.to_json()
        == json.dumps(
            observation.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n"
    )


def test_adapter_rejects_private_or_arbitrary_metadata() -> None:
    signature = inspect.signature(SafeObservationAdapter.build)
    assert "metadata" not in signature.parameters
    assert "private_state" not in signature.parameters
    with pytest.raises(TypeError):
        SafeObservationAdapter.build(  # type: ignore[call-arg]
            make_case(),
            provider_id="pine-mobile",
            provider_message="message",
            offers=(),
            metadata={"expected_outcome": "accept_offer"},
            observed_at=NOW,
        )


def test_adapter_accepts_only_utc_and_rejects_duplicate_offers() -> None:
    with pytest.raises(ValueError, match="UTC"):
        make_observation(observed_at=datetime(2026, 8, 23, 12, 0))
    duplicate = make_offer()
    with pytest.raises(ValueError, match="duplicate"):
        make_observation(offers=(duplicate, duplicate))


def test_oracle_requests_clarification_before_other_actions() -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(needs_clarification=True, transfer_available=True)
    )

    assert decision.action is OracleAction.REQUEST_CLARIFICATION
    assert decision.offer_id is None


def test_oracle_refuses_disallowed_disclosure() -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(requested_disclosures=("private_account_pin",))
    )

    assert decision.action is OracleAction.REFUSE_DISCLOSURE
    assert decision.offer_id is None


def test_oracle_requests_replan_for_stale_approval() -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(approval_current=False, transfer_available=True)
    )

    assert decision.action is OracleAction.REQUEST_REPLAN
    assert decision.offer_id is None


def test_oracle_escalates_when_transfer_is_available() -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(transfer_available=True)
    )

    assert decision.action is OracleAction.ESCALATE
    assert decision.offer_id is None


def test_oracle_requests_replan_when_confirmation_evidence_is_unavailable() -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(confirmation_evidence_available=False)
    )

    assert decision.action is OracleAction.REQUEST_REPLAN
    assert decision.offer_id is None
    assert decision.reason_codes == ("confirmation_evidence_unavailable",)


def test_oracle_selects_the_lowest_cost_valid_offer_stably() -> None:
    offers = (
        make_offer(offer_id="offer-expensive", monthly=7300, total=87600),
        make_offer(offer_id="offer-cheapest", monthly=7200, total=86400),
        make_offer(offer_id="offer-same-cost", monthly=7200, total=86400),
    )
    decision = ScriptedOracleConsumer().decide(make_observation(offers=offers))

    assert decision.action is OracleAction.ACCEPT_OFFER
    assert decision.offer_id == "offer-cheapest"


@pytest.mark.parametrize(
    "applied_change",
    ["account_cancellation", "change_phone_number", "remove_add_on"],
)
def test_oracle_declines_unsupported_applied_change(applied_change: str) -> None:
    decision = ScriptedOracleConsumer().decide(
        make_observation(
            case=make_case(),
            offers=(make_offer(applied_changes=(applied_change,)),),
        )
    )

    assert decision.action is OracleAction.DECLINE
    assert decision.offer_id is None


@pytest.mark.parametrize(
    "offer",
    [
        make_offer(offer_id="expired", expires_at=NOW),
        make_offer(offer_id="wrong-currency", currency="EUR"),
        make_offer(offer_id="too-expensive", monthly=9000, total=108000),
        make_offer(offer_id="missing-feature", features=()),
        make_offer(offer_id="forbidden-change", applied_changes=("device_financing",)),
    ],
)
def test_oracle_declines_when_no_offer_satisfies_constraints(offer: SafeOffer) -> None:
    case = make_case(forbidden_changes=("device_financing",))
    decision = ScriptedOracleConsumer().decide(
        make_observation(case=case, offers=(offer,))
    )

    assert decision.action is OracleAction.DECLINE
    assert decision.offer_id is None


def test_oracle_public_api_accepts_only_safe_observation() -> None:
    decide_signature = inspect.signature(ScriptedOracleConsumer.decide)
    assert list(decide_signature.parameters) == ["self", "observation"]
    with pytest.raises(TypeError):
        ScriptedOracleConsumer().decide({"private_state": "hidden"})  # type: ignore[arg-type]


def test_adapter_maps_canonical_provider_offer_without_private_fields() -> None:
    case = make_case()
    provider_offer = ProviderOffer(
        contract_type="provider_offer",
        schema_version="1.0",
        revision=1,
        offer_id=UUID("66666666-6666-4666-8666-666666666666"),
        case_id=CASE_ID,
        provider_id="pine-mobile",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        monthly_price=Money(amount_minor=7200, currency="USD"),
        total_cost=Money(amount_minor=86400, currency="USD"),
        fees=(),
        features=("mobile_hotspot",),
        term_months=0,
        evidence_ids=(EVIDENCE_ID,),
    )

    observation = SafeObservationAdapter.build(
        case,
        provider_id="pine-mobile",
        provider_message="public quote",
        offers=(provider_offer,),
        observed_at=NOW,
    )

    assert observation.offers[0].offer_id == str(provider_offer.offer_id)
    assert "evidence_ids" not in json.loads(observation.to_json())["offers"][0]
