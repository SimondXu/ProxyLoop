"""obs copies Slow's tool names (it imports only the contract); this keeps the
copy equal to what ``slow/tools.py`` ``_run`` dispatches."""

from __future__ import annotations

import ast
import inspect
import textwrap

from proxyloop.obs import trace
from proxyloop.slow import tools
from proxyloop.slow.prompt import TOOLS


def _dispatched() -> set[str]:
    """The string constants ``_run`` compares ``name`` with (==, !=, in)."""
    run = tools.SlowTools._run  # pyright: ignore[reportPrivateUsage]
    src = textwrap.dedent(inspect.getsource(run))
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Compare) and ast.unparse(node.left) == "name":
            for right in node.comparators:
                names |= {
                    c.value
                    for c in ast.walk(right)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                }
    return names


def test_the_tool_names_match_slow() -> None:
    dispatched = _dispatched()
    assert dispatched == set(TOOLS)  # the parse found every tool Slow offers
    assert dispatched | {"act"} == trace.TOOL_NAMES
