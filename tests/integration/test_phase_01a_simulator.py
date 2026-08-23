from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

import pytest
from proxyloop_contracts import ApprovalDecision, CompletionOutcome
from proxyloop_provider_simulator import (
    ApprovalExpiredError,
    IllegalOfferTransitionError,
    OfferState,
    Phase01AEpisode,
    run_success_episode,
)
from proxyloop_provider_simulator.cli import main
from proxyloop_telecom_domain import (
    CompletionVerification,
    confirmation_hash,
    verify_completion,
)


def test_success_episode_reaches_evidence_verified_completion() -> None:
    result = run_success_episode()

    assert result.offer_state_history == (
        OfferState.AVAILABLE,
        OfferState.OFFERED,
        OfferState.AWAITING_APPROVAL,
        OfferState.CONFIRMED,
    )
    assert result.approval_request.decision is ApprovalDecision.APPROVED
    assert result.completion_decision.decision is CompletionOutcome.COMPLETE
    assert result.completion_decision.evidence_ids == (
        result.confirmation_evidence.evidence_id,
    )
    assert result.case.bill_snapshot is not None
    assert (
        result.offer.monthly_price.amount_minor
        < result.case.bill_snapshot.monthly_total.amount_minor
    )
    assert set(result.case.goal.required_features) <= set(result.offer.features)
    assert json.loads(result.to_json()) == json.loads(run_success_episode().to_json())


def test_cli_emits_the_complete_episode_as_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["provider_id"] == "pine-mobile"
    assert payload["offer_state_history"][-1] == "confirmed"
    assert payload["completion_decision"]["decision"] == "complete"


def test_approval_cannot_be_used_at_expiry() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    assert episode.approval_request is not None

    with pytest.raises(ApprovalExpiredError, match="expired"):
        episode.execute(at=episode.approval_request.expires_at)

    assert episode.offer_state is OfferState.AWAITING_APPROVAL
    assert episode.confirmation is None
    assert episode.confirmation_evidence is None


def test_illegal_offer_transition_is_rejected_without_mutation() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()

    with pytest.raises(IllegalOfferTransitionError, match="offered"):
        episode.issue_offer()

    assert episode.offer_state is OfferState.OFFERED
    assert episode.offer_state_history == (
        OfferState.AVAILABLE,
        OfferState.OFFERED,
    )


def test_forged_confirmation_evidence_cannot_complete() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    assert episode.completion_decision is not None
    assert episode.offer is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    forged_evidence = episode.confirmation_evidence.model_copy(
        update={"content_hash": "0" * 64}
    )

    decision = verify_completion(
        CompletionVerification(
            completion_id=episode.completion_decision.completion_id,
            case=episode.case,
            offer=episode.offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=episode.confirmation,
            evidence=forged_evidence,
            confirmation_authority=episode.provider,
            executed_at=episode.confirmation.confirmed_at,
            evaluated_at=episode.completion_decision.evaluated_at,
        )
    )

    assert decision.decision is not CompletionOutcome.COMPLETE
    assert decision.evidence_ids == ()
    assert "evidence_hash_mismatch" in decision.reason_codes


def test_evidenced_forbidden_change_cannot_complete() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    episode.verify()
    assert episode.completion_decision is not None
    assert episode.offer is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    forbidden_confirmation = replace(
        episode.confirmation,
        applied_changes=(
            *episode.confirmation.applied_changes,
            "device_financing_change",
        ),
    )
    matching_evidence = episode.confirmation_evidence.model_copy(
        update={"content_hash": confirmation_hash(forbidden_confirmation)}
    )

    decision = verify_completion(
        CompletionVerification(
            completion_id=episode.completion_decision.completion_id,
            case=episode.case,
            offer=episode.offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=forbidden_confirmation,
            evidence=matching_evidence,
            confirmation_authority=episode.provider,
            executed_at=forbidden_confirmation.confirmed_at,
            evaluated_at=episode.completion_decision.evaluated_at,
        )
    )

    assert decision.decision is not CompletionOutcome.COMPLETE
    assert "forbidden_change_applied" in decision.reason_codes


def test_internally_consistent_forged_confirmation_cannot_complete() -> None:
    episode = Phase01AEpisode.success()
    episode.issue_offer()
    episode.request_approval()
    episode.approve()
    episode.execute()
    assert episode.confirmation is not None
    assert episode.confirmation_evidence is not None
    assert episode.offer is not None
    assert episode.action_intent is not None
    assert episode.approval_request is not None

    forged_confirmation = replace(
        episode.confirmation,
        confirmation_id="pine-confirmation-forged",
    )
    forged_evidence = episode.confirmation_evidence.model_copy(
        update={
            "source_ref": forged_confirmation.confirmation_id,
            "content_hash": confirmation_hash(forged_confirmation),
        }
    )

    decision = verify_completion(
        CompletionVerification(
            completion_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
            case=episode.case,
            offer=episode.offer,
            action_intent=episode.action_intent,
            approval_request=episode.approval_request,
            confirmation=forged_confirmation,
            evidence=forged_evidence,
            confirmation_authority=episode.provider,
            executed_at=forged_confirmation.confirmed_at,
            evaluated_at=episode.confirmation.confirmed_at,
        )
    )

    assert decision.decision is not CompletionOutcome.COMPLETE
    assert decision.evidence_ids == ()
    assert "provider_confirmation_mismatch" in decision.reason_codes
