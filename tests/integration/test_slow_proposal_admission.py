"""The A-3 Slow proposal admission check and its coordinator hook (PR-13).

A1a/A1b: one row per ``slow_proposal_*`` rule, the pair short-circuit, the
fixed order, and the two proposers that must pass. A2: the use-time
``standing_proposal_offer`` table. A3: each rule with an executor counterpart
is refused by the executor too. C1-C3: the coordinator hook.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from proxyloop_agent_core import (
    CapabilityExecutionRequest,
    CapabilityExecutor,
    CaseCoordinator,
    CoordinatorStatus,
    RouteRequest,
    ScriptedProposingSlowAdapter,
    ScriptedSlowAdapter,
    slow_proposal_violations,
    standing_proposal_offer,
)
from proxyloop_case_runtime import SCRIPTED_CASE_ID, ThinAgentRuntime
from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    CapabilityArgument,
    CapabilityProposal,
    CaseContextSnapshot,
    MaterialTerm,
    ModelResult,
    RoutingOutcome,
    SlowWorkRequest,
    SlowWorkResult,
    material_terms_hash,
    offer_material_terms,
)
from proxyloop_openai_adapter import compile_slow_output
from test_phase_04b_model_runtime import _slow_output_proposing_accept

T0 = datetime(2035, 1, 1, tzinfo=UTC)
AT = T0 + timedelta(minutes=31)  # the first strategy has expired: Slow refresh


def _snapshot() -> CaseContextSnapshot:
    runtime = ThinAgentRuntime(clock=lambda: T0)
    runtime.create_case(occurred_at=T0)
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    return state.snapshot


def _request(snapshot: CaseContextSnapshot, at: datetime = AT) -> SlowWorkRequest:
    return CaseCoordinator.build_slow_request(
        snapshot, reason_code="strategy_expired", created_at=at
    )


def _coherent(snapshot: CaseContextSnapshot) -> SlowWorkResult:
    return ScriptedProposingSlowAdapter().reason(_request(snapshot))


def _with(
    result: SlowWorkResult,
    *,
    capability: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
) -> SlowWorkResult:
    """``result`` with its one pair edited, bypassing contract validation."""

    (proposal,), (intent,) = result.capability_proposals, result.action_proposals
    return result.model_copy(
        update={
            "capability_proposals": (proposal.model_copy(update=capability or {}),),
            "action_proposals": (intent.model_copy(update=action or {}),),
        }
    )


def _case_with_authority(
    snapshot: CaseContextSnapshot, **authority: Any
) -> CaseContextSnapshot:
    delegated = snapshot.case.delegated_authority.model_copy(update=authority)
    case = snapshot.case.model_copy(update={"delegated_authority": delegated})
    return snapshot.model_copy(update={"case": case})


def _with_definition_expiry(
    snapshot: CaseContextSnapshot, expires_at: datetime
) -> CaseContextSnapshot:
    manifest = snapshot.capability_manifest
    (definition,) = manifest.capabilities
    changed = manifest.model_copy(
        update={
            "capabilities": (definition.model_copy(update={"expires_at": expires_at}),)
        }
    )
    return snapshot.model_copy(update={"capability_manifest": changed})


# -- A1b: the two proposers pass -----------------------------------------------


def test_a_scripted_proposing_result_is_admitted() -> None:
    snapshot = _snapshot()
    result = _coherent(snapshot)

    assert len(result.capability_proposals) == len(result.action_proposals) == 1
    assert slow_proposal_violations(result, snapshot, AT) == ()


def test_an_openai_compiled_accept_result_is_admitted() -> None:
    snapshot = _snapshot()
    result = compile_slow_output(_request(snapshot), _slow_output_proposing_accept())

    assert len(result.capability_proposals) == 1
    assert slow_proposal_violations(result, snapshot, AT) == ()


def test_a_result_without_proposals_has_no_violation() -> None:
    snapshot = _snapshot()
    result = ScriptedSlowAdapter().reason(_request(snapshot))

    assert slow_proposal_violations(result, snapshot, AT) == ()


def test_the_proposing_adapter_keeps_the_scripted_strategy() -> None:
    snapshot = _snapshot()
    request = _request(snapshot)
    plain = ScriptedSlowAdapter().reason(request)
    proposing = ScriptedProposingSlowAdapter().reason(request)

    assert proposing.strategy_proposal == plain.strategy_proposal
    assert proposing.result_id == plain.result_id
    (capability,) = proposing.capability_proposals
    (action,) = proposing.action_proposals
    (offer,) = snapshot.offers
    assert capability.expires_at == action.expires_at == offer.expires_at
    assert capability.arguments == (
        CapabilityArgument(name="offer_id", value=str(offer.offer_id)),
    )
    assert ScriptedProposingSlowAdapter.model_identity.model_version == ("proposing-v1")
    assert ScriptedSlowAdapter.model_identity.model_version == "deterministic-v1"


def test_the_proposing_adapter_proposes_nothing_once_the_offer_expired() -> None:
    snapshot = _snapshot()
    (offer,) = snapshot.offers
    result = ScriptedProposingSlowAdapter().reason(_request(snapshot, offer.expires_at))

    assert result.capability_proposals == () and result.action_proposals == ()


# -- A1a: one row per rule -----------------------------------------------------


def _rows() -> list[Any]:
    return [
        pytest.param(
            lambda r, s: (
                r.model_copy(
                    update={
                        "capability_proposals": (
                            r.capability_proposals[0],
                            r.capability_proposals[0].model_copy(
                                update={"proposal_id": r.action_proposals[0].intent_id}
                            ),
                        ),
                        "action_proposals": (
                            r.action_proposals[0],
                            r.action_proposals[0].model_copy(
                                update={
                                    "intent_id": r.capability_proposals[0].proposal_id
                                }
                            ),
                        ),
                    }
                ),
                s,
            ),
            ("slow_proposal_count_exceeded",),
            id="1-count",
        ),
        pytest.param(
            lambda r, s: (
                r.model_copy(
                    update={
                        "capability_proposals": (
                            r.capability_proposals[0],
                            r.capability_proposals[0].model_copy(
                                update={"proposal_id": r.action_proposals[0].intent_id}
                            ),
                        ),
                        # Every other rule is broken too; none is reported.
                        "action_proposals": (
                            r.action_proposals[0].model_copy(
                                update={"action_type": ActionType.END_INTERACTION}
                            ),
                        ),
                    }
                ),
                s,
            ),
            ("slow_proposal_count_exceeded", "slow_proposal_unpaired"),
            id="1+2-short-circuit",
        ),
        pytest.param(
            lambda r, s: (r.model_copy(update={"action_proposals": ()}), s),
            ("slow_proposal_unpaired",),
            id="2-capability-only",
        ),
        pytest.param(
            lambda r, s: (r.model_copy(update={"capability_proposals": ()}), s),
            ("slow_proposal_unpaired",),
            id="2-action-only",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r,
                    capability={
                        "capability": r.capability_proposals[0].capability.model_copy(
                            update={"version": "9.9"}
                        )
                    },
                ),
                s,
            ),
            ("slow_proposal_capability_unsupported",),
            id="3-unsupported",
        ),
        pytest.param(
            lambda r, s: (
                _with(r, action={"action_type": ActionType.SEND_MESSAGE}),
                s,
            ),
            ("slow_proposal_capability_action_mismatch",),
            id="4-action-mismatch",
        ),
        pytest.param(
            lambda r, s: (_with(r, capability={"expires_at": AT}), s),
            ("slow_proposal_capability_expired",),
            id="5-proposal-expired-at-boundary",
        ),
        pytest.param(
            lambda r, s: (r, _with_definition_expiry(s, AT)),
            ("slow_proposal_capability_expired",),
            id="5-definition-expired",
        ),
        pytest.param(
            lambda r, s: (
                r,
                s.model_copy(
                    update={
                        "capability_manifest": s.capability_manifest.model_copy(
                            update={"expires_at": AT}
                        )
                    }
                ),
            ),
            ("slow_proposal_capability_expired",),
            id="5-manifest-expired",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r, capability={"created_at": r.created_at - timedelta(seconds=1)}
                ),
                s,
            ),
            ("slow_proposal_predates_result",),
            id="6-predates",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r,
                    capability={
                        "arguments": (
                            CapabilityArgument(name="offer_id", value="not-an-offer"),
                        )
                    },
                ),
                s,
            ),
            ("slow_proposal_offer_binding_mismatch",),
            id="7-foreign-offer-argument",
        ),
        pytest.param(
            lambda r, s: (_with(r, capability={"arguments": ()}), s),
            ("slow_proposal_offer_binding_mismatch",),
            id="7-no-offer-argument",
        ),
        pytest.param(
            lambda r, s: (_with(r, action={"offer_ref": None}), s),
            ("slow_proposal_offer_binding_mismatch",),
            id="7-argument-without-offer-ref",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r,
                    action={
                        "offer_ref": r.action_proposals[0].offer_ref.model_copy(
                            update={
                                "offer_revision": (
                                    r.action_proposals[0].offer_ref.offer_revision + 1
                                )
                            }
                        )
                    },
                ),
                s,
            ),
            ("slow_proposal_offer_not_current",),
            id="8-offer-revision",
        ),
        pytest.param(
            lambda r, s: (_with(r, action={"material_terms_hash": "0" * 64}), s),
            ("slow_proposal_terms_mismatch",),
            id="9-hash",
        ),
        pytest.param(
            lambda r, s: (_with(r, action=_other_terms()), s),
            ("slow_proposal_terms_mismatch",),
            id="9-terms-differ-from-offer",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r,
                    action={"case_revision": r.action_proposals[0].case_revision + 1},
                ),
                s,
            ),
            ("slow_proposal_intent_binding_mismatch",),
            id="10-case-revision",
        ),
        pytest.param(
            lambda r, s: (
                _with(
                    r,
                    action={
                        "strategy_revision": r.action_proposals[0].strategy_revision + 1
                    },
                ),
                s,
            ),
            ("slow_proposal_intent_binding_mismatch",),
            id="10-strategy",
        ),
        pytest.param(
            lambda r, s: (
                r,
                _case_with_authority(
                    s,
                    allowed_actions=(ActionType.SEND_MESSAGE,),
                    approval_required_actions=(),
                ),
            ),
            ("slow_proposal_action_not_delegated",),
            id="11-not-delegated",
        ),
    ]


def _other_terms() -> dict[str, Any]:
    terms = (MaterialTerm(name="monthly_price_minor", value="1"),)
    return {"material_terms": terms, "material_terms_hash": material_terms_hash(terms)}


@pytest.mark.parametrize(("mutate", "expected"), _rows())
def test_each_rule_has_its_code(mutate: Any, expected: tuple[str, ...]) -> None:
    snapshot = _snapshot()
    result, current = mutate(_coherent(snapshot), snapshot)

    assert slow_proposal_violations(result, current, AT) == expected


def test_codes_come_in_rule_order_once_each() -> None:
    snapshot = _snapshot()
    result = _with(
        _coherent(snapshot),
        capability={
            "capability": _coherent(snapshot)
            .capability_proposals[0]
            .capability.model_copy(update={"capability_id": "simulator.unknown"}),
            "created_at": AT - timedelta(seconds=1),
            "expires_at": AT,
            "arguments": (),
        },
        action={
            "action_type": ActionType.END_INTERACTION,
            "material_terms_hash": "0" * 64,
            "case_revision": 99,
        },
    )

    assert slow_proposal_violations(result, snapshot, AT) == (
        "slow_proposal_capability_unsupported",
        "slow_proposal_capability_expired",
        "slow_proposal_predates_result",
        "slow_proposal_offer_binding_mismatch",
        "slow_proposal_terms_mismatch",
        "slow_proposal_intent_binding_mismatch",
        "slow_proposal_action_not_delegated",
    )


# -- A2: use-time admissibility ------------------------------------------------


def _proposal(snapshot: CaseContextSnapshot) -> CapabilityProposal:
    return _coherent(snapshot).capability_proposals[0]


def test_an_admissible_standing_proposal_names_the_current_offer() -> None:
    snapshot = _snapshot()

    assert (
        standing_proposal_offer(_proposal(snapshot), snapshot, evaluated_at=AT)
        == (snapshot.offers[0])
    )


def _not_admissible() -> list[Any]:
    def edit(**update: Any) -> Any:
        return lambda p, s: (p.model_copy(update=update), s)

    return [
        pytest.param(lambda p, s: (None, s), id="none"),
        pytest.param(
            lambda p, s: (
                p.model_copy(
                    update={
                        "capability": p.capability.model_copy(
                            update={"capability_id": "simulator.unknown"}
                        )
                    }
                ),
                s,
            ),
            id="unknown-capability",
        ),
        pytest.param(
            lambda p, s: (
                p,
                s.model_copy(
                    update={
                        "capability_manifest": s.capability_manifest.model_copy(
                            update={
                                "capabilities": (
                                    s.capability_manifest.capabilities[0].model_copy(
                                        update={
                                            "allowed_action_types": (
                                                ActionType.ACCEPT_OFFER,
                                                ActionType.SEND_MESSAGE,
                                            )
                                        }
                                    ),
                                )
                            }
                        )
                    }
                ),
            ),
            id="non-accept-definition",
        ),
        pytest.param(edit(expires_at=AT), id="proposal-expired"),
        pytest.param(
            lambda p, s: (p, _with_definition_expiry(s, AT)), id="definition-expired"
        ),
        pytest.param(
            lambda p, s: (
                p,
                s.model_copy(
                    update={
                        "capability_manifest": s.capability_manifest.model_copy(
                            update={"expires_at": AT}
                        )
                    }
                ),
            ),
            id="manifest-expired",
        ),
        pytest.param(edit(arguments=()), id="no-offer-argument"),
        pytest.param(
            lambda p, s: (
                p.model_copy(update={"arguments": (*p.arguments, *p.arguments)}),
                s,
            ),
            id="two-offer-arguments",
        ),
        pytest.param(
            edit(arguments=(CapabilityArgument(name="offer_id", value="elsewhere"),)),
            id="foreign-offer",
        ),
    ]


@pytest.mark.parametrize("mutate", _not_admissible())
def test_a_standing_proposal_that_is_not_admissible_names_no_offer(
    mutate: Any,
) -> None:
    snapshot = _snapshot()
    proposal, current = mutate(_proposal(snapshot), snapshot)

    assert standing_proposal_offer(proposal, current, evaluated_at=AT) is None


# -- A3: agreement with the executor -------------------------------------------


class _NeverPrepared:
    def prepare(self, proposal: CapabilityProposal, *, idempotency_key: str) -> Any:
        raise AssertionError("a refused request is never prepared")


def _executor_codes(
    snapshot: CaseContextSnapshot, capability: CapabilityProposal, action: ActionIntent
) -> tuple[str, ...]:
    executor = CapabilityExecutor(
        _NeverPrepared(), terms_derivation=offer_material_terms
    )
    outcome = executor.execute(
        CapabilityExecutionRequest(
            snapshot=snapshot,
            source_pins=snapshot.pins,
            proposal=capability,
            action_intent=action,
            approval=None,
            executed_at=AT,
        )
    )
    return outcome.reason_codes


@pytest.mark.parametrize(
    ("row", "counterpart"),
    [
        ("3-unsupported", "unsupported_capability"),
        ("4-action-mismatch", "capability_action_mismatch"),
        ("7-foreign-offer-argument", "capability_offer_binding_mismatch"),
        ("8-offer-revision", "current_offer_mismatch"),
        ("9-hash", "action_material_terms_hash_mismatch"),
        ("9-terms-differ-from-offer", "current_offer_terms_mismatch"),
    ],
)
def test_the_executor_refuses_what_the_admission_check_refuses(
    row: str, counterpart: str
) -> None:
    (param,) = [item for item in _rows() if item.id == row]
    mutate, expected = param.values
    snapshot = _snapshot()
    result, current = mutate(_coherent(snapshot), snapshot)
    assert slow_proposal_violations(result, current, AT) == expected

    codes = _executor_codes(
        current, result.capability_proposals[0], result.action_proposals[0]
    )

    assert counterpart in codes


# -- C1-C3: the coordinator hook -----------------------------------------------


class _Fixed:
    """A Slow adapter returning ``edit`` applied to the scripted proposal."""

    def __init__(self, edit: Any) -> None:
        self._edit = edit

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        result: SlowWorkResult = self._edit(
            ScriptedProposingSlowAdapter().reason(request)
        )
        return result


def _incoherent(result: SlowWorkResult) -> SlowWorkResult:
    return _with(result, action={"action_type": ActionType.SEND_MESSAGE})


def _advance(slow: Any, **hook: Any) -> Any:
    snapshot = _snapshot()
    coordinator = CaseCoordinator(snapshot=snapshot, **hook)
    return coordinator.advance(
        RouteRequest(snapshot=snapshot, created_at=AT), slow=slow
    )


def test_the_hook_rejects_the_whole_result_and_traces_its_codes() -> None:
    # C1
    outcome = _advance(
        _Fixed(_incoherent), slow_proposal_check=slow_proposal_violations
    )

    assert outcome.route.outcome is RoutingOutcome.SLOW_REFRESH
    assert outcome.status is CoordinatorStatus.REJECTED
    assert outcome.slow_result is None
    (audit,) = outcome.audits
    assert audit.accepted is False
    assert audit.reason_codes == ("slow_proposal_capability_action_mismatch",)
    (trace,) = outcome.traces
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == audit.reason_codes


def test_without_the_hook_the_coordinator_is_unchanged() -> None:
    # C2: the ML callers' coordinator admits the incoherent result as before.
    slow = _Fixed(_incoherent)
    outcome = _advance(slow)

    assert outcome.status is CoordinatorStatus.ACCEPTED
    assert outcome.slow_result is not None
    assert outcome.slow_result.action_proposals[0].action_type is (
        ActionType.SEND_MESSAGE
    )
    (audit,) = outcome.audits
    assert audit.reason_codes == ("slow_result_current",)
    (trace,) = outcome.traces
    assert trace.result is ModelResult.SUCCEEDED


def test_the_hook_runs_only_on_a_validated_result() -> None:
    # C3: a stale result keeps its validation codes; the hook is not called.
    calls: list[object] = []

    def hook(*args: object) -> tuple[str, ...]:
        calls.append(args)
        return ("slow_proposal_unpaired",)

    def expired(result: SlowWorkResult) -> SlowWorkResult:
        strategy = result.strategy_proposal
        assert strategy is not None
        return result.model_copy(
            update={"strategy_proposal": strategy.model_copy(update={"expires_at": AT})}
        )

    outcome = _advance(_Fixed(expired), slow_proposal_check=hook)

    assert calls == []
    (audit,) = outcome.audits
    assert audit.reason_codes == ("slow_strategy_expired",)
    assert outcome.slow_result is None
