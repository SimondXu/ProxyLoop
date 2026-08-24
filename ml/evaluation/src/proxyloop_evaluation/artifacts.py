"""Offline validation for committed Phase 03A1 baseline evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import BaselineCondition, BaselineReport, RunStatus
from .openai_frontier import (
    FRONTIER_MODEL,
    FRONTIER_PROVIDER,
    FRONTIER_RUNTIME,
)

REPORT_PATH = Path("data/evaluation/phase-03a1-baselines-report.json")
MANIFEST_PATH = Path("data/manifests/phase-03a1-manifest.json")
EPISODES_PATH = Path("data/manifests/phase-03a1-episodes.json")
CEILING_PATH = Path("data/manifests/phase-03a1-ceiling-report.json")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def report_fingerprint(report: BaselineReport) -> str:
    # Preserve the exact historical fingerprint when later optional evidence
    # fields are added to the parser but absent from the committed v1 report.
    payload = report.model_dump(mode="json", exclude_unset=True)
    payload.pop("report_fingerprint")
    return fingerprint(payload)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_baseline_artifacts(root: Path) -> tuple[bool, tuple[str, ...]]:
    """Validate shape, provenance bindings, truthfulness, and exact fingerprint."""

    errors: list[str] = []
    required = (REPORT_PATH, MANIFEST_PATH, EPISODES_PATH, CEILING_PATH)
    missing = [str(path) for path in required if not (root / path).is_file()]
    if missing:
        return False, tuple(f"missing artifact: {path}" for path in missing)

    try:
        report = BaselineReport.model_validate_json(
            (root / REPORT_PATH).read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, ValidationError, OSError) as error:
        return False, (f"invalid baseline report: {error}",)

    manifest = _load_json(root / MANIFEST_PATH)
    episodes = _load_json(root / EPISODES_PATH)
    ceiling = _load_json(root / CEILING_PATH)
    episode_rows = episodes.get("episodes")
    expected_episode_ids = (
        {
            str(row.get("episode_id"))
            for row in episode_rows
            if isinstance(row, dict) and row.get("episode_id") is not None
        }
        if isinstance(episode_rows, list)
        else set()
    )
    if report.manifest_fingerprint != manifest.get("content_hash"):
        errors.append("baseline manifest fingerprint does not match Harness")
    if report.episode_fingerprint != episodes.get("episode_fingerprint"):
        errors.append("baseline episode fingerprint does not match Harness")
    if report.harness_ceiling_fingerprint != ceiling.get("ceiling_fingerprint"):
        errors.append("baseline ceiling fingerprint does not match Harness")
    if (
        report.harness_ceiling_gate_passed is not True
        or ceiling.get("gate_passed") is not True
    ):
        errors.append("scripted Harness ceiling must pass")
    if report.report_fingerprint != report_fingerprint(report):
        errors.append("baseline report fingerprint drift")

    oracle = report.conditions[0]
    if oracle.condition is not BaselineCondition.SCRIPTED_ORACLE_CEILING:
        errors.append("scripted oracle must be the first condition")
    if oracle.run_status is not RunStatus.SUCCEEDED:
        errors.append("scripted oracle condition must succeed")
    if oracle.model_call_count != 0 or oracle.actual_cost_microusd != 0:
        errors.append("scripted oracle cannot report model calls or cost")

    for condition in report.conditions:
        if condition.run_status.value.startswith("not_run_"):
            if (
                condition.model_call_count
                or condition.input_tokens
                or condition.output_tokens
            ):
                errors.append(
                    f"{condition.condition}: not-run condition has model usage"
                )
            if condition.actual_cost_microusd:
                errors.append(f"{condition.condition}: not-run condition has cost")
        if condition.leakage_violation_count:
            errors.append(f"{condition.condition}: leakage violation detected")
        if any(row.false_completion and row.completed for row in condition.episodes):
            errors.append(
                f"{condition.condition}: model false completion became authoritative"
            )
        if condition.run_status is RunStatus.SUCCEEDED:
            observed_episode_ids = {row.episode_id for row in condition.episodes}
            if observed_episode_ids != expected_episode_ids:
                errors.append(
                    f"{condition.condition}: episode coverage does not match Harness"
                )

    qwen = report.conditions[1]
    if qwen.run_status is RunStatus.SUCCEEDED:
        if qwen.model_call_count != qwen.expected_episode_count:
            errors.append("Qwen reference must record one model call per episode")
        if qwen.actual_cost_microusd:
            errors.append("local Qwen reference cannot report hosted cost")
        if not any(
            item.model_id == "mlx-community/Qwen3-4B-Instruct-2507-4bit"
            and item.untuned_label == "quantized_untuned"
            and item.checkpoint_fingerprint
            == "941705797578fb931fdef40b55c03ae60274b48fe03f1626f01197b52394de50"
            and item.tokenizer_fingerprint
            == "5b06e759eb78534dbbf01b5ffc3faa43c9607921494151f7ca758b352f08722b"
            and item.chat_template_fingerprint
            == "40c21f34cf67d8c760ef72f8ad3ae5afad514299d4b06e91dd9a8d705af7b541"
            for item in qwen.model_provenance
        ):
            errors.append("Qwen reference provenance is not the frozen checkpoint")

    expected_hosted_maxima = (3_670_016, 7_340_032)
    for frontier, expected_maximum in zip(
        report.conditions[3:], expected_hosted_maxima, strict=True
    ):
        if frontier.hosted_max_cost_microusd != expected_maximum:
            errors.append(f"{frontier.condition}: hosted maximum cost drift")
        if frontier.run_status is RunStatus.FAILED:
            failed_calls = [
                call
                for row in frontier.episodes
                for call in row.hosted_calls
                if call.actual_cost_microusd is None
                and call.status in {"failed_provider_call", "failed_invalid_response"}
            ]
            if len(failed_calls) != 1:
                errors.append(
                    f"{frontier.condition}: failed run requires one attempted-call "
                    "failure"
                )
            if frontier.cost_accounting_complete:
                errors.append(
                    f"{frontier.condition}: failed provider cost cannot be complete"
                )
            if not frontier.episodes or "actual_cost_unknown" not in (
                frontier.episodes[-1].failure_codes
            ):
                errors.append(
                    f"{frontier.condition}: failed run lacks unknown-cost evidence"
                )
        if frontier.run_status is not RunStatus.SUCCEEDED:
            continue
        if frontier.model_call_count < frontier.expected_episode_count:
            errors.append(f"{frontier.condition}: frontier success has too few calls")
        if not frontier.prompt_provenance:
            errors.append(
                f"{frontier.condition}: frontier prompt provenance is missing"
            )
        if not any(
            item.provider == FRONTIER_PROVIDER
            and item.model_id == FRONTIER_MODEL
            and item.runtime == FRONTIER_RUNTIME
            for item in frontier.model_provenance
        ):
            errors.append(
                f"{frontier.condition}: frozen frontier provenance is missing"
            )
        if not frontier.cost_accounting_complete:
            errors.append(
                f"{frontier.condition}: successful cost accounting incomplete"
            )

    fast_slow, frontier_reference = report.conditions[3:]
    if fast_slow.run_status is RunStatus.FAILED and not (
        frontier_reference.run_status is RunStatus.NOT_RUN_BUDGET_REJECTED
        and frontier_reference.model_call_count == 0
        and frontier_reference.evaluated_episode_count == 0
        and frontier_reference.actual_cost_microusd == 0
    ):
        errors.append(
            "frontier reference must remain unattempted after unknown hosted cost"
        )

    from .replay import replay_report

    errors.extend(
        replay_report(
            root,
            report,
            manifest=manifest,
            episodes=episodes,
            ceiling=ceiling,
        )
    )

    expected_ready = all(
        condition.run_status is RunStatus.SUCCEEDED
        for condition in report.conditions[1:]
    )
    if report.phase_completion_ready != expected_ready:
        errors.append("phase completion readiness is inconsistent with run statuses")
    if expected_ready and report.phase_completion_blockers:
        errors.append("ready report cannot retain completion blockers")
    if not expected_ready and not report.phase_completion_blockers:
        errors.append("unready report must identify completion blockers")
    return not errors, tuple(errors)


def write_report(root: Path, report: BaselineReport) -> None:
    path = root / REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report.model_dump(mode="json", exclude_unset=True),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "REPORT_PATH",
    "canonical_json",
    "check_baseline_artifacts",
    "fingerprint",
    "report_fingerprint",
    "write_report",
]
