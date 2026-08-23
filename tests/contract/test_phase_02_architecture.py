from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ML_PROJECT = ROOT / "ml" / "pyproject.toml"
DATA_PIPELINE = ROOT / "ml" / "data_pipeline" / "src" / "proxyloop_data_pipeline"
RUNTIME_SOURCE_ROOTS = (
    ROOT / "runtime" / "packages",
    ROOT / "runtime" / "services",
)


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


def test_data_pipeline_is_an_independent_ml_project() -> None:
    with ML_PROJECT.open("rb") as project_file:
        project = tomllib.load(project_file)

    dependencies = {
        dependency.split("=", 1)[0].strip()
        for dependency in project["project"]["dependencies"]
    }
    assert {"proxyloop-agent-core", "proxyloop-provider-simulator"} <= dependencies
    assert not dependencies & {
        "fastapi",
        "openai",
        "pydantic-ai",
        "temporalio",
        "torch",
        "transformers",
        "vllm",
    }


def test_data_pipeline_imports_only_the_frozen_runtime_seams() -> None:
    imports = imported_roots(DATA_PIPELINE)

    assert "proxyloop_agent_core" in imports
    assert "proxyloop_provider_simulator" in imports
    assert not imports & {
        "fastapi",
        "openai",
        "pydantic_ai",
        "temporalio",
        "torch",
        "transformers",
        "vllm",
    }


def test_runtime_never_imports_the_ml_data_pipeline() -> None:
    imports = set().union(*(imported_roots(path) for path in RUNTIME_SOURCE_ROOTS))

    assert "proxyloop_data_pipeline" not in imports
