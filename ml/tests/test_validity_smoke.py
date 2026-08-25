from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from proxyloop_agent_core import CaseCoordinator
from proxyloop_evaluation.fresh_fixtures import (
    build_fresh_phase03a1_bundle,
    build_fresh_safe_observation,
)
from proxyloop_evaluation.runner_v2 import snapshot_without_strategy
from proxyloop_evaluation.validity_smoke import (
    SMOKE_CAPABILITIES,
    ValiditySmokeQwenAdapter,
    build_validity_slow_prompt,
    select_validity_smoke_fixtures,
    with_public_provider_state,
)

from scripts.run_phase_03a1_validity_smoke import (
    R4_PATH,
    REPORT_PATH,
    _check_report,
    _fingerprint,
    _sha256,
)


def _refingerprinted_report(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> Path:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    unsigned = {
        key: value for key, value in payload.items() if key != "report_fingerprint"
    }
    payload["report_fingerprint"] = _fingerprint(unsigned)
    path = tmp_path / "tampered-validity-smoke-report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_validity_smoke_checker_accepts_frozen_report() -> None:
    passed, failures = _check_report()

    assert passed, failures


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload["smoke_metrics"].__setitem__(
                "end_to_end_valid_count",
                payload["smoke_metrics"]["end_to_end_valid_count"] + 1,
            ),
            id="headline-metric",
        ),
        pytest.param(
            lambda payload: payload["selected_episode_ids"].append("extra-episode"),
            id="selected-episode-set",
        ),
        pytest.param(
            lambda payload: payload["reference_capabilities"].__setitem__(
                payload["selected_episode_ids"][0], "decline"
            ),
            id="reference-capability",
        ),
        pytest.param(
            lambda payload: payload["summary"]["episodes"][0].__setitem__(
                "actual_cost_microusd",
                payload["summary"]["episodes"][0]["actual_cost_microusd"] + 1,
            ),
            id="summary-cost",
        ),
        pytest.param(
            lambda payload: payload["summary"].__setitem__("model_call_count", 999),
            id="summary-model-call-count",
        ),
        pytest.param(
            lambda payload: payload.__setitem__("cost_note", "invoice"),
            id="cost-note",
        ),
        pytest.param(
            lambda payload: payload["summary"]["failure_slices"].__setitem__(
                "invalid_provider_outcome", 999
            ),
            id="summary-failure-slices",
        ),
        pytest.param(
            lambda payload: payload["summary"]["model_provenance"][0].__setitem__(
                "model_id", "tampered-model"
            ),
            id="summary-model-provenance",
        ),
    ],
)
def test_validity_smoke_checker_rejects_refingerprinted_tamper(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    report_path = _refingerprinted_report(tmp_path, mutate)

    passed, failures = _check_report(report_path=report_path)

    assert not passed
    assert failures


def test_validity_smoke_checker_rejects_refingerprinted_r4_tamper(
    tmp_path: Path,
) -> None:
    r4_payload = json.loads(R4_PATH.read_text(encoding="utf-8"))
    baseline = next(
        condition
        for condition in r4_payload["matrix_result"]["conditions"]
        if condition["condition"] == "untuned_fast_frontier_slow_medium"
    )
    baseline["episodes"][0]["latency_ms"] += 1
    unsigned_r4 = {
        key: value for key, value in r4_payload.items() if key != "report_fingerprint"
    }
    r4_payload["report_fingerprint"] = _fingerprint(unsigned_r4)
    r4_path = tmp_path / "tampered-r4-report.json"
    r4_path.write_text(json.dumps(r4_payload), encoding="utf-8")

    report_payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report_payload["source_r4_sha256"] = _sha256(r4_path)
    report_payload["source_r4_report_fingerprint"] = r4_payload["report_fingerprint"]
    unsigned_report = {
        key: value
        for key, value in report_payload.items()
        if key != "report_fingerprint"
    }
    report_payload["report_fingerprint"] = _fingerprint(unsigned_report)
    report_path = tmp_path / "refingerprinted-r5-report.json"
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    passed, failures = _check_report(report_path=report_path, r4_path=r4_path)

    assert not passed
    assert failures


def test_smoke_selects_one_frozen_episode_per_capability() -> None:
    selected = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)

    assert len(selected) == len(SMOKE_CAPABILITIES) == 6
    assert (
        tuple(
            fixture.reference_capability_id.removeprefix("simulator.")
            for fixture in selected
        )
        == SMOKE_CAPABILITIES
    )


def test_smoke_context_exposes_only_public_state_already_seen_by_oracle() -> None:
    fixture = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)[0]
    prepared = with_public_provider_state(fixture)
    observation = build_fresh_safe_observation(
        fixture.scenario, fixture.scenario.provider_turn
    )
    content = prepared.snapshot.visible_events[-1].content
    marker = "\nPUBLIC_PROVIDER_STATE_JSON:"

    assert marker in content
    public_state = json.loads(content.split(marker, maxsplit=1)[1])
    assert public_state == {
        "approval_current": observation.approval_current,
        "confirmation_evidence_available": (
            observation.confirmation_evidence_available
        ),
        "needs_clarification": observation.needs_clarification,
        "requested_disclosures": list(observation.requested_disclosures),
        "transfer_available": observation.transfer_available,
    }
    assert "expected_action" not in content
    assert "private_reason" not in content
    assert prepared.episode_id == fixture.episode_id


def test_validity_prompt_states_dynamic_identifier_and_position_contracts() -> None:
    fixture = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)[0]
    prepared = with_public_provider_state(fixture)
    initial = snapshot_without_strategy(prepared.snapshot)
    request = CaseCoordinator().build_slow_request(
        initial,
        reason_code="strategy_missing",
        created_at=prepared.scenario.observed_at,
    )

    bundle = build_validity_slow_prompt(request)
    system = str(bundle.messages[0]["content"])
    serialized = json.dumps(bundle.messages, sort_keys=True)

    assert "filtered SOFT constraints" in system
    assert "there are zero SOFT constraints, return []" in system
    assert "copy exact identifier tokens" in system
    assert "current_monthly_total" in system
    assert "required_features" in system
    assert "expected_action" not in serialized
    assert "oracle" not in serialized.lower()


def test_validity_fast_prompt_requires_not_done_without_verified_completion() -> None:
    fixture = select_validity_smoke_fixtures(build_fresh_phase03a1_bundle().fixtures)[0]
    view = CaseCoordinator().project_fast_view(fixture.snapshot)
    adapter = ValiditySmokeQwenAdapter(generator=lambda _: "{}")

    prompt = adapter.build_prompt(view)

    assert "completion_claim.status to not_done" in prompt.system
    assert "evidence_message_ids to []" in prompt.system
