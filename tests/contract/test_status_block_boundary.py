"""PR-8 I12 / PR-10: the Agent Status Bar never becomes the Fast prompt.

The Status Bar is rendered only in the Web (`apps/web/lib/status-block.ts`).
The disclosure gate reads contract fields directly, and no Fast prompt,
observation, or serving builder may import or re-create a status-block
renderer.
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
# agent_core (gate, Fast view, observation), the hosted Fast prompt builder,
# and every ML prompt, observation, data, and serving module.
FAST_SIDE_ROOTS = (
    ROOT / "runtime" / "packages" / "agent_core" / "src",
    ROOT / "runtime" / "packages" / "openai_adapter" / "src",
    ROOT / "ml",
)
RENDERER_NAMES = (
    "status_block",
    "render_status_block",
    "status-block",
    "renderStatusBlock",
)


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


def test_fast_side_sources_never_reference_a_status_block_renderer() -> None:
    sources = [path for root in FAST_SIDE_ROOTS for path in _python_sources(root)]
    assert GATE in sources
    offenders = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in sources
        for name in RENDERER_NAMES
        if name in path.read_text(encoding="utf-8")
    )
    assert offenders == []
