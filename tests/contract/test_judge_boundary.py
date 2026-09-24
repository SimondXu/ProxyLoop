"""PR-14 JG7: the Judge never reaches evaluation, metrics, or authority.

Decision 7: the Judge is quality only; a Judge that reaches a metric repeats
D2-1. This is a static tripwire over the import graph and the source names:
no ML or script source, and no authority, storage, or measurement module of
the Runtime, imports or names the Judge. The Judge module itself depends on
the contracts and the adapter interfaces only, and the coordinator's outcome
carries no Judge output for the Runtime to read.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import fields
from pathlib import Path

from proxyloop_agent_core import CoordinatorOutcome

ROOT = Path(__file__).resolve().parents[2]
AGENT_CORE = (
    ROOT / "runtime" / "packages" / "agent_core" / "src" / "proxyloop_agent_core"
)
CASE_RUNTIME = (
    ROOT / "runtime" / "packages" / "case_runtime" / "src" / "proxyloop_case_runtime"
)
JUDGE_MODULE = "proxyloop_agent_core.judge"
JUDGE_NAMES = frozenset(
    {
        "ScriptedJudgeAdapter",
        "JudgeAdapter",
        "JudgeVerdict",
        "JudgeAdapterFailure",
        "FeedbackReasoningSlowAdapter",
    }
)
# Runtime modules that decide authority, store state, or measure.
GUARDED_MODULES = (
    AGENT_CORE / "capabilities.py",
    AGENT_CORE / "proposal_admission.py",
    AGENT_CORE / "router.py",
    AGENT_CORE / "disclosure_gate.py",
    CASE_RUNTIME / "turn_split.py",
    CASE_RUNTIME / "repository.py",
    CASE_RUNTIME / "postgres_repository.py",
)
OUTCOME_FIELDS = frozenset(
    {
        "route",
        "status",
        "fast_decision",
        "slow_result",
        "audits",
        "traces",
        "fast_disclosure_rejected",
        "fast_failed",
    }
)


def _python_sources(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
    ]


def _judge_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name
                for alias in node.names
                if alias.name == JUDGE_MODULE
                or alias.name.startswith(JUDGE_MODULE + ".")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and module.startswith(JUDGE_MODULE):
                found.append(module)
            if node.level > 0 and module == "judge":
                found.append(f"relative .{module}")
            found.extend(
                alias.name
                for alias in node.names
                if alias.name in JUDGE_NAMES or alias.name.startswith("JUDGE_")
            )
        elif isinstance(node, ast.Name) and (
            node.id in JUDGE_NAMES or node.id.startswith("JUDGE_")
        ):
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and (
            node.attr in JUDGE_NAMES or node.attr.startswith("JUDGE_")
        ):
            found.append(node.attr)
    return found


def _offenders(paths: list[Path]) -> list[str]:
    return sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in paths
        for name in _judge_references(path)
    )


def test_b1_no_ml_or_script_source_references_the_judge() -> None:
    roots = [ROOT / "ml", ROOT / "scripts"]
    sources = [path for root in roots for path in _python_sources(root)]
    # Not vacuous: both roots are scanned and hold the evaluation entry points.
    names = {path.relative_to(ROOT).as_posix() for path in sources}
    assert "scripts/run_fast_slow_split_report.py" in names
    assert "ml/evaluation/src/proxyloop_evaluation/runner_v2.py" in names
    assert _offenders(sources) == []


def test_b2_no_authority_storage_or_measurement_module_references_the_judge() -> None:
    domain = _python_sources(ROOT / "runtime" / "packages" / "telecom_domain" / "src")
    assert domain
    paths = [*GUARDED_MODULES, *domain]
    assert all(path.is_file() for path in paths)
    assert _offenders(paths) == []


def test_b3_the_judge_module_depends_on_contracts_and_interfaces_only() -> None:
    tree = ast.parse((AGENT_CORE / "judge.py").read_text(encoding="utf-8"))
    absolute: set[str] = set()
    relative: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative.add(node.module or "")
            elif node.module:
                absolute.add(node.module.split(".", 1)[0])
    assert absolute <= sys.stdlib_module_names | {"__future__", "proxyloop_contracts"}
    assert relative <= {"interfaces"}


def test_b3_the_coordinator_outcome_carries_no_judge_output() -> None:
    assert {item.name for item in fields(CoordinatorOutcome)} == OUTCOME_FIELDS
