"""Characterize the documented contract-semantics limits (audit A-3, A-5).

These tests pin today's behaviour so that the wording in ``CONTEXT.md``,
``docs/architecture.md`` and the Fast/Slow ADR amendment of 2026-09-24 has to
change together with it:

- A-3: an Action Intent carries no capability reference, and neither the
  ``SlowWorkResult`` contract nor the coordinator's Slow result audit binds an
  action proposal to a capability proposal; only the capability executor does
  (``unsupported_capability`` and ``capability_action_mismatch`` are asserted
  in ``test_phase_03a1_agent_core.py``).
- A-5: every Evidence ``content_hash`` in a completed runtime Case recomputes
  from the artifact its ``(source_type, source_ref)`` names, per the referent
  table in ``docs/architecture.md``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from proxyloop_agent_core import CaseCoordinator
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    BINDING_REF,
    CHANNEL_KIND,
    VerifiedLocalMailboxEvent,
    build_fixture_headers,
    verify_local_mailbox_event,
)
from proxyloop_contracts import (
    ActionIntent,
    CasePhase,
    EvidenceType,
    SlowWorkResult,
)
from proxyloop_provider_simulator.provider import FictionalMobileProvider
from proxyloop_telecom_domain import confirmation_hash
from test_phase_03a1_agent_core import _approved_execution
from test_phase_06b1_channel_runtime import BASE_TIME, _create_command
from test_r10_terminal_delivery_callback import _CodecChannelRepository, _state

# -- A-3: contract validation does not bind an action to a capability ----------


def test_contract_validation_does_not_bind_an_action_to_a_capability() -> None:
    snapshot, episode, _ = _approved_execution()
    intent = episode.action_intent
    assert intent is not None
    # An Action Intent names an action type, never a capability or proposal.
    assert not {
        name
        for name in ActionIntent.model_fields
        if "capability" in name or "proposal" in name
    }

    # An accept-offer action with no capability proposal at all is a valid
    # Slow Work Result on the wire ...
    document = SlowWorkResult(
        contract_type="slow_work_result",
        schema_version="1.0",
        revision=1,
        result_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        request_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        case_id=snapshot.case.case_id,
        pins=snapshot.pins,
        planning_basis=snapshot.planning_basis,
        capability_proposals=(),
        action_proposals=(intent,),
        created_at=intent.created_at,
    ).model_dump_json()
    result = SlowWorkResult.model_validate_json(document)
    assert result.capability_proposals == ()
    assert result.action_proposals == (intent,)

    # ... and the coordinator's current-state audit accepts it as well.
    audit = CaseCoordinator.validate_slow_result(
        result, snapshot, evaluated_at=intent.created_at
    )
    assert audit.accepted is True
    assert audit.reason_codes == ("slow_result_current",)


# -- A-5: each Evidence content_hash recomputes from its named artifact ---------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object, *, ensure_ascii: bool) -> bytes:
    return json.dumps(
        value, ensure_ascii=ensure_ascii, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _verified(payload: dict[str, object]) -> tuple[bytes, VerifiedLocalMailboxEvent]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = build_fixture_headers(raw)
    headers["X-ProxyLoop-Local-Timestamp"] = _utc_text(BASE_TIME)
    return raw, verify_local_mailbox_event(raw, headers, BASE_TIME)


def test_completed_case_evidence_hashes_recompute_from_their_referents() -> None:
    repository = _CodecChannelRepository()
    now = [BASE_TIME]
    runtime = ThinAgentRuntime(repository, clock=lambda: now[0])
    runtime.apply_command(_create_command())

    # A verified local-mailbox Provider message, projected the way the API's
    # channel route builds its command (``content_hash`` over the content).
    message_id = uuid4()
    message_content = "Synthetic Provider message about the offer."
    _, message = _verified(
        {
            "schema_version": "local-mailbox-v1",
            "event_id": str(message_id),
            "binding_ref": BINDING_REF,
            "occurred_at": _utc_text(BASE_TIME),
            "kind": "provider_message",
            "content": message_content,
        }
    )
    inbox = repository.reserve_channel_event(message, received_at=BASE_TIME)
    applied = runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.INGEST_CHANNEL_EVENT,
            occurred_at=message.occurred_at,
            expected_revision=_state(repository).snapshot.revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=message.event_id,
            content_hash=_sha256(message_content.encode("utf-8")),
            payload_hash=message.raw_payload_hash,
        )
    )
    assert applied.delivery_id is not None
    outbox = repository.get_outbox_record(applied.delivery_id)
    assert outbox is not None
    provider_message_id = "local-provider-evidence-hash"
    repository.outbox[applied.delivery_id] = replace(
        outbox, state="accepted", provider_message_id=provider_message_id
    )

    # Offer, approval, execution, and verified completion.
    now[0] = BASE_TIME + timedelta(minutes=1)
    waiting = runtime.append_event(SCRIPTED_CASE_ID, content="Review the offer.")
    assert waiting.approval is not None
    runtime.apply_command(
        CaseCommand(
            command_id=uuid4(),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=BASE_TIME + timedelta(minutes=2),
            expected_revision=waiting.snapshot.revision,
            approval_id=waiting.approval.approval_id,
            decision="approved",
        )
    )

    # A verified delivery callback, projected the way the API's channel route
    # builds its command (``artifact_hash`` is the raw payload hash).
    delivery_raw, delivery = _verified(
        {
            "schema_version": "local-mailbox-v1",
            "event_id": str(uuid4()),
            "binding_ref": BINDING_REF,
            "occurred_at": _utc_text(BASE_TIME),
            "kind": "delivery",
            "delivery_id": str(applied.delivery_id),
            "provider_message_id": provider_message_id,
            "delivery_status": "delivered",
        }
    )
    delivery_inbox = repository.reserve_channel_event(delivery, received_at=BASE_TIME)
    runtime.apply_command(
        CaseCommand(
            schema_version="phase-06b1-v1",
            command_id=delivery_inbox.command_id,
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.RECORD_CHANNEL_DELIVERY,
            occurred_at=delivery.occurred_at,
            expected_revision=_state(repository).snapshot.revision,
            channel_kind=CHANNEL_KIND,
            binding_ref=BINDING_REF,
            event_id=delivery.event_id,
            delivery_id=applied.delivery_id,
            provider_message_id=provider_message_id,
            delivery_status="delivered",
            artifact_hash=delivery.raw_payload_hash,
            payload_hash=delivery.raw_payload_hash,
        )
    )

    state = _state(repository)
    snapshot = state.snapshot
    assert snapshot.case.phase is CasePhase.COMPLETE
    evidence = snapshot.evidence
    # The runtime produces exactly these source types; the table is complete.
    assert Counter(item.source_type for item in evidence) == Counter(
        {
            EvidenceType.PROVIDER_MESSAGE: 2,
            EvidenceType.SIMULATOR_TRANSITION: 1,
            EvidenceType.CONFIRMATION: 1,
            EvidenceType.PROVIDER_EVENT: 1,
        }
    )
    by_ref = {(item.source_type, item.source_ref): item for item in evidence}

    # PROVIDER_MESSAGE, simulator quote: canonical JSON of the quoted terms.
    (offer,) = snapshot.offers
    quote_ref = (
        f"{offer.provider_id}:offer:{FictionalMobileProvider.plan_id}:v{offer.revision}"
    )
    quote = by_ref[(EvidenceType.PROVIDER_MESSAGE, quote_ref)]
    assert quote.evidence_id in offer.evidence_ids
    assert quote.content_hash == _sha256(
        _canonical_json(
            {
                "case_id": str(snapshot.case.case_id),
                "provider_id": offer.provider_id,
                "plan_id": FictionalMobileProvider.plan_id,
                "monthly_price_minor": offer.monthly_price.amount_minor,
                "currency": offer.monthly_price.currency,
                "features": list(offer.features),
            },
            ensure_ascii=True,
        )
    )

    # PROVIDER_MESSAGE, channel message: SHA-256 of the UTF-8 message text.
    channel = by_ref[(EvidenceType.PROVIDER_MESSAGE, str(message_id))]
    assert channel.content_hash == _sha256(message_content.encode("utf-8"))

    # PROVIDER_EVENT, delivery callback: SHA-256 of the raw callback payload.
    event = by_ref[(EvidenceType.PROVIDER_EVENT, provider_message_id)]
    assert event.content_hash == _sha256(delivery_raw)

    # CONFIRMATION: the confirmation hash, the only one a verifier recomputes.
    confirmation = state.provider.confirmation
    assert confirmation is not None
    confirmed = by_ref[(EvidenceType.CONFIRMATION, confirmation.confirmation_id)]
    assert confirmed.content_hash == _sha256(
        _canonical_json(confirmation.to_dict(), ensure_ascii=False)
    )
    assert confirmed.content_hash == confirmation_hash(confirmation)
    assert snapshot.completion_receipt is not None
    assert snapshot.completion_receipt.confirmation_content_hash == (
        confirmed.content_hash
    )

    # SIMULATOR_TRANSITION: an executor attestation minted before commit. Its
    # hash is producer-defined (today the runtime hashes its own idempotency
    # key) and names no Provider artifact; nothing may rely on it.
    (intent,) = snapshot.action_intents
    transition = by_ref[(EvidenceType.SIMULATOR_TRANSITION, intent.idempotency_key)]
    assert transition.content_hash == _sha256(intent.idempotency_key.encode())
