"""Versioned scripted-oracle precedence (P1 D1-8, root decision 3).

V1 stays the default and byte-identical over the whole V1 generation space;
V2_OFFER_FIRST accepts a compliant offer with evidence before escalating.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from functools import cache

import pytest
from proxyloop_agent_core import (
    OracleAction,
    OracleDecision,
    OraclePrecedence,
    SafeObservation,
    ScriptedOracleConsumer,
)
from proxyloop_evaluation.phase03c_scenarios import harvest_positions
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    build_parameterised_scenarios,
)

# SHA-256 of the default oracle's (action, offer_id, reason_codes) over the
# observations below, measured on unmodified main @ 383d1fa.
_PRE_CHANGE_V1_DIGEST = (
    "21c81841a5f9c207a7f2c5dd17c8d6687060bae307556f0b06a7ea20e69bed22"
)
_V1_SPACE_SIZE = 64_704  # (32 catalogue + 1010 seeds x 32) instances x 2 positions


@cache
def _v1_space() -> tuple[SafeObservation, ...]:
    scenarios = BENCHMARK_SCENARIOS + build_parameterised_scenarios(
        seeds=range(1, 1011)
    )
    return tuple(
        position.observation
        for scenario in scenarios
        for position in harvest_positions(scenario)
    )


def _row(decision: OracleDecision) -> list[object]:
    return [decision.action.value, decision.offer_id, list(decision.reason_codes)]


def _digest(decisions: list[OracleDecision]) -> str:
    rows = [_row(decision) for decision in decisions]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _probe_e() -> tuple[SafeObservation, str | None]:
    scenario = next(s for s in BENCHMARK_SCENARIOS if s.family_id == "direct-success")
    opening = harvest_positions(scenario)[0].observation
    assert not opening.transfer_available
    return replace(opening, transfer_available=True), scenario.expected_offer_id


def test_probe_e_v2_accepts_the_compliant_offer_before_escalating() -> None:
    observation, expected_offer_id = _probe_e()

    v2 = ScriptedOracleConsumer(precedence=OraclePrecedence.V2_OFFER_FIRST)

    assert v2.decide(observation) == OracleDecision(
        OracleAction.ACCEPT_OFFER, expected_offer_id, ("valid_offer",)
    )


def test_probe_e_default_precedence_still_escalates() -> None:
    observation, _ = _probe_e()
    escalate = OracleDecision(OracleAction.ESCALATE, None, ("transfer_available",))

    assert ScriptedOracleConsumer().decide(observation) == escalate
    assert (
        ScriptedOracleConsumer(precedence=OraclePrecedence.V1).decide(observation)
        == escalate
    )


def test_v2_escalates_on_transfer_when_no_offer_is_compliant() -> None:
    observation, _ = _probe_e()
    no_offer = replace(observation, offers=())
    no_evidence = replace(observation, confirmation_evidence_available=False)
    v2 = ScriptedOracleConsumer(precedence=OraclePrecedence.V2_OFFER_FIRST)
    escalate = OracleDecision(OracleAction.ESCALATE, None, ("transfer_available",))

    assert v2.decide(no_offer) == escalate
    assert v2.decide(no_evidence) == escalate
    assert v2.decide(replace(no_evidence, transfer_available=False)) == (
        OracleDecision(
            OracleAction.REQUEST_REPLAN, None, ("confirmation_evidence_unavailable",)
        )
    )
    assert v2.decide(replace(no_offer, transfer_available=False)) == (
        OracleDecision(OracleAction.DECLINE, None, ("no_valid_offer",))
    )


def test_unknown_precedence_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScriptedOracleConsumer(precedence="v3")  # type: ignore[arg-type]


def test_default_precedence_is_unchanged_over_the_v1_generation_space() -> None:
    observations = _v1_space()
    assert len(observations) == _V1_SPACE_SIZE

    default = [ScriptedOracleConsumer().decide(o) for o in observations]
    explicit_v1 = ScriptedOracleConsumer(precedence=OraclePrecedence.V1)

    assert _digest(default) == _PRE_CHANGE_V1_DIGEST
    assert [explicit_v1.decide(o) for o in observations] == default


def test_v2_matches_v1_over_the_v1_generation_space() -> None:
    # Transfer is set only on refusal-transfer and multi-hazard, which carry
    # no compliant offer, so the V2 reorder never applies here.
    observations = _v1_space()
    v1 = ScriptedOracleConsumer(precedence=OraclePrecedence.V1)
    v2 = ScriptedOracleConsumer(precedence=OraclePrecedence.V2_OFFER_FIRST)

    differing = [o for o in observations if v1.decide(o) != v2.decide(o)]

    assert differing == []


def test_v2_differs_from_v1_exactly_on_transfer_with_a_compliant_offer() -> None:
    v1 = ScriptedOracleConsumer(precedence=OraclePrecedence.V1)
    v2 = ScriptedOracleConsumer(precedence=OraclePrecedence.V2_OFFER_FIRST)
    compared = 0
    differed = 0

    for observation in _v1_space():
        if observation.transfer_available:
            continue
        original = v1.decide(observation)
        transferred = replace(observation, transfer_available=True)
        v1_decision = v1.decide(transferred)
        v2_decision = v2.decide(transferred)
        compared += 1
        if original.action is OracleAction.ACCEPT_OFFER:
            differed += 1
            assert v1_decision.action is OracleAction.ESCALATE
            assert v2_decision == original
        else:
            assert v2_decision == v1_decision

    assert compared > 0
    assert differed > 0
