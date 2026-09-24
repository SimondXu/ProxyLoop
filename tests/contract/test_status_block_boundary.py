"""PR-8 I12 / PR-10: the Agent Status Bar never becomes the Fast prompt.

I12 is enforced by placement: the Status Bar renderer is TypeScript in the Web
(`apps/web/lib/status-block.ts`), which no Python module can import. This test
is a tripwire for the ways that could erode: the disclosure gate importing
anything beyond the contracts, or any Runtime or ML source growing or naming a
status-block renderer.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (
    ROOT
    / "runtime"
    / "packages"
    / "agent_core"
    / "src"
    / "proxyloop_agent_core"
    / "disclosure_gate.py"
)
RENDERER_NAMES = (
    "status_block",
    "render_status_block",
    "status-block",
    "renderStatusBlock",
)


def _scanned_roots() -> list[Path]:
    # Every Runtime package and service source tree, plus all of `ml/`.
    return sorted(ROOT.glob("runtime/*/*/src")) + [ROOT / "ml"]


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _python_sources(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
    ]


def test_disclosure_gate_reads_contract_fields_directly() -> None:
    assert _imported_roots(GATE) <= sys.stdlib_module_names | {
        "__future__",
        "proxyloop_contracts",
    }


def test_every_scanned_root_has_python_sources() -> None:
    roots = _scanned_roots()
    names = {path.relative_to(ROOT).as_posix() for path in roots}
    # The Fast-side seams must be among the scanned roots.
    assert {
        "runtime/packages/agent_core/src",
        "runtime/packages/openai_adapter/src",
        "runtime/packages/case_runtime/src",
        "runtime/services/api/src",
        "ml",
    } <= names
    assert all(_python_sources(root) for root in roots)


def test_no_runtime_or_ml_source_names_a_status_block_renderer() -> None:
    sources = [path for root in _scanned_roots() for path in _python_sources(root)]
    assert GATE in sources
    offenders = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in sources
        for name in RENDERER_NAMES
        if name in path.read_text(encoding="utf-8")
    )
    assert offenders == []
