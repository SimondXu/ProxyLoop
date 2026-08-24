from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def document(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def imported_roots(source: Path) -> set[str]:
    roots: set[str] = set()
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_phase_03a1_baselines_are_the_only_active_gate() -> None:
    agents = document("AGENTS.md")
    plans = document("PLANS.md")
    harness = document("harness/build/phase-03a1-harness.md")
    baselines = document("harness/build/phase-03a1-baselines.md")

    assert "e08c9b6" in agents + plans + harness + baselines
    assert "Phase 03A1-B untuned Qwen/frontier baselines is the only active" in agents
    assert "| 03A1-H |" in plans and "Complete; squash merged" in plans
    assert "| 03A1-B |" in plans and "In progress" in plans
    assert "| 03B |" in plans and "Not started" in plans
    assert "**Status**: Complete; squash merged" in harness
    assert "**Status**: In progress." in baselines


def test_phase_03a1_harness_required_implementation_surface_exists() -> None:
    required_paths = (
        "runtime/packages/agent_core/src/proxyloop_agent_core/interfaces.py",
        "runtime/packages/agent_core/src/proxyloop_agent_core/router.py",
        "runtime/packages/agent_core/src/proxyloop_agent_core/scripted.py",
        "runtime/packages/agent_core/src/proxyloop_agent_core/coordinator.py",
        "runtime/packages/agent_core/src/proxyloop_agent_core/capabilities.py",
        "runtime/packages/provider_simulator/src/proxyloop_provider_simulator/multi_turn.py",
        "scripts/run_phase_03a1_harness.py",
    )

    missing = [path for path in required_paths if not (ROOT / path).is_file()]
    assert not missing, f"missing Phase 03A1 Harness surface: {missing}"


def test_phase_03a1_canonical_contracts_are_public_and_generated() -> None:
    contracts = document(
        "runtime/packages/contracts/src/proxyloop_contracts/contracts.py"
    )
    exports = document("runtime/packages/contracts/src/proxyloop_contracts/__init__.py")

    contract_names = (
        "ModelInputPins",
        "PlanningBasis",
        "VisibleCaseEvent",
        "CapabilityManifest",
        "CaseContextSnapshot",
        "FastModelView",
        "SlowReasonerView",
        "RoutingDecision",
        "SlowWorkRequest",
        "SlowWorkResult",
    )
    for name in contract_names:
        assert f"class {name}(" in contracts
        assert f'"{name}"' in exports

    schema = document("contracts/jsonschema/proxyloop-contracts.schema.json")
    typescript = document("contracts/typescript/proxyloop-contracts.d.ts")
    for name in contract_names:
        assert f'"{name}"' in schema
        assert f"export interface {name}" in typescript


def test_phase_03a1_router_precedence_and_fast_action_boundary_are_executable() -> None:
    router = document("runtime/packages/agent_core/src/proxyloop_agent_core/router.py")
    coordinator = document(
        "runtime/packages/agent_core/src/proxyloop_agent_core/coordinator.py"
    )

    outcomes = (
        "terminal",
        "verify_only",
        "wait_for_approval",
        "slow_refresh",
        "fast_now_and_slow_refresh",
        "fast_now",
    )
    positions = [router.index(f'"{outcome}"') for outcome in outcomes]

    assert positions == sorted(positions)
    assert "action_intent" in coordinator
    assert "stale" in coordinator.lower()
    assert "planning_basis_fingerprint" in coordinator


def test_phase_03a1_runtime_has_no_model_provider_dependencies_or_imports() -> None:
    runtime_root = ROOT / "runtime"
    forbidden = {
        "mlx",
        "openai",
        "pydantic_ai",
        "torch",
        "transformers",
        "vllm",
    }

    dependency_names: set[str] = set()
    for path in runtime_root.rglob("pyproject.toml"):
        with path.open("rb") as project_file:
            project = tomllib.load(project_file)
        dependency_groups = [
            project.get("project", {}).get("dependencies", ()),
            *project.get("dependency-groups", {}).values(),
        ]
        for dependencies in dependency_groups:
            for dependency in dependencies:
                name = re.split(r"[<>=!~\[\s]", dependency, maxsplit=1)[0]
                dependency_names.add(name.replace("-", "_").casefold())

    assert not forbidden & dependency_names
    assert not forbidden & imported_roots(runtime_root / "packages")


def test_phase_03a1_make_gate_is_part_of_preflight() -> None:
    makefile = document("Makefile")

    assert "harness:" in makefile
    assert "harness-check:" in makefile
    assert "run_phase_03a1_harness.py" in makefile
    assert (
        "test: unit-test contracts-check benchmark-check data-pilot-check harness-check"
    ) in makefile


def test_phase_03a1_contract_forbids_model_training_and_product_scope() -> None:
    build = document("harness/build/phase-03a1-harness.md")

    for marker in (
        "Qwen/LFM/frontier dependency",
        "SFT, QLoRA, DPO, RL",
        "FastAPI, PostgreSQL, Temporal",
        "credentials, consumer PII",
        "Phase 03B remain separately user-gated",
    ):
        assert marker in build
