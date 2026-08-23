from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "runtime" / "packages" / "contracts"
SOURCE = PACKAGE / "src" / "proxyloop_contracts"
ALLOWED_IMPORT_ROOTS = sys.stdlib_module_names | {"pydantic"}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_contract_package_imports_only_stdlib_and_pydantic() -> None:
    imported = set().union(*(imported_roots(path) for path in SOURCE.rglob("*.py")))

    assert imported <= ALLOWED_IMPORT_ROOTS


def test_contract_runtime_dependency_surface_is_pydantic_only() -> None:
    with (PACKAGE / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    dependencies = project["project"]["dependencies"]
    assert len(dependencies) == 1
    assert dependencies[0].startswith("pydantic")
