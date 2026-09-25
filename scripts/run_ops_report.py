#!/usr/bin/env python3
"""One offline, deterministic operations report (Phase 07, D5).

``--write`` writes ``data/evaluation/ops-report.json`` and prints a summary;
``--check`` re-derives it and fails on drift. The report reads only committed
repository files (the Makefile, the gated-skip pin, the three Fast/Slow split
reports, the M1 and M2 parity reports, and the Scene J journey evidence when
it exists) plus the test counts that ``pytest --collect-only`` reports for the
three real-dependency gates, which needs no database or Temporal. It opens no
socket, starts no container, and calls no model. Pass counts of the
real-dependency gates are not computed here: they come only from the serial
gate run recorded in the phase log.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path("data/evaluation/ops-report.json")
SCHEMA_VERSION = "ops-report-v1"
CLAIM_BOUNDARY = (
    "A local summary of committed repository artifacts. Every number is copied "
    "or derived from the named inputs, whose own claim boundaries apply; "
    "real-dependency gate pass counts are not computed here (they come from the "
    "serial gate run recorded in the phase log). Not a production, latency, "
    "capacity, or model-quality claim."
)
SPLIT_REPORTS = {
    "scripted": Path("data/evaluation/fast-slow-split-scripted.json"),
    "distilled": Path("data/evaluation/fast-slow-split-distilled.json"),
    "untuned": Path("data/evaluation/fast-slow-split-untuned.json"),
}
M1_REPORT = Path("data/experiments/phase-03c/local-parity/parity-report.json")
M2_REPORT = Path("data/experiments/phase-03c/local-parity/product-path-report.json")
JOURNEY_REPORT = Path("data/evaluation/phase-07-demo-journey-scripted.json")
GATED_SKIPS_SCRIPT = Path("scripts/check_gated_skips.py")
MAKEFILE = Path("Makefile")
PRE_JUDGE_NOTE = (
    "pre-Judge observed artifact: recorded before the PR-14 Judge seam and not "
    "regenerated (Phase 07 D6); never compared on Judge fields"
)
# Every "not done" item of the Phase 07 contract (Non-goals and hard limits,
# DoD item 6) plus the measurement gaps of the inputs above.
NOT_MEASURED = (
    "production of any kind: production serving of the distilled adapter, "
    "real-model load, p95, capacity, concurrency, OOM, automatic fallback under "
    "load, production exactly-once effects, production monitoring, and "
    "production readiness (decision 18)",
    "deployment, hosting, and release",
    "Phase 06B2 and every real channel: real Providers, Gmail and OAuth, e-mail, "
    "MCP, SMS, Voice (LiveKit, SIP, telephony), and any credential",
    "V0 (a hosted frontier model in both slots), frontier-as-Fast, and a "
    "second-family Judge: not measured (budget; decision 17)",
    "a model Judge and any Judge verdict distribution (decisions 7 and 17)",
    "further training, data expansion, reruns, or promotion; Phase 03B stays "
    "NO_GO_STOP_PHASE03B (decision 17)",
    "narrow contracts 1.2 (PR-15, dropped by decision 21)",
    "the build-plan Do-not-do list: D3-5, D3-6, D1-10 to D1-12, D2-7 to D2-9, "
    "D3-7 to D3-9, A-9b, and SlowWorkRequest.revision_feedback",
    "a Web free-text turn after Case creation, Web exposure of channels or the "
    "Judge, and any UI redesign",
    "hosted spend of any kind (no budget is recorded)",
    "the local distilled and untuned split reports after the Judge seam (D6)",
    "fresh-clone reproduction of the local model outputs (the adapter is "
    "not committed)",
)
_COLLECTED = re.compile(r"(\d+) tests? collected")

Collector = Callable[[Path, tuple[str, ...]], int]


class OpsReportError(RuntimeError):
    """An input is missing or has an unexpected shape."""


def _read_json(root: Path, path: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise OpsReportError(f"cannot read {path}") from None
    if not isinstance(value, dict):
        raise OpsReportError(f"{path} is not a JSON object")
    return value


def _sha256(root: Path, path: Path) -> str:
    return hashlib.sha256((root / path).read_bytes()).hexdigest()


def _load_gated_skips(root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_ops_report_check_gated_skips", root / GATED_SKIPS_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise OpsReportError(f"cannot load {GATED_SKIPS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_targets(makefile: str) -> dict[str, str]:
    """Map each target to its prerequisites plus recipe text (continuations joined)."""

    joined = makefile.replace("\\\n", " ")
    targets: dict[str, str] = {}
    current: str | None = None
    for line in joined.splitlines():
        if line.startswith("\t"):
            if current is not None:
                targets[current] += " " + line
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+):(?!=)(.*)$", line)
        current = match.group(1) if match else None
        if match:
            targets[match.group(1)] = match.group(2)
    return targets


def collect_count(root: Path, files: tuple[str, ...]) -> int:
    """Count the test items pytest collects for ``files`` (no DB or Temporal).

    The subprocess only imports the test modules and collects them; no test
    or fixture runs, so it opens no database, Temporal, or network connection.
    """

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PROXYLOOP_TEST_")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "runtime/pyproject.toml",
            "-q",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            *files,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    match = _COLLECTED.search(result.stdout)
    if result.returncode != 0 or match is None:
        raise OpsReportError(f"pytest could not collect {' '.join(files)}")
    return int(match.group(1))


def _gates(root: Path, gated: ModuleType, collector: Collector) -> dict[str, Any]:
    targets = _make_targets((root / MAKEFILE).read_text(encoding="utf-8"))
    if "test" not in targets:
        raise OpsReportError("the Makefile has no test target")
    prerequisites = targets["test"].split()
    checks = sorted(name for name in prerequisites if name.endswith("-check"))
    real: dict[str, Any] = {}
    for target in gated.REAL_DEPENDENCY_TARGETS:
        recipe = targets.get(target)
        if recipe is None:
            raise OpsReportError(f"the Makefile has no {target} target")
        files = tuple(
            sorted(set(re.findall(r"tests/integration/[\w./-]+\.py", recipe)))
        )
        if not files:
            raise OpsReportError(f"{target} names no test file")
        real[target] = {
            "collected_test_items": collector(root, files),
            "files": list(files),
        }
    return {
        "make_test_checks": checks,
        "make_test_check_count": len(checks),
        "real_dependency_gates": real,
        "real_dependency_pass_counts": (
            "not computed: recorded from the serial gate run in the phase log"
        ),
    }


def _gated_skip_pin(gated: ModuleType, gates: Mapping[str, Any]) -> dict[str, Any]:
    per_file = dict(sorted(gated.EXPECTED_GATED_SKIPS_PER_FILE.items()))
    gate_files = {
        path
        for gate in gates["real_dependency_gates"].values()
        for path in gate["files"]
    }
    return {
        "per_file": per_file,
        "total": sum(per_file.values()),
        "every_pinned_file_is_in_a_gate": all(path in gate_files for path in per_file),
    }


def _top_codes(histogram: Mapping[str, int], limit: int = 3) -> list[list[Any]]:
    ranked = sorted(histogram.items(), key=lambda item: (-item[1], item[0]))
    return [[code, count] for code, count in ranked[:limit]]


_SCENARIO_KEYS = (
    "turns",
    "dialogue_turns",
    "fast_model_line_rate",
    "gate_fallback_rate",
    "fallback_cause_counts",
    "calls_by_role_and_result",
    "unapplied_model_calls",
)
_JUDGE_KEYS = (
    "judge_calls_by_result",
    "unapplied_judge_calls_by_result",
    "slow_retry_counts",
)


def _split(report: Mapping[str, Any], backend: str) -> dict[str, Any]:
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, Mapping):
        raise OpsReportError(f"the {backend} split report has no scenarios")
    has_judge = "judge_backend" in report
    summary: dict[str, Any] = {}
    for name, scenario in sorted(scenarios.items()):
        aggregates = scenario["aggregates"]
        entry = {key: aggregates[key] for key in _SCENARIO_KEYS}
        entry["top_fast_reject_codes"] = _top_codes(
            aggregates["fast_reject_reason_histogram"]
        )
        if has_judge:
            entry.update({key: aggregates[key] for key in _JUDGE_KEYS})
        summary[name] = entry
    result: dict[str, Any] = {
        "schema_version": report["schema_version"],
        "claim_boundary": report["claim_boundary"],
        "scenarios": summary,
    }
    if has_judge:
        result["judge_backend"] = report["judge_backend"]
    else:
        result["judge"] = PRE_JUDGE_NOTE
    for key in ("label", "adapter_mode", "measured"):
        if key in report:
            result[key] = report[key]
    return result


def _parity(m1: Mapping[str, Any], m2: Mapping[str, Any]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for backend, arm in sorted(m2["arms"].items()):
        summary = arm["summary"]
        arms[backend] = {
            "label": m2["labels"][backend],
            "rows": summary["rows"],
            "delivered_line": summary["delivered_line"],
            "act_agreement_true_oracle": summary["act_agreement_true_oracle"],
            "act_agreement_product_oracle": summary["act_agreement_product_oracle"],
            "delivery_stages": summary["delivery_stages"],
        }
    return {
        "m1_stack_parity": {
            "schema_version": m1["schema_version"],
            "result_role": m1["result_role"],
            "verdict": m1["verdict"],
            "labels": m1["labels"],
            # Referenced, not restated: M1's text predates M2 and calls it
            # pending; M2 is reported below as m2_product_path.
            "claim_boundary": (
                f"see claim_boundary in {M1_REPORT}; it predates M2, which is "
                "reported below as m2_product_path"
            ),
        },
        "m2_product_path": {
            "schema_version": m2["schema_version"],
            "result_role": m2["result_role"],
            "arms": arms,
            "divergence": m2["divergence"],
            "claim_boundary": m2["claim_boundary"],
        },
        "caveats": (
            "The distilled backend is a Local Opt-in Candidate, never promoted; "
            "decision 18's E1-E5 and the four Phase 03C caveats apply to every "
            "number (harness/context/audit-remediation-decisions.md)."
        ),
    }


def _split_health(report: Mapping[str, Any]) -> dict[str, Any]:
    health: dict[str, Any] = {}
    for name, scenario in sorted(report["scenarios"].items()):
        aggregates = scenario["aggregates"]
        delivered = sum(
            1
            for turn in scenario["turns"]
            if turn["delivered"] in {"model", "fallback"}
        )
        fast = aggregates["calls_by_role_and_result"]["fast"]
        entry: dict[str, Any] = {
            "dialogue_turns": aggregates["dialogue_turns"],
            "turns_with_one_line": delivered,
            "one_line_per_dialogue_turn": delivered == aggregates["dialogue_turns"],
            "fast_failed": fast["failed"],
            "fast_rejected": fast["rejected"],
        }
        if "judge_calls_by_result" in aggregates:
            slow = aggregates["calls_by_role_and_result"]["slow"]
            unapplied_slow = aggregates["unapplied_calls_by_role_and_result"]["slow"]
            judge = sum(aggregates["judge_calls_by_result"].values())
            unapplied_judge = sum(
                aggregates["unapplied_judge_calls_by_result"].values()
            )
            retries = sum(aggregates["slow_retry_counts"].values())
            entry.update(
                {
                    "judge_calls": judge,
                    "admitted_slow_results": slow["succeeded"],
                    "judge_calls_equal_admitted_slow": judge == slow["succeeded"]
                    and unapplied_judge == unapplied_slow["succeeded"],
                    "slow_retries": retries,
                }
            )
        health[name] = entry
    return health


def _journey_health(journey: Mapping[str, Any] | None) -> dict[str, Any]:
    if journey is None:
        return {"status": "not_recorded", "path": str(JOURNEY_REPORT)}
    counts = journey["trace_counts"]
    executions = journey["execution_count"]
    return {
        "status": "recorded",
        "readiness": journey["readiness"],
        "trace_counts": counts,
        "judge_calls_equal_slow_results": sum(counts["judge"].values())
        == sum(counts["slow"].values()),
        "execution_count": executions,
        "executed_once_after_replay": executions["after_approve"] == 1
        and executions["after_replay"] == 1,
        "receipt_predicate": journey["receipt_predicate"],
        "marker_absent": journey["marker_absent"],
        "marker_absent_everywhere": all(journey["marker_absent"].values()),
        "operation_records": journey["operation_records"],
    }


def build_report(
    root: Path = ROOT, *, collector: Collector | None = None
) -> dict[str, Any]:
    gated = _load_gated_skips(root)
    splits = {name: _read_json(root, path) for name, path in SPLIT_REPORTS.items()}
    m1 = _read_json(root, M1_REPORT)
    m2 = _read_json(root, M2_REPORT)
    journey = (
        _read_json(root, JOURNEY_REPORT) if (root / JOURNEY_REPORT).is_file() else None
    )
    # Data artifacts are pinned by hash; the two source inputs are pinned by
    # the fields derived from them, so an unrelated Makefile edit does not
    # make the report stale.
    inputs = [*SPLIT_REPORTS.values(), M1_REPORT, M2_REPORT]
    if journey is not None:
        inputs.append(JOURNEY_REPORT)
    gates = _gates(root, gated, collector if collector is not None else collect_count)
    return {
        "schema_version": SCHEMA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": [
            {"path": str(path), "sha256": _sha256(root, path)} for path in inputs
        ],
        "source_inputs": [str(MAKEFILE), str(GATED_SKIPS_SCRIPT)],
        "gates": gates,
        "gated_skip_pin": _gated_skip_pin(gated, gates),
        "fast_slow_split": {
            name: _split(report, name) for name, report in splits.items()
        },
        "parity": _parity(m1, m2),
        "trace_and_log_health": {
            "split_reports": {
                name: _split_health(report) for name, report in splits.items()
            },
            "journey": _journey_health(journey),
        },
        "not_measured_or_not_done": list(NOT_MEASURED),
    }


def render(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def summary_lines(report: Mapping[str, Any]) -> list[str]:
    gates = report["gates"]
    pin = report["gated_skip_pin"]
    lines = [
        f"make test runs {gates['make_test_check_count']} committed *-check targets.",
        "Real-dependency gates (collected test items; pass counts come from the "
        "phase log): "
        + ", ".join(
            f"{name} {gate['collected_test_items']}"
            for name, gate in gates["real_dependency_gates"].items()
        ),
        f"Gated-skip pin: {pin['total']} across {len(pin['per_file'])} files "
        f"(every pinned file in a gate: {pin['every_pinned_file_is_in_a_gate']}).",
    ]
    for backend, split in report["fast_slow_split"].items():
        demo = split["scenarios"]["demo_path"]
        dialogue = split["scenarios"]["dialogue_path"]
        lines.append(
            f"Split {backend} ({split['schema_version']}): model-line rate "
            f"demo {demo['fast_model_line_rate']}, dialogue "
            f"{dialogue['fast_model_line_rate']}; gate fallback rate dialogue "
            f"{dialogue['gate_fallback_rate']}"
            + ("" if "judge_backend" in split else "; pre-Judge")
        )
    m1 = report["parity"]["m1_stack_parity"]["verdict"]
    lines.append(
        f"M1: {m1['result']} (distilled local act agreement "
        f"{m1['distilled_local_act_agreement']:.3f}, cloud concordance "
        f"{m1['distilled_cloud_act_concordance']:.3f})."
    )
    for backend, arm in report["parity"]["m2_product_path"]["arms"].items():
        lines.append(
            f"M2 {backend} ({arm['label']}): delivered "
            f"{arm['delivered_line']['count']}/{arm['rows']}, act agreement "
            f"{arm['act_agreement_true_oracle']['count']}/{arm['rows']}."
        )
    journey = report["trace_and_log_health"]["journey"]
    lines.append(f"Scene J journey evidence: {journey['status']}.")
    return lines


def _print_observed_gated_skips(root: Path) -> None:
    junit = root / ".gate" / "runtime-junit.xml"
    if not junit.is_file():
        return
    gated = _load_gated_skips(root)
    observed = gated.gated_skips(junit)
    print(
        f"Local {junit.relative_to(root)} (not written to the report): "
        f"{sum(observed.values())} gated skips against a pin of "
        f"{gated.EXPECTED_GATED_SKIPS}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report()
    except OpsReportError as exc:
        print(f"ops-report: {exc}", file=sys.stderr)
        return 1
    text = render(report)
    target = ROOT / REPORT_PATH
    if args.write:
        target.write_text(text, encoding="utf-8")
        for line in summary_lines(report):
            print(line)
        _print_observed_gated_skips(ROOT)
        print(f"Wrote {REPORT_PATH}.")
        return 0
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        print(
            f"ops-report: {REPORT_PATH} is stale or missing; run make ops-report",
            file=sys.stderr,
        )
        return 1
    print(f"{REPORT_PATH} is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
