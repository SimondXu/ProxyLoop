"""An injectable Provider offer TTL, persisted without a storage bump (R-6).

The Runtime takes the offer TTL as a constructor parameter (default 1 h). The
PostgreSQL codec stores a non-default TTL as the optional version 3 field
``provider_offer_ttl_seconds`` and omits it for the default, so a default row
is the document an earlier writer produced. Decoding regenerates the offer
with the stored TTL and still compares it, so a tampered ``expires_at`` fails.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseConflictError,
    CaseRuntimeState,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime import runtime as runtime_module
from proxyloop_case_runtime.postgres_repository import (
    PostgresCaseRepository,
    _CaseStorageEnvelope,
)
from proxyloop_contracts import CasePhase, EvidenceType
from proxyloop_provider_simulator.provider import (
    MAX_OFFER_TTL,
    FictionalMobileProvider,
)
from test_phase_04c_persistent_case_store import _assert_non_provider_fields_equal
from test_r10_terminal_delivery_callback import _CodecChannelRepository, _round_trip

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TWO_DAYS = timedelta(hours=48)
KEY = "provider_offer_ttl_seconds"
INVALID = "stored Case payload is invalid"
REFUSED = "Case state failed storage validation"


def _waiting(
    repository: InMemoryCaseRepository, *, offer_ttl: timedelta | None = None
) -> ThinAgentRuntime:
    runtime = (
        ThinAgentRuntime(repository)
        if offer_ttl is None
        else ThinAgentRuntime(repository, offer_ttl=offer_ttl)
    )
    runtime.create_case(occurred_at=T0)
    runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Review the offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )
    return runtime


def _state(runtime: ThinAgentRuntime) -> CaseRuntimeState:
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state


def _approve(runtime: ThinAgentRuntime, *, at: datetime) -> None:
    (approval,) = _state(runtime).snapshot.approval_requests
    runtime.approve(SCRIPTED_CASE_ID, approval.approval_id, occurred_at=at)


def _payload(state: CaseRuntimeState) -> dict[str, Any]:
    encoded: dict[str, Any] = json.loads(
        json.dumps(PostgresCaseRepository._encode_state(state))
    )
    return encoded


def _decode(state: CaseRuntimeState, payload: dict[str, Any]) -> CaseRuntimeState:
    return PostgresCaseRepository._decode_state(
        state.snapshot.case.case_id, state.snapshot.revision, payload
    )


def _assert_completed_once(state: CaseRuntimeState) -> None:
    assert state.snapshot.case.phase is CasePhase.COMPLETE
    assert state.execution_count == 1
    confirmations = [
        item
        for item in state.snapshot.evidence
        if item.source_type is EvidenceType.CONFIRMATION
    ]
    assert len(confirmations) == 1


def test_the_default_offer_ttl_is_one_hour() -> None:
    runtime = _waiting(InMemoryCaseRepository())
    state = _state(runtime)
    (offer,) = state.snapshot.offers
    (approval,) = state.snapshot.approval_requests

    assert state.provider.offer_ttl == timedelta(hours=1)
    assert offer.expires_at == approval.expires_at == T0 + timedelta(hours=1)


def test_an_injected_offer_ttl_sets_the_offer_and_approval_expiry() -> None:
    runtime = _waiting(InMemoryCaseRepository(), offer_ttl=TWO_DAYS)
    state = _state(runtime)
    (offer,) = state.snapshot.offers
    (approval,) = state.snapshot.approval_requests

    assert state.provider.offer_ttl == TWO_DAYS
    assert offer.created_at == T0
    assert offer.expires_at == approval.expires_at == T0 + TWO_DAYS
    assert approval.expires_at <= state.snapshot.capability_manifest.expires_at


def test_an_approval_after_25_hours_completes_in_memory() -> None:
    runtime = _waiting(InMemoryCaseRepository(), offer_ttl=TWO_DAYS)

    _approve(runtime, at=T0 + timedelta(hours=25))

    _assert_completed_once(_state(runtime))


def test_with_the_default_ttl_an_approval_after_25_hours_is_expired() -> None:
    runtime = _waiting(InMemoryCaseRepository())

    with pytest.raises(CaseConflictError, match=r"^approval expired$"):
        _approve(runtime, at=T0 + timedelta(hours=25))

    state = _state(runtime)
    assert state.execution_count == 0
    assert state.snapshot.completion_decision is None


def test_an_approval_after_25_hours_completes_through_the_postgres_codec() -> None:
    # Every write goes through encode -> JSON -> decode, so the Provider the
    # Runtime continues with is the one the codec reconstructed.
    repository = _CodecChannelRepository()
    runtime = _waiting(repository, offer_ttl=TWO_DAYS)
    assert _state(runtime).provider.offer_ttl == TWO_DAYS

    _approve(runtime, at=T0 + timedelta(hours=25))

    terminal = _state(runtime)
    _assert_completed_once(terminal)
    assert terminal.provider.offer_ttl == TWO_DAYS
    _assert_non_provider_fields_equal(terminal, _round_trip(terminal))


def test_an_injected_ttl_is_stored_and_read_back() -> None:
    waiting = _state(_waiting(InMemoryCaseRepository(), offer_ttl=TWO_DAYS))

    payload = _payload(waiting)
    decoded = _decode(waiting, payload)

    assert payload[KEY] == 172800
    assert decoded.provider.offer_ttl == TWO_DAYS
    assert decoded.provider.state is waiting.provider.state
    _assert_non_provider_fields_equal(waiting, decoded)


def test_a_default_ttl_row_has_no_ttl_key() -> None:
    waiting = _state(_waiting(InMemoryCaseRepository()))

    payload = _payload(waiting)

    assert KEY not in payload
    assert sorted(payload) == [
        "events",
        "execution_approval",
        "execution_claim",
        "execution_count",
        "execution_intent",
        "execution_proposal",
        "execution_source_pins",
        "last_fast_decision",
        "snapshot",
        "storage_version",
        "transitions",
    ]
    assert _decode(waiting, payload).provider.offer_ttl == timedelta(hours=1)


def _tamper_expiry(payload: dict[str, Any]) -> None:
    offer = payload["snapshot"]["offers"][0]
    offer["expires_at"] = (T0 + TWO_DAYS + timedelta(hours=1)).isoformat()


def _tamper_ttl(payload: dict[str, Any]) -> None:
    payload[KEY] = 172800 + 3600


def _drop_ttl(payload: dict[str, Any]) -> None:
    del payload[KEY]


def _default_ttl_by_value(payload: dict[str, Any]) -> None:
    payload[KEY] = 3600


def _ttl(value: object) -> Any:
    def edit(payload: dict[str, Any]) -> None:
        payload[KEY] = value

    edit.__name__ = f"ttl_{value!r}"
    return edit


MAX_SECONDS = MAX_OFFER_TTL // timedelta(seconds=1)


@pytest.mark.parametrize(
    "edit",
    [
        _tamper_expiry,
        _tamper_ttl,
        _drop_ttl,
        _ttl(0),
        _ttl(-5),
        _ttl(None),
        _ttl(MAX_SECONDS + 1),
        # Past the bound; unbounded, these overflowed timedelta or datetime.
        _ttl(10**12),
        _ttl(10**15),
        _ttl(172800.0),
        _ttl("172800"),
        _ttl(True),
    ],
    ids=lambda edit: edit.__name__,
)
def test_the_codec_rejects_an_offer_that_does_not_match_the_stored_ttl(
    edit: Any,
) -> None:
    waiting = _state(_waiting(InMemoryCaseRepository(), offer_ttl=TWO_DAYS))
    payload = _payload(waiting)
    edit(payload)

    with pytest.raises(RuntimeError, match=rf"^{INVALID}$"):
        _decode(waiting, payload)


@pytest.mark.parametrize(
    "edit",
    # The default is stored only by omission, so each Case has one document:
    # neither by value nor as an explicit null; nor may a TTL be added to a
    # default row.
    [_default_ttl_by_value, _ttl(None), _ttl(7200), _ttl(10**15)],
    ids=lambda edit: edit.__name__,
)
def test_the_codec_rejects_a_ttl_key_on_a_default_row(edit: Any) -> None:
    waiting = _state(_waiting(InMemoryCaseRepository()))
    payload = _payload(waiting)
    edit(payload)

    with pytest.raises(RuntimeError, match=rf"^{INVALID}$"):
        _decode(waiting, payload)


def _unchecked_payload(state: CaseRuntimeState, offer_ttl: timedelta) -> dict[str, Any]:
    """The document a writer without the codec's checks would store."""

    values = {
        field.name: getattr(state, field.name)
        for field in fields(CaseRuntimeState)
        if field.name != "provider"
    }
    envelope = _CaseStorageEnvelope.model_construct(
        storage_version=3,
        provider_offer_ttl_seconds=offer_ttl // timedelta(seconds=1),
        **values,
    )
    payload: dict[str, Any] = json.loads(
        envelope.model_dump_json(
            exclude={"standing_proposal"} if state.standing_proposal is None else None
        )
    )
    return payload


def test_the_unchecked_payload_helper_writes_a_valid_document() -> None:
    # Control for the two forgeries below: the helper alone changes nothing.
    waiting = _state(_waiting(InMemoryCaseRepository(), offer_ttl=TWO_DAYS))

    assert _unchecked_payload(waiting, TWO_DAYS) == _payload(waiting)


def test_a_consistent_30_day_row_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Offer, Evidence, intent and approval all agree on a 30-day TTL; only the
    # approval-time manifest guard is bypassed to build it.
    build_approval = runtime_module._build_approval

    def unguarded(*args: Any, **kwargs: Any) -> Any:
        offer = args[2]
        manifest = kwargs["manifest"].model_copy(
            update={"expires_at": offer.expires_at}
        )
        return build_approval(*args, **{**kwargs, "manifest": manifest})

    monkeypatch.setattr(runtime_module, "_build_approval", unguarded)
    runtime = ThinAgentRuntime(InMemoryCaseRepository())
    runtime._offer_ttl = timedelta(days=30)
    runtime.create_case(occurred_at=T0)
    runtime.append_event(
        SCRIPTED_CASE_ID,
        content="Review the offer.",
        occurred_at=T0 + timedelta(minutes=1),
    )
    forged = _state(runtime)
    (approval,) = forged.snapshot.approval_requests
    assert approval.expires_at == T0 + timedelta(days=30)

    with pytest.raises(RuntimeError, match=rf"^{REFUSED}$"):
        PostgresCaseRepository._encode_state(forged)
    with pytest.raises(RuntimeError, match=rf"^{INVALID}$"):
        _decode(forged, _unchecked_payload(forged, timedelta(days=30)))


def test_an_offer_outliving_the_manifest_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 48 h offer on a Case whose manifest ends after one day (the pre-A-11
    # lifetime): the TTL is in range, but the offer would outlive the manifest.
    manifest = runtime_module._manifest

    def one_day(case: Any) -> Any:
        minted = manifest(case)
        expires_at = T0 + timedelta(days=1)
        return minted.model_copy(
            update={
                "expires_at": expires_at,
                "capabilities": tuple(
                    item.model_copy(update={"expires_at": expires_at})
                    for item in minted.capabilities
                ),
            }
        )

    monkeypatch.setattr(runtime_module, "_manifest", one_day)
    runtime = ThinAgentRuntime(InMemoryCaseRepository(), offer_ttl=TWO_DAYS)
    runtime.create_case(occurred_at=T0)
    created = _state(runtime)
    assert created.snapshot.capability_manifest.expires_at == T0 + timedelta(days=1)
    assert created.snapshot.offers[0].expires_at == T0 + TWO_DAYS

    with pytest.raises(RuntimeError, match=rf"^{REFUSED}$"):
        PostgresCaseRepository._encode_state(created)
    with pytest.raises(RuntimeError, match=rf"^{INVALID}$"):
        _decode(created, _unchecked_payload(created, TWO_DAYS))


def test_a_default_ttl_row_with_a_tampered_expiry_is_still_rejected() -> None:
    waiting = _state(_waiting(InMemoryCaseRepository()))
    payload = _payload(waiting)
    payload["snapshot"]["offers"][0]["expires_at"] = (
        T0 + timedelta(hours=2)
    ).isoformat()

    with pytest.raises(RuntimeError, match=rf"^{INVALID}$"):
        _decode(waiting, payload)


@pytest.mark.parametrize(
    "offer_ttl",
    [
        timedelta(0),
        timedelta(hours=-1),
        timedelta(hours=1, microseconds=1),
        timedelta(days=9, seconds=1),
    ],
)
def test_the_runtime_refuses_an_out_of_bounds_offer_ttl(offer_ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="offer_ttl"):
        ThinAgentRuntime(offer_ttl=offer_ttl)


def test_the_longest_offer_ttl_ends_at_the_case_deadline() -> None:
    runtime = _waiting(InMemoryCaseRepository(), offer_ttl=timedelta(days=9))
    snapshot = _state(runtime).snapshot
    (approval,) = snapshot.approval_requests

    assert approval.expires_at == snapshot.case.goal.deadline
    assert approval.expires_at == snapshot.capability_manifest.expires_at


@pytest.mark.parametrize("offer_ttl", [timedelta(0), timedelta(seconds=-1)])
def test_the_provider_refuses_a_non_positive_offer_ttl(offer_ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="offer_ttl must be positive"):
        FictionalMobileProvider(offer_ttl=offer_ttl)
