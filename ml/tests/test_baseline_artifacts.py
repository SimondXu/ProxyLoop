from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from proxyloop_agent_core import CaseCoordinator, DeterministicRouter, RouteRequest
from proxyloop_evaluation import BaselineReport, check_baseline_artifacts, runner
from proxyloop_evaluation.artifacts import fingerprint, report_fingerprint, write_report
from proxyloop_evaluation.legacy_slow_output import build_legacy_slow_prompt
from proxyloop_evaluation.models import BaselineCondition, RunStatus
from proxyloop_evaluation.openai_frontier import OpenAIFrontierAdapter
from proxyloop_evaluation.qwen_mlx import QwenMLXAdapter
from proxyloop_evaluation.runner import (
    FAST_SLOW_HOSTED_MAX_MICROUSD,
    FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD,
    HOSTED_BUDGET_CEILING_MICROUSD,
    compose_report,
    not_run_condition,
    run_frontier_condition,
    run_slow_off_ablation,
)

from scripts.run_phase_03a1_harness import PROBE_NOW, build_phase03a1_model_fixtures

ROOT = Path(__file__).resolve().parents[2]


def _copy_artifacts(target_root: Path) -> Path:
    for relative in (
        "data/evaluation/phase-03a1-baselines-report.json",
        "data/manifests/phase-03a1-manifest.json",
        "data/manifests/phase-03a1-episodes.json",
        "data/manifests/phase-03a1-ceiling-report.json",
    ):
        source = ROOT / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return target_root / "data/evaluation/phase-03a1-baselines-report.json"


def _write_refingerprinted(path: Path, payload: dict[str, object]) -> None:
    report = BaselineReport.model_validate_json(json.dumps(payload))
    report = report.model_copy(
        update={"report_fingerprint": report_fingerprint(report)}
    )
    path.write_text(
        json.dumps(report.model_dump(mode="json", exclude_unset=True)),
        encoding="utf-8",
    )


def _write_failed_frontier_report(target_root: Path) -> Path:
    report_path = _copy_artifacts(target_root)
    current = BaselineReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )

    @dataclass
    class RaisingResponses:
        def parse(self, **_: object) -> object:
            raise TimeoutError("redacted")

    @dataclass
    class RaisingClient:
        chat: SimpleNamespace = field(
            default_factory=lambda: SimpleNamespace(completions=RaisingResponses())
        )

    fixture = build_phase03a1_model_fixtures()[0]
    failed = run_frontier_condition(
        OpenAIFrontierAdapter(
            client=RaisingClient(),
            input_token_cap=8_192,
            max_output_tokens=4_096,
            call_cap=32,
            usd_ceiling=3.670016,
        ),
        condition=BaselineCondition.UNTUNED_FAST_FRONTIER_SLOW,
        qwen=QwenMLXAdapter(generator=lambda _: "{}"),
        fixtures=(fixture,),
    ).model_copy(update={"hosted_max_cost_microusd": FAST_SLOW_HOSTED_MAX_MICROUSD})
    initial = runner._without_strategy(fixture.snapshot)
    slow_route = DeterministicRouter().route(
        RouteRequest(snapshot=initial, created_at=PROBE_NOW)
    )
    request = CaseCoordinator().build_slow_request(
        initial,
        reason_code=slow_route.reason_codes[0],
        created_at=PROBE_NOW,
    )
    legacy_prompt = build_legacy_slow_prompt(request)
    row = failed.episodes[0]
    call = row.hosted_calls[0].model_copy(
        update={
            "prompt_fingerprint": legacy_prompt.prompt_fingerprint,
            "schema_fingerprint": legacy_prompt.schema_fingerprint,
        }
    )
    row = row.model_copy(
        update={
            "input_fingerprint": fingerprint(
                {"slow": legacy_prompt.prompt_fingerprint, "fast": None}
            ),
            "hosted_calls": (call,),
        }
    )
    prompt = failed.prompt_provenance[0].model_copy(
        update={
            "prompt_fingerprint": legacy_prompt.prompt_fingerprint,
            "output_schema_version": (
                f"SlowModelOutput:{legacy_prompt.schema_fingerprint}"
            ),
        }
    )
    failed = failed.model_copy(
        update={"episodes": (row,), "prompt_provenance": (prompt,)}
    )
    aborted = not_run_condition(
        BaselineCondition.FRONTIER_REFERENCE,
        "not attempted after a provider failure made actual hosted cost unknown",
        status=RunStatus.NOT_RUN_BUDGET_REJECTED,
        hosted_max_cost_microusd=FRONTIER_REFERENCE_HOSTED_MAX_MICROUSD,
    )
    report = compose_report(
        target_root,
        (*current.conditions[:3], failed, aborted),
        hosted_budget_ceiling_microusd=HOSTED_BUDGET_CEILING_MICROUSD,
    )
    write_report(target_root, report)
    return report_path


def test_committed_baseline_artifacts_are_bound_and_truthful() -> None:
    ok, errors = check_baseline_artifacts(ROOT)
    assert ok, errors


def test_compose_report_records_actual_utc_generation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "2026-08-24T05:24:05Z"
    monkeypatch.setattr(runner, "_utc_timestamp", lambda: expected)
    current = BaselineReport.model_validate_json(
        (ROOT / "data/evaluation/phase-03a1-baselines-report.json").read_text(
            encoding="utf-8"
        )
    )

    report = compose_report(
        ROOT,
        current.conditions,
        hosted_budget_ceiling_microusd=current.hosted_budget_ceiling_microusd,
    )

    assert report.generated_at == expected
    assert report.report_fingerprint == report_fingerprint(report)


def test_frontier_conditions_cannot_claim_success_without_calls(
    tmp_path: Path,
) -> None:
    report_path = _copy_artifacts(tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    fabricated = dict(payload["conditions"][2])
    fabricated["condition"] = "untuned_fast_frontier_slow"
    payload["conditions"][3] = fabricated
    _write_refingerprinted(report_path, payload)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert not ok
    assert any("frontier success has too few calls" in error for error in errors)


def test_qwen_prompt_tamper_fails_offline_replay(tmp_path: Path) -> None:
    report_path = _copy_artifacts(tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["conditions"][1]["episodes"][0]["input_fingerprint"] = "0" * 64
    _write_refingerprinted(report_path, payload)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert not ok
    assert any("Qwen prompt fingerprint mismatch" in error for error in errors)


def test_hosted_cost_ceiling_tamper_fails_offline_check(tmp_path: Path) -> None:
    report_path = _copy_artifacts(tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["conditions"][3]["hosted_max_cost_microusd"] = 1
    _write_refingerprinted(report_path, payload)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert not ok
    assert any("hosted maximum cost drift" in error for error in errors)


def test_failed_provider_artifact_replays_attempt_and_global_abort(
    tmp_path: Path,
) -> None:
    _write_failed_frontier_report(tmp_path)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert ok, errors


def test_failed_provider_model_call_tamper_fails_offline_replay(
    tmp_path: Path,
) -> None:
    report_path = _write_failed_frontier_report(tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["conditions"][3]["model_call_count"] = 0
    _write_refingerprinted(report_path, payload)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert not ok
    assert any("model-call evidence count mismatch" in error for error in errors)


def test_failed_provider_unknown_cost_tamper_fails_offline_replay(
    tmp_path: Path,
) -> None:
    report_path = _write_failed_frontier_report(tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    failed = payload["conditions"][3]
    failed["episodes"][0]["hosted_calls"][0]["actual_cost_microusd"] = 0
    failed["cost_accounting_complete"] = True
    _write_refingerprinted(report_path, payload)

    ok, errors = check_baseline_artifacts(tmp_path)

    assert not ok
    assert any("failed provider cost" in error for error in errors)


def test_slow_off_ablation_never_bypasses_mandatory_slow() -> None:
    summary = run_slow_off_ablation()

    assert summary.run_status.value == "succeeded"
    assert summary.evaluated_episode_count == 32
    assert summary.model_call_count == 0
    assert summary.valid_noncompletion_count == 32
    assert summary.failure_slices == {"slow_unavailable": 32}
    assert all(row.route_outcomes == ("slow_refresh",) for row in summary.episodes)


def test_model_run_rejects_live_fixture_drift_before_loading_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "build_phase03a1_harness_report",
        lambda: {
            "manifest_fingerprint": "0" * 64,
            "episode_fingerprint": "0" * 64,
            "ceiling_fingerprint": "0" * 64,
        },
    )

    with pytest.raises(ValueError, match="drifted"):
        runner.qwen_report(ROOT, model_path="checkpoint-must-not-be-read")
