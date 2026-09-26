"""The contract imports only the standard library, pydantic and itself (§2)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import proxyloop.contract

ROOT = Path(proxyloop.contract.__file__).resolve().parent


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_contract_imports_only_stdlib_and_pydantic() -> None:
    files = sorted(ROOT.rglob("*.py"))
    assert len(files) >= 12
    for path in files:
        for module in _imports(path):
            top = module.split(".")[0]
            ok = top in sys.stdlib_module_names or top == "pydantic"
            assert ok or module.startswith("proxyloop.contract"), (path.name, module)
