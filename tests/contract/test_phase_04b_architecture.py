from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "runtime" / "packages" / "openai_adapter"


def test_phase_04b_runtime_owned_adapter_and_server_surface_exist() -> None:
    assert (ADAPTER / "pyproject.toml").is_file()
    assert (ADAPTER / "src" / "proxyloop_openai_adapter").is_dir()
    assert (
        ROOT / "runtime" / "services" / "api" / "src" / "proxyloop_api" / "server.py"
    ).is_file()


def test_phase_04b_runtime_does_not_import_ml_evaluation() -> None:
    source_roots = (
        ADAPTER / "src",
        ROOT / "runtime" / "services" / "api" / "src",
    )
    imported: set[str] = set()
    for path in (file for root in source_roots for file in root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert all(not name.startswith("proxyloop_evaluation") for name in imported)
    assert all(not name.startswith("ml") for name in imported)


def test_phase_04b_adapter_declares_one_openai_sdk_dependency() -> None:
    with (ADAPTER / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    dependencies = project["project"]["dependencies"]
    assert sum(dependency.startswith("openai") for dependency in dependencies) == 1
    assert not any("gateway" in dependency.lower() for dependency in dependencies)
