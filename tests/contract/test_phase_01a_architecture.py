from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "runtime" / "packages"


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


def project_dependencies(package: str) -> set[str]:
    with (PACKAGES / package / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    return {
        dependency.split("=", 1)[0].strip()
        for dependency in project["project"]["dependencies"]
    }


def test_telecom_domain_depends_only_on_contracts_and_stdlib() -> None:
    imports = imported_roots(
        PACKAGES / "telecom_domain" / "src" / "proxyloop_telecom_domain"
    )

    assert imports <= sys.stdlib_module_names | {"proxyloop_contracts"}
    assert project_dependencies("telecom_domain") == {"proxyloop-contracts"}


def test_provider_simulator_depends_inward_only() -> None:
    imports = imported_roots(
        PACKAGES / "provider_simulator" / "src" / "proxyloop_provider_simulator"
    )

    assert imports <= sys.stdlib_module_names | {
        "proxyloop_contracts",
        "proxyloop_telecom_domain",
    }
    assert project_dependencies("provider_simulator") == {
        "proxyloop-contracts",
        "proxyloop-telecom-domain",
    }
